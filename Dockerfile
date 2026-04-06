# Multi-stage Dockerfile for helios-agent
# Stage 1: Builder - Install dependencies
# Stage 2: Runtime - Minimal production image with non-root user

# Stage 1: Builder
FROM python:3.12-slim as builder

WORKDIR /build

# Install uv for fast Python dependency management
RUN pip install --no-cache-dir uv

# Copy project files needed for dependency installation
COPY pyproject.toml uv.lock* ./

# Install dependencies with uv into a virtual environment
RUN uv sync --no-editable

# Stage 2: Runtime
FROM python:3.12-slim as runtime

WORKDIR /app

# Create non-root user for running the application
RUN useradd -m -u 1000 appuser

# Copy virtual environment from builder
COPY --from=builder --chown=appuser:appuser /build/.venv /app/.venv

# Copy application source code
COPY --chown=appuser:appuser src /app/src
COPY --chown=appuser:appuser config /app/config
COPY --chown=appuser:appuser pyproject.toml /app/

# Switch to non-root user
USER appuser

# Set PATH to use virtual environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Health check: verify the service is responsive via /api/health endpoint
# Checks every 30 seconds, fails if 3 consecutive checks fail (after 10s startup grace)
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -m uvicorn --version >/dev/null 2>&1 && \
  python -c "import httpx; httpx.get('http://localhost:8000/api/health', timeout=2)" || exit 1

# Expose the default port
EXPOSE 8000

# Run the FastAPI application with uvicorn
CMD ["uvicorn", "mcp_agent.main:app", "--host", "0.0.0.0", "--port", "8000"]
