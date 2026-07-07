"""
AgentCore Deploy Service — deploys fixed code via CodeBuild.

Scalable approach that works for ANY container-based agent:
1. Zip fixed code → upload to CodeBuild source bucket
2. Trigger the agent's CodeBuild project (builds arm64 image, pushes to ECR)
3. Wait for CodeBuild to complete
4. Call update_agent_runtime with new ECR image URI
5. Poll until READY

Naming conventions (auto-discovered):
- CodeBuild project: bedrock-agentcore-{agent_name}-builder
- Source bucket: bedrock-agentcore-codebuild-sources-{account}-{region}
- Source key: {agent_name}/source.zip
- ECR repo: bedrock-agentcore-{agent_name}

Progress tracked via file-based storage (works across gunicorn workers).
"""
import os
import io
import json
import zipfile
import time
import logging
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime

import boto3
from botocore.config import Config

from app.core.aws_clients import get_agentcore_control

logger = logging.getLogger(__name__)

RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 10}, read_timeout=120)

# File-based progress tracker (works across gunicorn workers)
PROGRESS_DIR = "/tmp/deploy_progress"
os.makedirs(PROGRESS_DIR, exist_ok=True)


def _progress_file(build_id: str) -> str:
    return os.path.join(PROGRESS_DIR, f"{build_id}.json")


def _update_progress(build_id: str, phase: str, message: str, extra: Dict = None):
    """Update build progress (file-based for multi-worker support)."""
    existing = _load_progress(build_id) or {}
    existing_extra = existing.get("extra", {})
    if extra:
        existing_extra.update(extra)
    progress = {
        "phase": phase,
        "message": message,
        "timestamp": datetime.utcnow().isoformat(),
        "extra": existing_extra,
    }
    try:
        with open(_progress_file(build_id), "w") as f:
            json.dump(progress, f)
    except Exception as e:
        logger.error(f"[DEPLOY:{build_id}] Failed to write progress: {e}")
    logger.info(f"[DEPLOY:{build_id}] [{phase}] {message}")


def _load_progress(build_id: str) -> Optional[Dict[str, Any]]:
    path = _progress_file(build_id)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


