# Tasks: MCP-Integrated LangGraph Agent

**Input**: Design documents from `/specs/001-mcp-langgraph-agent/`  
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/api.md ✅, quickstart.md ✅  
**Branch**: `001-mcp-langgraph-agent`  
**Date**: 2026-04-06

---

## Format: `[ID] [P?] [Story?] Description — file path`

- **[P]**: Can run in parallel (operates on different files, no incomplete dependencies)
- **[US1–US4]**: User story this task belongs to (from spec.md)
- Setup and Foundational phases carry **no** story label

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create project skeleton, config files, and container definitions. No code logic yet.

- [X] T001 Create src/mcp_agent package directory tree with all `__init__.py` stubs for api/, agent/, mcp/, session/, logging/, utils/ in `src/mcp_agent/`
- [X] T002 [P] Create `config/mcp_servers.yaml` template with one stdio, one sse, and one fastmcp example entry
- [X] T003 [P] Create `.env.example` with all required environment variables: `LLM_BASE_URL`, `LLM_MODEL`, `REDIS_URL`, `MAX_TURNS`, `SESSION_TTL_SECONDS`, `TOOL_TIMEOUT_MS`, `LOG_LEVEL`, `MCP_CONFIG_PATH`
- [X] T004 [P] Create `Dockerfile` with multi-stage build (builder + final), non-root `appuser`, health check, and `CMD ["uvicorn", "mcp_agent.main:app", ...]`
- [X] T005 [P] Create `docker-compose.yml` defining `redis`, `openrouter-llm`, and `helios-agent` services with correct `depends_on`, volumes, and env references

**Checkpoint**: Project skeleton exists; all directories and config templates in place.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core modules that ALL user stories depend on. Must be complete before any story work begins.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T006 Implement `src/mcp_agent/settings.py` — Pydantic `BaseSettings` class loading all env vars from `.env.example` with type annotations and field defaults (`LLM_BASE_URL`, `LLM_MODEL`, `REDIS_URL`, `MAX_TURNS=5`, `SESSION_TTL_SECONDS=3600`, `TOOL_TIMEOUT_MS=5000`, `LOG_LEVEL="INFO"`, `MCP_CONFIG_PATH`)
- [X] T007 [P] Implement `src/mcp_agent/logging/setup.py` — `configure_logging(settings)` function using loguru: JSON sink to stdout, `logger.bind(session_id=..., node=...)` pattern, log level from settings
- [X] T008 [P] Implement `src/mcp_agent/types.py` — type aliases: `SessionId = str`, `ToolId = str`, `AgentDecision = Literal["use_tool", "direct_response", "error"]`
- [X] T009 Implement `src/mcp_agent/agent/state.py` — `@dataclass AgentState`, `@dataclass Message`, `@dataclass ToolCallRecord` matching exact schema in [data-model.md](data-model.md) (session_id, created_at, last_activity, messages, turn_count, current_input, current_thought, current_decision, selected_tool_id, tool_calls_this_turn, current_tool_output, last_error, error_count, available_tools, metadata); use `field(default_factory=...)` for mutable defaults; add comprehensive field-level docstrings
- [X] T010 [P] Implement `src/mcp_agent/api/models.py` — Pydantic models: `ChatRequest`, `ChatResponse`, `ErrorResponse` (with `error_code`, `message`, `severity_level`, `detail`, `recovery_hint`), `HealthResponse`, `SessionModel`, `ToolCallSummary` per contracts/api.md schemas
- [X] T011 [P] Implement `src/mcp_agent/utils/validators.py` — `validate_session_id(value: str) -> str` (UUID4 regex check, raises `ValueError`), `validate_message(value: str) -> str` (1–4096 chars, raises `ValueError`)

**Checkpoint**: Foundation ready — all shared data types, config, and utilities exist for story implementation.

---

## Phase 3: User Story 1 — Multi-Turn Assisted Chat (Priority: P1) 🎯 MVP

**Goal**: Clients submit messages; the agent creates new sessions, stores conversation context in Redis, and returns LLM-generated responses with session metadata across multiple turns — no tools required for this story.

**Independent Test**: `POST /api/chat` with no `session_id` → 200 with `session_id` and `turn_count=1`. Send same `session_id` again → 200 with `turn_count=2` and the second response references first-turn context.

