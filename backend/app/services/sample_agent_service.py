"""
Sample Agent Service — deploys the bundled demo agent via direct code deployment.

Lets users try the AgentCore Debugger on a known-buggy sample agent before
pointing it at their real agents. Uses direct code deployment (zip → S3 →
create/update_agent_runtime with codeConfiguration) — no Docker, no CodeBuild,
no ECR. The account ID is resolved at runtime via STS; nothing is hardcoded.

The sample agent (test_customer_agent) contains intentional bugs:
  - pandas df.append() (removed in pandas 2.0)
  - numpy np.int (removed in numpy 1.20+)
  - API call without retry
  - division by zero in helper_module
"""
import io
import json
import time
import zipfile
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional

import boto3
from botocore.config import Config

from app.core.config import settings
from app.core.aws_clients import get_agentcore_control
from app.services.codebuild_service import _update_progress, _load_progress

logger = logging.getLogger(__name__)

RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 10}, read_timeout=120)

SAMPLE_AGENT_NAME = "acd_sample_agent"
SAMPLE_CODE_DIR = "/app/sample_agent"


class SampleAgentService:
    """Deploy the bundled sample/demo agent for trying out the debugger."""

    def __init__(self, region: str = ""):
        self.region = region or settings.AWS_REGION
        self.s3 = boto3.client("s3", region_name=self.region, config=RETRY_CONFIG)
        self.sts = boto3.client("sts", region_name=self.region, config=RETRY_CONFIG)
        self.control = get_agentcore_control(self.region)

    def _account_id(self) -> str:
        return self.sts.get_caller_identity()["Account"]

    def _deploy_bucket(self, account_id: str) -> str:
        return f"bedrock-agentcore-code-{account_id}-{self.region}"

    def _ensure_bucket(self, bucket: str):
        try:
            self.s3.head_bucket(Bucket=bucket)
        except Exception:
            logger.info(f"[SAMPLE] Creating deploy bucket {bucket}")
            if self.region == "us-east-1":
                self.s3.create_bucket(Bucket=bucket)
            else:
                self.s3.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": self.region},
                )

    def _find_existing_runtime(self) -> Optional[Dict[str, Any]]:
        """Find an existing sample agent runtime by name."""
        try:
            paginator = self.control.get_paginator("list_agent_runtimes")
            for page in paginator.paginate():
                for rt in page.get("agentRuntimes", []):
                    if rt.get("agentRuntimeName") == SAMPLE_AGENT_NAME:
                        return rt
        except Exception as e:
            logger.warning(f"[SAMPLE] list_agent_runtimes failed: {e}")
        return None

    def _build_zip(self) -> io.BytesIO:
        """
        Package the bundled sample agent code + its dependencies into a zip.

        Direct code deployment requires dependencies to be bundled in the
        package (AgentCore does not pip-install at invoke time). We install
        arm64 (aarch64) wheels via pip --platform so the package works on the
        AgentCore Runtime regardless of the backend's own architecture.
        """
        import subprocess
        import tempfile
        import shutil

        code_dir = Path(SAMPLE_CODE_DIR)
        if not code_dir.exists():
            raise Exception(f"Sample agent code not found at {SAMPLE_CODE_DIR}")

        build_dir = Path(tempfile.mkdtemp(prefix="sample_pkg_"))
        try:
            # Copy source files
            for f in code_dir.iterdir():
                if f.is_file():
                    shutil.copy(f, build_dir / f.name)

            # Install dependencies as arm64 wheels into the package
            req = build_dir / "requirements.txt"
            if req.exists():
                logger.info("[SAMPLE] Installing arm64 dependencies into package...")
                result = subprocess.run(
                    [
                        "pip", "install",
                        "--target", str(build_dir),
                        "--platform", "manylinux2014_aarch64",
                        "--implementation", "cp",
                        "--python-version", "3.13",
                        "--only-binary=:all:",
                        "--upgrade",
                        "-r", str(req),
                    ],
                    capture_output=True, text=True, timeout=600,
                )
                if result.returncode != 0:
                    logger.warning(f"[SAMPLE] pip install warnings: {result.stderr[-500:]}")

            # Zip everything (source + deps), excluding caches
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in build_dir.rglob("*"):
                    if f.is_file() and "__pycache__" not in f.parts:
                        zf.write(f, f.relative_to(build_dir))

            size_mb = len(zip_buffer.getvalue()) / (1024 * 1024)
            logger.info(f"[SAMPLE] Package built: {size_mb:.1f} MB")
            if size_mb > 250:
                raise Exception(f"Package too large: {size_mb:.0f} MB (max 250 MB)")
            return zip_buffer
        finally:
            shutil.rmtree(build_dir, ignore_errors=True)

    async def deploy_sample(self) -> Dict[str, Any]:
        """
        Start deploying (or updating) the sample agent in the background.

        Returns immediately with a build_id. The actual packaging + deploy + poll
        is long-running (pip install of arm64 deps + runtime READY can take a few
        minutes), so it runs in a background thread to avoid CloudFront/ALB
        gateway timeouts. Poll progress via /test-agent/build-status/{build_id}.
        """
        if not settings.SAMPLE_AGENT_ROLE_ARN:
            return {
                "status": "failed",
                "error": "SAMPLE_AGENT_ROLE_ARN not configured. Redeploy the stack to enable the sample agent feature.",
            }

        build_id = f"sample-{int(time.time())}"
        _update_progress(build_id, "preparing", "Preparing sample agent...",
                         extra={"agent_name": SAMPLE_AGENT_NAME})
        threading.Thread(target=self._run_deploy, args=(build_id,), daemon=True).start()
        return {
            "status": "started",
            "build_id": build_id,
            "message": "Sample deployment started. Poll /test-agent/build-status/{build_id} for progress.",
        }

    def _run_deploy(self, build_id: str):
        """Background worker: package → upload → create/update runtime → poll READY."""
        try:
            account_id = self._account_id()
            bucket = self._deploy_bucket(account_id)
            s3_key = f"{SAMPLE_AGENT_NAME}/deployment_package.zip"

            # Step 1: Package + upload
            _update_progress(build_id, "packaging", "Packaging sample agent code + arm64 dependencies...")
            zip_buffer = self._build_zip()
            self._ensure_bucket(bucket)
            _update_progress(build_id, "uploading", f"Uploading package to s3://{bucket}/{s3_key}...")
            zip_buffer.seek(0)
            self.s3.put_object(
                Bucket=bucket, Key=s3_key, Body=zip_buffer.getvalue(),
                ExpectedBucketOwner=account_id,
            )
            logger.info(f"[SAMPLE] Uploaded to s3://{bucket}/{s3_key}")

            artifact = {
                "codeConfiguration": {
                    "code": {"s3": {"bucket": bucket, "prefix": s3_key}},
                    "runtime": "PYTHON_3_13",
                    "entryPoint": ["agent.py"],
                }
            }

            # Step 2: Create or update the runtime
            existing = self._find_existing_runtime()
            if existing:
                # SAFETY: only ever update the runtime whose name is exactly the
                # bundled sample agent. _find_existing_runtime already matches by
                # name, but we re-assert here so buggy code can NEVER be pushed to
                # a real/customer agent — that path does not exist in this service.
                if existing.get("agentRuntimeName") != SAMPLE_AGENT_NAME:
                    _update_progress(build_id, "failed",
                        "Refusing to deploy sample (buggy) code to a non-sample agent.")
                    return
                agent_id = existing["agentRuntimeId"]
                logger.info(f"[SAMPLE] Updating existing sample agent {agent_id}")
                _update_progress(build_id, "deploying", "Updating sample AgentCore Runtime...")
                resp = self.control.update_agent_runtime(
                    agentRuntimeId=agent_id,
                    agentRuntimeArtifact=artifact,
                    roleArn=settings.SAMPLE_AGENT_ROLE_ARN,
                    networkConfiguration={"networkMode": "PUBLIC"},
                )
                action = "updated"
            else:
                logger.info("[SAMPLE] Creating new sample agent")
                _update_progress(build_id, "deploying", "Creating sample AgentCore Runtime...")
                resp = self.control.create_agent_runtime(
                    agentRuntimeName=SAMPLE_AGENT_NAME,
                    agentRuntimeArtifact=artifact,
                    roleArn=settings.SAMPLE_AGENT_ROLE_ARN,
                    networkConfiguration={"networkMode": "PUBLIC"},
                )
                agent_id = resp["agentRuntimeId"]
                action = "created"

            agent_arn = resp.get("agentRuntimeArn", "")
            logger.info(f"[SAMPLE] {action}: id={agent_id}, arn={agent_arn}")

            # Step 3: Poll until READY
            final = self._poll_ready(agent_id, build_id=build_id)
            if final.get("status") == "READY":
                _update_progress(build_id, "ready",
                    f"Sample agent {action} and ready. It contains intentional bugs "
                    f"(pandas df.append, numpy np.int, missing API retry, division by zero). "
                    f"Invoke it, then use the debugger to fix it.",
                    extra={
                        "agent_id": agent_id,
                        "agent_arn": final.get("agentRuntimeArn", agent_arn),
                        "agent_name": SAMPLE_AGENT_NAME,
                        "version": final.get("agentRuntimeVersion", ""),
                        "action": action,
                        "deployed_as": "sample",
                    })
            else:
                _update_progress(build_id, "failed",
                    f"Runtime status: {final.get('status')} - {final.get('failureReason', '')}")
        except Exception as e:
            logger.error(f"[SAMPLE] Deploy failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            _update_progress(build_id, "failed", str(e))

    def _poll_ready(self, agent_id: str, max_wait: int = 180, build_id: str = "") -> Dict[str, Any]:
        for i in range(max_wait // 10):
            r = self.control.get_agent_runtime(agentRuntimeId=agent_id)
            s = r.get("status", "")
            logger.info(f"[SAMPLE] Poll {i+1}: {s}")
            if build_id:
                _update_progress(build_id, "deploying", f"Runtime: {s} ({(i+1)*10}s)...")
            if s == "READY":
                return r
            if "FAILED" in s:
                return {"status": s, "failureReason": r.get("failureReason", "")}
            time.sleep(10)
        return {"status": "TIMEOUT", "failureReason": f"Not READY after {max_wait}s"}

    async def get_sample_status(self) -> Dict[str, Any]:
        """Return whether the sample agent exists and its status."""
        existing = self._find_existing_runtime()
        if not existing:
            return {"deployed": False}
        return {
            "deployed": True,
            "agent_id": existing["agentRuntimeId"],
            "agent_arn": existing.get("agentRuntimeArn", ""),
            "agent_name": SAMPLE_AGENT_NAME,
            "status": existing.get("status", ""),
        }
