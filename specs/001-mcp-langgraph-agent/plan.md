# Implementation Plan: MCP-Integrated LangGraph Agent

**Branch**: `001-mcp-langgraph-agent` | **Date**: 2026-04-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-mcp-langgraph-agent/spec.md`

## Summary

Build a production-ready multi-turn agent service (`helios-agent`) that discovers tools from multiple MCP servers at startup, orchestrates tool execution through a bounded LangGraph state graph, persists conversation state in Redis, and exposes a REST API for chat, session management, and operator diagnostics. All tool failures trigger automatic retry with exponential backoff and configurable fallback chains before surfacing structured error responses to clients.

## Technical Context

**Language/Version**: Python 3.12  
**Primary Dependencies**: FastAPI 0.135+, LangGraph 1.0+, langchain-mcp 0.2+, fastmcp 3.2+, redis 5.3+, loguru 0.7+, httpx 0.28+, pydantic 2.12+, uvicorn  
**Storage**: Redis 7.0+ (ephemeral session state, per-session write locks); no relational DB in v1  
**Testing**: pytest 9+, pytest-asyncio 1.3+  
**Target Platform**: Linux server (Docker Compose single-node)  
**Project Type**: web-service  
**Performance Goals**: p95 chat response ≤8s end-to-end; p95 health/metrics ≤2s; tool invocation p95 ≤500ms; Redis session retrieval <50ms  
**Constraints**: REST-only (no streaming/WebSocket v1); synchronous request-response; sequential tool execution per turn; static tool catalog (restart to add tools); Redis required for all session operations  
**Scale/Scope**: Single-server Docker Compose MVP; horizontal scaling via shared Redis when replicated behind a load balancer

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Multi-Source Tool Orchestration | ✅ PASS | MCPAggregator + ToolRegistry abstract all transport types (stdio, sse, fastmcp); tools normalized into a single catalog |
| II. Stateful Multi-Turn Reasoning | ✅ PASS | AgentState persisted in Redis per session; context (messages, tool outcomes, errors) flows across turns |
| III. Conditional Logic Over Agentic Loops | ✅ PASS | LangGraph graph is explicitly defined: 8 nodes, 3 conditional routing functions; no open-ended agent loops |
| IV. Tools Are Optional, But Preferred | ✅ PASS | `decide_action` node routes to either `invoke_tool` or `direct_response` based on LLM decision; no forced tool use |
| V. Comprehensive Observability | ✅ PASS | loguru structured logs on every node; `/api/debug/trace`, `/api/debug/metrics`, `/api/health` endpoints |
| VI. Error Recovery Is Built-In | ✅ PASS | Exponential backoff (1s/2s/4s ±jitter), fallback tool chains, and graceful error responses modeled in graph |
| Hard Constraint: REST-only | ✅ PASS | No WebSocket or streaming; request-response only |
| Hard Constraint: Stateless FastAPI | ✅ PASS | All state in Redis; FastAPI handlers access `app.state` (init-time globals only) |
| Hard Constraint: Static MCP catalog | ✅ PASS | Tool discovery in lifespan startup handler only; no mid-flight registration |
| Hard Constraint: Sequential tools | ✅ PASS | One tool per turn; no parallel execution |

**Post-Design Re-evaluation**: All constraints satisfied. No violations. Graph node count = 8 (≤10 limit met).

## Complexity Tracking

No constitution violations. No extra justification required.

## Project Structure

### Documentation (this feature)

```text
specs/001-mcp-langgraph-agent/
├── plan.md              # This file
├── research.md          # Phase 0: all NEEDS CLARIFICATION resolved
├── data-model.md        # Phase 1: entities, Redis schema, error codes
├── quickstart.md        # Phase 1: setup, first request, test commands
├── contracts/
│   └── api.md           # Phase 1: full REST API contract
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/
└── mcp_agent/
    ├── __init__.py
    ├── main.py                 # FastAPI app factory + lifespan
    ├── settings.py             # Pydantic-settings config from env
    ├── types.py                # Shared type aliases
    │
    ├── api/
    │   ├── __init__.py
    │   ├── router.py           # All route registrations
    │   ├── models.py           # ChatRequest, ChatResponse, ErrorResponse, HealthResponse
    │   └── handlers.py         # Business logic called by route functions
    │
    ├── agent/
    │   ├── __init__.py
    │   ├── graph.py            # build_agent_graph() → CompiledGraph
    │   ├── nodes.py            # node_think, node_decide_action, node_invoke_tool,
    │   │                       # node_tool_result, node_evaluate_result,
    │   │                       # node_direct_response, node_error, node_respond
    │   ├── edges.py            # route_decide_action, route_tool_result, route_evaluate_result
    │   └── state.py            # AgentState, Message, ToolCallRecord dataclasses
    │
    ├── mcp/
    │   ├── __init__.py
    │   ├── aggregator.py       # MCPAggregator: discovers tools from all configured servers
    │   ├── registry.py         # ToolRegistry + ToolDefinition
    │   ├── adapter.py          # MCPToolAdapter: ToolDefinition → LangChain Tool
    │   ├── executors.py        # ToolExecutor: retry/fallback/timeout logic
    │   └── server.py           # FastMCP custom server (in-process tools)
    │
    ├── session/
    │   ├── __init__.py
    │   ├── store.py            # SessionStore: Redis get/set/delete/lock
    │   ├── models.py           # SessionModel (API view), serialization helpers
    │   └── manager.py          # SessionManager: load-or-create, lock lifecycle
    │
    ├── logging/
    │   ├── __init__.py
    │   └── setup.py            # loguru configure(), JSON sink
    │
    └── utils/
        ├── __init__.py
        └── validators.py       # validate_session_id(), validate_message()

