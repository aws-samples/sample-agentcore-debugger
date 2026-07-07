"""
Configuration settings for FastAPI backend
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    """Application settings"""

    # API Settings
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "AgentCore Debugger API"
    VERSION: str = "1.1.0"

    # CORS Settings — add your CloudFront URL in production
    CORS_ORIGINS: list = [
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    # AWS Settings
    AWS_REGION: str = "us-east-1"

    # Database (DynamoDB in production, SQLite for local dev)
    DATABASE_URL: str = "sqlite:///./agentcore_state.db"

    # ── Authentication (Cognito) ──────────────────────────────────────────
    # Set AUTH_ENABLED=true in production. When false, all endpoints are
    # accessible without a token (local dev convenience).
    AUTH_ENABLED: bool = False
    COGNITO_USER_POOL_ID: str = ""
    COGNITO_APP_CLIENT_ID: str = ""
    COGNITO_REGION: str = "us-east-1"
    COGNITO_DOMAIN: str = ""  # e.g. "agentcoredebuggerstack-auth"

    # ── Sample Agent ──────────────────────────────────────────────────────
    # Execution role ARN for the bundled sample/demo agent (set by CDK).
    SAMPLE_AGENT_ROLE_ARN: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
