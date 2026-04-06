<!--
Sync Impact Report
Version change: N/A -> 1.0.0 (initial ratification)
Modified principles:
  - Template placeholders -> helios-agent constitution content
  - Added I. Multi-Source Tool Orchestration
  - Added II. Stateful Multi-Turn Reasoning
  - Added III. Conditional Logic Over Agentic Loops
  - Added IV. Tools Are Optional, But Preferred
  - Added V. Comprehensive Observability
  - Added VI. Error Recovery Is Built-In
Added sections:
  - Project Vision
  - Core Principles
  - Operational Constraints and Non-Goals
  - Success Metrics
  - Architectural Constraints
  - Decision Log
  - Future Roadmap
  - Success Criteria
Removed sections:
  - Template placeholder sections and example comments
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ no changes required; Constitution Check already exists and remains aligned
  - .specify/templates/spec-template.md ✅ no changes required; mandatory sections and clarification markers already align
  - .specify/templates/tasks-template.md ✅ no changes required; phase-based task structure already supports the constitution's gates
Runtime guidance docs reviewed:
  - README.md ✅ no changes required; no constitution-specific references needed updates
Follow-up TODOs:
  - TODO(RATIFICATION_DATE): original adoption date is not recorded in repository history
-->

# helios-agent Constitution

## Project Vision

Build a production-ready, general-purpose agent capable of multi-turn
reasoning and dynamic tool orchestration across multiple MCP servers. The
agent serves as a flexible orchestration layer between user intent and
diverse tool ecosystems, prioritizing extensibility, reliability, and
observability.

## Core Principles

All core principles below are binding. If implementation choices conflict,
the design that best preserves correctness, observability, and bounded
behavior MUST win unless a maintainer documents an explicit exception in
the change that introduced the conflict.

### I. Multi-Source Tool Orchestration

The agent MUST integrate tools from multiple MCP servers through a unified
discovery and aggregation layer, treating all tools as first-class citizens
regardless of origin.

- MCP servers are the primary tool source; custom tools are exposed via
  FastMCP for parity.
- No tool is harder to add than another; the aggregation layer abstracts
  transport and protocol differences.
- The tool registry MUST be dynamic and discoverable at runtime.
- Tooling decisions MUST be centralized in the aggregation layer, not
  scattered across adapters.

Rationale: flexibility and extensibility are non-negotiable, so adding new
capabilities MUST not require scattered code changes.

### II. Stateful Multi-Turn Reasoning

Agent reasoning and tool decisions MUST persist across turns via session
state in Redis, enabling complex multi-step workflows without round-trip
overhead.

- Session state is ephemeral, uses Redis, and is queryable and debuggable.
- The agent MUST maintain context across turns, including prior decisions,
  failed attempts, and partial results.
- Tool call results MUST feed back into agent reasoning; failures trigger
  conditional re-planning.
- State expires after a configurable TTL; clients are responsible for
  resuming old sessions.

Rationale: multi-turn interactions are foundational to real-world agent use
cases, and ephemeral storage keeps systems fast while persistent logs
support auditing.

### III. Conditional Logic Over Agentic Loops

Agent decision-making MUST follow pre-defined conditional flows instead of
open-ended self-directed reasoning.

- The LangGraph graph structure MUST be explicitly defined, and every
  decision point MUST be a branching node.
- The agent MUST NOT invent new goals or arbitrarily chain tools; it
  executes within designed bounds.
- Error handling MUST be choreographed with retries, fallback tools, and
  graceful degradation.
- Bounded flows MUST remain easier to reason about, test, and debug than
  fully agentic systems.

Rationale: bounded reasoning reduces hallucinations, improves
predictability, and simplifies observability for production systems.

### IV. Tools Are Optional, But Preferred

The agent MAY respond directly without invoking tools, but it MUST default
to tool use when a relevant tool is available and improves correctness or
speed.

- The LLM MAY decline tool use explicitly when a direct response is enough.
- Tool availability does not guarantee invocation; relevance filtering is
  part of the agent logic.
