"""
Main CDK application file for the API Gateway Fan-out pattern
"""

import os
from aws_cdk import App, Environment, Tags

# Import only the original stack implementation
from api_gw.api_gw_stack import APIGWStack

# Set up environment
env_data = {
    'account': os.environ.get('CDK_DEFAULT_ACCOUNT', ''),
    'region': os.environ.get('CDK_DEFAULT_REGION', '')
}

# Initialize CDK app
app = App()

# Get context properties
props = {
    "namespace": app.node.try_get_context("namespace"),
    "hosted_zone_id": app.node.try_get_context("hosted_zone_id"),
    "hosted_zone_name": app.node.try_get_context("hosted_zone_name"),
    "cert_arn": app.node.try_get_context("cert_arn"),
    "custom_domain_name": app.node.try_get_context("custom_domain_name"),
    "alarm_email": app.node.try_get_context("alarm_email"),
    "vpc_cidr": app.node.try_get_context("vpc_cidr")
}

# Use the original stack implementation
APIGWStack(app, "ApiGatewayFanOut", props=props, env=env_data)

# Synthesize the CloudFormation template
app.synth()