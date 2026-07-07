#!/usr/bin/env python3
"""
AgentCore Debugger CDK App

Deploys the AgentCore Debugger sample: a FastAPI backend on ECS Fargate
(behind an ALB + CloudFront), a React frontend on S3, DynamoDB for state,
Cognito authentication with RBAC, WAF, and KMS encryption.
"""
import os
from aws_cdk import App, Environment
from stacks.fargate_production_stack import FargateProductionStack

app = App()

account = app.node.try_get_context("account") or os.environ.get("CDK_DEFAULT_ACCOUNT")
region = app.node.try_get_context("region") or os.environ.get("CDK_DEFAULT_REGION", "us-east-1")

FargateProductionStack(
    app,
    "AgentCoreDebuggerStack",
    env=Environment(account=account, region=region),
    description=(
        "AgentCore Debugger (sample) - AI-powered debugging and auto-fix tool for "
        "Amazon Bedrock AgentCore agents. Deploys a FastAPI backend on ECS Fargate "
        "(ALB + CloudFront), a React frontend on S3, DynamoDB state, Cognito auth "
        "with RBAC, WAF, and KMS encryption."
    ),
)

app.synth()