- Responses without tool calls are valid and encouraged for simple queries.
- Hybrid turns are expected: some turns use tools, others do not.

Rationale: the agent MUST avoid over-tooling while still using external
capabilities when they add value.

### V. Comprehensive Observability

Every agent action, including LLM calls, tool invocations, state
transitions, and errors, MUST be logged, traced, and metrified.

- Structured logging with loguru MUST capture decision trees, tool outcomes,
  latency, and errors.
- Debug endpoints MUST expose agent state, execution traces, and decision
  metadata.
- Metrics MUST track tool success rates, LLM latency, session volume, and
  error distribution.
- Logs and traces MUST be queryable and exportable for offline analysis.

Rationale: production agents are complex, so visibility is required to
diagnose failures and optimize performance.

### VI. Error Recovery Is Built-In

Tool failures MUST trigger automatic recovery before errors are surfaced to
the user.

- Transient failures, including timeouts and rate limits, MUST be retried
  with exponential backoff.
- Permanent failures, including missing tools and invalid inputs, MUST fall
  back to alternate tools when available.
- The agent MAY re-plan if a preferred tool fails, and the graph MUST model
  recovery paths explicitly.
- Errors MUST be logged with context; the user sees either a successful
  fallback result or a clear explanation of what failed.

Rationale: reliability matters more than perfection, and graceful
degradation keeps systems running.

## Operational Constraints and Non-Goals

### Hard Constraints

1. **REST-only API**: no WebSocket or streaming initially; request/response
   only.
2. **No persistent state in agent**: all session state lives in Redis; FastAPI
   remains stateless.
3. **Synchronous HTTP response**: the client MUST wait for agent completion;
   no async job queue.
4. **MCP servers must be available at startup**: no lazy-loading or dynamic
   registration of servers at runtime in v1.
5. **Single-threaded tool execution per session**: tools execute sequentially
   per turn, with no parallel tool calls yet.

### Non-Goals (v1)

- **Persistent conversation history**: sessions expire; no long-term memory.
- **User authentication and RBAC**: no per-user tool restrictions or billing.
- **Tool output streaming**: all results return atomically at the end.
- **Agentic tool invention**: the agent cannot create or modify tool
  definitions on the fly.
- **OpenAPI schema auto-generation**: no Swagger UI for dynamic tool discovery.
- **Cost tracking per tool**: no metering or billing per tool call.

## Success Metrics

### Functional Metrics

| Metric | Target | Rationale |
|--------|--------|-----------|
| Multi-turn accuracy | >=95% task completion rate | Core use case: the agent solves multi-step problems. |
| Tool invocation latency | <500ms p95 | User experience: fast tool selection and execution. |
| Error recovery rate | >=90% of failures trigger fallback | Reliability: the system recovers gracefully. |
| Tool success rate | >=92% per tool post-retry | Integration quality: tools must be reliable. |

### Operational Metrics

| Metric | Target | Rationale |
|--------|--------|-----------|
| System uptime | >=99.5% | Production readiness. |
| Observability coverage | 100% of actions logged and traced | Every failure must be traceable. |
| Session state consistency | 0 inconsistencies, audit-log verified | No lost or corrupted state. |
| MCP server discovery latency | <100ms at startup | Fast initialization. |

### Design Metrics

| Metric | Target | Rationale |
|--------|--------|-----------|
| Tool onboarding time | <30 minutes per new MCP server | Low-friction extensibility. |
| Graph complexity | <=10 decision nodes per agent type | Bounded cognitive load. |
| Test coverage | >=85% unit plus integration | Confidence in refactoring. |

## Architectural Constraints

### Performance

- LLM latency budget: 1-5 seconds per turn, accounting for OpenRouter rate
  limits and model inference.
- Tool execution budget: 500ms-2s per tool for typical API calls.
- Session retrieval: <50ms from Redis on the hot path.
- Total response SLA: <8s for LLM plus up to 2 tools and overhead.

### Reliability

- Redis availability is required for session persistence; there is no offline
  fallback.
