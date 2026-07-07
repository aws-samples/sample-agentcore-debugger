# IAM Policies for AgentCore Debugger

## Overview

In the Fargate architecture, IAM permissions are managed by CDK automatically — the Fargate task role gets least-privilege permissions baked in.

The policy files in this directory are provided for:
- **CI/CD pipelines** that need their own IAM role (`gitlab-ci-policy.json`)
- **Reference** to understand what permissions the app needs (`minimal-required-policy.json`)

## Permissions Summary

| Service | Actions | Scope |
|---------|---------|-------|
| CloudWatch Logs | Read | `/aws/bedrock-agentcore/*`, `aws/spans/*` |
| CloudWatch Metrics | Read | `*` (required by AWS) |
| Bedrock | InvokeModel | Foundation models + inference profiles |
| Bedrock AgentCore | Read/Invoke | Account-scoped ARNs |
| ECR | Read | `agentcore-*` repositories only |
| Secrets Manager | GetSecretValue | `AgentCoreDebugger*` secrets only |
| DynamoDB | Read/Write | App state table (CDK-managed) |
| S3 | GetObject | Agent config files only |

## Key Scoping Decisions

- **ECR**: `arn:aws:ecr:*:ACCOUNT_ID:repository/agentcore-*` — not `*`
- **SecretsManager**: `arn:aws:secretsmanager:*:ACCOUNT_ID:secret:AgentCoreDebugger*` — not `*`
- **BedrockAgentCore**: `arn:aws:bedrock-agentcore:*:ACCOUNT_ID:*` — account-scoped
- **ECR GetAuthorizationToken**: Must remain `Resource: *` (AWS requirement)

## Files

| File | Purpose |
|------|---------|
| `minimal-required-policy.json` | Full app permissions (reference) |
| `gitlab-ci-policy.json` | CI/CD pipeline permissions |
| `trust-policy.json` | Trust policy for ECS tasks / EC2 |

## For CI/CD Setup

If using GitLab CI/CD, create a role with `gitlab-ci-policy.json` and configure it as a GitLab CI/CD variable. The trust policy should allow the GitLab runner's role to assume it.