tests/
├── conftest.py                 # Shared fixtures: mock_agent_state, mock_llm, mock_tool_executor
├── unit/
│   ├── test_nodes.py           # Each graph node in isolation
│   ├── test_edges.py           # Routing functions
│   ├── test_executors.py       # Retry/fallback/timeout logic
│   ├── test_registry.py        # ToolRegistry CRUD
│   └── test_session_store.py   # Redis serialization round-trips
├── integration/
│   ├── test_chat_flow.py       # Full graph: message → response
│   ├── test_multiturn.py       # Session context across turns
│   └── test_error_recovery.py  # Retry, fallback, provider-down scenarios
└── api/
    ├── test_chat_endpoint.py   # POST /api/chat — happy path + all error codes
    ├── test_session_endpoints.py  # GET/DELETE /api/session/{id}
    └── test_health_endpoints.py   # /api/health, /api/debug/*

config/
└── mcp_servers.yaml            # MCP server declarations (stdio / sse / fastmcp)

docker-compose.yml              # redis + openrouter-llm + helios-agent
Dockerfile                      # Multi-stage: builder + final (non-root user)
.env.example                    # All required environment variables
```

**Structure Decision**: Single-package `src/mcp_agent/` layout inside the existing `helios-agent` repo. No new top-level packages. All production dependencies already present in `pyproject.toml`.

## Design Artifacts

The following artifacts were produced by this planning pass. All contain authoritative implementation decisions and must not be overridden without updating this plan:

| Artifact | Phase | Content |
|----------|-------|---------|
| [research.md](research.md) | Phase 0 | 10 architectural decisions resolving all NEEDS CLARIFICATION items |
| [data-model.md](data-model.md) | Phase 1 | Entity definitions, Redis key schema, canonical error codes |
| [contracts/api.md](contracts/api.md) | Phase 1 | REST API contract: all 6 endpoints, request/response schemas |
| [quickstart.md](quickstart.md) | Phase 1 | Developer setup, first request walkthrough, test commands |

## Implementation Notes

Key decisions for task generation (see `research.md` for rationale):

- **State carrier**: `@dataclass AgentState` — not Pydantic, not `TypedDict`. Reason: better mutability + pyright support.
- **Serialization**: Custom `dataclass_to_dict()` and `dict_to_agent_state()` round-trips stored as JSON strings in Redis.
- **Locking**: `SET session:lock:{id} NX EX 30` — no Lua script. Acquire before graph run, release in `finally`.
- **LLM integration**: `LLMClient` wrapper class over `httpx.AsyncClient`. All non-200 responses raise `LLMProviderError`.
- **Retry backoff formula**: `delay = 2^attempt + random.uniform(0, 0.5)` capped at 10s. Implemented in `ToolExecutor`.
- **Tool discovery**: Called once in FastAPI `lifespan()`. `ToolRegistry` is stored on `app.state.tool_registry`.
- **Graph entry point**: `START → node_think`. All turns start at `node_think` regardless of session history.
- **Turn limit enforcement**: `node_think` reads `AgentState.turn_count`; if `>= max_turns` routes to `node_error`.
