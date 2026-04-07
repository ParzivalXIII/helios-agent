# Copilot Instructions for helios-agent

A multi-turn LLM agent with MCP (Model Context Protocol) server integration, LangGraph orchestration, OpenRouter backend, and Redis-backed sessions.

## Quick commands (copy-paste)

- Install dependencies (recommended):
  - `uv sync` (installs into .venv from pyproject.toml / uv.lock)
  - `uv sync --no-editable` (non-editable installs for CI/build)
- Activate venv: `source .venv/bin/activate`
- Run single pytest test function or file:
  - `pytest tests/test_agent.py` (single file)
  - `pytest tests/test_agent.py::test_function_name` (single test)
- Run type check: `pyright src/`

## Build & Run

**Prerequisites:** Python 3.12, UV, Docker & Docker Compose

### Local Development

```bash
# Install dependencies using UV (faster than pip)
uv sync

# Activate virtual environment
source .venv/bin/activate

# Copy and configure environment
cp .env.example .env
# Edit .env with your OpenRouter API key and settings
```

**Run locally (requires Redis running separately):**

```bash
# Start a local Redis in another terminal
redis-server

# Run the FastAPI app (reload for dev)
uvicorn mcp_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

Notes: ensure `REDIS_URL` in `.env` points to your Redis instance (default redis://localhost:6379/0).

**Run with Docker Compose (recommended):**

```bash
docker-compose up --build --remove-orphans
# Follow logs: docker-compose logs -f helios-agent
# Stop: docker-compose down
```

## Testing

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_agent.py

# Run a single test function in-file
pytest tests/test_agent.py::test_function_name

# Run with coverage
pytest --cov=src/mcp_agent

# Verbose async tests
pytest -v -s tests/
```

Dev dependencies: `pytest>=9.0.2`, `pytest-asyncio>=1.3.0` (see pyproject.toml)

## Linting & Type checking

- Type checking: `pyright src/` (project uses Pyright via dev deps)
- Formatting/lint: follow PEP 8 and project type-hinting conventions. Use your preferred formatter (`ruff`/`black`) if present.

## Architecture (high-level)

- FastAPI app exposes the agent API and health endpoints (`mcp_agent.main`, `mcp_agent/api/`)
- Redis-backed session store holds conversation state, tool call records, and agent metadata (`mcp_agent/session/`)
- Agent decision & orchestration layer uses LangGraph and dataclass-based AgentState to route messages, call tools, and persist turns (`mcp_agent/agent/`)
- MCP (Model Context Protocol) servers provide tool integrations (stdio, SSE, FastMCP). Tools are discovered at startup and routed via a ToolRegistry (`mcp_agent/mcp/`)
- Structured JSON logging (loguru) is used with session/node context binding for observability

## Key components & entrypoints

- mcp_agent.main: application entrypoint (uvicorn)
- mcp_agent/api/models.py: Pydantic request/response models
- mcp_agent/session/: Redis session management utilities
- mcp_agent/agent/: Agent state, decision logic, and orchestration
- config/mcp_servers.yaml: Example MCP server entries (edit to add servers)

## Key conventions (project-specific)

- Async-first: prefer `async def` and `await` for I/O. Tests use `pytest-asyncio`.
- Type hints everywhere: functions and methods must be typed (pyright checks).
- Dataclass AgentState: agent conversation state serializes to Redis; keep fields stable to avoid migration issues.
- Pydantic for external/API contracts: add fields to Pydantic models rather than mutating raw dicts.
- Tool call resilience: tool failures use auto-retry and optional fallback tools—keep retries/fallback logic in place when adding tools.
- Config via environment: `.env` values control LLM, Redis, and timeouts—don't hardcode secrets.

## Environment variables (high-level)

Required:
- LLM_BASE_URL or OPENROUTER_BASE_URL (LLM provider URL)
- LLM_MODEL or OPENROUTER model id
- REDIS_URL (e.g., redis://localhost:6379/0)

Useful defaults are defined in docker-compose.yml and `.env.example`.

## Docker & CI notes

- The Dockerfile is multi-stage (uv sync in build stage). CI should export a cached `.venv` or re-run `uv sync`.
- Compose healthchecks validate Redis and the FastAPI health endpoint. Use `docker-compose logs -f helios-agent` to debug startup failures.

## MCP servers & tools

- Edit `config/mcp_servers.yaml` to declare MCP servers. The agent discovers tools at startup and registers them in the ToolRegistry.
- Example transports: stdio (subprocess), sse (HTTP), fastmcp (in-process)

## Where to look next (quick pointers)

- Add routes: `mcp_agent/api/` (models + new routes in `api/routes.py`)
- Session debugging: `redis-cli -u redis://localhost:6379/0` and inspect session keys
- Tests: `tests/` contains unit/async tests—run single tests during development

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
