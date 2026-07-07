"""
FastAPI main application
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import logging
import httpx

from app.core.config import settings
from app.api.v1 import agents, errors, fix, health, test_agent, users, settings as settings_api

logger = logging.getLogger(__name__)

# Disable Swagger/ReDoc in production (AUTH_ENABLED=true)
_docs_url = "/docs" if not settings.AUTH_ENABLED else None
_redoc_url = "/redoc" if not settings.AUTH_ENABLED else None

# Create FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="REST API for AgentCore Debugger",
    docs_url=_docs_url,
    redoc_url=_redoc_url,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint (unauthenticated — used by ALB)
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return JSONResponse(
        content={
            "status": "healthy",
            "service": settings.PROJECT_NAME,
            "version": settings.VERSION
        }
    )


# Root endpoint (unauthenticated)
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "AgentCore Debugger API",
        "version": settings.VERSION,
        "docs": "/docs",
        "health": "/health"
    }


# Auth info endpoint — frontend calls this to check auth config
@app.get("/auth/config")
async def auth_config():
    """Return auth configuration for the frontend."""
    cognito_domain = ""
    if settings.AUTH_ENABLED and settings.COGNITO_USER_POOL_ID:
        cognito_domain = f"https://{settings.COGNITO_DOMAIN}.auth.{settings.COGNITO_REGION}.amazoncognito.com"
    return {
        "auth_enabled": settings.AUTH_ENABLED,
        "cognito_user_pool_id": settings.COGNITO_USER_POOL_ID if settings.AUTH_ENABLED else "",
        "cognito_app_client_id": settings.COGNITO_APP_CLIENT_ID if settings.AUTH_ENABLED else "",
        "cognito_region": settings.COGNITO_REGION if settings.AUTH_ENABLED else "",
        "cognito_domain": cognito_domain,
    }


class TokenExchangeRequest(BaseModel):
    """Authorization-code exchange request from the SPA."""
    code: str
    redirect_uri: str


@app.post("/auth/token")
async def auth_token(req: TokenExchangeRequest):
    """Exchange an OAuth2 authorization code for Cognito tokens, server-side.

    The browser only ever talks to this backend (via the app's API client);
    the cross-origin request to the Cognito hosted-UI token endpoint is made
    here. The token endpoint host is derived solely from server configuration
    (COGNITO_DOMAIN / COGNITO_REGION), never from client input — the only
    client-supplied values (code, redirect_uri) are sent in the form body and
    are validated by Cognito against the registered callback URLs.
    """
    if not (settings.AUTH_ENABLED and settings.COGNITO_DOMAIN and settings.COGNITO_APP_CLIENT_ID):
        raise HTTPException(status_code=400, detail="Authentication is not configured")

    token_url = (
        f"https://{settings.COGNITO_DOMAIN}.auth."
        f"{settings.COGNITO_REGION}.amazoncognito.com/oauth2/token"
    )
    form = {
        "grant_type": "authorization_code",
        "client_id": settings.COGNITO_APP_CLIENT_ID,
        "code": req.code,
        "redirect_uri": req.redirect_uri,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                token_url,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError as exc:
        logger.error("Cognito token exchange request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Token exchange request failed")

    if resp.status_code != 200:
        logger.warning("Cognito token exchange returned %s: %s", resp.status_code, resp.text)
        raise HTTPException(status_code=401, detail="Token exchange failed")

    tokens = resp.json()
    return {
        "id_token": tokens.get("id_token"),
        "access_token": tokens.get("access_token"),
        "expires_in": tokens.get("expires_in"),
        "token_type": tokens.get("token_type"),
    }


# Include routers
app.include_router(agents.router, prefix=settings.API_V1_PREFIX)
app.include_router(errors.router, prefix=settings.API_V1_PREFIX)
app.include_router(fix.router, prefix=settings.API_V1_PREFIX)
app.include_router(health.router, prefix=settings.API_V1_PREFIX)
app.include_router(test_agent.router, prefix=settings.API_V1_PREFIX)
app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(settings_api.router, prefix=settings.API_V1_PREFIX)


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler — never leak internal details to clients."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
        }
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
