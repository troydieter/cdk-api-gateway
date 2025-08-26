#!/usr/bin/env python3
"""
Main CDK application file for the API Gateway Fan-out pattern
"""

import os
from typing import Dict, Any
from aws_cdk import App, Environment, Tags

# Import both the original and improved stack implementations
from api_gw.api_gw_stack import APIGWStack
from api_gw.api_gw_stack_improved import APIGWStack as APIGWStackImproved


def main() -> None:
    """Main function to initialize and deploy the CDK app"""
    # Set up environment
    env_data = Environment(
        account=os.environ.get('CDK_DEFAULT_ACCOUNT', ''),
        region=os.environ.get('CDK_DEFAULT_REGION', '')
    )
    
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
        "vpc_cidr": app.node.try_get_context("vpc_cidr"),
        # Additional properties for improved stack
        "environment": app.node.try_get_context("environment") or "dev",
        "owner": app.node.try_get_context("owner") or "cdk-deployment"
    }
    
    # Determine which stack implementation to use
    use_improved_stack = app.node.try_get_context("use_improved_stack") or "true"
    
    if use_improved_stack.lower() == "true":
        # Use the improved stack implementation
        stack = APIGWStackImproved(
            app, 
            "ApiGatewayFanOut", 
            props=props, 
            env=env_data,
            description="Private API Gateway with Fan-out Pattern (Improved Implementation)"
        )
    else:
        # Use the original stack implementation
        stack = APIGWStack(
            app, 
            "ApiGatewayFanOut", 
            props=props, 
            env=env_data
        )
    
    # Apply common tags to all resources
    Tags.of(app).add("Project", props["namespace"])
    Tags.of(app).add("Environment", props.get("environment", "dev"))
    Tags.of(app).add("Owner", props.get("owner", "cdk-deployment"))
    Tags.of(app).add("ManagedBy", "AWS CDK")
    
    # Synthesize the CloudFormation template
    app.synth()


if __name__ == "__main__":
    main()