- [X] T012 [US1] Implement `src/mcp_agent/session/models.py` — `dataclass_to_dict(state: AgentState) -> dict` and `dict_to_agent_state(data: dict) -> AgentState` round-trip helpers; handle nested `Message` and `ToolCallRecord` dataclasses; handle `datetime` ISO 8601 serialization
- [X] T013 [US1] Implement `src/mcp_agent/session/store.py` — async `SessionStore` class: `get(session_id)`, `set(session_id, state, ttl)`, `delete(session_id)`, `acquire_lock(session_id, timeout_ms)` using `SET NX EX 30`, `release_lock(session_id)`; uses `dataclass_to_dict`/`dict_to_agent_state`
- [X] T014 [US1] Implement `src/mcp_agent/session/manager.py` — `SessionManager` class: `load_or_create(session_id: str | None) -> AgentState` (creates new UUID4 session when `None`; returns `404` error state when session expired); `__aenter__`/`__aexit__` context manager that acquires lock on entry and releases in `finally`
- [X] T015 [US1] Implement `LlmClient` class in `src/mcp_agent/agent/nodes.py` — wraps `httpx.AsyncClient`; `async def complete(messages: list[dict]) -> str`; raises `LLMProviderError` on any non-200 HTTP response with provider status in error detail
- [X] T016 [US1] Implement `node_think` in `src/mcp_agent/agent/nodes.py` — checks `state.turn_count >= settings.max_turns` (routes to error), increments `turn_count`, calls `LlmClient.complete()` with last-5 messages as context window, stores chain-of-thought in `state.current_thought`
- [X] T017 [P] [US1] Implement `node_decide_action` in `src/mcp_agent/agent/nodes.py` — parses LLM output to determine `AgentDecision`; sets `state.current_decision` and `state.selected_tool_id` if `"use_tool"`; falls back to `"direct_response"` when no tools available
- [X] T018 [P] [US1] Implement `node_direct_response`, `node_respond`, and `node_error` in `src/mcp_agent/agent/nodes.py` — `node_direct_response`: calls LLMClient for final answer without a tool; `node_respond`: packages `state` into final response fields; `node_error`: fills `state.last_error` from `AgentState.error_count`, constructs `ErrorResponse`
- [X] T019 [US1] Implement routing functions in `src/mcp_agent/agent/edges.py` — `route_decide_action(state) -> str` (returns `"invoke_tool"` or `"direct_response"` or `"error"`); `route_tool_result(state) -> str`; `route_evaluate_result(state) -> str` with all edge labels matching graph node names
- [X] T020 [US1] Implement `build_agent_graph()` in `src/mcp_agent/agent/graph.py` — `StateGraph(AgentState)` with 8 nodes (`node_think`, `node_decide_action`, `node_invoke_tool`, `node_tool_result`, `node_evaluate_result`, `node_direct_response`, `node_error`, `node_respond`), 3 conditional edges using routing functions from edges.py, `START → node_think`, `node_respond → END`; returns `CompiledGraph`
- [X] T021 [US1] Implement `chat_handler` in `src/mcp_agent/api/handlers.py` — async function: validates request via `validate_message`/`validate_session_id`, uses `SessionManager` context manager to load/create/lock session, wraps compiled `graph.ainvoke()` in `asyncio.wait_for(timeout=8.0)` to enforce FR-023 p95≤8s SLA (returns 408 timeout response on `asyncio.TimeoutError`), saves updated state via `SessionStore`, builds and returns `ChatResponse` with `session_id`, `response`, `turn_count`, `tool_calls`, `duration_ms`; handles `LLMProviderError` → 503, `SessionLockedError` → 409, `SessionExpiredError` → 404, `TimeoutError` → 408
- [X] T022 [US1] Register `POST /api/chat` in `src/mcp_agent/api/router.py` — `APIRouter(prefix="/api")`; route uses `chat_handler`; `response_model=ChatResponse`; HTTP 200 on success; error responses use `ErrorResponse` structure per contracts/api.md
- [X] T023 [US1] Implement `src/mcp_agent/main.py` — `create_app() -> FastAPI` with async `lifespan` context manager: startup logs, Redis ping, `configure_logging`, include router; `app = create_app()` at module level for uvicorn import

**Checkpoint**: `POST /api/chat` works end-to-end. New sessions created, turns persisted, direct LLM responses returned. US1 independently testable.

---

## Phase 4: User Story 2 — Tool-Orchestrated Problem Solving (Priority: P1)

**Goal**: The agent discovers all configured MCP tools at startup and, when a request requires it, selects and executes one tool per turn, returning the grounded answer together with tool call details.

**Independent Test**: Configure a mock MCP tool in `mcp_servers.yaml`. Send a message that requires that tool. Verify response includes `tool_calls` array with `tool_id`, `status: "success"`, and `duration_ms`.

