# Security Policy

> ⚠️ **Important — Sample Code Notice**
>
> This project is provided as **sample code** for educational and demonstration
> purposes. It is **NOT intended for production use** without additional security
> hardening and review. See [Production Hardening Recommendations](#production-hardening-recommendations)
> below before any production deployment.

## Reporting Vulnerabilities

If you discover a security vulnerability in this project, please report it responsibly:

1. **Do not** open a public issue
2. Email the security concern to the development team
3. Include steps to reproduce the vulnerability
4. Allow reasonable time for a fix before disclosure

## Security Controls

### Authentication
- Amazon Cognito with JWT token validation on every API request
- SSO/SAML federation support via Cognito
- Self-signup disabled — admin-only user creation

### Authorization (RBAC)
- Three roles: **viewer**, **operator**, **admin**
- Enforced server-side on every endpoint
- Role hierarchy: admin > operator > viewer

### Network Security
- ALB restricted to CloudFront IPs only (AWS managed prefix list)
- Fargate tasks in public subnets with security group lockdown (ALB-only inbound)
- HTTPS enforced via CloudFront (HTTP → HTTPS redirect)
- WAF on CloudFront: rate limiting, AWS Common Rule Set, Known Bad Inputs

### Data Protection
- KMS encryption for DynamoDB and CloudWatch Logs
- Security headers: CSP, HSTS, X-Frame-Options, X-Content-Type-Options

### IAM
- Least-privilege policies scoped to specific resources
- ECR access scoped to `agentcore-*` and `bedrock-agentcore-*` repositories
- `Resource: *` used only where AWS requires it (CloudWatch Metrics, ECR GetAuthorizationToken) — documented in policy files

### Code Security
- No hardcoded credentials or account IDs in source code
- `.env` files excluded via `.gitignore`
- SAST scanning (Bandit) runs on every pipeline
- Dependency vulnerability scanning (Safety) on every pipeline

## Configuration Files

Sensitive configuration files use placeholders (`ACCOUNT_ID`, `YOUR_ALIAS`, etc.) and must be populated per-environment. Never commit actual credentials or account-specific values.

## Dependencies

- Dependencies are pinned in `requirements.txt` and `package.json`
- Automated vulnerability scanning via GitLab CI pipeline
- AWS SDK clients use adaptive retry to handle throttling gracefully

## Production Hardening Recommendations

This is sample code. Before any production use, address the following:

- **Authentication**: Integrate with your organization's IdP (SAML/OIDC) via
  Cognito federation; enforce MFA; shorten token lifetimes.
- **Network**: Move Fargate tasks to private subnets behind NAT or VPC
  endpoints instead of public subnets with SG lockdown.
- **IAM**: Re-review all policies and tighten any remaining broad scopes for
  your account/region. Replace account-wide `bedrock-agentcore:*` grants with
  per-resource ARNs where possible.
- **Observability**: Enable CloudTrail, GuardDuty, and AWS Config; ship logs
  to a central account; add alerting on WAF blocks and auth failures.
- **Data**: Review DynamoDB and S3 retention/lifecycle for your compliance
  needs; enable point-in-time recovery on DynamoDB.
- **Dependency management**: Add automated dependency updates (e.g. Dependabot/
  Renovate) and fail the pipeline on high-severity CVEs.

## Resource Cleanup

To avoid ongoing charges and dangling resources, delete the stack when done:

```bash
# If deployed via CDK
cdk destroy AgentCoreDebuggerStack

# Or via CloudFormation
aws cloudformation delete-stack --stack-name AgentCoreDebuggerStack
```

After deletion, verify no dangling resources remain (CloudFront distributions,
S3 buckets, ECR images, Cognito pools, sample agent runtimes). Globally-named
resources (S3, CloudFront) left behind can be a security risk if recreated by
another party.

## Known Security Debt

The following are tracked, accepted limitations in this sample:

| Item | Reason |
|------|--------|
| `cloudwatch:GetMetricStatistics` uses `Resource: *` | CloudWatch Metrics does not support resource-level permissions (AWS limitation) |
| `ecr:GetAuthorizationToken` uses `Resource: *` | ECR auth token does not support resource-level permissions (AWS limitation) |
| `xray:PutTraceSegments` / `xray:PutTelemetryRecords` use `Resource: *` | X-Ray trace ingestion APIs do not support resource-level permissions (AWS limitation) |
| `/tmp` paths for per-build progress files | Isolated per Fargate task; ephemeral and not shared across tenants |
