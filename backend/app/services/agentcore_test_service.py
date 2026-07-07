"""
AgentCore Draft Testing Service

Deploys fixed code to AgentCore Runtime and tests it via the invoke API.
Uses direct code deployment (zip → S3) or container-based deployment:

  1. update_agent_runtime → creates new version (V_new)
  2. create/update "test" endpoint → points to V_new
  3. invoke via qualifier="test" → test the fix
  4. If good: update production endpoint to V_new
  5. If bad: delete test endpoint, production untouched
"""
import json
import time
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from app.core.aws_clients import get_agentcore_control, get_agentcore_data

logger = logging.getLogger(__name__)

TEST_ENDPOINT_NAME = "test"
PRODUCTION_ENDPOINT_NAME = "production"


class AgentCoreTestService:
    """Deploy fixed code to AgentCore as a draft version and test it."""

    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.control_client = get_agentcore_control(region)
        self.data_client = get_agentcore_data(region)

    # ── Deploy fixed image as new version ────────────────────────────────

    async def deploy_draft(
        self,
        agent_runtime_id: str,
        image_uri: str,
    ) -> Dict[str, Any]:
        """
        Deploy fixed code to AgentCore as a new version.
        Supports both container URIs and S3 code locations.
        Creates/updates a 'test' endpoint pointing to the new version.
        Production (DEFAULT) endpoint is NOT touched.
        """
        try:
            # Determine artifact type based on image_uri format
            if image_uri.startswith("s3://"):
                # Direct code deployment: s3://bucket/key
                parts = image_uri.replace("s3://", "").split("/", 1)
                bucket = parts[0]
                prefix = parts[1] if len(parts) > 1 else ""
                logger.info(f"Updating agent runtime {agent_runtime_id} with code from s3://{bucket}/{prefix}")
                artifact = {
                    "codeConfiguration": {
                        "code": {"s3": {"bucket": bucket, "prefix": prefix}},
                        "runtime": "PYTHON_3_13",
                        "entryPoint": ["main.py"],
                    }
                }
            else:
                # Container-based deployment
                logger.info(f"Updating agent runtime {agent_runtime_id} with image {image_uri}")
                artifact = {"containerConfiguration": {"containerUri": image_uri}}

            update_resp = self.control_client.update_agent_runtime(
                agentRuntimeId=agent_runtime_id,
                agentRuntimeArtifact=artifact,
            )
            new_version = update_resp.get("agentRuntimeVersion", "latest")
            runtime_status = update_resp.get("status", "UNKNOWN")
            agent_arn = update_resp.get("agentRuntimeArn", "")
            logger.info(f"New version created: {new_version}, status: {runtime_status}, ARN: {agent_arn}")

            # Step 2: Wait for runtime to be ready
            await self._wait_for_runtime_ready(agent_runtime_id)

            # Step 3: Create or update the 'test' endpoint
            endpoint_result = await self._ensure_test_endpoint(
                agent_runtime_id, new_version
            )

            return {
                "status": "success",
                "agent_runtime_id": agent_runtime_id,
                "agent_arn": agent_arn,
                "version": new_version,
                "test_endpoint": TEST_ENDPOINT_NAME,
                "endpoint_status": endpoint_result.get("status"),
                "message": f"Draft version {new_version} deployed. Use qualifier='{TEST_ENDPOINT_NAME}' to test.",
            }

        except Exception as e:
            logger.error(f"Failed to deploy draft: {e}")
            return {"status": "failed", "error": str(e)}

    # ── Invoke the test endpoint ─────────────────────────────────────────

    async def invoke_test(
        self,
        agent_runtime_arn: str,
        prompt: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a prompt to the 'test' endpoint of the agent.
        Production traffic is unaffected.
        """
        try:
            import uuid

            sid = session_id or f"test-{uuid.uuid4().hex}-{uuid.uuid4().hex[:8]}"
            # AgentCore requires runtimeSessionId to be at least 33 chars
            if len(sid) < 33:
                sid = (sid + "-" + uuid.uuid4().hex)[:48]

            logger.info(f"Invoking test endpoint for {agent_runtime_arn}, session={sid}")

            # Use the correct API: invoke_agent_runtime with qualifier
            response = self.data_client.invoke_agent_runtime(
                agentRuntimeArn=agent_runtime_arn,
                runtimeSessionId=sid,
                payload=json.dumps({"prompt": prompt}).encode("utf-8"),
                qualifier=TEST_ENDPOINT_NAME,
            )

            # Read streaming response
            output_chunks = []
            if "response" in response:
                for chunk in response["response"]:
                    if isinstance(chunk, bytes):
                        output_chunks.append(chunk.decode("utf-8"))
                    elif isinstance(chunk, str):
                        output_chunks.append(chunk)
            elif "body" in response:
                for event in response["body"]:
                    if "chunk" in event:
                        chunk_data = event["chunk"].get("bytes", b"")
                        output_chunks.append(chunk_data.decode("utf-8"))

            full_response = "".join(output_chunks)

            return {
                "status": "success",
                "prompt": prompt,
                "response": full_response,
                "session_id": sid,
                "qualifier": TEST_ENDPOINT_NAME,
            }

        except Exception as e:
            logger.error(f"Test invocation failed: {e}")
            return {"status": "failed", "prompt": prompt, "error": str(e)}

    # ── Promote test version to production ───────────────────────────────

    async def promote_to_production(
        self,
        agent_runtime_id: str,
    ) -> Dict[str, Any]:
        """
        Promote the version currently on the 'test' endpoint to the stable
        'production' named endpoint.

        AgentCore's DEFAULT endpoint always tracks the newest version and cannot
        be pinned ("Default endpoints are managed through agent updates"), so
        production is served by a dedicated named 'production' endpoint that we
        repoint here. Clients should invoke production via qualifier='production'.
        """
        try:
            # Find the version the 'test' endpoint points at (get is authoritative;
            # list_agent_runtime_endpoints is eventually consistent / often empty).
            try:
                test_ep = self.control_client.get_agent_runtime_endpoint(
                    agentRuntimeId=agent_runtime_id, endpointName=TEST_ENDPOINT_NAME
                )
            except self.control_client.exceptions.ResourceNotFoundException:
                return {
                    "status": "failed",
                    "error": "No test endpoint found. Deploy a draft first.",
                }

            test_version = test_ep.get("liveVersion") or test_ep.get("targetVersion")
            if not test_version:
                return {"status": "failed", "error": "Test endpoint has no resolved version yet."}

            # Repoint (or create) the 'production' named endpoint to the tested version.
            if self._endpoint_exists(agent_runtime_id, PRODUCTION_ENDPOINT_NAME):
                self.control_client.update_agent_runtime_endpoint(
                    agentRuntimeId=agent_runtime_id,
                    endpointName=PRODUCTION_ENDPOINT_NAME,
                    agentRuntimeVersion=test_version,
                    description="Stable production endpoint — managed by AgentCore Debugger",
                )
            else:
                self.control_client.create_agent_runtime_endpoint(
                    agentRuntimeId=agent_runtime_id,
                    name=PRODUCTION_ENDPOINT_NAME,
                    agentRuntimeVersion=test_version,
                    description="Stable production endpoint — managed by AgentCore Debugger",
                )

            logger.info(f"Promoted version {test_version} to '{PRODUCTION_ENDPOINT_NAME}' endpoint")

            return {
                "status": "success",
                "agent_runtime_id": agent_runtime_id,
                "promoted_version": test_version,
                "production_endpoint": PRODUCTION_ENDPOINT_NAME,
                "message": (
                    f"Version {test_version} is now live on the '{PRODUCTION_ENDPOINT_NAME}' "
                    f"endpoint. Invoke production with qualifier='{PRODUCTION_ENDPOINT_NAME}'."
                ),
            }

        except Exception as e:
            logger.error(f"Promotion failed: {e}")
            return {"status": "failed", "error": str(e)}

    def _endpoint_exists(self, agent_runtime_id: str, name: str) -> bool:
        try:
            self.control_client.get_agent_runtime_endpoint(
                agentRuntimeId=agent_runtime_id, endpointName=name)
            return True
        except self.control_client.exceptions.ResourceNotFoundException:
            return False

    # ── Discard test version ─────────────────────────────────────────────

    async def discard_draft(
        self,
        agent_runtime_id: str,
    ) -> Dict[str, Any]:
        """
        Delete the test endpoint. Production stays on its current version.
        """
        try:
            self.control_client.delete_agent_runtime_endpoint(
                agentRuntimeId=agent_runtime_id,
                endpointName=TEST_ENDPOINT_NAME,
            )
            logger.info(f"Deleted test endpoint for {agent_runtime_id}")
            return {
                "status": "success",
                "message": "Test endpoint deleted. Production unchanged.",
            }
        except self.control_client.exceptions.ResourceNotFoundException:
            return {"status": "success", "message": "No test endpoint to delete."}
        except Exception as e:
            logger.error(f"Failed to discard draft: {e}")
            return {"status": "failed", "error": str(e)}

    # ── Get test endpoint status ─────────────────────────────────────────

    async def get_test_status(
        self,
        agent_runtime_id: str,
    ) -> Dict[str, Any]:
        """Get the status of the test, production, and DEFAULT endpoints.

        Uses get_agent_runtime_endpoint per-name because
        list_agent_runtime_endpoints is eventually consistent and frequently
        returns an empty list even when endpoints exist.
        """
        def _get(name):
            try:
                ep = self.control_client.get_agent_runtime_endpoint(
                    agentRuntimeId=agent_runtime_id, endpointName=name)
                return {
                    "version": ep.get("liveVersion") or ep.get("targetVersion"),
                    "status": ep.get("status"),
                }
            except self.control_client.exceptions.ResourceNotFoundException:
                return None
            except Exception as e:
                logger.warning(f"get endpoint {name} failed: {e}")
                return None

        try:
            test_ep = _get(TEST_ENDPOINT_NAME)
            prod_ep = _get(PRODUCTION_ENDPOINT_NAME)
            default_ep = _get("DEFAULT")

            return {
                "status": "success",
                "has_test_endpoint": test_ep is not None,
                "test_endpoint": test_ep,
                "production_endpoint": prod_ep,
                "default_endpoint": default_ep,
            }

        except Exception as e:
            logger.error(f"Failed to get test status: {e}")
            return {"status": "failed", "error": str(e)}

    # ── Internal helpers ─────────────────────────────────────────────────

    async def _wait_for_runtime_ready(
        self, agent_runtime_id: str, max_wait: int = 180
    ):
        """Poll until the runtime status is READY or timeout."""
        logger.info(f"Waiting for runtime {agent_runtime_id} to become READY (max {max_wait}s)")
        for i in range(max_wait // 5):
            resp = self.control_client.get_agent_runtime(
                agentRuntimeId=agent_runtime_id
            )
            status = resp.get("status", "")
            logger.info(f"  Poll {i+1}: status={status}")
            if status == "READY":
                logger.info(f"Runtime {agent_runtime_id} is READY")
                return
            if status in ("FAILED", "CREATE_FAILED", "UPDATE_FAILED"):
                failure_reason = resp.get("failureReason", "Unknown")
                raise Exception(f"Runtime entered {status} state: {failure_reason}")
            time.sleep(5)
        raise Exception(f"Runtime not ready after {max_wait}s")

    async def _ensure_test_endpoint(
        self, agent_runtime_id: str, version: str
    ) -> Dict[str, Any]:
        """Create the test endpoint if it doesn't exist, otherwise update it.

        update_agent_runtime_endpoint is an upsert that returns 202 even when the
        endpoint doesn't exist (without creating it), so we check existence with
        get rather than relying on ResourceNotFoundException from update.
        """
        if self._endpoint_exists(agent_runtime_id, TEST_ENDPOINT_NAME):
            resp = self.control_client.update_agent_runtime_endpoint(
                agentRuntimeId=agent_runtime_id,
                endpointName=TEST_ENDPOINT_NAME,
                agentRuntimeVersion=version,
                description="Draft testing endpoint — managed by AgentCore Debugger",
            )
            logger.info(f"Updated test endpoint to version {version}")
            return {"status": resp.get("status", "UPDATING")}
        resp = self.control_client.create_agent_runtime_endpoint(
            agentRuntimeId=agent_runtime_id,
            name=TEST_ENDPOINT_NAME,
            agentRuntimeVersion=version,
            description="Draft testing endpoint — managed by AgentCore Debugger",
        )
        logger.info(f"Created test endpoint at version {version}")
        return {"status": resp.get("status", "CREATING")}
