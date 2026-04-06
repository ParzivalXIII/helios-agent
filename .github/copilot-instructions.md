# Copilot Instructions for helios-agent

A multi-turn LLM agent with MCP (Model Context Protocol) server integration, LangGraph orchestration, OpenRouter backend, and Redis-backed sessions.

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

**Run with Docker Compose (recommended):**
```bash
docker-compose up
# Service runs on http://localhost:8000
# Redis on localhost:6379
# Health check: curl http://localhost:8000/api/health
```

**Run locally (requires Redis running separately):**
```bash
redis-server  # in another terminal
uvicorn mcp_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

## Testing

```bash
# Run all tests
pytest

# Run single test file
pytest tests/test_agent.py

# Run with coverage
pytest --cov=src/mcp_agent

# Run async tests with verbose output
pytest -v -s tests/
```

Dependencies: `pytest>=9.0.2`, `pytest-asyncio>=1.3.0`

## Code Style & Linting

**Type checking with Pyright:**
```bash
pyright src/
```

**Format & lint:** Project uses standard Python conventions. Follow PEP 8, use type hints throughout, and keep functions focused.

## Architecture

### High-Level Flow

1. **API Entry Point** (`mcp_agent/api/models.py`): FastAPI receives chat requests with `session_id` and `message`
2. **Session Management** (`mcp_agent/session/`): Redis stores ephemeral session state with TTL (default 1 hour)
3. **Agent State** (`mcp_agent/agent/state.py`): Dataclasses for conversation history, tool calls, and agent decisions
4. **LangGraph Orchestration**: Multi-turn loop with conditional routing:
   - Analyze user message → decide: use tool, direct response, or error handling
   - Tool execution with retry & fallback (if primary tool fails)
   - Generate LLM response, persist to session, return to user
5. **MCP Server Integration** (`mcp_agent/mcp/`): Discover and route to multiple MCP servers (stdio, SSE, FastMCP) based on `config/mcp_servers.yaml`
6. **Logging** (`mcp_agent/logging/setup.py`): Structured JSON logs with loguru, session/node context binding

### Key Components

- **Settings** (`settings.py`): Pydantic-based config loaded from `.env` (LLM URL/model, Redis URL, timeouts, MCP config path)
- **Types** (`types.py`): Type aliases (`SessionId`, `ToolId`, `AgentDecision`)
- **Validators** (`utils/validators.py`): Input validation helpers
- **API Models** (`api/models.py`): Pydantic models for REST request/response (ChatRequest, ChatResponse, ToolCallSummary)

### Session State (Redis)

Sessions store:
- Conversation history (user, assistant, tool messages with timestamps)
- Tool call records (tool_id, status, output/error, attempt count, duration)
- Agent metadata (turn count, state snapshots)
- TTL-based auto-expiration (configurable via `SESSION_TTL_SECONDS`)

Per-session write locks prevent concurrent modifications.

### MCP Server Configuration

Edit `config/mcp_servers.yaml` to add/modify MCP servers:
- **Stdio transport**: Subprocess-based (e.g., local Python tools)
- **SSE transport**: HTTP-based with Server-Sent Events
- **FastMCP transport**: In-process FastMCP server

Each server has a timeout (default 5000ms) and tools are auto-discovered on startup.

## Key Conventions

- **Async-first design**: Use `async/await` throughout; leverage `pytest-asyncio` for tests
- **Type hints required**: All functions/methods must have type hints (enables Pyright checking)
- **Structured logging**: Use loguru logger, not print(); JSON output to stdout
- **Pydantic models**: All API contracts use Pydantic with validation
- **Dataclass state**: Agent state uses `@dataclass` with field defaults for Redis serialization
- **Error handling**: Tool failures auto-retry with fallback; agent decisions include error handling path
- **Config via environment**: All runtime config in `.env`, validated at startup via Settings class
- **Session-scoped state**: No global state; everything Redis-backed with session_id

## Environment Variables

**Required:**
- `LLM_BASE_URL`: LLM provider URL (e.g., https://api.openrouter.ai/api/v1)
- `LLM_MODEL`: Model identifier (e.g., openrouter/anthropic/claude-3.5-sonnet)
- `REDIS_URL`: Redis connection string (e.g., redis://localhost:6379/0)

**Optional (with defaults):**
- `MAX_TURNS=5`: Max conversation turns per session
- `SESSION_TTL_SECONDS=3600`: Session expiry in seconds
- `TOOL_TIMEOUT_MS=5000`: Tool execution timeout
- `LOG_LEVEL=INFO`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `MCP_CONFIG_PATH=./config/mcp_servers.yaml`: Path to MCP server config

See `.env.example` for full list.

## Docker

**Multi-stage Dockerfile:**
- Stage 1: Builder (installs deps with UV)
- Stage 2: Runtime (minimal Python slim image, non-root user `appuser`)

**Compose services:**
- `redis`: Session store (Redis 7.2 Alpine)
- `openrouter-llm`: Mock LLM server for local testing (MockServer)
- `helios-agent`: FastAPI app with health checks

Run: `docker-compose up` (starts all services with health checks and networking)

## Common Tasks

**Add a new MCP server:**
1. Update `config/mcp_servers.yaml` with server details (name, type, command/url)
2. Server tools are auto-discovered on agent startup
3. Tool execution routes through ToolRegistry based on tool_id (server.tool_name)

**Add API endpoint:**
1. Define Pydantic model in `api/models.py`
2. Add route to FastAPI app (typically in a new `api/routes.py`)
3. Validate input with Pydantic, call agent logic, return typed response

**Handle tool failures:**
- Tool failures trigger auto-retry logic (configurable attempts)
- After retries exhausted, fallback tool is invoked if available
- Failure recorded in ToolCallRecord with error message and attempt count

**Debug session state:**
- Use Redis CLI: `redis-cli -u redis://localhost:6379/0`
- Query session keys: `KEYS *session_id*`
- Inspect session data: `GET session_key` (returns JSON-serialized state)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
