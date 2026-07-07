# AgentCore Debugger - CDK Deployment

Deploy the AgentCore Debugger infrastructure using AWS CDK.

## What Gets Deployed

- **VPC** — Multi-AZ with public + private subnets, NAT gateway
- **ECS Fargate** — FastAPI backend (auto-scaling 1–6 tasks)
- **S3 + CloudFront** — React frontend as static files
- **DynamoDB** — Application state (pay-per-request)
- **Cognito** — User pool with admin/operator/viewer groups
- **ALB** — Routes API traffic (restricted to CloudFront IPs)
- **WAF** — Rate limiting + AWS Managed Rules on CloudFront
- **KMS** — Encryption for logs, DynamoDB
- **CloudWatch** — Logs, CPU alarms, ALB 5xx alarms

## Quick Start

```bash
# 1. Install dependencies
cd cdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Bootstrap (first time)
cdk bootstrap aws://ACCOUNT_ID/us-east-1

# 3. Deploy
cdk deploy AgentCoreDebuggerStack

# 4. Deploy frontend
cd ../frontend && npm run build
aws s3 sync dist/ s3://<FrontendBucketName from output>
aws cloudfront create-invalidation --distribution-id <ID> --paths "/*"
```

## Parameters

| Parameter | Required | Default | Description |
|-----------|----------|---------|-------------|
| `AlertEmail` | No | — | Email for CloudWatch alarms |
| `BackendCPU` | No | 512 | Fargate CPU units |
| `BackendMemory` | No | 1024 | Fargate memory (MiB) |
| `BackendDesiredCount` | No | 2 | Number of Fargate tasks |

## CDK Commands

```bash
cdk synth     # Generate CloudFormation template
cdk diff      # Show changes vs deployed
cdk deploy    # Deploy stack
cdk destroy   # Tear down everything
```

## Post-Deploy Steps

1. Deploy frontend to S3 (see Quick Start step 4)
2. Create Cognito users and assign to groups (see [SETUP_GUIDE.md](../SETUP_GUIDE.md#authentication-setup))

> Cognito callback URLs are wired to the CloudFront domain automatically by a
> custom resource in the stack — no manual update needed.

## IAM

The Fargate task role is created by CDK with least-privilege permissions. See `cdk/iam-policies/` for the standalone policy if needed for CI/CD roles.

## Cost

~$95-100/month (Fargate + ALB + NAT + CloudFront + WAF). Bedrock API costs are usage-based.

## Clean Up

```bash
cdk destroy   # Removes all resources
```
