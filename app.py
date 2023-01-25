#!/usr/bin/env python3

import os
from aws_cdk import App

from api_gw.api_gw_stack import APIGWStack


env_data = {
    'account': os.environ['CDK_DEFAULT_ACCOUNT'],
    'region': os.environ['CDK_DEFAULT_REGION']
}
app = App()
props = {
    "namespace": app.node.try_get_context("namespace"),
    "hosted_zone_id": app.node.try_get_context("hosted_zone_id"),
    "hosted_zone_name": app.node.try_get_context("hosted_zone_name"),
    "cert_arn": app.node.try_get_context("cert_arn"),
    "custom_domain_name": app.node.try_get_context("custom_domain_name")
}
APIGWStack(app, "ApiGatewayFanOut", props=props, env=env_data)

app.synth()
