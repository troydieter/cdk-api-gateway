"""
AWS CDK Stack for Private API Gateway with Fan-out Pattern (FIXED to remove circular dependencies)
- Uses API Gateway -> SNS (AWS service integration) -> SQS -> Lambda
- Removes SNS<->APIGW resource-policy coupling and VPC Link to SNS
- Preserves your VTL templates, models, alarms, WAF, etc.
"""

import json
from typing import Dict, Any

from aws_cdk import (
    Stack, Duration, Tags, CfnOutput, RemovalPolicy,
    aws_apigateway as apigw,
    aws_certificatemanager as acm,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_lambda_event_sources as lambda_event_sources,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
    aws_sns as sns,
    aws_sns_subscriptions as subscriptions,
    aws_sqs as sqs,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_ssm as ssm,
    aws_logs as logs,
    aws_wafv2 as wafv2,
    aws_cloudwatch as cloudwatch,
    aws_kms as kms,
)
from constructs import Construct


class APIGWStack(Stack):
    """
    An AWS CDK Stack that creates a private API Gateway with a fan-out pattern
    using SNS and SQS, deployed within a VPC with proper networking components.
    """

    def __init__(self, scope: Construct, id: str, props: Dict[str, Any], **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Apply tags to all resources in this stack
        self._apply_tags(props)

        # Create VPC and network infrastructure
        vpc = self._create_vpc_infrastructure(props)

        # Create NLB and VPC Link (left as-is, though SNS is not behind VPC)
        nlb, vpc_link = self._create_nlb_and_vpc_link(vpc)

        # Create VPC Endpoints
        self._create_vpc_endpoints(vpc)

        # Create KMS key for encryption
        kms_key = self._create_kms_key()

        # Create the IAM Role that API Gateway will assume to publish to SNS
        api_gw_sns_role = iam.Role(
            self, 'ApiGatewaySNSRole',
            assumed_by=iam.ServicePrincipal('apigateway.amazonaws.com'),
            description="Role for API Gateway to publish to SNS"
        )

        # Create SNS Topic (grant publish to the APIGW role)
        topic = self._create_sns_topic(api_gw_sns_role, kms_key)

        # Create SQS Queues and Subscriptions
        created_status_queue, other_status_queue = self._create_sqs_queues_and_subscriptions(
            topic)

        # Create Lambda Functions
        self._create_lambda_functions(created_status_queue, other_status_queue)

        # Set up Route53 and Certificate
        route53_zone, cert = self._setup_route53_and_certificate(props)

        # Create API Gateway (now uses AWS integration to SNS; VpcLink NOT used)
        gateway, custom_domain_name = self._create_api_gateway(
            vpc_link, topic, route53_zone, cert, props, api_gw_sns_role)

        # Create WAF for API Gateway
        self._create_waf_for_api_gateway(gateway)

        # Create CloudWatch Alarms
        self._create_cloudwatch_alarms(
            gateway, topic, created_status_queue, other_status_queue)

        # Create Outputs
        self._create_outputs(vpc, custom_domain_name)

    def _apply_tags(self, props: Dict[str, Any]) -> None:
        Tags.of(self).add("project", props["namespace"])
        Tags.of(self).add("environment", props.get("environment", "dev"))
        Tags.of(self).add("owner", props.get("owner", "cdk-deployment"))
        Tags.of(self).add("created-by", "aws-cdk")

    def _create_vpc_infrastructure(self, props: Dict[str, Any]) -> ec2.Vpc:
        vpc = ec2.Vpc(
            self, 'ApiGWVPC',
            ip_addresses=ec2.IpAddresses.cidr(props["vpc_cidr"]),
            max_azs=2,
            enable_dns_hostnames=True,
            enable_dns_support=True,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name='Public-Subnet',
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=26
                ),
                ec2.SubnetConfiguration(
                    name='Private-Subnet',
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=26
                )
            ],
            nat_gateways=1,
            flow_logs={
                'flow-logs': {
                    'destination': ec2.FlowLogDestination.to_cloud_watch_logs(
                        logs.LogGroup(
                            self, 'VpcFlowLogs',
                            retention=logs.RetentionDays.ONE_MONTH,
                            removal_policy=RemovalPolicy.DESTROY
                        )
                    ),
                    'traffic_type': ec2.FlowLogTrafficType.ALL
                }
            }
        )

        priv_subnets = [subnet.subnet_id for subnet in vpc.private_subnets]
        for idx, psub in enumerate(priv_subnets, 1):
            ssm.StringParameter(
                self, f'private-subnet-{idx}',
                string_value=psub,
                parameter_name=f'/{props["namespace"]}/private-subnet-{idx}',
                description=f'Private subnet {idx} ID for {props["namespace"]}',
                tier=ssm.ParameterTier.STANDARD
            )

        return vpc

    def _create_nlb_and_vpc_link(self, vpc: ec2.Vpc) -> tuple[elbv2.NetworkLoadBalancer, apigw.VpcLink]:
        nlb = elbv2.NetworkLoadBalancer(
            self, "NLB",
            vpc=vpc,
            internet_facing=False,
            cross_zone_enabled=True
        )

        health_listener = nlb.add_listener("HealthListener", port=80)

        target_group = elbv2.NetworkTargetGroup(
            self, "HealthTargetGroup",
            vpc=vpc,
            port=80,
            protocol=elbv2.Protocol.TCP,
            health_check=elbv2.HealthCheck(
                enabled=True,
                protocol=elbv2.Protocol.TCP,
                healthy_threshold_count=2,
                unhealthy_threshold_count=2
            )
        )

        health_listener.add_target_groups("HealthTargetGroup", target_group)

        vpc_link = apigw.VpcLink(
            self, "PrivateLink",
            targets=[nlb],
            description=f"VPC Link for Private API Gateway in {vpc.vpc_id}"
        )

        return nlb, vpc_link

    def _create_vpc_endpoints(self, vpc: ec2.Vpc) -> None:
        security_group = ec2.SecurityGroup(
            self, "VpcEndpointSG",
            vpc=vpc,
            description="Security Group for VPC Endpoints",
            allow_all_outbound=True
        )

        security_group.add_ingress_rule(
            ec2.Peer.ipv4(vpc.vpc_cidr_block),
            ec2.Port.all_traffic(),
            "Allow all traffic from within VPC"
        )

        endpoint_config = {
            "SNSVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.SNS,
            "SQSVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.SQS,
            "LambdaVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.LAMBDA_,
            "ELBVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.ELASTIC_LOAD_BALANCING,
            "APIGatewayVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.APIGATEWAY,
            "CloudWatchVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH,
            "CloudWatchLogsVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
            "KMSVPCEndpoint": ec2.InterfaceVpcEndpointAwsService.KMS,
        }

        for name, service in endpoint_config.items():
            ec2.InterfaceVpcEndpoint(
                self, name,
                vpc=vpc,
                service=service,
                private_dns_enabled=True,
                security_groups=[security_group],
                subnets=ec2.SubnetSelection(
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS)
            )

    def _create_kms_key(self) -> kms.Key:
        key = kms.Key(
            self, "MessageEncryptionKey",
            description="Key for encrypting SNS and SQS messages",
            enable_key_rotation=True,
            policy=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=["kms:*"],
                        resources=["*"],
                        principals=[iam.AccountRootPrincipal()]
                    ),
                    iam.PolicyStatement(
                        actions=["kms:Decrypt", "kms:GenerateDataKey*"],
                        resources=["*"],
                        principals=[
                            iam.ServicePrincipal("sns.amazonaws.com"),
                            iam.ServicePrincipal("sqs.amazonaws.com"),
                            iam.ServicePrincipal("lambda.amazonaws.com")
                        ]
                    )
                ]
            )
        )

        kms.Alias(
            self, "MessageEncryptionKeyAlias",
            alias_name="alias/api-gateway-fanout-key",
            target_key=key
        )

        return key

    def _create_sns_topic(self, api_gw_sns_role: iam.Role, kms_key: kms.Key) -> sns.Topic:
        """Create SNS Topic for API Gateway fan-out pattern and allow APIGW role to publish."""
        topic = sns.Topic(
            self, 'ApiGWFanTopic',
            display_name='The Big Fan CDK Pattern Topic',
            topic_name='api-gateway-fan-out-topic',
            master_key=kms_key,
            fifo=False,
            content_based_deduplication=False
        )

        # IMPORTANT: Do NOT attach a separate topic resource policy granting apigateway service principal.
        # Rely solely on a grant to the specific APIGW role to avoid circular dependencies.
        topic.grant_publish(api_gw_sns_role)

        return topic

    def _create_sqs_queues_and_subscriptions(self, topic: sns.ITopic):
        created_status_queue = sqs.Queue(self, "CreatedStatusQueue")
        other_status_queue = sqs.Queue(self, "OtherStatusQueue")


        # Correct SNS -> SQS subscriptions
        topic.add_subscription(subscriptions.SqsSubscription(created_status_queue))
        topic.add_subscription(subscriptions.SqsSubscription(other_status_queue))


        return created_status_queue, other_status_queue

    def _create_lambda_functions(self, created_status_queue: sqs.Queue, other_status_queue: sqs.Queue) -> None:
        lambda_tracing_config = lambda_.Tracing.ACTIVE
        lambda_log_retention = logs.RetentionDays.ONE_WEEK

        sqs_created_status_subscriber = lambda_.Function(
            self, "SQSCreatedStatusSubscribeLambdaHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="createdStatus.handler",
            code=lambda_.Code.from_asset("lambda_fns/subscribe"),
            tracing=lambda_tracing_config,
            retry_attempts=2,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
                "POWERTOOLS_SERVICE_NAME": "created-status-processor",
                "POWERTOOLS_METRICS_NAMESPACE": "ApiGatewayFanOut"
            },
            log_retention=lambda_log_retention
        )

        created_status_queue.grant_consume_messages(
            sqs_created_status_subscriber)
        sqs_created_status_subscriber.add_event_source(
            lambda_event_sources.SqsEventSource(
                created_status_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(5),
                report_batch_item_failures=True
            )
        )

        sqs_other_status_subscriber = lambda_.Function(
            self, "SQSAnyOtherStatusSubscribeLambdaHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            handler="anyOtherStatus.handler",
            code=lambda_.Code.from_asset("lambda_fns/subscribe"),
            tracing=lambda_tracing_config,
            retry_attempts=2,
            timeout=Duration.seconds(30),
            memory_size=128,
            environment={
                "LOG_LEVEL": "INFO",
                "POWERTOOLS_SERVICE_NAME": "other-status-processor",
                "POWERTOOLS_METRICS_NAMESPACE": "ApiGatewayFanOut"
            },
            log_retention=lambda_log_retention
        )

        other_status_queue.grant_consume_messages(sqs_other_status_subscriber)
        sqs_other_status_subscriber.add_event_source(
            lambda_event_sources.SqsEventSource(
                other_status_queue,
                batch_size=10,
                max_batching_window=Duration.seconds(5),
                report_batch_item_failures=True
            )
        )

    def _setup_route53_and_certificate(self, props: Dict[str, Any]) -> tuple[route53.IHostedZone, acm.ICertificate]:
        zone_name = props["hosted_zone_name"]
        route53_zone = route53.HostedZone.from_hosted_zone_attributes(
            self, "ImportedZone",
            hosted_zone_id=props["hosted_zone_id"],
            zone_name=zone_name
        )

        cert = acm.Certificate.from_certificate_arn(
            self, "ImportedWildcardCert",
            certificate_arn=props["cert_arn"]
        )

        return route53_zone, cert

    def _create_api_gateway(
        self,
        vpc_link: apigw.VpcLink,  # unused now for SNS, kept for compatibility
        topic: sns.Topic,
        route53_zone: route53.IHostedZone,
        cert: acm.ICertificate,
        props: Dict[str, Any],
        api_gw_sns_role: iam.Role,
    ) -> tuple[apigw.RestApi, apigw.DomainName]:
        # Access logs
        access_log_group = logs.LogGroup(
            self, "ApiGatewayAccessLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY
        )

        gateway = apigw.RestApi(
            self, 'ApiGWFanAPI',
            rest_api_name=f"{props['namespace']}-private-api",
            description="Private API Gateway with fan-out pattern",
            deploy_options=apigw.StageOptions(
                stage_name='prod',
                metrics_enabled=True,
                logging_level=apigw.MethodLoggingLevel.INFO,
                data_trace_enabled=True,
                access_log_destination=apigw.LogGroupLogDestination(
                    access_log_group),
                access_log_format=apigw.AccessLogFormat.json_with_standard_fields(
                    caller=True,
                    http_method=True,
                    ip=True,
                    protocol=True,
                    request_time=True,
                    resource_path=True,
                    response_length=True,
                    status=True,
                    user=True
                ),
                throttling_rate_limit=1000,
                throttling_burst_limit=500,
                tracing_enabled=True
            ),
            endpoint_types=[apigw.EndpointType.PRIVATE],
            policy=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        actions=["execute-api:Invoke"],
                        principals=[iam.AnyPrincipal()],
                        resources=["execute-api:/*"],
                        effect=iam.Effect.ALLOW,
                        conditions={
                            "StringEquals": {
                                "aws:SourceVpc": props.get("vpc_id", "${aws:SourceVpc}")
                            }
                        }
                    )
                ]
            )
        )

        # Request validator
        validator = gateway.add_request_validator(
            "RequestValidator",
            validate_request_body=True,
            validate_request_parameters=True
        )

        # Usage plan & key
        gateway_usage_plan = apigw.UsagePlan(
            self, "GWUsagePlan",
            name=f"{gateway.rest_api_name}-usageplan",
            description="API Gateway Unlimited Use",
            throttle=apigw.ThrottleSettings(rate_limit=1000, burst_limit=500),
            quota=apigw.QuotaSettings(limit=10000, period=apigw.Period.DAY)
        )

        gateway_api_key = gateway.add_api_key(
            props["custom_domain_name"],
            description=f"{gateway.rest_api_name}-apikey"
        )
        gateway_usage_plan.add_api_key(gateway_api_key)

        # Custom domain (note: private REST APIs don't support custom domains in AWS; kept to match original)
        custom_domain_name = self._apigw_custom_domain(cert, gateway, props)

        apigw.BasePathMapping(
            self, "APIGwMapping",
            base_path=props["namespace"],
            domain_name=custom_domain_name,
            rest_api=gateway
        )

        # === Models ===
        request_model = gateway.add_model(
            'RequestModel',
            content_type='application/json',
            model_name='RequestModel',
            schema=apigw.JsonSchema(
                schema=apigw.JsonSchemaVersion.DRAFT4,
                title='messageRequest',
                type=apigw.JsonSchemaType.OBJECT,
                required=['message', 'status'],
                properties={
                    'message': apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                    'status': apigw.JsonSchema(type=apigw.JsonSchemaType.STRING)
                }
            )
        )

        response_model = gateway.add_model(
            'ResponseModel',
            content_type='application/json',
            model_name='ResponseModel',
            schema=apigw.JsonSchema(
                schema=apigw.JsonSchemaVersion.DRAFT4,
                title='pollResponse',
                type=apigw.JsonSchemaType.OBJECT,
                properties={'message': apigw.JsonSchema(
                    type=apigw.JsonSchemaType.STRING)}
            )
        )

        error_response_model = gateway.add_model(
            'ErrorResponseModel',
            content_type='application/json',
            model_name='ErrorResponseModel',
            schema=apigw.JsonSchema(
                schema=apigw.JsonSchemaVersion.DRAFT4,
                title='errorResponse',
                type=apigw.JsonSchemaType.OBJECT,
                properties={
                    'state': apigw.JsonSchema(type=apigw.JsonSchemaType.STRING),
                    'message': apigw.JsonSchema(type=apigw.JsonSchemaType.STRING)
                }
            )
        )

        # === VTL templates preserved ===
        request_template = (
            "Action=Publish&"
            f"TargetArn=$util.urlEncode('{topic.topic_arn}')&"
            "Message=$util.urlEncode($input.path('$.message'))&"
            "Version=2010-03-31&"
            "MessageAttributes.entry.1.Name=status&"
            "MessageAttributes.entry.1.Value.DataType=String&"
            "MessageAttributes.entry.1.Value.StringValue=$util.urlEncode($input.path('$.status'))"
        )

        error_template = {
            "state": 'error',
            "message": "$util.escapeJavaScript($input.path('$.errorMessage'))"
        }
        error_template_string = json.dumps(
            error_template, separators=(',', ':'))

        # === Integration: AWS Service (SNS) — NO VPC LINK ===
        sns_integration = apigw.AwsIntegration(
            service='sns',
            action='Publish',
            integration_http_method='POST',
            options=apigw.IntegrationOptions(
                credentials_role=api_gw_sns_role,
                request_parameters={
                    'integration.request.header.Content-Type': "'application/x-www-form-urlencoded'"
                },
                request_templates={
                    'application/json': request_template
                },
                passthrough_behavior=apigw.PassthroughBehavior.NEVER,
                integration_responses=[
                    apigw.IntegrationResponse(
                        status_code='200',
                        response_templates={
                            'application/json': json.dumps({"message": 'message added to topic'})
                        },
                        response_parameters={
                            'method.response.header.Content-Type': "'application/json'",
                            'method.response.header.Access-Control-Allow-Origin': "'*'",
                            'method.response.header.Access-Control-Allow-Credentials': "'true'"
                        }
                    ),
                    apigw.IntegrationResponse(
                        selection_pattern=r"^\\[Error\\].*",
                        status_code='400',
                        response_templates={
                            'application/json': error_template_string
                        },
                        response_parameters={
                            'method.response.header.Content-Type': "'application/json'",
                            'method.response.header.Access-Control-Allow-Origin': "'*'",
                            'method.response.header.Access-Control-Allow-Credentials': "'true'"
                        }
                    )
                ]
            )
        )

        # Resource & Methods
        send_event_resource = gateway.root.add_resource('SendEvent')

        # CORS preflight
        send_event_resource.add_method(
            'OPTIONS',
            apigw.MockIntegration(
                integration_responses=[
                    apigw.IntegrationResponse(
                        status_code='200',
                        response_parameters={
                            'method.response.header.Access-Control-Allow-Headers': "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'",
                            'method.response.header.Access-Control-Allow-Methods': "'OPTIONS,POST'",
                            'method.response.header.Access-Control-Allow-Origin': "'*'"
                        }
                    )
                ],
                passthrough_behavior=apigw.PassthroughBehavior.NEVER,
                request_templates={"application/json": '{"statusCode": 200}'}
            ),
            method_responses=[
                apigw.MethodResponse(
                    status_code='200',
                    response_parameters={
                        'method.response.header.Access-Control-Allow-Headers': True,
                        'method.response.header.Access-Control-Allow-Methods': True,
                        'method.response.header.Access-Control-Allow-Origin': True
                    }
                )
            ]
        )

        # POST method using SNS service integration
        send_event_resource.add_method(
            'POST',
            sns_integration,
            request_models={'application/json': request_model},
            request_validator=validator,
            api_key_required=True,
            method_responses=[
                apigw.MethodResponse(
                    status_code='200',
                    response_parameters={
                        'method.response.header.Content-Type': True,
                        'method.response.header.Access-Control-Allow-Origin': True,
                        'method.response.header.Access-Control-Allow-Credentials': True
                    },
                    response_models={'application/json': response_model}
                ),
                apigw.MethodResponse(
                    status_code='400',
                    response_parameters={
                        'method.response.header.Content-Type': True,
                        'method.response.header.Access-Control-Allow-Origin': True,
                        'method.response.header.Access-Control-Allow-Credentials': True
                    },
                    response_models={'application/json': error_response_model}
                ),
            ]
        )

        # DNS (alias record to API; kept as in original)
        self._r53_dns_record(gateway, route53_zone, props)

        return gateway, custom_domain_name

    def _create_waf_for_api_gateway(self, gateway: apigw.RestApi) -> None:
        web_acl = wafv2.CfnWebACL(
            self, "ApiGatewayWAF",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            scope="REGIONAL",
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name="ApiGatewayWAF",
                sampled_requests_enabled=True
            ),
            rules=[
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitRule",
                    priority=1,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=1000,
                            aggregate_key_type="IP"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="RateLimitRule",
                        sampled_requests_enabled=True
                    )
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=2,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(
                        none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesCommonRuleSet",
                        sampled_requests_enabled=True
                    )
                ),
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesSQLiRuleSet",
                    priority=3,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(
                        none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesSQLiRuleSet"
                        )
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesSQLiRuleSet",
                        sampled_requests_enabled=True
                    )
                )
            ]
        )

        wafv2.CfnWebACLAssociation(
            self, "ApiGatewayWAFAssociation",
            resource_arn=f"arn:aws:apigateway:{self.region}::/restapis/{gateway.rest_api_id}/stages/prod",
            web_acl_arn=web_acl.attr_arn
        )

    def _create_cloudwatch_alarms(
        self,
        gateway: apigw.RestApi,
        topic: sns.Topic,
        created_status_queue: sqs.Queue,
        other_status_queue: sqs.Queue
    ) -> None:
        cloudwatch.Alarm(
            self, "ApiGateway4XXErrorsAlarm",
            metric=gateway.metric_client_error(),
            evaluation_periods=1,
            threshold=10,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Alarm if API Gateway returns too many 4XX errors"
        )

        cloudwatch.Alarm(
            self, "ApiGateway5XXErrorsAlarm",
            metric=gateway.metric_server_error(),
            evaluation_periods=1,
            threshold=5,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Alarm if API Gateway returns too many 5XX errors"
        )

        cloudwatch.Alarm(
            self, "ApiGatewayLatencyAlarm",
            metric=gateway.metric_latency(),
            evaluation_periods=3,
            threshold=1000,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Alarm if API Gateway latency is too high"
        )

        cloudwatch.Alarm(
            self, "SNSThrottledAlarm",
            metric=cloudwatch.Metric(
                namespace="AWS/SNS",
                metric_name="NumberOfNotificationsFilteredOut",
                dimensions_map={"TopicName": topic.topic_name},
                statistic="Sum"
            ),
            evaluation_periods=1,
            threshold=5,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Alarm if SNS messages are being throttled"
        )

        cloudwatch.Alarm(
            self, "CreatedStatusQueueAgeAlarm",
            metric=created_status_queue.metric_approximate_age_of_oldest_message(),
            evaluation_periods=1,
            threshold=300,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Alarm if messages in created status queue are too old"
        )

        cloudwatch.Alarm(
            self, "OtherStatusQueueAgeAlarm",
            metric=other_status_queue.metric_approximate_age_of_oldest_message(),
            evaluation_periods=1,
            threshold=300,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description="Alarm if messages in other status queue are too old"
        )

    def _apigw_custom_domain(
        self,
        cert: acm.ICertificate,
        gateway: apigw.RestApi,
        props: Dict[str, Any]
    ) -> apigw.DomainName:
        custom_domain_name = gateway.add_domain_name(
            "DomainName",
            domain_name=props["custom_domain_name"],
            security_policy=apigw.SecurityPolicy.TLS_1_2,
            certificate=acm.Certificate.from_certificate_arn(
                self, "APIGWCert",
                cert.certificate_arn
            )
        )
        return custom_domain_name

    def _r53_dns_record(
        self,
        gateway: apigw.RestApi,
        route53_zone_creation: route53.IHostedZone,
        props: Dict[str, Any]
    ) -> None:
        route53.ARecord(
            self, "AliasRecord",
            zone=route53_zone_creation,
            target=route53.RecordTarget.from_alias(
                route53_targets.ApiGateway(gateway)),
            record_name=props["custom_domain_name"],
            ttl=Duration.minutes(5)
        )

    def _create_outputs(self, vpc: ec2.Vpc, custom_domain_name: apigw.DomainName) -> None:
        CfnOutput(self, "VPC_ID", description="VPC ID",
                  export_name="vpcid", value=vpc.vpc_id)
        CfnOutput(self, "VPC_ARN", description="VPC ARN",
                  export_name="vpcarn", value=vpc.vpc_arn)
        CfnOutput(
            self, "CUSTOM_DOMAIN_ADDR",
            description="CUSTOM DOMAIN ADDRESS",
            export_name="cust-domain-addr",
            value="https://" + custom_domain_name.domain_name + "/"
        )
        CfnOutput(
            self, "API_ENDPOINT",
            description="API Gateway Endpoint",
            export_name="api-endpoint",
            value="https://" + custom_domain_name.domain_name + "/"
        )
