# FastAPI Backend Dockerfile — slim build
FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

# Install minimal system deps (curl removed — health check uses Python stdlib;
# git removed — diff capture is best-effort/optional and the runtime dir is not a repo)

# Copy and install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy application code
COPY backend/ /app/backend/
COPY src/ /app/src/

# Bundle the sample (demo) agent so users can deploy it from the app
# to try the debugger before using it on their real agents.
COPY sample_agent/agent.py /app/sample_agent/agent.py
COPY sample_agent/helper_module.py /app/sample_agent/helper_module.py
COPY sample_agent/requirements.txt /app/sample_agent/requirements.txt

# Create directories for fixes and logs
RUN mkdir -p /app/agentcore_fixes /app/logs && \
    chmod 777 /app/agentcore_fixes /app/logs

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Set Python path
ENV PYTHONPATH=/app:/app/backend
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 8000

# Health check (Python stdlib — no curl dependency)
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=5).status==200 else 1)"]

# Switch to non-root user
USER appuser

# Start the application
WORKDIR /app/backend
CMD ["gunicorn", "app.main:app", "--bind", "0.0.0.0:8000", "--workers", "3", "--worker-class", "uvicorn.workers.UvicornWorker", "--timeout", "900", "--access-logfile", "-"]
