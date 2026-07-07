# AgentCore Debugger Assistant 🤖🔧

> ⚠️ **Important**: This project is provided as sample code for educational and demonstration
> purposes. It is NOT intended for production use without additional security hardening.
> See [SECURITY.md](SECURITY.md) for production recommendations.

AI-powered debugging and auto-fix tool for Amazon Bedrock AgentCore agents. Automatically detects, analyzes, classifies, and fixes agent errors — then deploys the fix as a draft to AgentCore Runtime for testing and one-click promotion to production.

## 🎯 What It Does

Give it your AgentCore Runtime ID, and watch it:

1. 📊 **Monitor** — Real-time observability metrics from CloudWatch (invocations, errors, latency)
2. 🔍 **Detect** — Automatically clusters error patterns from CloudWatch logs
3. 🏷️ **Classify** — AI classifies errors as code bugs, package conflicts, or mixed issues
4. 📦 **Extract** — Downloads your agent code from ECR via boto3 API
5. 🔧 **Fix** — Multi-agent system applies intelligent fixes automatically
6. 🧪 **Test** — Deploy the fix as a draft on AgentCore Runtime and validate it with prompts
7. 🚀 **Promote** — Once validated, promote the draft to the production endpoint (admin only)

### 🧪 Try it with the bundled Sample Agent

Don't have a buggy agent handy? The app ships with a **Sample Agent** — a
deliberately broken customer-service agent you can deploy with one click to
try the full detect → fix → deploy flow before pointing the debugger at your
real agents. It contains intentional bugs (pandas `df.append`, numpy `np.int`,
missing API retry, division by zero). See [sample_agent/README.md](sample_agent/README.md).

## Architecture

```
                         ┌──────────────────────────────────┐
                         │          CloudFront (WAF)        │
                         │           + HTTPS                │
                         └──────┬───────────────┬───────────┘
                                │               │
                    Static assets (React)   /api/* + /auth/*
                                │               │
                                ▼               ▼
                         ┌────────────┐  ┌─────────────┐
                         │  S3 Bucket │  │     ALB     │
                         │  (React)   │  │ (CF only)   │
                         └────────────┘  └──────┬──────┘
                                                │
                                    ┌───────────┴───────────┐
                                    │   ECS Fargate         │
                                    │   FastAPI Backend      │
                                    │   (auto-scaling 1-6)   │
                                    └───────────┬───────────┘
                                                │
                        ┌───────────┬───────────┼───────────┬───────────┐
                        ▼           ▼           ▼           ▼           ▼
                   ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐
                   │Bedrock  │ │DynamoDB │ │Cognito  │ │  ECR    │ │Secrets  │
                   │(Claude) │ │(State)  │ │(Auth)   │ │(Images) │ │Manager  │
                   └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘
```

**Key components:**
- **CloudFront + WAF** — Public HTTPS entry point with rate limiting, SQLi/XSS protection
- **S3** — Serves the React frontend as static files
- **ALB** — Routes API traffic to Fargate (restricted to CloudFront IPs only)
- **ECS Fargate** — Runs FastAPI backend, auto-scales 1–6 tasks
- **DynamoDB** — Serverless application state (pay-per-request)
- **Cognito** — SSO/JWT authentication with RBAC (viewer, operator, admin)
- **KMS** — Encryption for secrets, logs, and DynamoDB

## 👥 User Roles & Permissions

Access is controlled by Cognito groups, enforced server-side on every API request. A user's role is determined by the Cognito group they belong to.

| Role | Cognito Group | Can do |
|------|---------------|--------|
| **Viewer** | `viewer` | Read-only — view agents, error clusters, metrics, and fix results. Cannot start fixes or deploy. |
| **Operator** | `operator` | Everything a viewer can, plus: start fix workflows, deploy fixed/sample code as a draft, and invoke test agents. |
| **Admin** | `admin` | Everything an operator can, plus: manage users (create/delete, assign roles) and promote a tested draft to the live (DEFAULT) agent endpoint. |

Role checks are applied per endpoint (e.g. `/fix/start` requires operator, `/users/*` and `/test-agent/promote` require admin). A viewer calling an operator-only endpoint receives `403 Forbidden`.

## 🔐 Security

- **Authentication**: Cognito JWT tokens validated on every API request
- **Authorization**: Three roles (viewer, operator, admin) enforced server-side
- **WAF**: Rate limiting + AWS Managed Rules (Common Rule Set, Known Bad Inputs)
- **Network**: ALB restricted to CloudFront IPs only, Fargate SG allows ALB-only inbound
- **Encryption**: KMS for secrets, logs, DynamoDB; HTTPS enforced via CloudFront
- **IAM**: Least-privilege — ECR scoped to `agentcore-*`, SecretsManager scoped to app secrets
- **Non-root containers**: Backend Dockerfile runs as non-root user

## 🛠️ Quick Start

### Local Development

```bash
# 1. Clone and configure
git clone <repository-url>
cd agentcore-debugger
cp .env.example .env
# Adjust .env as needed (AUTH_ENABLED defaults to false for local dev)

# 2. Start backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 3. Start frontend (separate terminal)
cd frontend
npm install
npm run dev

# 4. Access
# Frontend: http://localhost:5173
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

### AWS Deployment (via GitLab Pipeline)

The stack is deployed through the GitLab CI/CD pipeline. On push to `main` or
`gitops`, the pipeline runs: **scan → prepare → build → deploy** (the deploy
stage is manual).

```
scan          → SAST (bandit/safety) + frontend lint
prepare       → ensure ECR repository exists
build         → build & push backend image to ECR (Kaniko, no Docker daemon)
deploy        → (manual) deploy CloudFormation stack + frontend to S3 +
                force new ECS deployment + invalidate CloudFront
