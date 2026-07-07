# AgentCore Debugger - Setup Guide

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Local Development](#local-development)
5. [AWS Deployment](#aws-deployment)
6. [Authentication Setup](#authentication-setup)
7. [Configuration](#configuration)
8. [Troubleshooting](#troubleshooting)

---

## Overview

AgentCore Debugger runs on a serverless-first AWS architecture:
- **Frontend**: React static build served from S3 via CloudFront
- **Backend**: FastAPI on ECS Fargate (auto-scaling, multi-AZ)
- **State**: DynamoDB (pay-per-request, serverless)
- **Auth**: Amazon Cognito with RBAC (viewer, operator, admin)
- **Security**: WAF on CloudFront, KMS encryption, least-privilege IAM

---

## Architecture

```
CloudFront (WAF + HTTPS)
  ├── Static assets → S3 (React build)
  └── /api/*, /auth/config → ALB → ECS Fargate Spot (auto-scaling 1-6)
                                  │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
               DynamoDB       Bedrock         ECR/S3
               (state)       (Claude)        (agent code)
```

---

## Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| AWS CLI | 2.x | AWS operations |
| AWS CDK | 2.x | Infrastructure deployment |
| Node.js | 18+ | CDK CLI + frontend build |
| Python | 3.9+ | CDK + backend |

External services:
- **Amazon Bedrock**: Claude model access enabled in your region

---

## Local Development

```bash
# 1. Clone and configure
git clone <repository-url>
cd agentcore-debugger
cp .env.example .env
# AUTH_ENABLED defaults to false for local dev

# 2. Start backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Start frontend (separate terminal)
cd frontend
npm install
npm run dev

# Access
# Frontend: http://localhost:5173
# Backend:  http://localhost:8000
# API Docs: http://localhost:8000/docs
```

---

## AWS Deployment

### Step 1: Install CDK dependencies

```bash
cd cdk
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Step 2: Bootstrap CDK (first time only)

```bash
cdk bootstrap aws://ACCOUNT_ID/us-east-1
```

### Step 3: Deploy the stack

```bash
cdk deploy AgentCoreDebuggerStack
```

This creates: VPC, Fargate cluster, ALB, S3 bucket, CloudFront, DynamoDB, Cognito, WAF, KMS, CloudWatch alarms.

### Step 4: Deploy frontend to S3

```bash
cd frontend
npm install && npm run build

# Get bucket name from CDK output
aws s3 sync dist/ s3://<FrontendBucketName>

# Invalidate CloudFront cache
aws cloudfront create-invalidation \
  --distribution-id <CloudFrontDistributionId> \
  --paths "/*"
```

### Step 5: Get the application URL

```bash
aws cloudformation describe-stacks \
  --stack-name AgentCoreDebuggerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`ApplicationURL`].OutputValue' \
  --output text
```

---

## Authentication Setup

The stack creates a Cognito User Pool with three groups: `admin`, `operator`, `viewer`.

### Create users

```bash
# Get User Pool ID from CDK output
USER_POOL_ID=<CognitoUserPoolId>

# Create a user
aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username user@example.com \
  --user-attributes Name=email,Value=user@example.com \
  --temporary-password TempPass123!

# Assign to a role group
aws cognito-idp admin-add-user-to-group \
  --user-pool-id $USER_POOL_ID \
  --username user@example.com \
  --group-name admin   # or: operator, viewer
```

### Role permissions

| Action | viewer | operator | admin |
|--------|--------|----------|-------|
| View agents, errors, dashboards | ✅ | ✅ | ✅ |
| Trigger AI analysis | ✅ | ✅ | ✅ |
| Apply fixes, deploy drafts | ❌ | ✅ | ✅ |
| Promote to production, manage users, settings | ❌ | ❌ | ✅ |

### Cognito callback URLs (automatic)

The stack auto-registers the CloudFront URL as a Cognito callback via a custom
resource (it updates the app client once the CloudFront domain is known), so no
manual step is required after deploy.

If you ever need to set them by hand (e.g. adding an extra domain), use:

```bash
APP_CLIENT_ID=<CognitoAppClientId>
CF_URL=https://<CloudFrontDomainName>

aws cognito-idp update-user-pool-client \
  --user-pool-id $USER_POOL_ID \
  --client-id $APP_CLIENT_ID \
  --callback-urls "$CF_URL/auth/callback" "http://localhost:5173/auth/callback" \
  --logout-urls "$CF_URL" "http://localhost:5173" \
  --allowed-o-auth-flows code \
  --allowed-o-auth-scopes email openid profile \
  --allowed-o-auth-flows-user-pool-client \
  --supported-identity-providers COGNITO \
  --explicit-auth-flows ALLOW_REFRESH_TOKEN_AUTH ALLOW_USER_SRP_AUTH
```

---

## Configuration

### CDK Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `AlertEmail` | No | — | Email for CloudWatch alarms |
| `BackendCPU` | No | 512 | Fargate CPU units (256/512/1024) |
| `BackendMemory` | No | 1024 | Fargate memory in MiB |
| `BackendDesiredCount` | No | 1 | Number of Fargate tasks |

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AWS_REGION` | AWS region | us-east-1 |
| `AUTH_ENABLED` | Enable Cognito auth | false (local), true (prod) |
| `COGNITO_USER_POOL_ID` | Cognito pool ID | Set by CDK |
| `COGNITO_APP_CLIENT_ID` | Cognito client ID | Set by CDK |
| `DYNAMODB_TABLE_NAME` | DynamoDB table | Set by CDK |

---

## Troubleshooting

### Fargate tasks not starting
```bash
# Check ECS service events
aws ecs describe-services \
  --cluster AgentCoreDebuggerStack-cluster \
  --services <service-name> \
  --query 'services[0].events[:5]'

# Check task logs
aws logs tail /aws/ecs/AgentCoreDebuggerStack --follow
```

### Frontend not loading after S3 deploy
```bash
# Verify files are in S3
aws s3 ls s3://<FrontendBucketName>/

# Invalidate CloudFront cache
aws cloudfront create-invalidation \
  --distribution-id <ID> --paths "/*"
```

### 401 Unauthorized errors
- Check `AUTH_ENABLED` is set correctly
- Verify Cognito callback URLs include your domain
- Ensure user is in the correct Cognito group

### 403 Forbidden on API calls
- User's Cognito group doesn't have the required role
- Check the role mapping: viewer < operator < admin

### CDK deploy fails
```bash
# Check CDK diff first
cdk diff

# Re-bootstrap if needed
cdk bootstrap aws://ACCOUNT_ID/us-east-1 --force
```

---

## Cost Estimation

| Resource | Monthly Cost (USD) |
|----------|-------------------|
| Fargate Spot (1 task, 0.5 vCPU, 1GB) | ~$9 |
| ALB | ~$20 |
| CloudFront | ~$1-5 |
| S3 (frontend) | ~$0.50 |
| DynamoDB (on-demand) | ~$1-5 |
| Cognito (< 50k MAU) | Free |
| WAF | ~$6 |
| **Total** | **~$40** |

*Bedrock API costs are usage-based and not included.*

---

## Security Checklist

- [x] Cognito JWT auth on all API endpoints
- [x] RBAC with three roles (viewer, operator, admin)
- [x] WAF on CloudFront (rate limiting + managed rules)
- [x] ALB restricted to CloudFront IPs only
- [x] Fargate with SG lockdown (ALB-only inbound)
- [x] KMS encryption for DynamoDB, secrets, logs
- [x] Security headers (CSP, HSTS, X-Frame-Options)
- [x] IAM least-privilege (ECR, Bedrock, AgentCore scoped)
- [x] Non-root containers
- [x] Auto-scaling (1–6 tasks based on CPU/memory)
