# AgentCore Debugger — REST API Reference & Testing Guide

> ⚠️ **Sample code.** This API is provided for educational and demonstration
> purposes and is not intended for production use without additional hardening.
> See [../SECURITY.md](../SECURITY.md).

This document describes every REST endpoint the backend exposes, the role required
to call it, request/response shapes, and how to test the API end to end.

- **API version:** `1.1.0` (FastAPI)
- **API prefix:** all versioned endpoints are under `/api/v1`
- **Interactive docs:** Swagger (`/docs`) and ReDoc (`/redoc`) are **disabled when
  `AUTH_ENABLED=true`** (the default for a deployed stack). Run the backend locally
  with `AUTH_ENABLED=false` to browse Swagger.

---

## 1. Base URL & routing

In a deployed stack, the frontend and API share one CloudFront distribution:

```
https://<cloudfront-domain>/            → React frontend (S3)
https://<cloudfront-domain>/api/*       → ALB → Fargate (backend)
https://<cloudfront-domain>/health      → ALB → Fargate (health check)
https://<cloudfront-domain>/auth/config → ALB → Fargate (auth bootstrap)
```

So the effective base URL for versioned calls is:

```
https://<cloudfront-domain>/api/v1
```

Set a convenience variable for the examples below:

```bash
export BASE="https://<cloudfront-domain>"
```

---

## 2. Authentication

Authentication uses **Amazon Cognito** (JWT). Every `/api/v1/*` endpoint (except
the unauthenticated `/health`, `/`, and `/auth/config`) requires a bearer token:

```
Authorization: Bearer <ID_TOKEN>
```

### Roles (Cognito groups)

Roles are derived from the user's Cognito groups and are hierarchical — a higher
role inherits all lower-role permissions:

| Role       | Inherits        | Can do                                                        |
|------------|-----------------|---------------------------------------------------------------|
| `viewer`   | —               | View agents, errors, health, dashboards                       |
| `operator` | viewer          | + run fixes, deploy drafts, invoke test endpoint, push GitLab |
| `admin`    | viewer, operator| + promote to production, manage users, change model/settings  |

A user with no recognized group defaults to `viewer`.

### Getting a token

**Option A — Hosted UI (normal users):** log in through the app; the frontend
performs the OAuth authorization-code flow and stores the ID token.

**Option B — CLI (testing/automation):** if the app client has
`ALLOW_ADMIN_USER_PASSWORD_AUTH` enabled, fetch a token directly:

```bash
export TOKEN=$(aws cognito-idp admin-initiate-auth \
  --user-pool-id <USER_POOL_ID> \
  --client-id <APP_CLIENT_ID> \
  --auth-flow ADMIN_USER_PASSWORD_AUTH \
  --auth-parameters "USERNAME=<email>,PASSWORD=<password>" \
  --region us-east-1 \
  --query 'AuthenticationResult.IdToken' --output text)
```

> Tip (zsh): wrap any value containing `!` in single quotes to avoid history expansion.

