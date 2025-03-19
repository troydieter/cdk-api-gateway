import json
from aws_cdk import Stack, Duration, Tags
from aws_cdk.aws_apigateway import (RestApi, StageOptions, MethodLoggingLevel,
                                    Integration, IntegrationType, IntegrationOptions,
                                    PassthroughBehavior, IntegrationResponse, UsagePlan,
                                    SecurityPolicy, BasePathMapping)
from aws_cdk.aws_iam import Role, ServicePrincipal
from aws_cdk.aws_lambda import Function, Runtime, Code
from aws_cdk.aws_lambda_event_sources import SqsEventSource
from aws_cdk.aws_route53 import HostedZone, ARecord, RecordTarget
from aws_cdk.aws_route53_targets import ApiGateway
from aws_cdk.aws_sns import Topic, SubscriptionFilter
from aws_cdk.aws_sns_subscriptions import SqsSubscription
from aws_cdk.aws_sqs import Queue, DeadLetterQueue
from aws_cdk.aws_certificatemanager import Certificate
from aws_cdk.aws_wafv2 import CfnWebACL, CfnWebACLAssociation
from cdk_watchful import Watchful
from constructs import Construct


class SNSConstruct(Construct):
    def __init__(self, scope: Construct, id: str) -> None:
        super().__init__(scope, id)

        self.topic = Topic(self, "ApiGWFanTopic",
                           display_name="APIGW Incoming SNS Topic")

        # Dead Letter Queue (DLQ)
        self.dlq = Queue(self, "SNSDLQ",
                         queue_name="SNSDLQ",
                         retention_period=Duration.days(14))

        # Created Status Queue
        self.created_status_queue = Queue(self, "BigFanStatusCreatedQueue",
                                          visibility_timeout=Duration.seconds(
                                              300),
                                          dead_letter_queue=DeadLetterQueue(queue=self.dlq, max_receive_count=5))
        self.topic.add_subscription(SqsSubscription(self.created_status_queue,
                                                    raw_message_delivery=True,
                                                    filter_policy={"status": SubscriptionFilter.string_filter(allowlist=["created"])})
                                    )

        # Other Status Queue
        self.other_status_queue = Queue(self, "BigFanAnyOtherStatusQueue",
                                        visibility_timeout=Duration.seconds(
                                            300),
                                        dead_letter_queue=DeadLetterQueue(queue=self.dlq, max_receive_count=5))
        self.topic.add_subscription(SqsSubscription(self.other_status_queue,
                                                    raw_message_delivery=True,
                                                    filter_policy={"status": SubscriptionFilter.string_filter(denylist=["created"])})
                                    )


class LambdaConstruct(Construct):
    def __init__(self, scope: Construct, id: str, sns_construct: SNSConstruct) -> None:
        super().__init__(scope, id)

        # Created status queue lambda
        self.sqs_created_status_subscriber = Function(self, "SQSCreatedStatusSubscriber",
                                                      runtime=Runtime.PYTHON_3_8,
                                                      handler="createdStatus.handler",
                                                      code=Code.from_asset("lambda_fns/subscribe"))
        sns_construct.created_status_queue.grant_consume_messages(
            self.sqs_created_status_subscriber)
        self.sqs_created_status_subscriber.add_event_source(
            SqsEventSource(sns_construct.created_status_queue))

        # Other status queue lambda
        self.sqs_other_status_subscriber = Function(self, "SQSOtherStatusSubscriber",
                                                    runtime=Runtime.PYTHON_3_8,
                                                    handler="anyOtherStatus.handler",
                                                    code=Code.from_asset("lambda_fns/subscribe"))
        sns_construct.other_status_queue.grant_consume_messages(
            self.sqs_other_status_subscriber)
        self.sqs_other_status_subscriber.add_event_source(
            SqsEventSource(sns_construct.other_status_queue))


