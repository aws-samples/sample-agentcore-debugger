# Sample Agent (Demo)

A deliberately buggy customer-service agent used to demonstrate the AgentCore
Debugger. It is bundled into the backend image and deployed on demand through
the app's **Deploy Sample Agent** action (no local setup required).

## Intentional bugs

| Trigger prompt | Bug | Type |
|----------------|-----|------|
| "show me my order history" | `df.append()` removed in pandas 2.0 | pandas API change |
| "what is my customer score" | `np.int` removed in NumPy 1.20+ | numpy API change |
| "check service status" | API call without retry/error handling | resilience |
| "test the imported module" | division by zero in `helper_module.py` | logic error |

## How it is deployed

The backend packages these files into a `.zip`, uploads it to the AgentCore
code-deployment S3 bucket, and calls `CreateAgentRuntime` / `UpdateAgentRuntime`
with `codeConfiguration` (direct code deployment — no Docker/ECR/CodeBuild).
The execution role is provisioned by the CDK stack and passed at runtime; no
account ID is hardcoded.

To try it: deploy the sample agent from the app, invoke it with one of the
prompts above to generate an error, then use the debugger to detect, fix, and
redeploy it.
