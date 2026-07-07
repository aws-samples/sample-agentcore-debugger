# CDK Configuration Files

Environment-specific configuration for CDK deployments.

## Files

- `dev.json` — Development (smaller Fargate tasks, 1 replica)
- `prod.json` — Production (larger tasks, 2+ replicas)
- `dev.json.example` — Template to copy

## Config Values (Non-Sensitive)

| Key | Description |
|-----|-------------|
| `environment` | dev / prod |
| `aws_region` | AWS region |
| `alert_email` | CloudWatch alarm email |
| `backend_cpu` | Fargate CPU units (256/512/1024) |
| `backend_memory` | Fargate memory in MiB |
| `backend_desired_count` | Number of Fargate tasks |

## Sensitive Values

Store as GitLab CI/CD variables (protected + masked):
- `AWS_ACCOUNT_ID`