class CodeBuildService:
    """Deploy fixed agent code via CodeBuild (scalable for any agent)."""

    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.s3 = boto3.client("s3", region_name=region, config=RETRY_CONFIG)
        self.sts = boto3.client("sts", region_name=region, config=RETRY_CONFIG)
        self.codebuild = boto3.client("codebuild", region_name=region, config=RETRY_CONFIG)
        self.control = get_agentcore_control(region)

    def _get_account_id(self) -> str:
        return self.sts.get_caller_identity()["Account"]

    def _get_agent_name_from_id(self, agent_runtime_id: str) -> str:
        """Extract agent name from runtime ID (e.g. 'test_customer_agent-eBYAyh5syD' -> 'test_customer_agent')."""
        # Runtime ID format: {name}-{random10chars}
        parts = agent_runtime_id.rsplit("-", 1)
        return parts[0] if len(parts) == 2 else agent_runtime_id

    # ── Main entry point ─────────────────────────────────────────────────

    async def build_and_deploy_draft(
        self,
        agent_runtime_id: str,
        working_directory: str,
        agent_name: str,
    ) -> Dict[str, Any]:
        """
        Deploy fixed code via CodeBuild:
        1. Zip working_directory → upload to CodeBuild source bucket
        2. Trigger CodeBuild project
        3. Background thread polls until done
        4. Calls update_agent_runtime

        Returns build_id for progress polling.
        """
        build_id = f"build-{agent_runtime_id}-{int(time.time())}"

        try:
            # Validate working directory
            work_path = Path(working_directory)
            app_dir = self._find_code_directory(work_path)
            if not app_dir:
                raise Exception(f"Working directory not found: {working_directory}")

            _update_progress(build_id, "preparing", "Preparing fixed code...",
                             extra={"agent_runtime_id": agent_runtime_id, "agent_name": agent_name})

            # Detect deployment type: container (CodeBuild) vs code (direct S3)
            deployment_type = self._detect_deployment_type(agent_runtime_id)
            logger.info(f"[DEPLOY:{build_id}] Deployment type: {deployment_type}")

            if deployment_type == "code":
                worker = self._run_code_deploy
            else:
                worker = self._run_codebuild_deploy

            thread = threading.Thread(
                target=worker,
                args=(build_id, str(app_dir), agent_name, agent_runtime_id),
                daemon=True,
            )
            thread.start()

            return {
                "status": "started",
                "build_id": build_id,
                "message": "Deployment started. Poll /test-agent/build-status/{build_id} for progress.",
            }
        except Exception as e:
            _update_progress(build_id, "failed", str(e))
            return {"status": "failed", "build_id": build_id, "error": str(e)}

    def _detect_deployment_type(self, agent_runtime_id: str) -> str:
        """Return 'code' or 'container' based on the agent's current artifact."""
        rid = agent_runtime_id[:-8] if agent_runtime_id.endswith("-DEFAULT") else agent_runtime_id
        try:
            resp = self.control.get_agent_runtime(agentRuntimeId=rid)
            artifact = resp.get("agentRuntimeArtifact", {})
            if artifact.get("codeConfiguration"):
                return "code"
            return "container"
        except Exception as e:
            logger.warning(f"Could not detect deployment type: {e}; defaulting to container")
            return "container"

    def _run_code_deploy(self, build_id: str, app_dir: str, agent_name: str, agent_runtime_id: str):
        """Direct code deployment: zip fixed code + bundle arm64 deps → S3 → update_agent_runtime."""
        try:
            rid = agent_runtime_id[:-8] if agent_runtime_id.endswith("-DEFAULT") else agent_runtime_id
            account_id = self._get_account_id()
            bucket = f"bedrock-agentcore-code-{account_id}-{self.region}"
            s3_key = f"{agent_name}/deployment_package.zip"

            _update_progress(build_id, "packaging", "Packaging fixed code + dependencies...")
            zip_buffer = self._build_code_package(app_dir)

            _update_progress(build_id, "uploading", f"Uploading to s3://{bucket}/{s3_key}...")
            zip_buffer.seek(0)
            self.s3.put_object(Bucket=bucket, Key=s3_key, Body=zip_buffer.getvalue(),
                               ExpectedBucketOwner=account_id)

            # Read current runtime config to preserve role + network + entrypoint
            current = self.control.get_agent_runtime(agentRuntimeId=rid)
            role_arn = current["roleArn"]
            network = current.get("networkConfiguration", {"networkMode": "PUBLIC"})
            code_cfg = current.get("agentRuntimeArtifact", {}).get("codeConfiguration", {})
            runtime = code_cfg.get("runtime", "PYTHON_3_13")
            entry = code_cfg.get("entryPoint", ["agent.py"])

            # Snapshot the CURRENT (known-good) production version onto a stable
            # 'production' endpoint BEFORE we deploy the fix. AgentCore always
            # advances the DEFAULT endpoint to the newest version on update, so
            # DEFAULT cannot protect production — a pinned named endpoint can.
            prod_version = current.get("agentRuntimeVersion")
            if prod_version:
                self._pin_production_if_absent(build_id, rid, prod_version)

            _update_progress(build_id, "deploying", "Updating AgentCore Runtime with fixed code...")
            resp = self.control.update_agent_runtime(
                agentRuntimeId=rid,
                agentRuntimeArtifact={
                    "codeConfiguration": {
                        "code": {"s3": {"bucket": bucket, "prefix": s3_key}},
                        "runtime": runtime,
                        "entryPoint": entry,
                    }
                },
                roleArn=role_arn,
                networkConfiguration=network,
            )
            agent_arn = resp.get("agentRuntimeArn", "")
            new_version = resp.get("agentRuntimeVersion", "")

            final = self._poll_runtime(build_id, rid)
            if final.get("status") != "READY":
                _update_progress(build_id, "failed",
                    f"Runtime failed: {final.get('status')} - {final.get('failureReason','')}")
                return

            new_version = final.get("agentRuntimeVersion", new_version)

            # Draft pattern: the fix is now the latest version. DEFAULT auto-points
            # to it (the draft/test channel); 'production' stays pinned to the prior
            # version until an admin promotes. Also expose an explicit 'test' endpoint.
            _update_progress(build_id, "deploying", f"Pointing 'test' endpoint at version {new_version}...")
            self._ensure_endpoint(rid, "test", new_version)

            _update_progress(build_id, "ready",
                f"Fixed code deployed as draft (version {new_version}). "
                f"Production still serves v{prod_version}. Test via qualifier='test', then promote.",
                extra={"agent_arn": final.get("agentRuntimeArn", agent_arn),
                       "version": new_version,
                       "test_endpoint": "test",
                       "production_version": prod_version,
                       "deployed_as": "draft"})
        except Exception as e:
            logger.error(f"[DEPLOY:{build_id}] Code deploy error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            _update_progress(build_id, "failed", str(e))

    def _build_code_package(self, app_dir: str) -> io.BytesIO:
        """Zip source files + bundle arm64 deps from requirements.txt for direct code deploy."""
        import subprocess
        import tempfile
        import shutil

        src = Path(app_dir)
        build_dir = Path(tempfile.mkdtemp(prefix="code_pkg_"))
        try:
            for f in src.iterdir():
                if f.is_file():
                    shutil.copy(f, build_dir / f.name)

            req = build_dir / "requirements.txt"
            if req.exists():
                logger.info("[DEPLOY] Installing arm64 deps into package...")
                r = subprocess.run(
                    ["pip", "install", "--target", str(build_dir),
                     "--platform", "manylinux2014_aarch64", "--implementation", "cp",
                     "--python-version", "3.13", "--only-binary=:all:", "--upgrade",
                     "-r", str(req)],
                    capture_output=True, text=True, timeout=600,
                )
                if r.returncode != 0:
                    logger.warning(f"[DEPLOY] pip warnings: {r.stderr[-400:]}")

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in build_dir.rglob("*"):
                    if f.is_file() and "__pycache__" not in f.parts:
                        zf.write(f, f.relative_to(build_dir))
            return buf
        finally:
            shutil.rmtree(build_dir, ignore_errors=True)

    async def deploy_from_fixed_files(
        self,
        agent_runtime_id: str,
        agent_name: str,
        fixed_files: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Deploy fixed code directly from file contents (no filesystem dependency).
        Zips in memory → uploads to CodeBuild source → triggers build → polls → updates runtime.
        """
        build_id = f"build-{agent_runtime_id}-{int(time.time())}"

        try:
            _update_progress(build_id, "preparing", "Packaging fixed code...",
                             extra={"agent_runtime_id": agent_runtime_id, "agent_name": agent_name})

            thread = threading.Thread(
                target=self._run_codebuild_from_files,
                args=(build_id, agent_name, agent_runtime_id, fixed_files),
                daemon=True,
            )
            thread.start()

            return {
                "status": "started",
                "build_id": build_id,
                "message": "Deployment started. Poll /test-agent/build-status/{build_id} for progress.",
            }
        except Exception as e:
            _update_progress(build_id, "failed", str(e))
            return {"status": "failed", "build_id": build_id, "error": str(e)}

    # ── Background workers ───────────────────────────────────────────────

    def _run_codebuild_deploy(self, build_id: str, app_dir: str, agent_name: str, agent_runtime_id: str):
        """Background: zip only top-level files from directory → CodeBuild → update runtime."""
        try:
            # Step 1: Create zip from top-level files only (matches source.zip structure)
            _update_progress(build_id, "packaging", "Zipping fixed code...")
            zip_buffer = io.BytesIO()
            app_path = Path(app_dir)
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in app_path.iterdir():  # Top-level only, not rglob
                    if f.is_file():
                        zf.writestr(f.name, f.read_bytes())
            logger.info(f"[DEPLOY:{build_id}] Zipped top-level files from {app_dir}")
            self._upload_and_build(build_id, agent_name, agent_runtime_id, zip_buffer)
        except Exception as e:
            logger.error(f"[DEPLOY:{build_id}] Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            _update_progress(build_id, "failed", str(e))

    def _run_codebuild_from_files(self, build_id: str, agent_name: str, agent_runtime_id: str, fixed_files: Dict[str, str]):
        """Background: zip file contents → CodeBuild → update runtime."""
        try:
            _update_progress(build_id, "packaging", "Zipping fixed code...")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for filename, content in fixed_files.items():
                    zf.writestr(filename, content)
            self._upload_and_build(build_id, agent_name, agent_runtime_id, zip_buffer)
        except Exception as e:
            logger.error(f"[DEPLOY:{build_id}] Error: {e}")
            import traceback
            logger.error(traceback.format_exc())
            _update_progress(build_id, "failed", str(e))

    def _upload_and_build(self, build_id: str, agent_name: str, agent_runtime_id: str, zip_buffer: io.BytesIO):
        """Shared logic: download existing source.zip, patch fixed files in, re-upload, trigger CodeBuild."""
        account_id = self._get_account_id()
        source_bucket = f"bedrock-agentcore-codebuild-sources-{account_id}-{self.region}"
        source_key = f"{agent_name}/source.zip"
        ecr_repo = f"bedrock-agentcore-{agent_name}"
        ecr_uri = f"{account_id}.dkr.ecr.{self.region}.amazonaws.com/{ecr_repo}:latest"
        codebuild_project = f"bedrock-agentcore-{agent_name}-builder"

        # Step 2: Download existing source.zip (has Dockerfile, requirements, etc.)
        # Then patch in the fixed files from our zip_buffer
        _update_progress(build_id, "uploading", "Patching fixed files into deployment package...")

        # Get the fixed files from our zip (index by basename for matching)
        zip_buffer.seek(0)
        fixed_files = {}
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            for name in zf.namelist():
                basename = name.split("/")[-1]
                if basename:
                    fixed_files[basename] = zf.read(name)
        logger.info(f"[DEPLOY:{build_id}] Fixed files to patch (by basename): {list(fixed_files.keys())}")

        # Download existing source.zip from S3
        try:
            existing_obj = self.s3.get_object(Bucket=source_bucket, Key=source_key)
            existing_zip_data = existing_obj["Body"].read()
            logger.info(f"[DEPLOY:{build_id}] Downloaded existing source.zip ({len(existing_zip_data)} bytes)")
        except Exception as e:
            logger.warning(f"[DEPLOY:{build_id}] No existing source.zip, using fixed files only: {e}")
            existing_zip_data = None

        # Create new zip: existing files + patched fixed files
        new_zip = io.BytesIO()
        if existing_zip_data:
            existing_zip = io.BytesIO(existing_zip_data)
            with zipfile.ZipFile(existing_zip, "r") as src:
                with zipfile.ZipFile(new_zip, "w", zipfile.ZIP_DEFLATED) as dst:
                    for item in src.namelist():
                        basename = item.split("/")[-1]
                        if basename in fixed_files:
                            dst.writestr(item, fixed_files[basename])
                            logger.info(f"[DEPLOY:{build_id}] Patched: {item}")
                        else:
                            dst.writestr(item, src.read(item))
        else:
            new_zip = self._ensure_dockerfile_in_zip(zip_buffer)

        # Upload patched source.zip
        new_zip.seek(0)
        self.s3.put_object(Bucket=source_bucket, Key=source_key, Body=new_zip.getvalue())
        logger.info(f"[DEPLOY:{build_id}] Uploaded patched source to s3://{source_bucket}/{source_key}")

        # Step 3: Trigger CodeBuild
        _update_progress(build_id, "building", f"Triggering CodeBuild: {codebuild_project}...")
        cb_resp = self.codebuild.start_build(projectName=codebuild_project)
        cb_build_id = cb_resp["build"]["id"]
        logger.info(f"[DEPLOY:{build_id}] CodeBuild started: {cb_build_id}")

        # Step 4: Poll CodeBuild until complete
        _update_progress(build_id, "building", "Building arm64 container image (2-5 min)...")
        cb_status = self._poll_codebuild(build_id, cb_build_id, max_wait=600)

        if cb_status != "SUCCEEDED":
            _update_progress(build_id, "failed", f"CodeBuild failed: {cb_status}")
            return

        # Step 5: Update agent runtime with new image
        _update_progress(build_id, "deploying", "Updating AgentCore Runtime with new image...")
        current = self.control.get_agent_runtime(agentRuntimeId=agent_runtime_id)

        # Snapshot the current known-good production version onto a stable
        # 'production' endpoint before deploying the fix (DEFAULT auto-advances).
        prod_version = current.get("agentRuntimeVersion")
        if prod_version:
            self._pin_production_if_absent(build_id, agent_runtime_id, prod_version)

        update_resp = self.control.update_agent_runtime(
            agentRuntimeId=agent_runtime_id,
            agentRuntimeArtifact={"containerConfiguration": {"containerUri": ecr_uri}},
            roleArn=current["roleArn"],
            networkConfiguration=current["networkConfiguration"],
        )
        agent_arn = update_resp.get("agentRuntimeArn", "")
        logger.info(f"[DEPLOY:{build_id}] update_agent_runtime: status={update_resp['status']}, arn={agent_arn}")

        # Step 6: Poll until READY
        _update_progress(build_id, "deploying", "Waiting for runtime READY...")
        final = self._poll_runtime(build_id, agent_runtime_id)

        if final.get("status") == "READY":
            new_version = final.get("agentRuntimeVersion", "")
            # Draft pattern: fix is the latest version (DEFAULT/draft channel);
            # 'production' stays pinned to the prior version until promotion.
            _update_progress(build_id, "deploying",
                f"Pointing 'test' endpoint at version {new_version}...")
            self._ensure_endpoint(agent_runtime_id, "test", new_version)

            _update_progress(build_id, "ready",
                f"Fixed image deployed as draft (version {new_version}). "
                f"Production still serves v{prod_version}. Test via qualifier='test', then promote.",
                extra={
                    "agent_arn": final.get("agentRuntimeArn", agent_arn),
                    "version": new_version,
                    "ecr_uri": ecr_uri,
                    "test_endpoint": "test",
                    "production_version": prod_version,
                    "deployed_as": "draft",
                })
        else:
            _update_progress(build_id, "failed",
                f"Runtime failed: {final.get('status')} - {final.get('failureReason', '')}")

    # ── Helpers ──────────────────────────────────────────────────────────

    def _find_code_directory(self, work_path: Path) -> Optional[Path]:
        """Find the directory containing agent code files (agent.py, etc.)."""
        # Direct check: does this path have agent.py or main.py?
        for candidate in [work_path, work_path / "app", work_path / "extracted_code" / "app",
                          work_path / "extracted_code"]:
            if candidate.exists() and candidate.is_dir():
                # Must have .py files directly in it (not just in subdirs)
                direct_py = [f for f in candidate.iterdir() if f.is_file() and f.suffix == ".py"]
                if direct_py:
                    return candidate

        # Search deeper: find a directory that has agent.py or main.py
        for pattern in ["**/agent.py", "**/main.py", "**/app.py"]:
            matches = list(work_path.glob(pattern))
            if matches:
                return matches[0].parent

        return None

    def _zip_directory(self, app_dir: str) -> io.BytesIO:
        """Zip a directory into a BytesIO buffer."""
        zip_buffer = io.BytesIO()
        app_path = Path(app_dir)
        exclude = {"__pycache__", ".git", "venv", ".venv", "node_modules"}

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in app_path.rglob("*"):
                if f.is_file() and not any(p in exclude for p in f.parts):
                    zf.write(f, f.relative_to(app_path))
        return zip_buffer

    def _ensure_dockerfile_in_zip(self, zip_buffer: io.BytesIO) -> io.BytesIO:
        """Ensure the zip has a Dockerfile. If not, add a standard one."""
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            names = zf.namelist()
            if "Dockerfile" in names:
                return zip_buffer  # Already has one

        # Detect if there's a requirements.txt
        zip_buffer.seek(0)
        has_requirements = False
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            has_requirements = "requirements.txt" in zf.namelist()

        # Detect entry point
        zip_buffer.seek(0)
        entry_point = "agent.py"
        with zipfile.ZipFile(zip_buffer, "r") as zf:
            for candidate in ["main.py", "agent.py", "app.py", "handler.py"]:
                if candidate in zf.namelist():
                    entry_point = candidate
                    break

        # Generate Dockerfile
        dockerfile = f"""FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
ENV UV_SYSTEM_PYTHON=1 UV_COMPILE_BYTECODE=1 UV_NO_PROGRESS=1 PYTHONUNBUFFERED=1
"""
        if has_requirements:
            dockerfile += """COPY requirements.txt requirements.txt
RUN uv pip install -r requirements.txt
"""
        dockerfile += """RUN uv pip install aws-opentelemetry-distro>=0.10.1
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore
EXPOSE 8080
COPY . .
CMD ["opentelemetry-instrument", "python", "-m", "{entry}"]
""".replace("{entry}", entry_point.replace(".py", ""))

        # Create new zip with Dockerfile added
        new_buffer = io.BytesIO()
        zip_buffer.seek(0)
        with zipfile.ZipFile(zip_buffer, "r") as src:
            with zipfile.ZipFile(new_buffer, "w", zipfile.ZIP_DEFLATED) as dst:
                for item in src.namelist():
                    dst.writestr(item, src.read(item))
                dst.writestr("Dockerfile", dockerfile)

        logger.info("[DEPLOY] Added Dockerfile to zip")
        return new_buffer

    def _poll_codebuild(self, build_id: str, cb_build_id: str, max_wait: int = 600) -> str:
        """Poll CodeBuild until terminal state. Returns SUCCEEDED/FAILED/TIMED_OUT."""
        elapsed = 0
        while elapsed < max_wait:
            resp = self.codebuild.batch_get_builds(ids=[cb_build_id])
            build = resp["builds"][0]
            status = build["buildStatus"]
            phase = build.get("currentPhase", "UNKNOWN")

            if status == "IN_PROGRESS":
                _update_progress(build_id, "building", f"CodeBuild: {phase} ({elapsed}s)...")
                time.sleep(15)
                elapsed += 15
            else:
                logger.info(f"[DEPLOY:{build_id}] CodeBuild finished: {status}")
                return status

        return "TIMED_OUT"

    def _poll_runtime(self, build_id: str, agent_runtime_id: str, max_wait: int = 120) -> Dict:
        """Poll GetAgentRuntime until READY or failure."""
        for i in range(max_wait // 10):
            r = self.control.get_agent_runtime(agentRuntimeId=agent_runtime_id)
            s = r["status"]
            _update_progress(build_id, "deploying", f"Runtime: {s} ({(i+1)*10}s)...")
            if s == "READY":
                return r
            elif "FAILED" in s:
                return {"status": s, "failureReason": r.get("failureReason", "")}
            time.sleep(10)
        return {"status": "TIMEOUT", "failureReason": f"Not READY after {max_wait}s"}

    def _endpoint_exists(self, agent_runtime_id: str, name: str) -> bool:
        """Reliable existence check (list_agent_runtime_endpoints is eventually
        consistent and often returns empty; get is authoritative)."""
        try:
            self.control.get_agent_runtime_endpoint(
                agentRuntimeId=agent_runtime_id, endpointName=name)
            return True
        except self.control.exceptions.ResourceNotFoundException:
            return False

    def _ensure_endpoint(self, agent_runtime_id: str, name: str, version: str) -> Dict[str, Any]:
        """
        Create or update a NAMED endpoint to point at a specific version.

        NOTE: update_agent_runtime_endpoint behaves as an upsert that returns 202
        even when the endpoint does not exist (without actually creating it), so we
        must check existence explicitly with get rather than catching
        ResourceNotFoundException from update.
        """
        if self._endpoint_exists(agent_runtime_id, name):
            resp = self.control.update_agent_runtime_endpoint(
                agentRuntimeId=agent_runtime_id,
                endpointName=name,
                agentRuntimeVersion=version,
                description="Managed by AgentCore Debugger",
            )
            logger.info(f"Updated '{name}' endpoint -> v{version}")
            return {"status": resp.get("status", "UPDATING")}
        resp = self.control.create_agent_runtime_endpoint(
            agentRuntimeId=agent_runtime_id,
            name=name,
            agentRuntimeVersion=version,
            description="Managed by AgentCore Debugger",
        )
        logger.info(f"Created '{name}' endpoint -> v{version}")
        return {"status": resp.get("status", "CREATING")}

    def _pin_production_if_absent(self, build_id: str, agent_runtime_id: str, version: str):
        """
        Capture the current known-good production version on a stable 'production'
        endpoint, ONLY if it does not already exist. If it exists, it already holds
        the real production version and must not be overwritten by a draft deploy.
        """
        try:
            if not self._endpoint_exists(agent_runtime_id, "production"):
                self.control.create_agent_runtime_endpoint(
                    agentRuntimeId=agent_runtime_id,
                    name="production",
                    agentRuntimeVersion=version,
                    description="Stable production endpoint — managed by AgentCore Debugger",
                )
                logger.info(f"[DEPLOY:{build_id}] Pinned 'production' endpoint -> v{version} (pre-fix snapshot)")
        except Exception as e:
            logger.warning(f"[DEPLOY:{build_id}] Could not pin 'production' endpoint: {e}")

    # ── Status endpoint ──────────────────────────────────────────────────

    async def get_build_status(self, build_id: str) -> Dict[str, Any]:
        """Get current build/deploy progress."""
        progress = _load_progress(build_id)
        if not progress:
            return {"status": "not_found", "build_id": build_id}

        extra = progress.get("extra", {})
        return {
            "build_id": build_id,
            "status": progress.get("phase", "unknown"),
            "message": progress.get("message", ""),
            "version": extra.get("version", ""),
            "agent_runtime_id": extra.get("agent_runtime_id", ""),
            "agent_arn": extra.get("agent_arn", ""),
            "agent_name": extra.get("agent_name", ""),
            "ecr_uri": extra.get("ecr_uri", ""),
            "timestamp": progress.get("timestamp", ""),
        }
