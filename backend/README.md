# AgentCore Debugger - FastAPI Backend

REST API backend for the AgentCore Debugger. Runs on ECS Fargate when deployed to AWS, or locally via uvicorn for development.

## Setup

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

- **API**: http://localhost:8000
- **Docs**: http://localhost:8000/docs
- **Health**: http://localhost:8000/health

## Authentication & RBAC

All endpoints require a valid Cognito JWT token (when `AUTH_ENABLED=true`).

Roles (from Cognito groups):
- **viewer** — read-only access to agents, errors, dashboards
- **operator** — viewer + apply fixes, push to GitLab
- **admin** — operator + deploy, rollback, settings, cleanup

For local dev, `AUTH_ENABLED=false` bypasses auth with a default admin user.

## API Endpoints

| Prefix | Auth | Description |
|--------|------|-------------|
| `/api/v1/agents` | viewer | List/view agents, metrics, health |
| `/api/v1/errors` | viewer | Error logs, analysis, patterns |
| `/api/v1/fix` | viewer (read), operator (mutate) | Fix workflow, push changes |
| `/api/v1/deploy` | viewer (read), operator (push), admin (deploy) | GitLab push, AgentCore deploy |
| `/api/v1/health` | viewer | System health, service status |
| `/health` | none | ALB health check (unauthenticated) |
| `/auth/config` | none | Frontend auth bootstrap (unauthenticated) |

## Project Structure

```
backend/
├── app/
│   ├── api/v1/          # Route handlers
│   ├── core/
│   │   ├── config.py    # Settings (Cognito, DynamoDB, etc.)
│   │   └── security.py  # JWT validation + RBAC
│   ├── models/          # Pydantic models
│   ├── services/        # Business logic
│   └── main.py          # FastAPI app
├── requirements.txt
└── Dockerfile
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `AUTH_ENABLED` | Enable Cognito JWT auth | false |
| `COGNITO_USER_POOL_ID` | Cognito pool ID | — |
| `COGNITO_APP_CLIENT_ID` | Cognito client ID | — |
| `DYNAMODB_TABLE_NAME` | DynamoDB state table | — |
| `AWS_REGION` | AWS region | us-east-1 |
