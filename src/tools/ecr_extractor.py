"""
ECR Code Extractor — pulls agent code from ECR without Docker.

Uses boto3 ECR API to download image layers and extract code files.
Works in Fargate/serverless environments where Docker daemon is unavailable.
"""
import os
import io
import gzip
import json
import tarfile
import tempfile
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

RETRY_CONFIG = Config(retries={"mode": "adaptive", "max_attempts": 10}, read_timeout=120)


class ECRExtractor:
    """Extract code from ECR container images using boto3 (no Docker needed)."""

    def __init__(self, region: str = "us-east-1"):
        self.region = region
        self.ecr_client = boto3.client("ecr", region_name=region, config=RETRY_CONFIG)

    def extract_code(
        self,
        repository: str,
        tag: str = "latest",
        extract_to: Optional[Path] = None,
        registry: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Download and extract code from an ECR image.

        Args:
            repository: ECR repository name (e.g. 'bedrock-agentcore-test_customer_agent')
            tag: Image tag (default: 'latest')
            extract_to: Directory to extract code into
            registry: ECR registry URL (auto-detected if not provided)

        Returns:
            Dict with extracted files, paths, and analysis
        """
        if extract_to is None:
            extract_to = Path(tempfile.mkdtemp(prefix="ecr_extract_"))

        extract_to.mkdir(parents=True, exist_ok=True)
        logger.info(f"Extracting {repository}:{tag} to {extract_to}")

        try:
            # Step 1: Get image manifest
            manifest = self._get_image_manifest(repository, tag)

            # Step 2: Download and extract each layer
            layers = manifest.get("layers", [])
            logger.info(f"Image has {len(layers)} layers")

            extracted_files = {}
            for i, layer in enumerate(layers):
                digest = layer["digest"]
                logger.info(f"Processing layer {i+1}/{len(layers)}: {digest[:20]}...")
                layer_files = self._download_and_extract_layer(
                    repository, digest, extract_to
                )
                extracted_files.update(layer_files)

            # Step 3: Analyze extracted code
            analysis = self._analyze_extracted_code(extract_to)

            return {
                "status": "success",
                "extract_path": str(extract_to),
                "files_extracted": len(extracted_files),
                "file_list": list(extracted_files.keys()),
                "analysis": analysis,
            }

        except Exception as e:
            logger.error(f"ECR extraction failed: {e}")
            return {"status": "failed", "error": str(e)}

    def extract_requirements_only(
        self, repository: str, tag: str = "latest"
    ) -> Dict[str, str]:
        """
        Extract only requirements.txt from an ECR image (fast path).
        Used by Library Agent for package analysis.
        """
        try:
            manifest = self._get_image_manifest(repository, tag)
            layers = manifest.get("layers", [])

            # Search layers in reverse (app code is usually in later layers)
            for layer in reversed(layers):
                digest = layer["digest"]
                content = self._search_layer_for_file(
                    repository, digest, ["requirements.txt", "setup.py", "pyproject.toml"]
                )
                if content:
                    return content

            return {}

        except Exception as e:
            logger.error(f"Failed to extract requirements: {e}")
            return {}

    # ── Internal methods ─────────────────────────────────────────────────

    def _get_image_manifest(self, repository: str, tag: str) -> dict:
        """Get the image manifest from ECR."""
        resp = self.ecr_client.batch_get_image(
            repositoryName=repository,
            imageIds=[{"imageTag": tag}],
            acceptedMediaTypes=[
                "application/vnd.docker.distribution.manifest.v2+json",
                "application/vnd.oci.image.manifest.v1+json",
            ],
        )

        images = resp.get("images", [])
        if not images:
            raise Exception(f"Image {repository}:{tag} not found in ECR")

        manifest = json.loads(images[0]["imageManifest"])
        return manifest

    def _download_and_extract_layer(
        self, repository: str, digest: str, extract_to: Path
    ) -> Dict[str, str]:
        """Download a single layer and extract its contents. Streams to disk to avoid OOM."""
        resp = self.ecr_client.get_download_url_for_layer(
            repositoryName=repository, layerDigest=digest
        )
        download_url = resp["downloadUrl"]

        import tempfile
        extracted = {}
        try:
            # Stream to temp file instead of memory to avoid OOM
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=True) as tmp:
                import requests
                with requests.get(download_url, stream=True, timeout=120) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        tmp.write(chunk)
                tmp.flush()
                tmp.seek(0)

                try:
                    with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
                        extracted = self._safe_extract_tar(tar, extract_to)
                except tarfile.ReadError:
                    tmp.seek(0)
                    try:
                        with tarfile.open(fileobj=tmp, mode="r:") as tar:
                            extracted = self._safe_extract_tar(tar, extract_to)
                    except Exception:
                        logger.debug(f"Layer {digest[:20]} is not a tar archive, skipping")
        except Exception as e:
            logger.warning(f"Failed to process layer {digest[:20]}: {e}")

        return extracted

    def _safe_extract_tar(self, tar: tarfile.TarFile, extract_to: Path) -> Dict[str, str]:
        """Safely extract tar contents, filtering out dangerous paths."""
        extracted = {}
        code_dirs = ["/app/", "/code/", "/src/", "/opt/app/", "/usr/src/app/", "/var/task/"]

        for member in tar.getmembers():
            # Skip directories, symlinks, and non-regular files
            if not member.isreg():
                continue

            # Skip very large files (>5MB)
            if member.size > 5 * 1024 * 1024:
                continue

            # Security: prevent path traversal
            if member.name.startswith("..") or member.name.startswith("/"):
                clean_name = member.name.lstrip("./")
            else:
                clean_name = member.name

            # Focus on code-relevant files
            is_code_file = any(
                clean_name.endswith(ext)
                for ext in [".py", ".txt", ".yaml", ".yml", ".json", ".toml", ".cfg", ".ini", ".md"]
            )
            is_in_code_dir = any(d.lstrip("/") in clean_name for d in code_dirs)

            if is_code_file or is_in_code_dir:
                dest = extract_to / clean_name
                dest.parent.mkdir(parents=True, exist_ok=True)

                try:
                    f = tar.extractfile(member)
                    if f:
                        content = f.read()
                        dest.write_bytes(content)
                        extracted[clean_name] = str(dest)
                except Exception:
                    pass

        return extracted

    def _search_layer_for_file(
        self, repository: str, digest: str, filenames: List[str]
    ) -> Dict[str, str]:
        """Search a layer for specific files without full extraction. Streams to disk."""
        resp = self.ecr_client.get_download_url_for_layer(
            repositoryName=repository, layerDigest=digest
        )

        import tempfile
        import requests as req
        results = {}
        try:
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=True) as tmp:
                with req.get(resp["downloadUrl"], stream=True, timeout=120) as r:
                    r.raise_for_status()
                    for chunk in r.iter_content(chunk_size=8192):
                        tmp.write(chunk)
                tmp.flush()
                tmp.seek(0)

                with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
                    for member in tar.getmembers():
                        if member.isreg() and any(
                            member.name.endswith(fn) for fn in filenames
                        ):
                            f = tar.extractfile(member)
                            if f:
                                results[os.path.basename(member.name)] = f.read().decode(
                                    "utf-8", errors="replace"
                                )
        except Exception:
            pass

        return results

    def _analyze_extracted_code(self, extract_path: Path) -> Dict[str, Any]:
        """Analyze the extracted code structure."""
        analysis = {
            "python_files": [],
            "requirements_files": [],
            "entry_points": [],
            "total_files": 0,
        }

        for f in extract_path.rglob("*"):
            if f.is_file():
                analysis["total_files"] += 1
                rel = str(f.relative_to(extract_path))

                if f.suffix == ".py":
                    analysis["python_files"].append(rel)
                    # Check for common entry points
                    if f.name in ["agent.py", "main.py", "app.py", "handler.py"]:
                        analysis["entry_points"].append(rel)

                elif f.name in ["requirements.txt", "setup.py", "pyproject.toml"]:
                    analysis["requirements_files"].append(rel)

        return analysis