Then call any endpoint:

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/agents/deployed"
```

`GET /auth/config` (no auth) returns the Cognito pool/client/domain the frontend
needs to start the login flow.

---

## 3. Conventions

- **Content type:** JSON request and response bodies.
- **Errors:** failures return an appropriate HTTP status; unhandled errors return
  `500` with `{"error": "Internal server error"}` (internal details are never leaked).
- **Async jobs + polling:** long-running operations return immediately with a
  `build_id` or `job_id`; poll the matching status endpoint until `ready`/`completed`/`failed`.
- **Draft → test → promote:** fixes never touch live production automatically. See §5.

---

## 4. Endpoint reference

Role column shows the **minimum** role required. All `/api/v1/*` paths require a
valid token even when the minimum is `viewer`.

### 4.1 Unauthenticated (app-level)

| Method | Path           | Description                                    |
|--------|----------------|------------------------------------------------|
| GET    | `/health`      | Liveness probe (used by the ALB).              |
| GET    | `/`            | Root info (name, version).                     |
| GET    | `/auth/config` | Cognito config for the frontend login flow.    |

### 4.2 Agents — `/api/v1/agents`

| Method | Path                              | Role   | Description                                   |
|--------|-----------------------------------|--------|-----------------------------------------------|
| GET    | `/agents`                         | viewer | List agents (optional `?status=` filter).     |
| GET    | `/agents/deployed`                | viewer | List deployed AgentCore runtimes (`?region=`).|
| GET    | `/agents/{agent_id}`              | viewer | Get one agent.                                |
| GET    | `/agents/{agent_id}/health`       | viewer | Agent health status.                          |
| GET    | `/agents/{agent_id}/metrics`      | viewer | Agent metrics.                                |
| GET    | `/agents/{agent_id}/configuration`| viewer | Agent configuration.                          |
| POST   | `/agents/test-deployed`           | viewer | Invoke a deployed agent (DEFAULT endpoint).   |
| POST   | `/agents/{agent_id}/generate-test-error` | viewer | Generate a test error for the demo flow. |

`POST /agents/test-deployed` body:

```json
{ "agent_arn": "arn:aws:bedrock-agentcore:us-east-1:<acct>:runtime/<name>-<id>",
  "prompt": "Show me my order history",
  "session_id": "optional, auto-generated if omitted (min 33 chars)" }
```

### 4.3 Errors — `/api/v1/errors` (all `viewer`)

| Method | Path               | Description                                                  |
|--------|--------------------|--------------------------------------------------------------|
| GET    | `/errors/logs`     | Parsed CloudWatch error logs. Filters: `agent_id, log_group, start_time, end_time, error_type, severity, limit`. |
| GET    | `/errors/analyze`  | Error summary stats. Filters: `agent_id, start_time, end_time`. |
| GET    | `/errors/traces`   | X-Ray trace errors. Filters: `start_time, end_time, filter_expression`. |
| GET    | `/errors/patterns` | Recurring error patterns with suggested fixes.               |
| GET    | `/errors/types`    | Known error types and descriptions.                          |

### 4.4 Fix workflow — `/api/v1/fix`

| Method | Path                      | Role     | Description                                            |
|--------|---------------------------|----------|--------------------------------------------------------|
| GET    | `/fix/clusters/{agent_id}`| viewer   | Clustered error patterns + suppression summary. `?start_time&end_time&limit&refresh`. |
| POST   | `/fix/analyze`            | viewer   | AI analysis of one error cluster.                      |
| POST   | `/fix/start`              | operator | Start the auto-fix workflow (async → returns `job_id`).|
| GET    | `/fix/job/{job_id}`       | viewer   | Poll fix job status; returns result when `completed`.  |
| POST   | `/fix/continue`           | operator | Continue a mixed workflow after a user choice.         |
| GET    | `/fix/ping`               | viewer   | Connectivity check.                                    |
| GET    | `/fix/health`             | viewer   | Fix subsystem health + best-effort cleanup.            |

`POST /fix/start` body (key fields): `agent_id`, `pattern_id`, `error_cluster {…}`,
optional `user_choice` (`library|code|both|skip`), `is_fix_all`, `fix_all_session_id`,
`pre_analysis`. The result includes `fixed_files` and a `working_directory` used by
the deploy step.

### 4.5 Draft test & deploy — `/api/v1/test-agent`

This is the **draft → test → promote** surface (see §5).

| Method | Path                                | Role     | Description                                           |
|--------|-------------------------------------|----------|-------------------------------------------------------|
| POST   | `/test-agent/build-and-test`        | operator | Build/deploy fixed code as a **draft** (async → `build_id`). Auto-routes container vs code agents. |
| POST   | `/test-agent/deploy-fixed-code`     | operator | Deploy from in-memory fixed file contents (async).    |
| GET    | `/test-agent/build-status/{build_id}`| viewer  | Poll deploy progress (`preparing→packaging→uploading→building→deploying→ready/failed`). |
| POST   | `/test-agent/deploy-draft`          | operator | Deploy a pre-built image/S3 package as a draft.       |
| POST   | `/test-agent/invoke`                | operator | Invoke the **`test`** endpoint (draft) with a prompt. |
| POST   | `/test-agent/promote`               | **admin**| Promote the tested version to the `production` endpoint. |
| POST   | `/test-agent/discard`               | operator | Delete the `test` endpoint; production unchanged.     |
| GET    | `/test-agent/status/{agent_runtime_id}` | viewer | Versions on `test`, `production`, and `DEFAULT` endpoints. |
| POST   | `/test-agent/deploy-sample`         | operator | Deploy/reset the bundled buggy **sample agent** (async → `build_id`). |
| GET    | `/test-agent/sample-status`         | viewer   | Whether the sample agent is deployed and its status.  |

`POST /test-agent/build-and-test` body:

```json
{ "agent_runtime_id": "<name>-<id>",
  "agent_name": "<name>",
  "working_directory": "<working_directory from the fix job result>" }
```

`POST /test-agent/invoke` body: `{ "agent_runtime_arn": "...", "prompt": "...", "session_id": "optional" }`
`POST /test-agent/promote` / `discard` body: `{ "agent_runtime_id": "<name>-<id>" }`

### 4.6 System health — `/api/v1/health` (all `viewer`)

| Method | Path               | Description                              |
|--------|--------------------|------------------------------------------|
| GET    | `/health/system`   | Overall health score and error metrics.  |
| GET    | `/health/agents`   | Active/failed/pending agent counts.      |
| GET    | `/health/services` | Status of CloudWatch, Bedrock, ECR, etc. |
| GET    | `/health/activity` | Recent activity (`?limit=`).             |

### 4.7 User management — `/api/v1/users` (all **admin**)

| Method | Path            | Description                                          |
|--------|-----------------|------------------------------------------------------|
| POST   | `/users/create` | Create a user and assign a role.                     |
| PUT    | `/users/role`   | Change a user's role.                                |
| GET    | `/users/list`   | List users with their roles.                         |
| DELETE | `/users/delete` | Delete a user.                                       |

Bodies: create `{email, role, temporary_password?}`; role `{email, role}`; delete `{email}`.
Valid roles: `viewer | operator | admin`.

### 4.8 Settings — `/api/v1/settings`

| Method | Path              | Role     | Description                                        |
|--------|-------------------|----------|----------------------------------------------------|
| GET    | `/settings/model` | viewer   | Active Bedrock model + available choices.          |
| PUT    | `/settings/model` | **admin**| Set the model used for analysis/fixes `{model_id}`.|

---

## 5. The draft → test → promote model

AgentCore's `DEFAULT` endpoint **always tracks the newest version** and cannot be
pinned ("Default endpoints are managed through agent updates"). To protect live
traffic, the debugger uses a dedicated **named `production` endpoint**:

1. **Deploy a fix** (`build-and-test`): the current production version is first
   captured onto a `production` endpoint (created once if absent). The fix is then
   deployed as a **new version**. `DEFAULT` auto-advances to it (the draft/test
   channel) and a `test` endpoint is pointed at it. **`production` stays on the old
   version.**
2. **Test** (`invoke`, qualifier `test`) — validate the fix in isolation; live
   traffic on `production` is unaffected.
3. **Promote** (`promote`, admin only) — repoints the `production` endpoint to the
   tested version. Invoke production with qualifier `production`.
4. **Discard** (`discard`) — deletes the `test` endpoint; `production` is untouched.

`GET /test-agent/status/{id}` returns the version each of `test`, `production`, and
`DEFAULT` is serving so you can confirm isolation.

> Container agents (ECR) and code agents (S3) follow the **same** draft/test/promote
> flow. Only the build step differs (CodeBuild image vs. zipped code package).

---

## 6. End-to-end testing walkthrough

The fastest way to exercise the whole product is with the bundled **sample agent**,
which has intentional bugs and is safe to break/reset (real agents are never reset).

```bash
export BASE="https://<cloudfront-domain>"
export TOKEN="<id token from §2>"
AUTH=(-H "Authorization: Bearer $TOKEN")
JSON=(-H "Content-Type: application/json")
```

**1. Deploy / reset the sample agent (async):**

```bash
BID=$(curl -s "${AUTH[@]}" -X POST "$BASE/api/v1/test-agent/deploy-sample" | jq -r .build_id)
# poll until ready
while :; do
  S=$(curl -s "${AUTH[@]}" "$BASE/api/v1/test-agent/build-status/$BID" | jq -r .status)
  echo "$S"; [ "$S" = ready ] || [ "$S" = failed ] && break; sleep 8
done
ARN=$(curl -s "${AUTH[@]}" "$BASE/api/v1/test-agent/sample-status" | jq -r .agent_arn)
RID=$(curl -s "${AUTH[@]}" "$BASE/api/v1/test-agent/sample-status" | jq -r .agent_id)
```

**2. Trigger an error and confirm it (DEFAULT is buggy):**

```bash
curl -s "${AUTH[@]}" "${JSON[@]}" -X POST "$BASE/api/v1/agents/test-deployed" \
  -d "{\"agent_arn\":\"$ARN\",\"prompt\":\"Show me my order history\"}"
```

**3. Find the error cluster, then start a fix (async):**

```bash
curl -s "${AUTH[@]}" "$BASE/api/v1/fix/clusters/$RID?refresh=true&limit=10"
JOB=$(curl -s "${AUTH[@]}" "${JSON[@]}" -X POST "$BASE/api/v1/fix/start" -d '{
  "agent_id":"'$RID'","pattern_id":"<pattern_id>","user_choice":"code",
  "error_cluster":{"pattern_id":"<pattern_id>","error_type":"AttributeError",
    "error_message":"'\''DataFrame'\'' object has no attribute '\''append'\''"}
}' | jq -r .job_id)
# poll
while :; do
  S=$(curl -s "${AUTH[@]}" "$BASE/api/v1/fix/job/$JOB" | jq -r .status)
  echo "$S"; [ "$S" = completed ] || [ "$S" = failed ] && break; sleep 10
done
WD=$(curl -s "${AUTH[@]}" "$BASE/api/v1/fix/job/$JOB" | jq -r .result.working_directory)
```

**4. Deploy the fix as a draft (async):**

```bash
DBID=$(curl -s "${AUTH[@]}" "${JSON[@]}" -X POST "$BASE/api/v1/test-agent/build-and-test" \
  -d "{\"agent_runtime_id\":\"$RID\",\"agent_name\":\"acd_sample_agent\",\"working_directory\":\"$WD\"}" \
  | jq -r .build_id)
# poll build-status/$DBID until ready → message reports "deployed as draft … production still serves vN"
```

**5. Confirm isolation, test the draft, then promote:**

```bash
curl -s "${AUTH[@]}" "$BASE/api/v1/test-agent/status/$RID"   # test=new, production=old
curl -s "${AUTH[@]}" "${JSON[@]}" -X POST "$BASE/api/v1/test-agent/invoke" \
  -d "{\"agent_runtime_arn\":\"$ARN\",\"prompt\":\"Show me my order history\"}"   # FIXED
curl -s "${AUTH[@]}" "${JSON[@]}" -X POST "$BASE/api/v1/test-agent/promote" \
  -d "{\"agent_runtime_id\":\"$RID\"}"   # admin only → production now serves the fix
```

For your **own** agents, the steps are identical except you skip `deploy-sample` and
use the real agent's `agent_runtime_id` / `agent_arn` from `GET /api/v1/agents/deployed`.

---

## 7. Notes for integrators

- Treat `build_id` / `job_id` as opaque; always drive the UI/automation off the
  status endpoints, not fixed sleeps.
- `promote` is the only write that affects live production traffic and is **admin-only**.
- The sample agent (`acd_sample_agent`) is the only runtime that can be reset to
  buggy code; the service refuses to push sample code to any other runtime.
- When auth is enabled, Swagger/ReDoc are off by design — use this document as the
  contract.
