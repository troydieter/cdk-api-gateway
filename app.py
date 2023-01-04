#!/usr/bin/env python3

from aws_cdk import App

from api_gw.api_gw_stack import APIGWStack

app = App()
APIGWStack(app, "ApiGatewayFanOut")

app.synth()