```

To deploy: push your branch, then trigger the manual **deploy** job in the
GitLab pipeline UI. The deploy job uses the pre-synthesized CloudFormation
template in `cdk/cdk.out/` and the CDK bootstrap bucket/execution role.

> **Prerequisite (first time only):** `cdk bootstrap aws://ACCOUNT_ID/us-east-1`
> must have been run once so the CDK toolkit bucket and execution role exist.

### Post-Deployment Setup (one time)

The stack automatically registers your CloudFront URL as a Cognito callback
(a custom resource updates the app client once the CloudFront domain exists),
so the only manual step is creating your first admin user.

**Create your first admin user** so you can sign in (the pool starts empty):

```bash
POOL_ID=$(aws cloudformation describe-stacks --stack-name AgentCoreDebuggerStack \
  --query 'Stacks[0].Outputs[?OutputKey==`CognitoUserPoolId`].OutputValue' --output text)

# 1. Create the user (email = username)
aws cognito-idp admin-create-user \
  --user-pool-id "$POOL_ID" \
  --username you@example.com \
  --user-attributes Name=email,Value=you@example.com Name=email_verified,Value=true \
  --message-action SUPPRESS

# 2. Set a permanent password (no forced reset)
aws cognito-idp admin-set-user-password \
  --user-pool-id "$POOL_ID" \
  --username you@example.com \
  --password 'YourStrongPassword!1' --permanent

# 3. Add to the admin group (groups: admin / operator / viewer are created by the stack)
aws cognito-idp admin-add-user-to-group \
  --user-pool-id "$POOL_ID" \
  --username you@example.com \
  --group-name admin
```

Once you can sign in as admin, all further user management (adding teammates,
assigning viewer/operator/admin roles) is done from the **Settings** page in
the app — no CLI needed.

The application URL is in the stack output `ApplicationURL` (the CloudFront
domain).

### Local Development Deployment (alternative)

If you prefer to deploy directly from your machine instead of the pipeline:

```bash
cd cdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cdk bootstrap aws://ACCOUNT_ID/us-east-1   # first time only
cdk deploy AgentCoreDebuggerStack

# Then deploy the frontend
cd ../frontend && npm run build
aws s3 sync dist/ s3://<FrontendBucketName from CDK output>
aws cloudfront create-invalidation --distribution-id <ID> --paths "/*"
```

For full instructions see **[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)**.

## Project Structure

```
agentcore-debugger/
├── backend/                 # FastAPI backend
│   ├── app/api/v1/         # API endpoints (agents, errors, fix, deploy, test_agent, users)
│   ├── app/core/           # Config, security (Cognito JWT + RBAC), AWS clients
│   ├── app/services/       # Business logic (fix, codebuild, sample_agent, etc.)
│   └── Dockerfile          # Container image (for Fargate)
├── frontend/               # React frontend (deployed to S3)
│   ├── src/pages/          # Dashboard, ErrorAnalysis, FixWorkflow, Deploy, Settings
│   ├── src/stores/         # Zustand stores (app, auth, workflow)
│   └── src/components/     # Reusable components
├── src/                    # Shared Python modules
│   ├── agents/             # Strands orchestrator, package agent, code agent
│   ├── collectors/         # CloudWatch metrics & logs collectors
│   └── tools/              # AgentCore auto-fixer, ECR extractor
├── sample_agent/           # Bundled demo agent (intentional bugs) for trying the app
├── cdk/                    # AWS CDK (Fargate + S3 + DynamoDB + Cognito + WAF)
├── docker/                 # Backend entrypoint scripts
└── docs/                   # SETUP_GUIDE, SECURITY
```

## 🔧 Tech Stack

| Component | Technology |
|-----------|------------|
| Frontend | React + Material UI + TypeScript |
| Frontend Hosting | S3 + CloudFront |
| Backend | FastAPI (Python) on ECS Fargate |
| Auth | Amazon Cognito (JWT + RBAC) |
| State | DynamoDB (pay-per-request) |
| AI Engine | Claude Sonnet 4 via Amazon Bedrock |
| Agent Framework | Strands SDK |
| Security | WAF, KMS, Secrets Manager |
| Infrastructure | AWS CDK (Fargate, S3, DynamoDB, Cognito, WAF) |
| CI/CD | GitLab CI/CD |

## 💰 Cost Estimation (AWS)

| Resource | Monthly Cost (USD) |
|----------|-------------------|
| Fargate (1 task, 0.5 vCPU, 1GB) | ~$15 |
| ALB | ~$20 |
| CloudFront | ~$1-5 |
| S3 (frontend) | ~$0.50 |
| DynamoDB (on-demand) | ~$1-5 |
| Cognito (< 50k users) | Free |
| WAF | ~$6 |
| **Total** | **~$45** |

*Amazon Bedrock API costs are usage-based and not included above.*

## 📖 Documentation

| Document | Description |
|----------|-------------|
| **[docs/API.md](docs/API.md)** | REST API reference + end-to-end testing guide |
| **[docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md)** | Complete setup, deployment, and configuration guide |
| **[SECURITY.md](SECURITY.md)** | Security controls and production hardening recommendations |
| [cdk/README.md](cdk/README.md) | CDK stack details |
| [cdk/iam-policies/README.md](cdk/iam-policies/README.md) | IAM role and policy setup |

## License

This project is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