- MCP server availability is required at startup; the system degrades
  gracefully if a server goes down mid-session.
- LLM availability depends on OpenRouter SLAs; the agent retries on rate
  limits and other transient errors.
- Database availability is optional for audit logs; the system MUST still
  work without it.

### Scalability

- The MVP is designed to run on one machine using Docker Compose.
- Horizontal scaling uses shared Redis state; FastAPI can be replicated
  behind a load balancer.
- Redis can hold roughly 1M ephemeral sessions depending on payload size.
- Concurrent sessions have no hard limit; OpenRouter rate limits are the
  expected bottleneck.

## Decision Log

### Decision 1: Ephemeral vs Persistent Session State

**Choice**: Ephemeral Redis-only state.

**Trade-off**: fast and simple with less history versus slower and more
complex with a full audit trail.

**Rationale**: the MVP needs speed and simplicity; audit logging can layer
on top through structured logs.

### Decision 2: REST vs WebSocket

**Choice**: REST request/response.

**Trade-off**: simpler API and no streaming versus more complex state
management and real-time updates.

**Rationale**: the MVP favors request/response, and WebSocket can be added
later if needed.

### Decision 3: Sequential vs Parallel Tool Execution

**Choice**: sequential, one tool per agent turn.

**Trade-off**: simpler logic and easier debugging versus faster workflows
with more complex coordination.

**Rationale**: sequential execution is easier to reason about; parallelism is
future work.

### Decision 4: LangGraph vs Custom Agent Loop

**Choice**: LangGraph.

**Trade-off**: an opinionated framework with less control versus custom code
with more implementation burden.

**Rationale**: LangGraph is production-tested, and graph visualization is
valuable for debugging.

### Decision 5: MCP Aggregation Pattern

**Choice**: custom discovery layer plus LangChain MCP adapters.

**Trade-off**: more custom code and fewer dependencies versus a simpler but
more locked-in pattern.

**Rationale**: a custom layer enables tool normalization and dynamic
discovery.

## Future Roadmap

- Phase 2: parallel tool execution plus result merging.
- Phase 3: persistent audit logs in PostgreSQL plus a query interface.
- Phase 4: WebSocket streaming plus real-time agent traces.
- Phase 5: cost tracking and rate limiting per client.
- Phase 6: multi-user sessions plus RBAC.
- Phase 7: agent fine-tuning and custom reasoning models.

## Success Criteria

The implementation is considered complete when all of the following are
true:

- The agent successfully completes 3+ multi-turn workflows in the test
  suite.
- All MCP servers integrate without code changes to the agent core.
- Error recovery logic triggers and succeeds in >=90% of failure cases.
- Structured logs and traces are queryable and complete.
- Single-server deployment runs cleanly on Docker Compose.
- The API contract is documented and stable with no breaking changes during
  testing.

## Governance

This constitution supersedes conflicting project guidance. Any change to a
mandatory principle, hard constraint, or governance rule MUST be treated as
a constitution amendment.

### Amendment Procedure

1. Propose the amendment as a pull request that modifies this file.
2. Include the rationale and impact assessment in the pull request
   description.
3. Update the Sync Impact Report at the top of this file.
4. Increment the version according to semantic versioning:
   - MAJOR: backward-incompatible principle removals or redefinitions.
   - MINOR: new principles or sections, or material expansion of guidance.
   - PATCH: clarifications, wording fixes, or other non-semantic refinements.
5. Update `LAST_AMENDED_DATE` to the merge date when the amendment lands.

### Compliance Review

- Every pull request MUST be checked against the constitution before merge.
- Reviewers SHOULD reference specific principle numbers when requesting
  changes.
- The Constitution Check in `.specify/templates/plan-template.md` MUST pass
  before implementation begins.
- If a feature needs an exception, the exception MUST be documented in the
  relevant plan and approved in review.

**Version**: 1.0.0 | **Ratified**: TODO(RATIFICATION_DATE): original adoption date is not recorded in repository history | **Last Amended**: 2026-04-05