class APIGatewayConstruct(Construct):
    def __init__(self, scope: Construct, id: str, topic: Topic, props) -> None:
        super().__init__(scope, id)

        self.gateway = RestApi(self, "ApiGWFanAPI",
                               deploy_options=StageOptions(metrics_enabled=True,
                                                           logging_level=MethodLoggingLevel.INFO,
                                                           data_trace_enabled=True,
                                                           stage_name='prod'),
                               description="API GW Fanout Example")

        self.usage_plan = UsagePlan(self, "GWUsagePlan",
                                    name=f"{self.gateway.rest_api_name}-usageplan",
                                    description="API Gateway Unlimited Use")

        self.api_key = self.gateway.add_api_key(props["custom_domain_name"],
                                                description=f"{self.gateway.rest_api_name}-apikey")
        self.usage_plan.add_api_key(self.api_key)

        # IAM Role for API Gateway to publish SNS messages
        self.api_gw_sns_role = Role(self, "APIGatewaySNSRole",
                                    assumed_by=ServicePrincipal("apigateway.amazonaws.com"))
        topic.grant_publish(self.api_gw_sns_role)

        request_template = """
            Action=Publish&
            TargetArn=$util.urlEncode('{}')&
            Message=$util.urlEncode($input.path('$.message'))&
            Version=2010-03-31&
            MessageAttributes.entry.1.Name=status&
            MessageAttributes.entry.1.Value.DataType=String&
            MessageAttributes.entry.1.Value.StringValue=$util.urlEncode($input.path('$.status'))
        """.format(topic.topic_arn)

        integration_options = IntegrationOptions(
            credentials_role=self.api_gw_sns_role,
            request_parameters={
                'integration.request.header.Content-Type': "'application/x-www-form-urlencoded'"
            },
            request_templates={
                "application/json": request_template.strip()
            },
            passthrough_behavior=PassthroughBehavior.NEVER,
            integration_responses=[
                IntegrationResponse(status_code='200', response_templates={
                                    "application/json": json.dumps({"message": "message added to topic"})}),
                IntegrationResponse(selection_pattern="^\\[Error\\].*", status_code='400', response_templates={
                                    "application/json": json.dumps({"state": "error", "message": "$util.escapeJavaScript($input.path('$.errorMessage'))"})})
            ]
        )

        send_event_resource = self.gateway.root.add_resource("SendEvent")
        send_event_resource.add_method("POST", Integration(type=IntegrationType.AWS,
                                                           integration_http_method="POST",
                                                           uri="arn:aws:apigateway:us-east-1:sns:path//",
                                                           options=integration_options))

        # Import the domain certificate
        cert = Certificate.from_certificate_arn(
            self, "ImportedWildcardCert", certificate_arn=props["cert_arn"])

        # Define the custom domain name
        custom_domain_name = self.gateway.add_domain_name("CustomDomain",
                                                          domain_name=props["custom_domain_name"],
                                                          security_policy=SecurityPolicy.TLS_1_2,
                                                          certificate=cert)

        # Ensure API Gateway uses this domain
        BasePathMapping(self, "APIGwMapping",
                        base_path=props["namespace"],
                        domain_name=custom_domain_name,
                        rest_api=self.gateway)

        api_web_acl = CfnWebACL(self, "ApiWebACL",
            description="API Gateway WAF WEB ACL",
            default_action=CfnWebACL.DefaultActionProperty(allow={}),
            scope="REGIONAL",
            visibility_config=CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name="ApiWebACLMetric",
                sampled_requests_enabled=True
            ),
            rules=[
                # AWS Managed Rules
                CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=1,
                    override_action=CfnWebACL.OverrideActionProperty(none={}),
                    statement=CfnWebACL.StatementProperty(
                        managed_rule_group_statement=CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet"
                        )
                    ),
                    visibility_config=CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSManagedRulesCommonRuleSetMetric",
                        sampled_requests_enabled=True
                    )
                ),
                # Rate-limiting rule: Block IPs exceeding 100 requests per 5 minutes
                CfnWebACL.RuleProperty(
                    name="LimitRequests100",
                    priority=2,
                    action=CfnWebACL.RuleActionProperty(block={}),
                    statement=CfnWebACL.StatementProperty(
                        rate_based_statement=CfnWebACL.RateBasedStatementProperty(
                            aggregate_key_type="IP",
                            limit=100
                        )
                    ),
                    visibility_config=CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="LimitRequests100Metric",
                        sampled_requests_enabled=True
                    )
                )
            ]
        )

        # Associate the ACL with the AWS WAF
        CfnWebACLAssociation(self, "WafAssociation",
            resource_arn=self.gateway.deployment_stage.stage_arn,
            web_acl_arn=api_web_acl.attr_arn
        )


class APIGWStack(Stack):
    def __init__(self, scope: Construct, id: str, props, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        Tags.of(self).add("project", props["namespace"])
        Tags.of(self).add("api_endpoint", props["custom_domain_name"])
        Watchful(self, "Watchful",
                 alarm_email=props["alarm_email"]).watch_scope(self)

        sns_construct = SNSConstruct(self, "SNSConstruct")
        lambda_construct = LambdaConstruct(
            self, "LambdaConstruct", sns_construct)
        api_gw_construct = APIGatewayConstruct(
            self, "APIGatewayConstruct", sns_construct.topic, props)

        hosted_zone = HostedZone.from_hosted_zone_attributes(self, "ImportedZone",
                                                             hosted_zone_id=props["hosted_zone_id"],
                                                             zone_name=props["hosted_zone_name"])

        ARecord(self, "AliasRecord", zone=hosted_zone,
                target=RecordTarget.from_alias(
                    ApiGateway(api_gw_construct.gateway)),
                record_name=props["custom_domain_name"])
