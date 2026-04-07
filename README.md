# helios-agent

## A Production-Ready Multi-Turn LLM Agent with MCP Server Integration

Multi-turn LLM agent with Model Context Protocol (MCP) server integration, LangGraph-based orchestration, and OpenRouter backend. Features Redis-backed sessions, conditional tool routing, automatic error recovery, and comprehensive observability for reliable, scalable agent-driven applications.

## Table of Contents

- [Quick Start](#quick-start)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Service](#running-the-service)
- [Testing](#testing)
- [Architecture](#architecture)
- [API Documentation](#api-documentation)
- [Development](#development)
- [Project Structure](#project-structure)

## Quick Start

```bash
# Clone and install
git clone <repo-url> helios-agent
cd helios-agent
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your OpenRouter API key

# Run with Docker Compose (recommended)
docker-compose up --build

# Or run locally with Redis
redis-server &
uv run uvicorn mcp_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

Then test the agent:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is 2+2?",
    "client_metadata": {"user_id": "test"}
  }'
```

See [Quickstart Guide](specs/001-mcp-langgraph-agent/quickstart.md) for detailed setup and integration examples.

## Features

### ✅ Core Capabilities

- **Multi-Turn Conversations**: Persistent session state across multiple agent turns with configurable TTL and max-turn limits
- **MCP Server Integration**: Automatically discover and orchestrate tools from multiple Model Context Protocol servers (stdio, SSE, FastMCP transports)
- **LangGraph Orchestration**: Explicit, bounded state graph (8 nodes, 3 decision points) for deterministic, debuggable agent behavior
- **Conditional Tool Routing**: Smart decision logic routes requests to tools only when needed; direct responses otherwise
- **Automatic Error Recovery**: Exponential backoff retry (1s/2s/4s ± jitter) and fallback tool chains for transient failures
- **Comprehensive Observability**: Structured JSON logging, per-session traces, metrics endpoints, and health checks

### 🔒 Production-Ready

- **Redis-Backed Sessions**: Scalable session storage with per-session write locks for concurrent request safety
- **Structured Error Responses**: Consistent JSON error format with error codes, severity levels, and recovery hints
- **Request Validation**: Message length limits (max 4096 chars), session ID validation, and payload schema enforcement
- **Operator Diagnostics**: REST endpoints for session inspection, tracing, metrics, and service health
- **Async-First**: Built on FastAPI/asyncio for high concurrency and low-latency I/O

## Prerequisites

- **Python 3.12** or later
- **uv** package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **Docker + Docker Compose 3.8+** (for containerized deployment)
- **Redis 7.0+** (for session storage; included in docker-compose.yml)
- **OpenRouter API access** (or any compatible LLM provider)

## Installation

### 1. Clone the Repository

```bash
git clone <repo-url> helios-agent
cd helios-agent
```

### 2. Install Dependencies

```bash
# Using uv (recommended, faster than pip)
uv sync

# Activate virtual environment
source .venv/bin/activate

# Optionally, run type checking
uv run pyright src/
```

## Configuration

### Environment Variables

Create a `.env` file in the project root (copy from `.env.example`):

```dotenv
# LLM Configuration
LLM_BASE_URL=http://localhost:8001              # LLM provider URL (e.g., OpenRouter)
LLM_MODEL=openai/gpt-4o-mini                    # Model ID
LLM_REQUEST_TIMEOUT_MS=30000                    # Request timeout in milliseconds

# Redis Session Store
REDIS_URL=redis://localhost:6379/0              # Redis connection URL

# Agent Limits
MAX_TURNS=5                                     # Maximum turns per session
SESSION_TTL_SECONDS=3600                        # Session time-to-live in seconds
SESSION_LOCK_TIMEOUT_MS=5000                    # Concurrent request lock timeout
TOOL_TIMEOUT_MS=5000                            # Tool invocation timeout

# Logging & Diagnostics
LOG_LEVEL=INFO                                  # Log level: DEBUG, INFO, WARNING, ERROR
ENVIRONMENT=development                         # Environment: development, staging, production

# MCP Server Configuration
MCP_CONFIG_PATH=config/mcp_servers.yaml         # Path to MCP server declarations
```

### MCP Server Configuration

Edit `config/mcp_servers.yaml` to declare which MCP servers to connect at startup:

```yaml
servers:
  example_tool_server:
    type: stdio
    command: python
    args:
      - -m
      - example_mcp_server
    timeout_ms: 5000
    
  api_server:
    type: sse
    url: http://localhost:3001/
    timeout_ms: 5000
```

Tools are discovered once at startup and exposed through a unified catalog. Restart the service to add or remove tools.

## Running the Service

### Option 1: Docker Compose (Recommended)

```bash
# Build and run with all services (FastAPI + Redis)
docker-compose up --build --remove-orphans

# View logs
docker-compose logs -f helios-agent

# Stop services
docker-compose down
```

### Option 2: Local Development

**Terminal 1: Start Redis**

```bash
redis-server
```

**Terminal 2: Start the Agent Service**

```bash
source .venv/bin/activate
uv run uvicorn mcp_agent.main:app --host 0.0.0.0 --port 8000 --reload
```

The service will be available at `http://localhost:8000`.

**Health Check:**

```bash
curl http://localhost:8000/api/health
```

## Testing

### Run All Tests

```bash
# Run full test suite
uv run pytest -v

# Run with coverage
uv run pytest --cov=src/mcp_agent --cov-report=html
```

### Run Specific Test Categories

```bash
# Single test file
uv run pytest tests/test_agent.py

# Single test function
uv run pytest tests/test_agent.py::test_function_name

# Tests matching a pattern
uv run pytest -k "chat" -v
```

### Test a Chat Request Manually

```bash
# Create a new session and send a message
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What is the weather?",
    "client_metadata": {"user_id": "user123"}
  }'

# Sample response:
# {
#   "session_id": "sess_abc123...",
#   "turn_number": 1,
#   "response": "I can help with that. Let me check the weather...",
#   "tool_calls": [...],
#   "timestamp": "2026-04-07T12:00:00Z"
# }
```

## Architecture

### System Overview

```
┌─────────────────┐
│  Client App     │
└────────┬────────┘
         │ HTTP REST
         ▼
┌─────────────────────────────┐
│   FastAPI Router            │
│  /api/chat                  │
│  /api/sessions/{session_id} │
│  /api/health                │
│  /api/debug/trace           │
│  /api/debug/metrics         │
└────────┬────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│    Agent Orchestration (LangGraph)   │
│                                      │
│  1. Router (input validation)        │
│  2. Think (message + context)        │
│  3. Decide Action (tool or direct)   │
│  4. Invoke Tool (with retries)       │
│  5. Tool Result (processing)         │
│  6. Evaluate Result (next step)      │
│  7. Direct Response (no tool)        │
│  8. Node Complete (state update)     │
└────────┬──────────────┬──────────────┘
         │              │
         ▼              ▼
    ┌─────────┐   ┌──────────────────┐
    │  Redis  │   │  MCP Aggregator  │
    │         │   │                  │
    │Session  │   │ ┌──────────────┐ │
    │ State   │   │ │ MCP Server 1 │ │
    │         │   │ └──────────────┘ │
    │Locks    │   │ ┌──────────────┐ │
    │Traces   │   │ │ MCP Server 2 │ │
    │         │   │ └──────────────┘ │
    └─────────┘   │ ┌──────────────┐ │
                  │ │ MCP Server N │ │
                  │ └──────────────┘ │
                  │ Tool Registry    │
                  │ (unified catalog)│
                  └──────────────────┘
```

### Key Components

| Component | Location | Purpose |
|-----------|----------|---------|
| **FastAPI App** | `src/mcp_agent/main.py` | Application factory, lifespan management, route mounting |
| **Agent Graph** | `src/mcp_agent/agent/graph.py` | LangGraph state machine with 8 nodes and decision routing |
| **Session Store** | `src/mcp_agent/session/` | Redis-backed session persistence and locking |
| **MCP Aggregator** | `src/mcp_agent/mcp/` | Unified tool discovery and execution across multiple MCP servers |
| **API Handlers** | `src/mcp_agent/api/` | REST endpoint business logic and validation |
| **Logging** | `src/mcp_agent/logging/` | Structured JSON logging with session context binding |

### Request Flow Example

1. **Client** sends `/api/chat` with message and optional session ID
2. **Router** validates request, retrieves or creates session, acquires write lock
3. **Agent Graph** executes:
   - Think: Process message with conversation context
   - Decide: Determine if tool is needed
   - Act: Invoke tool with retry/fallback logic (if needed)
   - Respond: Generate user-facing response
4. **Session Store** persists updated state (messages, tool calls, results)
5. **Client** receives response with session ID for next turn

## API Documentation

### Chat Endpoint

**POST** `/api/chat`

Submit a user message to the agent and receive a response with optional tool execution details.

**Request:**

```json
{
  "message": "What is the capital of France?",
  "session_id": "sess_abc123...",  // Optional; omit for new session
  "client_metadata": {
    "user_id": "user123",
    "request_id": "req_xyz789"
  }
}
```

**Response (Success - 200):**

```json
{
  "session_id": "sess_abc123...",
  "turn_number": 1,
  "response": "The capital of France is Paris.",
  "tool_calls": [
    {
      "tool_id": "geography_lookup",
      "args": {"country": "France"},
      "result": {"capital": "Paris"}
    }
  ],
  "timestamp": "2026-04-07T12:00:00Z"
}
```

**Response (Error - 400/500):**

```json
{
  "error_code": "TOOL_INVOCATION_FAILED",
  "message": "Tool invocation failed after 3 retries",
  "severity_level": "error",
  "detail": "Connection timeout to MCP server",
  "recovery_hint": "Check MCP server connectivity and retry the request"
}
```

### Session Management

**GET** `/api/sessions/{session_id}`

Retrieve session details including conversation history and current state.

**DELETE** `/api/sessions/{session_id}`

Clear and remove a session.

### Operator Diagnostics

**GET** `/api/health`

Service health status including Redis and MCP server connectivity.

**GET** `/api/debug/trace/{session_id}`

Retrieve execution trace for a specific session including all node transitions and tool invocations.

**GET** `/api/debug/metrics`

Aggregate metrics including request counts, latencies, error rates, and tool usage.

Full API contract available in [contracts/api.md](specs/001-mcp-langgraph-agent/contracts/api.md).

## Development

### Type Checking

```bash
uv run pyright src/
```

### Code Style

Follow PEP 8 conventions. The project uses type hints extensively.

### Adding a New Tool

1. Configure the MCP server in `config/mcp_servers.yaml`
2. Tools are auto-discovered at startup; no code changes needed
3. The agent will automatically learn to use new tools

### Debugging

**View Logs:**

```bash
# Local run
tail -f logs/app.log

# Docker
docker-compose logs -f helios-agent
```

**Inspect a Session:**

```bash
# Get session details
curl http://localhost:8000/api/sessions/sess_abc123

# Get execution trace
curl http://localhost:8000/api/debug/trace/sess_abc123

# View current metrics
curl http://localhost:8000/api/debug/metrics
```

**Redis CLI:**

```bash
redis-cli -u redis://localhost:6379/0
> KEYS *sess_*
> GET sess_abc123
```

## Project Structure

```
helios-agent/
├── src/mcp_agent/
│   ├── main.py                # FastAPI app factory + lifespan
│   ├── settings.py             # Pydantic-based config from .env
│   ├── types.py                # Shared type aliases
│   │
│   ├── api/
│   │   ├── router.py           # Route registrations
│   │   ├── models.py           # Pydantic request/response schemas
│   │   └── handlers.py         # Endpoint business logic
│   │
│   ├── agent/
│   │   ├── graph.py            # LangGraph state machine definition
│   │   ├── nodes.py            # Graph node implementations
│   │   ├── edges.py            # Conditional routing logic
│   │   └── state.py            # AgentState dataclass
│   │
│   ├── session/
│   │   ├── manager.py          # Session CRUD operations
│   │   ├── store.py            # Redis persistence layer
│   │   └── models.py           # Session data models
│   │
│   ├── mcp/
│   │   ├── server.py           # MCP server lifecycle management
│   │   ├── aggregator.py       # Multi-server tool discovery
│   │   ├── registry.py         # Unified tool catalog
│   │   ├── adapter.py          # Tool execution wrapper
│   │   └── executors.py        # Tool invocation + retry logic
│   │
│   ├── logging/
│   │   └── setup.py            # Structured logging configuration
│   │
│   └── debug/
│       ├── trace.py            # Request trace capture
│       └── metrics.py          # Aggregation metrics
│
├── specs/001-mcp-langgraph-agent/
│   ├── spec.md                 # Feature specification
│   ├── plan.md                 # Implementation plan
│   ├── data-model.md           # Data models & Redis schema
│   ├── quickstart.md           # Setup & first-request guide
│   ├── research.md             # Technical decisions & rationale
│   ├── contracts/
│   │   └── api.md              # REST API contract
│   └── checklists/
│       └── requirements.md     # Implementation checklist
│
├── config/
│   └── mcp_servers.yaml        # MCP server declarations
│
├── tests/                      # Test suite (unit & integration)
│
├── Dockerfile                  # Multi-stage Docker build
├── docker-compose.yml          # Local dev environment
├── pyproject.toml              # Python dependencies & build config
├── .env.example                # Environment template
└── README.md                   # This file
```

## Specification & Design Documents

- **[Feature Specification](specs/001-mcp-langgraph-agent/spec.md)**: User stories, acceptance criteria, and requirements
- **[Implementation Plan](specs/001-mcp-langgraph-agent/plan.md)**: Technical architecture and design decisions
- **[Data Model](specs/001-mcp-langgraph-agent/data-model.md)**: Entity definitions and Redis schema
- **[Quickstart](specs/001-mcp-langgraph-agent/quickstart.md)**: Step-by-step setup and integration guide
- **[API Contract](specs/001-mcp-langgraph-agent/contracts/api.md)**: Full REST API specification
- **[Research](specs/001-mcp-langgraph-agent/research.md)**: Technical decisions and constraints

## Performance Targets

- **Chat response (p95)**: ≤ 8 seconds end-to-end
- **Health/Metrics (p95)**: ≤ 2 seconds
- **Tool invocation (p95)**: ≤ 500ms (before retries)
- **Session retrieval (p95)**: ≤ 50ms

## License

[See LICENSE file](LICENSE)

---

**Need help?** Check the [Quickstart Guide](specs/001-mcp-langgraph-agent/quickstart.md) or open an issue in the repository.
