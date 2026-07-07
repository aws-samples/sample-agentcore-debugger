"""
Shared AWS client factory with adaptive retry.

All Bedrock calls should use these clients instead of creating
boto3.client() directly. Adaptive retry handles TPM/quota limits
with exponential backoff automatically.

Usage:
    from app.core.aws_clients import get_bedrock_runtime, get_agentcore_control

    client = get_bedrock_runtime()
    client.invoke_model(...)
"""
import boto3
from botocore.config import Config
from functools import lru_cache

from app.core.config import settings

# Adaptive retry config — handles throttling, TPM limits, 429s, 503s
# max_attempts=10 with adaptive mode uses token bucket + exponential backoff
RETRY_CONFIG = Config(
    retries={
        "mode": "adaptive",
        "max_attempts": 10,
    },
    read_timeout=120,
    connect_timeout=10,
)


@lru_cache()
def get_bedrock_runtime(region: str = "") -> boto3.client:
    """Bedrock Runtime client for model invocations (InvokeModel)."""
    return boto3.client(
        "bedrock-runtime",
        region_name=region or settings.AWS_REGION,
        config=RETRY_CONFIG,
    )


@lru_cache()
def get_agentcore_control(region: str = "") -> boto3.client:
    """AgentCore Control Plane client (CRUD operations)."""
    return boto3.client(
        "bedrock-agentcore-control",
        region_name=region or settings.AWS_REGION,
        config=RETRY_CONFIG,
    )


@lru_cache()
def get_agentcore_data(region: str = "") -> boto3.client:
    """AgentCore Data Plane client (invoke agents)."""
    return boto3.client(
        "bedrock-agentcore",
        region_name=region or settings.AWS_REGION,
        config=RETRY_CONFIG,
    )


@lru_cache()
def get_ecr(region: str = "") -> boto3.client:
    """ECR client."""
    return boto3.client(
        "ecr",
        region_name=region or settings.AWS_REGION,
        config=RETRY_CONFIG,
    )


@lru_cache()
def get_s3(region: str = "") -> boto3.client:
    """S3 client."""
    return boto3.client(
        "s3",
        region_name=region or settings.AWS_REGION,
        config=RETRY_CONFIG,
    )


@lru_cache()
def get_sts(region: str = "") -> boto3.client:
    """STS client."""
    return boto3.client(
        "sts",
        region_name=region or settings.AWS_REGION,
        config=RETRY_CONFIG,
    )
