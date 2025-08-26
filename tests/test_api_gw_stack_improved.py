"""
Tests for the improved API Gateway Stack
"""

import os
import json
from typing import Dict, Any

import pytest
import aws_cdk as cdk
from aws_cdk.assertions import Template, Match

from api_gw.api_gw_stack import APIGWStack


@pytest.fixture
def app():
    """Create a CDK app fixture"""
    return cdk.App()


@pytest.fixture
def stack_props() -> Dict[str, Any]:
    """Create stack properties fixture"""
    return {
        "namespace": "test-apigw-fanout",
        "hosted_zone_id": "Z1234567890ABC",
        "hosted_zone_name": "example.com",
        "cert_arn": "arn:aws:acm:us-east-1:123456789012:certificate/12345678-1234-1234-1234-123456789012",
        "custom_domain_name": "api.example.com",
        "alarm_email": "test@example.com",
        "vpc_cidr": "10.0.0.0/16",
        "environment": "test",
        "owner": "test-owner"
    }


@pytest.fixture
def stack(app, stack_props):
    """Create a stack fixture"""
    return APIGWStack(app, "TestStack", props=stack_props)


@pytest.fixture
def template(stack):
    """Generate CloudFormation template from stack"""
    return Template.from_stack(stack)


def test_vpc_created(template):
    """Test that VPC is created with correct CIDR"""
    template.resource_count_is("AWS::EC2::VPC", 1)
    template.has_resource_properties("AWS::EC2::VPC", {
        "CidrBlock": "10.0.0.0/16",
        "EnableDnsHostnames": True,
        "EnableDnsSupport": True
    })


def test_api_gateway_created(template):
    """Test that API Gateway is created with correct configuration"""
    template.resource_count_is("AWS::ApiGateway::RestApi", 1)
    template.has_resource_properties("AWS::ApiGateway::RestApi", {
        "Name": Match.string_like_regexp("test-apigw-fanout-private-api"),
        "EndpointConfiguration": {
            "Types": ["PRIVATE"]
        }
    })


def test_sns_topic_created(template):
    """Test that SNS topic is created"""
    template.resource_count_is("AWS::SNS::Topic", 1)
    template.has_resource_properties("AWS::SNS::Topic", {
        "DisplayName": "The Big Fan CDK Pattern Topic",
        "TopicName": "api-gateway-fan-out-topic"
    })


def test_sqs_queues_created(template):
    """Test that SQS queues are created"""
    template.resource_count_is("AWS::SQS::Queue", 4)  # 2 main queues + 2 DLQs


def test_lambda_functions_created(template):
    """Test that Lambda functions are created"""
    template.resource_count_is("AWS::Lambda::Function", 2)
    
    # Test first Lambda function
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "createdStatus.handler",
        "Runtime": "python3.11",
        "TracingConfig": {
            "Mode": "Active"
        }
    })
    
    # Test second Lambda function
    template.has_resource_properties("AWS::Lambda::Function", {
        "Handler": "anyOtherStatus.handler",
        "Runtime": "python3.11",
        "TracingConfig": {
            "Mode": "Active"
        }
    })


def test_waf_created(template):
    """Test that WAF is created"""
    template.resource_count_is("AWS::WAFv2::WebACL", 1)


def test_cloudwatch_alarms_created(template):
    """Test that CloudWatch alarms are created"""
    template.resource_count_is("AWS::CloudWatch::Alarm", Match.greater_than_or_equal_to(3))


def test_vpc_endpoints_created(template):
    """Test that VPC endpoints are created"""
    template.resource_count_is("AWS::EC2::VPCEndpoint", Match.greater_than_or_equal_to(5))


def test_api_gateway_domain_name(template):
    """Test that API Gateway domain name is created"""
    template.resource_count_is("AWS::ApiGateway::DomainName", 1)
    template.has_resource_properties("AWS::ApiGateway::DomainName", {
        "DomainName": "api.example.com",
        "SecurityPolicy": "TLS_1_2"
    })


def test_route53_record_created(template):
    """Test that Route53 record is created"""
    template.resource_count_is("AWS::Route53::RecordSet", 1)
    template.has_resource_properties("AWS::Route53::RecordSet", {
        "Name": "api.example.com.",
        "Type": "A"
    })


def test_tags_applied(template):
    """Test that tags are applied to resources"""
    template.has_resource_properties("AWS::EC2::VPC", {
        "Tags": Match.array_with([
            {
                "Key": "project",
                "Value": "test-apigw-fanout"
            },
            {
                "Key": "environment",
                "Value": "test"
            },
            {
                "Key": "owner",
                "Value": "test-owner"
            }
        ])
    })