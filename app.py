#!/usr/bin/env python3

from aws_cdk import App

from api_gw.api_gw_stack import APIGWStack

app = App()
props = {
    "domain_name": app.node.try_get_context("domain_name")
}
APIGWStack(app, "ApiGatewayFanOut", props=props)

app.synth()