- [ ] T024 [US2] Implement `src/mcp_agent/mcp/registry.py` — `ToolDefinition` dataclass (id, name, server_name, description, input_schema, output_schema, timeout_ms, fallback_tool_id); `ToolRegistry` class with `register(tool: ToolDefinition)`, `get(tool_id: str) -> ToolDefinition | None`, `list_all() -> list[ToolDefinition]`, `count() -> int`
- [ ] T025 [US2] Implement `src/mcp_agent/mcp/aggregator.py` — `MCPAggregator` class: reads `config/mcp_servers.yaml`, connects to each server using the appropriate transport (`stdio` via `langchain-mcp`, `sse` via langchain-mcp, `fastmcp` via in-process import), calls `list_tools()`, normalizes each result into `ToolDefinition`; `async def discover_all() -> ToolRegistry`; logs each discovered tool with server name and tool count
- [ ] T026 [P] [US2] Implement `src/mcp_agent/mcp/adapter.py` — `MCPToolAdapter`: converts `ToolDefinition` to a LangChain-compatible `Tool` object (name, description, args_schema from input_schema); used by `node_decide_action` to present tool options to the LLM
- [ ] T027 [P] [US2] Implement `src/mcp_agent/mcp/server.py` — FastMCP in-process server with at least one example tool (`echo_tool`) decorated with `@mcp.tool()`; registered as a `fastmcp` transport entry in `mcp_servers.yaml` example
- [ ] T028 [US2] Implement `node_invoke_tool`, `node_tool_result`, and `node_evaluate_result` in `src/mcp_agent/agent/nodes.py` — `node_invoke_tool`: resolves `state.selected_tool_id` from registry, calls `ToolExecutor.execute()`, appends `ToolCallRecord` to `state.tool_calls_this_turn`; `node_tool_result`: stores raw output in `state.current_tool_output`; `node_evaluate_result`: calls LLMClient to synthesize final answer from tool output + conversation history
- [ ] T029 [US2] Update `lifespan` in `src/mcp_agent/main.py` — initialize `MCPAggregator`, call `discover_all()`, store resulting `ToolRegistry` on `app.state.tool_registry`; also build and store `CompiledGraph` on `app.state.agent_graph`; fail startup with clear log if MCP discovery raises an unrecoverable error
- [ ] T030 [US2] Update `chat_handler` in `src/mcp_agent/api/handlers.py` — inject `request.app.state.tool_registry` and `request.app.state.agent_graph` into graph invocation config; pass `tool_registry` to `node_decide_action` for tool selection

**Checkpoint**: Tool-assisted answers work. US2 independently verifiable with a mock MCP server.

---

## Phase 5: User Story 3 — Automatic Recovery from Tool Failures (Priority: P2)

**Goal**: Transient tool failures retry with exponential backoff; permanent failures with a configured fallback invoke the alternate tool; no recovery path → structured error response with full context.

**Independent Test**: Patch `ToolExecutor` to raise a transient error twice then succeed → verify response has `turn_count=1` and succeeded. Patch to always fail with a fallback configured → verify fallback tool invoked. Patch fallback to also fail → verify `error_code: "tool_execution_failed"` in response.

- [ ] T031 [US3] Implement `src/mcp_agent/mcp/executors.py` — `ToolExecutionResult` dataclass (tool_id, success, output, error, attempt_count, duration_ms, fallback_used); `ToolExecutor` class: `async def execute(tool_def: ToolDefinition, input: dict, registry: ToolRegistry) -> ToolExecutionResult`; enforces `TOOL_TIMEOUT_MS` via `asyncio.wait_for`; retry loop: `max_attempts=3`, delay formula `2**attempt + random.uniform(0, 0.5)` capped at 10s; on permanent failure checks `tool_def.fallback_tool_id` and recursively executes fallback (max 1 fallback level); populates `ToolExecutionResult` with attempt count and fallback flag
- [ ] T032 [US3] Update `node_invoke_tool` in `src/mcp_agent/agent/nodes.py` to delegate all execution to `ToolExecutor.execute()` instead of calling the tool directly; store `ToolExecutionResult` fields in `ToolCallRecord` appended to `state.tool_calls_this_turn`

**Checkpoint**: Recovery behavior complete. Retry, fallback, and clean failure paths all handled. US3 independently testable by mocking `ToolExecutor`.

---

## Phase 6: User Story 4 — Session and Diagnostic Visibility (Priority: P3)

**Goal**: Operators and clients can inspect active sessions, clear stale sessions, check service health, retrieve per-session execution traces, and read aggregate metrics.

**Independent Test**: `GET /api/session/{id}` → 200 with session summary. `DELETE /api/session/{id}` → 200. `GET /api/session/{id}` → 404. `GET /api/health` → 200 with `status: "healthy"`. `GET /api/debug/metrics` → 200 with non-null counters.

