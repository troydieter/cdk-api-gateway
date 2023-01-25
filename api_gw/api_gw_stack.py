import json

from aws_cdk import Stack, Duration, Tags, CfnOutput
from aws_cdk.aws_apigateway import StageOptions, RestApi, JsonSchema, JsonSchemaType, JsonSchemaVersion, \
    IntegrationOptions, PassthroughBehavior, Integration, IntegrationType, MethodResponse, MethodLoggingLevel, \
    IntegrationResponse, BasePathMapping, SecurityPolicy, UsagePlan, VpcLink, ConnectionType
from aws_cdk.aws_certificatemanager import Certificate
from aws_cdk.aws_iam import Role, ServicePrincipal
from aws_cdk.aws_lambda import Function, Runtime, Code
from aws_cdk.aws_lambda_event_sources import SqsEventSource
from aws_cdk.aws_route53 import HostedZone, ARecord, RecordTarget
from aws_cdk.aws_route53_targets import ApiGateway
from aws_cdk.aws_sns import Topic, SubscriptionFilter
from aws_cdk.aws_sns_subscriptions import SqsSubscription
from aws_cdk.aws_sqs import Queue
from aws_cdk.aws_ec2 import Vpc, SubnetConfiguration, SubnetType, IpAddresses, InterfaceVpcEndpoint, InterfaceVpcEndpointService, SubnetSelection, InterfaceVpcEndpointAwsService
from aws_cdk.aws_elasticloadbalancingv2 import NetworkLoadBalancer
from aws_cdk.aws_ssm import StringParameter
from constructs import Construct


