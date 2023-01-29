#!/usr/bin/env python3

from aws_cdk import App
from api_gw.api_gw_stack import APIGWStack


app = App()
props = {
    "namespace": app.node.try_get_context("namespace"),
    "hosted_zone_id": app.node.try_get_context("hosted_zone_id"),
    "hosted_zone_name": app.node.try_get_context("hosted_zone_name"),
    "cert_arn": app.node.try_get_context("cert_arn"),
    "custom_domain_name": app.node.try_get_context("custom_domain_name"),
    "alarm_email": app.node.try_get_context("alarm_email")
}
APIGWStack(app, "ApiGatewayFanOut", props=props)

app.synth()
