# Multi-stage Dockerfile for helios-agent
# Stage 1: Builder - Install dependencies
# Stage 2: Runtime - Minimal production image with non-root user

# Stage 1: Builder
FROM python:3.12-slim as builder

WORKDIR /build

# Copy project files needed for dependency installation
COPY pyproject.toml ./

# Install dependencies directly with pip (faster for Docker builds)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -e .

# Stage 2: Runtime
FROM python:3.12-slim as runtime

WORKDIR /app

# Create non-root user for running the application
RUN useradd -m -u 1000 appuser

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source code
COPY --chown=appuser:appuser src /app/src
COPY --chown=appuser:appuser config /app/config
COPY --chown=appuser:appuser pyproject.toml /app/

# Switch to non-root user
USER appuser

# Environment configuration
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH="/app/src:$PYTHONPATH"

# Health check: verify the service is responsive via /api/health endpoint
# Checks every 30 seconds, fails if 3 consecutive checks fail (after 10s startup grace)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import httpx; httpx.get('http://localhost:8000/api/health', timeout=2)" || exit 1

# Expose the default port
EXPOSE 8000

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "mcp_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