class APIGWStack(Stack):

    def __init__(self, scope: Construct, id: str, props, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        ###
        # Tag everything
        Tags.of(self).add("project", props["namespace"])

        ###
        # Provision the VPC
        vpc = Vpc(self, 'ApiGWVPC',
                  ip_addresses=IpAddresses.cidr("192.168.31.0/20"),
                  max_azs=2,
                  enable_dns_hostnames=True,
                  enable_dns_support=True,
                  subnet_configuration=[
                      SubnetConfiguration(
                          name='Public-Subnet',
                          subnet_type=SubnetType.PUBLIC,
                          cidr_mask=26
                      ),
                      SubnetConfiguration(
                          name='Private-Subnet',
                          subnet_type=SubnetType.PRIVATE_WITH_EGRESS,
                          cidr_mask=26
                      )
                  ],
                  nat_gateways=1,
                  )

        priv_subnets = [subnet.subnet_id for subnet in vpc.private_subnets]

        count = 1
        for psub in priv_subnets:
            StringParameter(self, 'private-subnet-' + str(count),
                            string_value=psub,
                            parameter_name='/' + props["namespace"] + '/private-subnet-' + str(count)
                            )
            count += 1

        ###
        # Create the NLB and privatelink
        nlb = NetworkLoadBalancer(self, "NLB", vpc=vpc)
        link = VpcLink(self, "PrivateLink", targets=[nlb])

        ###
        # Create the VPC Endpoints
        InterfaceVpcEndpoint(self, "SNSVPCEndpoint", vpc=vpc, service=InterfaceVpcEndpointAwsService.SNS)
        InterfaceVpcEndpoint(self, "SQSVPCEndpoint", vpc=vpc, service=InterfaceVpcEndpointAwsService.SQS)
        InterfaceVpcEndpoint(self, "LambdaVPCEndpoint", vpc=vpc, service=InterfaceVpcEndpointAwsService.LAMBDA_)
        InterfaceVpcEndpoint(self, "ELBVPCEndpoint", vpc=vpc, service=InterfaceVpcEndpointAwsService.ELASTIC_LOAD_BALANCING)

        ###
        # SNS Topic Creation
        # Our API Gateway posts messages directly to this
        ###
        topic = Topic(self, 'ApiGWFanTopic', display_name='The Big Fan CDK Pattern Topic')

        ###
        # SQS Subscribers creation for our SNS Topic
        # 2 subscribers, one for messages with a status of created one for any other message
        ###

        # Status:created SNS Subscriber Queue
        created_status_queue = Queue(self, 'BigFanTopicStatusCreatedSubscriberQueue',
                                     visibility_timeout=Duration.seconds(300),
                                     queue_name='BigFanTopicStatusCreatedSubscriberQueue')

        # Only send messages to our created_status_queue with a status of created
        created_filter = SubscriptionFilter.string_filter(allowlist=['created'])
        topic.add_subscription(SqsSubscription(created_status_queue,
                                               raw_message_delivery=True,
                                               filter_policy={'status': created_filter}))

        # Any other status SNS Subscriber Queue
        other_status_queue = Queue(self, 'BigFanTopicAnyOtherStatusSubscriberQueue',
                                   visibility_timeout=Duration.seconds(300),
                                   queue_name='BigFanTopicAnyOtherStatusSubscriberQueue')

        # Only send messages to our other_status_queue that do not have a status of created
        other_filter = SubscriptionFilter.string_filter(denylist=['created'])
        topic.add_subscription(SqsSubscription(other_status_queue,
                                               raw_message_delivery=True,
                                               filter_policy={'status': other_filter}))

        ###
        # Creation of Lambdas that subscribe to above SQS queues
        ###

        # Created status queue lambda
        sqs_created_status_subscriber = Function(self, "SQSCreatedStatusSubscribeLambdaHandler",
                                                 runtime=Runtime.PYTHON_3_8,
                                                 handler="createdStatus.handler",
                                                 code=Code.from_asset("lambda_fns/subscribe")
                                                 )
        created_status_queue.grant_consume_messages(sqs_created_status_subscriber)
        sqs_created_status_subscriber.add_event_source(SqsEventSource(created_status_queue))

        # Any other status queue lambda
        sqs_other_status_subscriber = Function(self, "SQSAnyOtherStatusSubscribeLambdaHandler",
                                               runtime=Runtime.PYTHON_3_8,
                                               handler="anyOtherStatus.handler",
                                               code=Code.from_asset("lambda_fns/subscribe")
                                               )
        other_status_queue.grant_consume_messages(sqs_other_status_subscriber)
        sqs_other_status_subscriber.add_event_source(SqsEventSource(other_status_queue))

        ###
        # Provision the custom domain
        ###
        zone_name = props["hosted_zone_name"]
        route53_zone_import = HostedZone.from_hosted_zone_attributes(self, "ImportedZone",
                                                                     hosted_zone_id=props["hosted_zone_id"],
                                                                     zone_name=zone_name)
        cert = Certificate.from_certificate_arn(self, "ImportedWildcardCert", certificate_arn=props["cert_arn"])

        ###
        # API Gateway Creation
        # This is complicated because it transforms the incoming json payload into a query string url
        # this url is used to post the payload to sns without a lambda inbetween
        ###

        gateway = RestApi(self, 'ApiGWFanAPI',
                          deploy_options=StageOptions(metrics_enabled=True,
                                                      logging_level=MethodLoggingLevel.INFO,
                                                      data_trace_enabled=True,
                                                      stage_name='prod'
                                                      ))

        gateway_usage_plan = UsagePlan(self, "GWUsagePlan", name=f"{gateway.rest_api_name}-usageplan", description="API Gateway Unlimited Use")

        gateway_api_key = gateway.add_api_key(props["custom_domain_name"], description=f"{gateway.rest_api_name}-apikey")
        gateway_usage_plan.add_api_key(gateway_api_key)

        custom_domain_name = self.apigw_custom_domain(cert, gateway, props)

        BasePathMapping(self, "APIGwMapping", base_path=props["namespace"],
                        domain_name=custom_domain_name, rest_api=gateway)

        # Give our gateway permissions to interact with SNS
        api_gw_sns_role = Role(self, 'DefaultLambdaHanderRole',
                               assumed_by=ServicePrincipal('apigateway.amazonaws.com'))
        topic.grant_publish(api_gw_sns_role)

        # shortening the lines of later code
        schema = JsonSchema
        schema_type = JsonSchemaType

        # Because this isn't a proxy integration, we need to define our response model
        response_model = gateway.add_model('ResponseModel',
                                           content_type='application/json',
                                           model_name='ResponseModel',
                                           schema=schema(schema=JsonSchemaVersion.DRAFT4,
                                                         title='pollResponse',
                                                         type=schema_type.OBJECT,
                                                         properties={
                                                             'message': schema(type=schema_type.STRING)
                                                         }))

        error_response_model = gateway.add_model('ErrorResponseModel',
                                                 content_type='application/json',
                                                 model_name='ErrorResponseModel',
                                                 schema=schema(schema=JsonSchemaVersion.DRAFT4,
                                                               title='errorResponse',
                                                               type=schema_type.OBJECT,
                                                               properties={
                                                                   'state': schema(type=schema_type.STRING),
                                                                   'message': schema(type=schema_type.STRING)
                                                               }))

        request_template = "Action=Publish&" + \
                           "TargetArn=$util.urlEncode('" + topic.topic_arn + "')&" + \
                           "Message=$util.urlEncode($input.path('$.message'))&" + \
                           "Version=2010-03-31&" + \
                           "MessageAttributes.entry.1.Name=status&" + \
                           "MessageAttributes.entry.1.Value.DataType=String&" + \
                           "MessageAttributes.entry.1.Value.StringValue=$util.urlEncode($input.path('$.status'))"

        # This is the VTL to transform the error response
        error_template = {
            "state": 'error',
            "message": "$util.escapeJavaScript($input.path('$.errorMessage'))"
        }
        error_template_string = json.dumps(error_template, separators=(',', ':'))

        # This is how our gateway chooses what response to send based on selection_pattern
        integration_options = IntegrationOptions(
            connection_type=ConnectionType.VPC_LINK,
            vpc_link=link,
            credentials_role=api_gw_sns_role,
            request_parameters={
                'integration.request.header.Content-Type': "'application/x-www-form-urlencoded'"
            },
            request_templates={
                "application/json": request_template
            },
            passthrough_behavior=PassthroughBehavior.NEVER,
            integration_responses=[
                IntegrationResponse(
                    status_code='200',
                    response_templates={
                        "application/json": json.dumps(
                            {"message": 'message added to topic'})
                    }),
                IntegrationResponse(
                    selection_pattern="^\[Error\].*",
                    status_code='400',
                    response_templates={
                        "application/json": error_template_string
                    },
                    response_parameters={
                        'method.response.header.Content-Type': "'application/json'",
                        'method.response.header.Access-Control-Allow-Origin': "'*'",
                        'method.response.header.Access-Control-Allow-Credentials': "'true'"
                    }
                )
            ]
        )

        # Add an SendEvent endpoint onto the gateway
        gateway.root.add_resource('SendEvent') \
            .add_method('POST', Integration(type=IntegrationType.HTTP_PROXY,
                                            integration_http_method='POST',
                                            # uri='arn:aws:apigateway:us-east-1:sns:path//',
                                            options=integration_options
                                            ),
                        method_responses=[
                            MethodResponse(status_code='200',
                                           response_parameters={
                                               'method.response.header.Content-Type': True,
                                               'method.response.header.Access-Control-Allow-Origin': True,
                                               'method.response.header.Access-Control-Allow-Credentials': True
                                           },
                                           response_models={
                                               'application/json': response_model
                                           }),
                            MethodResponse(status_code='400',
                                           response_parameters={
                                               'method.response.header.Content-Type': True,
                                               'method.response.header.Access-Control-Allow-Origin': True,
                                               'method.response.header.Access-Control-Allow-Credentials': True
                                           },
                                           response_models={
                                               'application/json': error_response_model
                                           }),
                        ]
                        )

        Integration(type=IntegrationType.HTTP_PROXY, options=integration_options)

        # Add the DNS record
        self.r53_dns_record(gateway, route53_zone_import, props)

        ##
        # Outputs
        #
        # VPC
        CfnOutput(self, "VPC_ID", description="VPC ID", export_name="vpcid", value=vpc.vpc_id)
        CfnOutput(self, "VPC_ARN", description="VPC ARN", export_name="vpcarn", value=vpc.vpc_arn)

    def apigw_custom_domain(self, cert, gateway, props):
        custom_domain_name = gateway.add_domain_name("DomainName",
                                                     domain_name=props["custom_domain_name"],
                                                     security_policy=SecurityPolicy.TLS_1_2,
                                                     certificate=Certificate.from_certificate_arn(self, "APIGWCert",
                                                                                                  cert.certificate_arn)
                                                     )
        return custom_domain_name

    def r53_dns_record(self, gateway, route53_zone_creation, props):
        ARecord(self, "AliasRecord", zone=route53_zone_creation, target=RecordTarget.from_alias(ApiGateway(gateway)),
                record_name=props["custom_domain_name"])
