"""
Shared adaptive retry config for all AWS clients in src/.

Handles Bedrock TPM limits, throttling, 429s, 503s automatically
with exponential backoff via boto3's adaptive retry mode.
"""
from botocore.config import Config

ADAPTIVE_RETRY = Config(
    retries={
        "mode": "adaptive",
        "max_attempts": 10,
    },
    read_timeout=120,
    connect_timeout=10,
)