- [ ] T033 [P] [US4] Implement `GET /api/session/{session_id}` handler in `src/mcp_agent/api/handlers.py` and route in `src/mcp_agent/api/router.py` — calls `SessionStore.get()`, returns `SessionModel` (id, turn_count, messages, last_activity, state); 404 with `error_code: "session_not_found"` if missing
- [ ] T034 [P] [US4] Implement `DELETE /api/session/{session_id}` handler in `src/mcp_agent/api/handlers.py` and route in `src/mcp_agent/api/router.py` — calls `SessionStore.delete()`, idempotent (200 even if session did not exist per contracts/api.md)
- [ ] T035 [P] [US4] Implement `GET /api/health` handler in `src/mcp_agent/api/handlers.py` and route in `src/mcp_agent/api/router.py` — pings Redis (`redis.ping()`), pings LLM provider via `LlmClient`; returns `HealthResponse` with `status: "healthy"|"degraded"|"unhealthy"`, per-dependency status, tool count from `tool_registry`; HTTP 200 for healthy/degraded, 503 for unhealthy
- [ ] T036 [P] [US4] Implement `GET /api/debug/trace/{session_id}` handler in `src/mcp_agent/api/handlers.py` and route in `src/mcp_agent/api/router.py` — reads structured log records bound with `session_id=` from an in-memory `TraceBuffer` (ring buffer populated by loguru sink); returns ordered list of trace events; 404 if no records found for session
- [ ] T037 [P] [US4] Implement `GET /api/debug/metrics` handler in `src/mcp_agent/api/handlers.py` and route in `src/mcp_agent/api/router.py` — reads from `MetricsStore` (thread-safe in-process counters populated by chat_handler and ToolExecutor): `total_sessions`, `total_turns`, `tool_calls`, `tool_failures`, `llm_invocations`, `avg_duration_ms`; initialize `MetricsStore` in `app.state` during lifespan startup

**Checkpoint**: All 6 REST endpoints implemented. Full operator visibility in place. US4 independently testable.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Configuration quality, type safety gate, and import smoke-test.

- [ ] T038 [P] Add `[tool.pyright]` strict settings and `[tool.pytest.ini_options]` with `testpaths`, `asyncio_mode = "auto"`, and `markers` to `pyproject.toml`
- [ ] T039 [P] Verify `src/mcp_agent` is importable: `uv run python -c "from mcp_agent.main import create_app; print('OK')"` must succeed (fix any import-time errors)

---

## Dependencies & Execution Order

### Phase Dependencies

| Phase | Depends On | Notes |
|-------|-----------|-------|
| Phase 1: Setup | — | Start immediately |
| Phase 2: Foundational | Phase 1 complete | **Blocks all user stories** |
| Phase 3: US1 (P1) | Phase 2 complete | MVP target |
| Phase 4: US2 (P1) | Phase 2 complete | Can be parallel to US1 if two developers |
| Phase 5: US3 (P2) | Phase 4 complete (needs ToolExecutor wiring) | Must follow US2 |
| Phase 6: US4 (P3) | Phase 2 complete | Can begin independently of US2/US3 |
| Phase 7: Polish | All desired phases complete | Final gate |

### User Story Dependencies

- **US1**: Independent after Phase 2. No dependency on US2, US3, or US4.
- **US2**: Independent after Phase 2. Shares nodes.py with US1 (add new nodes, don't modify existing).
- **US3**: Depends on US2 (requires `node_invoke_tool` to exist before wiring `ToolExecutor`).
- **US4**: Independent after Phase 2. Shares `SessionStore` with US1 (read-only usage).

---

## Parallel Execution Examples

### Phase 1 (all [P])
```
T002  config/mcp_servers.yaml
T003  .env.example
T004  Dockerfile
T005  docker-compose.yml
```

### Phase 2 (all [P] except T009 which anchors state.py)
```
T007  logging/setup.py
T008  types.py
T010  api/models.py
T011  utils/validators.py
```

### Phase 3 — US1 parallel group
```
T017  node_decide_action
T018  node_direct_response + node_respond + node_error
```

### Phase 4 — US2 parallel group
```
T026  mcp/adapter.py
T027  mcp/server.py
```

### Phase 6 — US4 (all [P], operate on separate handlers)
```
T033  GET /api/session/{id}
T034  DELETE /api/session/{id}
T035  GET /api/health
T036  GET /api/debug/trace/{id}
T037  GET /api/debug/metrics
```

---

## Implementation Strategy

### MVP First (US1 Only — 23 tasks)

1. Complete **Phase 1**: Setup (T001–T005)
2. Complete **Phase 2**: Foundational (T006–T011)
3. Complete **Phase 3**: US1 (T012–T023)
4. **STOP AND VALIDATE**: `uv run uvicorn mcp_agent.main:app --reload` → `POST /api/chat` returns 200 with session context
5. Demo / deploy MVP

### Incremental Delivery

| Slice | Tasks | Validates |
|-------|-------|-----------|
| MVP | T001–T023 | US1: multi-turn chat, session persistence |
| +Tools | T024–T030 | US2: tool discovery, tool-assisted answers |
| +Recovery | T031–T032 | US3: retry/fallback/failure handling |
| +Visibility | T033–T037 | US4: session/health/trace/metrics endpoints |
| Polish | T038–T039 | Type safety, import smoke-test |
