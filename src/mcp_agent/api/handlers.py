"""
API request handlers for the MCP Agent service.

Implements business logic for chat, session management, health checks,
and diagnostic endpoints.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from mcp_agent.agent.state import AgentState, Message
from mcp_agent.agent.nodes import LlmClient, LLMProviderError
from mcp_agent.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    ToolCallSummary,
    SessionModel,
    HealthResponse,
    TraceResponse,
    TraceEvent,
    MetricsResponse,
)
from mcp_agent.session.manager import SessionManager
from mcp_agent.session.store import (
    SessionStore,
    SessionNotFoundError,
    SessionExpiredError,
    SessionLockedError,
)
from mcp_agent.session.models import dataclass_to_dict, dict_to_agent_state
from mcp_agent.settings import Settings
from mcp_agent.utils.validators import validate_message, validate_session_id

if TYPE_CHECKING:
    from mcp_agent.debug.trace import TraceBuffer
    from mcp_agent.debug.metrics import MetricsStore

logger = logging.getLogger(__name__)


async def chat_handler(
    request: ChatRequest,
    store: SessionStore,
    llm_client: LlmClient,
    graph,  # CompiledGraph
    settings: Settings,
    tool_registry=None,  # T030: Tool registry for tool-aware execution
) -> ChatResponse:
    """
    Handle a chat message request and return an agent response.
    
    Process:
    1. Validate request via validate_message/validate_session_id
    2. Use SessionManager context manager to load/create/lock session
    3. Add user message to session conversation
    4. Wrap graph.ainvoke() in asyncio.wait_for(timeout=8.0) for SLA
    5. Inject tool_registry into graph context (T030 addition)
    6. Save updated state via SessionStore
    7. Build and return ChatResponse
    
    Handles all error cases:
    - validation_error → ValueError from validators
    - session_not_found → SessionNotFoundError
    - session_expired → SessionExpiredError
    - session_locked → SessionLockedError (409)
    - session_turn_limit_exceeded → Turn count >= max_turns
    - provider_unavailable → Non-200 LLM response (503)
    - provider_timeout → LLM timeout (504)
    - TimeoutError → asyncio.wait_for timeout (408)
    
    Args:
        request: ChatRequest with message and optional session_id
        store: SessionStore for Redis operations
        llm_client: LlmClient for LLM communication
        graph: Compiled LangGraph agent graph
        settings: Settings instance with configuration
        tool_registry: ToolRegistry for tool-aware decisions (T030 addition)
        
    Returns:
        ChatResponse with agent response and metadata
        
    Raises:
        ValueError: If validation fails
        SessionNotFoundError: If session not found
        SessionExpiredError: If session expired
        SessionLockedError: If session is locked
    """
    start_time = datetime.now(timezone.utc)
    
    # Step 1: Validate request
    try:
        validated_message = validate_message(request.message)
    except ValueError as e:
        logger.warning(f"Message validation failed: {e}")
        error_response = ErrorResponse(
            error_code="validation_error",
            message=str(e),
            severity_level="error",
            detail=None,
            recovery_hint="Please check your input and try again.",
        )
        return ChatResponse(
            session_id="",
            response="",
            success=False,
            turn_count=0,
            tool_calls=[],
            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            error=error_response,
            metadata=request.metadata,
        )
    
    # Validate session_id if provided
    validated_session_id = None
    if request.session_id:
        try:
            validated_session_id = validate_session_id(request.session_id)
        except ValueError as e:
            logger.warning(f"Session ID validation failed: {e}")
            error_response = ErrorResponse(
                error_code="validation_error",
                message=str(e),
                severity_level="error",
                detail=None,
                recovery_hint="Please check the session_id format (must be a valid UUID4).",
            )
            return ChatResponse(
                session_id=request.session_id or "",
                response="",
                success=False,
                turn_count=0,
                tool_calls=[],
                duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                error=error_response,
                metadata=request.metadata,
            )
    
    # Step 2: Load or create session with context manager
    manager = SessionManager(store, validated_session_id)
    
    try:
        async with manager as state:
            # Step 3: Check turn limit BEFORE executing
            if state.turn_count >= settings.max_turns:
                logger.warning(
                    f"Session {state.session_id} has exceeded max_turns "
                    f"({state.turn_count}/{settings.max_turns})"
                )
                # Return error response without executing graph
                error_response = ErrorResponse(
                    error_code="session_turn_limit_exceeded",
                    message=f"Session has reached its maximum of {settings.max_turns} turns.",
                    severity_level="error",
                    detail=f"Turn {state.turn_count} of {settings.max_turns} reached.",
                    recovery_hint="Start a new session.",
                )
                return ChatResponse(
                    session_id=state.session_id,
                    response="",
                    success=False,
                    turn_count=state.turn_count,
                    tool_calls=[],
                    duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                    error=error_response,
                    metadata=request.metadata,
                )
            
            # Step 4: Add user message to conversation
            user_message = Message(
                role="user",
                content=validated_message,
                created_at=datetime.now(timezone.utc),
            )
            state.messages.append(user_message)
            state.current_input = validated_message
            
            logger.info(
                f"Session {state.session_id} turn {state.turn_count + 1}: "
                f"User message: {validated_message[:50]}..."
            )
            
            # Step 5: Execute graph with timeout
            try:
                # T030: Pass tool_registry to graph execution for tool-aware decisions
                graph_config = {}
                if tool_registry:
                    graph_config["tool_registry"] = tool_registry
                
                result = await asyncio.wait_for(
                    graph.ainvoke(state, config=graph_config) if graph_config else graph.ainvoke(state),
                    timeout=60.0,  # 60 second timeout for external LLM calls
                )
                # ainvoke returns a dict representation of the state
                # Convert it back to AgentState
                if isinstance(result, dict):
                    from mcp_agent.session.models import dict_to_agent_state
                    state = dict_to_agent_state(result)
                else:
                    state = result
            except asyncio.TimeoutError:
                logger.error(
                    f"Session {state.session_id} graph execution timed out after 8s"
                )
                error_response = ErrorResponse(
                    error_code="request_timeout",
                    message="The request timed out. Please try again.",
                    severity_level="error",
                    detail="Timeout after 30 seconds.",
                    recovery_hint="Retry the request.",
                )
                return ChatResponse(
                    session_id=state.session_id,
                    response="",
                    success=False,
                    turn_count=state.turn_count,
                    tool_calls=[],
                    duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
                    error=error_response,
                    metadata=request.metadata,
                )
            
            # Step 6: Save updated state
            await store.set(
                state.session_id,
                state,
                ttl=settings.session_ttl_seconds,
            )
            
            logger.info(
                f"Session {state.session_id} turn {state.turn_count} completed. "
                f"Saved to Redis."
            )
            
            # Step 7: Build ChatResponse
            # Determine success/failure
            success = state.current_decision != "error"
            
            # Extract response content
            if state.messages:
                last_message = state.messages[-1]
                response_content = last_message.content if last_message.role == "assistant" else ""
            else:
                response_content = ""
            
            # Build tool calls summary (for now, empty for US1)
            tool_calls_summary = [
                ToolCallSummary(
                    tool_id=tc.tool_id,
                    status=tc.status,
                    duration_ms=tc.duration_ms,
                    fallback_used=tc.fallback_used if tc.fallback_used else None,
                )
                for tc in state.tool_calls_this_turn
            ]
            
            # Build error response if needed
            error_response = None
            if not success and state.last_error:
                error_response = ErrorResponse(
                    error_code="agent_error",
                    message=state.last_error,
                    severity_level="error",
                    detail=f"Error count: {state.error_count}",
                    recovery_hint="Please try your request again.",
                )
            
            # Calculate duration
            duration_ms = int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
            
            return ChatResponse(
                session_id=state.session_id,
                response=response_content,
                success=success,
                turn_count=state.turn_count,
                tool_calls=tool_calls_summary,
                duration_ms=duration_ms,
                error=error_response,
                metadata=request.metadata,
            )
    
    except SessionNotFoundError as e:
        logger.warning(f"Session not found: {e}")
        error_response = ErrorResponse(
            error_code="session_not_found",
            message="Session was not found.",
            severity_level="warning",
            detail=None,
            recovery_hint="Omit session_id to start a new session.",
        )
        return ChatResponse(
            session_id=validated_session_id or "unknown",
            response="",
            success=False,
            turn_count=0,
            tool_calls=[],
            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            error=error_response,
            metadata=request.metadata,
        )
    
    except SessionExpiredError as e:
        logger.warning(f"Session expired: {e}")
        error_response = ErrorResponse(
            error_code="session_expired",
            message="Session has expired.",
            severity_level="warning",
            detail=None,
            recovery_hint="Omit session_id to start a new session.",
        )
        return ChatResponse(
            session_id=validated_session_id or "unknown",
            response="",
            success=False,
            turn_count=0,
            tool_calls=[],
            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            error=error_response,
            metadata=request.metadata,
        )
    
    except SessionLockedError as e:
        logger.warning(f"Session locked: {e}")
        error_response = ErrorResponse(
            error_code="session_locked",
            message="Session is currently processing another request.",
            severity_level="warning",
            detail=f"Lock timeout: {SessionStore.LOCK_TIMEOUT_SECONDS}s",
            recovery_hint="Retry after the current request completes.",
        )
        return ChatResponse(
            session_id=validated_session_id or "unknown",
            response="",
            success=False,
            turn_count=0,
            tool_calls=[],
            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            error=error_response,
            metadata=request.metadata,
        )
    
    except LLMProviderError as e:
        logger.error(f"LLM provider error: {e}")
        error_response = ErrorResponse(
            error_code="provider_unavailable",
            message="The language model provider is currently unavailable.",
            severity_level="critical",
            detail=f"Provider error: {str(e)}",
            recovery_hint="Retry in a few minutes. If the problem persists, contact support.",
        )
        # Return 503 status via exception (handled by FastAPI exception handler)
        return ChatResponse(
            session_id=validated_session_id or "unknown",
            response="",
            success=False,
            turn_count=0,
            tool_calls=[],
            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            error=error_response,
            metadata=request.metadata,
        )
    
    except Exception as e:
        logger.exception(f"Unexpected error in chat handler: {e}")
        error_response = ErrorResponse(
            error_code="internal_error",
            message="An unexpected error occurred.",
            severity_level="critical",
            detail=str(e),
            recovery_hint="Please try again later.",
        )
        return ChatResponse(
            session_id=validated_session_id or "unknown",
            response="",
            success=False,
            turn_count=0,
            tool_calls=[],
            duration_ms=int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000),
            error=error_response,
            metadata=request.metadata,
        )


async def get_session_handler(
    session_id: str,
    store: SessionStore,
) -> SessionModel:
    """
    Retrieve session details by ID.
    
    Args:
        session_id: The session identifier
        store: SessionStore for Redis operations
        
    Returns:
        SessionModel with session details
        
    Raises:
        SessionNotFoundError: If session not found
    """
    try:
        validate_session_id(session_id)
    except ValueError as e:
        logger.warning(f"Session ID validation failed: {e}")
        raise SessionNotFoundError(f"Invalid session ID format: {e}")
    
    state = await store.get(session_id)
    if state is None:
        logger.warning(f"Session not found: {session_id}")
        raise SessionNotFoundError(f"Session {session_id} not found")
    
    # Extract messages as dicts
    messages = [dataclass_to_dict(msg) for msg in state.messages]
    
    # Convert state to dict for response
    state_dict = dataclass_to_dict(state)
    
    return SessionModel(
        id=session_id,
        turn_count=state.turn_count,
        messages=messages,
        last_activity=state.last_activity,
        state=state_dict,
    )


async def delete_session_handler(
    session_id: str,
    store: SessionStore,
) -> dict[str, str]:
    """
    Delete a session (idempotent).
    
    Args:
        session_id: The session identifier
        store: SessionStore for Redis operations
        
    Returns:
        Dictionary with success message
    """
    try:
        validate_session_id(session_id)
    except ValueError as e:
        logger.warning(f"Session ID validation failed: {e}")
        # Still return 200 for idempotence
        return {"message": f"Session deleted (or did not exist)"}
    
    try:
        await store.delete(session_id)
        logger.info(f"Session {session_id} deleted")
    except Exception as e:
        # Log error but still return 200 for idempotence
        logger.error(f"Error deleting session {session_id}: {e}")
    
    return {"message": "Session deleted"}


async def get_health_handler(
    store: SessionStore,
    llm_client: LlmClient,
    tool_registry=None,
) -> HealthResponse:
    """
    Check service health by pinging dependencies.
    
    Args:
        store: SessionStore with Redis connection
        llm_client: LlmClient for LLM provider health check
        tool_registry: ToolRegistry with available tools
        
    Returns:
        HealthResponse with dependency status
    """
    redis_up = False
    llm_up = False
    tool_count = 0
    
    # Check Redis
    try:
        await store.redis.ping()
        redis_up = True
        logger.debug("Redis health check passed")
    except Exception as e:
        logger.warning(f"Redis health check failed: {e}")
    
    # Check LLM provider
    try:
        # Try a simple completion to verify provider is accessible
        # Use a minimal request
        test_messages = [{"role": "user", "content": "ping"}]
        response = await asyncio.wait_for(
            llm_client.complete(test_messages),
            timeout=5.0,
        )
        llm_up = True
        logger.debug("LLM provider health check passed")
    except asyncio.TimeoutError:
        logger.warning("LLM provider health check timed out")
    except Exception as e:
        logger.warning(f"LLM provider health check failed: {e}")
    
    # Get tool count
    if tool_registry:
        tool_count = tool_registry.count()
    
    # Determine overall status
    if redis_up and llm_up:
        status = "healthy"
    elif redis_up or llm_up:
        status = "degraded"
    else:
        status = "unhealthy"
    
    return HealthResponse(
        status=status,
        redis="up" if redis_up else "down",
        llm_provider="up" if llm_up else "down",
        tool_count=tool_count,
        timestamp=datetime.now(timezone.utc),
    )


async def get_trace_handler(
    session_id: str,
    trace_buffer: "TraceBuffer",
) -> TraceResponse:
    """
    Retrieve trace events for a session.
    
    Args:
        session_id: The session identifier
        trace_buffer: TraceBuffer with collected events
        
    Returns:
        TraceResponse with ordered list of trace events
        
    Raises:
        SessionNotFoundError: If no traces found for session
    """
    try:
        validate_session_id(session_id)
    except ValueError as e:
        logger.warning(f"Session ID validation failed: {e}")
        raise SessionNotFoundError(f"Invalid session ID format: {e}")
    
    events = trace_buffer.get_traces_by_session_id(session_id)
    if not events:
        logger.info(f"No traces found for session {session_id}")
        raise SessionNotFoundError(f"No traces found for session {session_id}")
    
    # Convert events to TraceEvent models
    trace_events = [
        TraceEvent(
            timestamp=event["timestamp"],
            level=event["level"],
            message=event["message"],
            context=event.get("context", {}),
        )
        for event in events
    ]
    
    return TraceResponse(
        session_id=session_id,
        events=trace_events,
    )


async def get_metrics_handler(
    metrics_store: "MetricsStore",
) -> MetricsResponse:
    """
    Retrieve aggregate metrics.
    
    Args:
        metrics_store: MetricsStore with collected metrics
        
    Returns:
        MetricsResponse with all metric counters
    """
    snapshot = metrics_store.get_snapshot()
    
    return MetricsResponse(
        total_sessions=snapshot["total_sessions"],
        total_turns=snapshot["total_turns"],
        tool_calls=snapshot["tool_calls"],
        tool_failures=snapshot["tool_failures"],
        llm_invocations=snapshot["llm_invocations"],
        total_duration_ms=snapshot["total_duration_ms"],
        avg_duration_ms=snapshot["avg_duration_ms"],
    )
