"""
API route registration for the MCP Agent service.

Defines all REST endpoints for the chat API, session management,
health checks, and diagnostics.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status

from mcp_agent.api.models import (
    ChatRequest,
    ChatResponse,
    ErrorResponse,
    SessionModel,
    HealthResponse,
    TraceResponse,
    MetricsResponse,
)
from mcp_agent.api.handlers import (
    chat_handler,
    get_session_handler,
    delete_session_handler,
    get_health_handler,
    get_trace_handler,
    get_metrics_handler,
)
from mcp_agent.session.store import (
    SessionStore,
    SessionNotFoundError,
)
from mcp_agent.agent.nodes import LlmClient
from mcp_agent.settings import Settings

logger = logging.getLogger(__name__)


def create_api_router() -> APIRouter:
    """
    Create and configure the API router with all endpoints.
    
    Returns:
        APIRouter: Configured router with /api endpoints
    """
    router = APIRouter(prefix="/api", tags=["chat"])
    
    @router.post(
        "/chat",
        response_model=ChatResponse,
        status_code=200,
        summary="Submit a message and receive an agent response",
        responses={
            200: {"description": "Message processed successfully or agent error"},
            422: {"description": "Validation error", "model": ErrorResponse},
            404: {"description": "Session not found or expired", "model": ErrorResponse},
            409: {"description": "Session locked", "model": ErrorResponse},
            503: {"description": "LLM provider unavailable", "model": ErrorResponse},
        },
    )
    async def post_chat(request_body: ChatRequest, request: Request) -> ChatResponse:
        """
        Submit a user message and receive an agent response.
        
        The agent may use tools to answer the question, persist the conversation
        in Redis, and return turn metadata. A `session_id` can be provided to
        continue a previous conversation; omit it to start a new session.
        
        Args:
            request_body: ChatRequest with message and optional session_id
            request: FastAPI Request object (used to access app state)
            
        Returns:
            ChatResponse with agent response, session metadata, and any tool calls
            
        Raises:
            HTTPException: For validation errors, session errors, or timeouts
        """
        try:
            # Get dependencies from app state (T030: Add tool_registry)
            store = request.app.state.session_store
            llm_client = request.app.state.llm_client
            graph = request.app.state.agent_graph
            settings = request.app.state.settings
            tool_registry = getattr(request.app.state, "tool_registry", None)  # T030: Tool registry
            
            # Call handler (T030: Pass tool_registry)
            response = await chat_handler(
                request=request_body,
                store=store,
                llm_client=llm_client,
                graph=graph,
                settings=settings,
                tool_registry=tool_registry,  # T030: Pass tool registry
            )
            
            logger.info(
                f"Chat request completed for session {response.session_id}: "
                f"turn {response.turn_count}, duration {response.duration_ms}ms"
            )
            
            return response
        
        except Exception as e:
            # Other unexpected errors
            logger.exception(f"Unexpected error in chat endpoint: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred.",
            )
    
    # ========================================================================
    # T033: GET /api/session/{session_id}
    # ========================================================================
    @router.get(
        "/session/{session_id}",
        response_model=SessionModel,
        status_code=200,
        summary="Get session details",
        responses={
            200: {"description": "Session found"},
            404: {"description": "Session not found", "model": ErrorResponse},
        },
    )
    async def get_session(session_id: str, request: Request) -> SessionModel:
        """
        Retrieve details of a specific session.
        
        Args:
            session_id: The session UUID4
            request: FastAPI Request object (used to access app state)
            
        Returns:
            SessionModel with session details
            
        Raises:
            HTTPException: 404 if session not found
        """
        try:
            store = request.app.state.session_store
            return await get_session_handler(session_id, store)
        except SessionNotFoundError as e:
            logger.warning(f"Session not found: {session_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error_code="session_not_found",
                    message=str(e),
                    severity_level="warning",
                ).model_dump(),
            )
        except Exception as e:
            logger.exception(f"Unexpected error retrieving session {session_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred.",
            )
    
    # ========================================================================
    # T034: DELETE /api/session/{session_id}
    # ========================================================================
    @router.delete(
        "/session/{session_id}",
        status_code=200,
        summary="Delete a session (idempotent)",
        responses={
            200: {"description": "Session deleted or did not exist"},
        },
    )
    async def delete_session(session_id: str, request: Request) -> dict[str, str]:
        """
        Delete a session (idempotent operation).
        
        Args:
            session_id: The session UUID4
            request: FastAPI Request object (used to access app state)
            
        Returns:
            Dictionary with success message (always 200)
        """
        try:
            store = request.app.state.session_store
            return await delete_session_handler(session_id, store)
        except Exception as e:
            logger.exception(f"Unexpected error deleting session {session_id}: {e}")
            # Still return 200 for idempotence
            return {"message": "Session deleted"}
    
    # ========================================================================
    # T035: GET /api/health
    # ========================================================================
    @router.get(
        "/health",
        response_model=HealthResponse,
        status_code=200,
        summary="Service health check",
        responses={
            200: {"description": "Service is healthy or degraded"},
            503: {"description": "Service is unhealthy"},
        },
    )
    async def get_health(request: Request) -> HealthResponse:
        """
        Check the health of the service and its dependencies.
        
        Pings Redis and LLM provider to determine overall health status.
        
        Args:
            request: FastAPI Request object (used to access app state)
            
        Returns:
            HealthResponse with dependency status
            
        Raises:
            HTTPException: 503 if unhealthy
        """
        try:
            store = request.app.state.session_store
            llm_client = request.app.state.llm_client
            tool_registry = getattr(request.app.state, "tool_registry", None)
            
            response = await get_health_handler(store, llm_client, tool_registry)
            
            # Return 503 if unhealthy
            if response.status == "unhealthy":
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=response.model_dump(),
                )
            
            return response
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error in health check: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Service health check failed.",
            )
    
    # ========================================================================
    # T036: GET /api/debug/trace/{session_id}
    # ========================================================================
    @router.get(
        "/debug/trace/{session_id}",
        response_model=TraceResponse,
        status_code=200,
        summary="Get session trace events",
        responses={
            200: {"description": "Trace events found"},
            404: {"description": "No traces found", "model": ErrorResponse},
        },
    )
    async def get_trace(session_id: str, request: Request) -> TraceResponse:
        """
        Retrieve trace events for a session.
        
        Args:
            session_id: The session UUID4
            request: FastAPI Request object (used to access app state)
            
        Returns:
            TraceResponse with ordered trace events
            
        Raises:
            HTTPException: 404 if no traces found
        """
        try:
            trace_buffer = getattr(request.app.state, "trace_buffer", None)
            if not trace_buffer:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ErrorResponse(
                        error_code="no_traces",
                        message="Trace buffer not initialized",
                        severity_level="warning",
                    ).model_dump(),
                )
            
            return await get_trace_handler(session_id, trace_buffer)
        except SessionNotFoundError as e:
            logger.info(f"No traces for session {session_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ErrorResponse(
                    error_code="no_traces",
                    message=str(e),
                    severity_level="warning",
                ).model_dump(),
            )
        except Exception as e:
            logger.exception(f"Unexpected error retrieving traces for {session_id}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred.",
            )
    
    # ========================================================================
    # T037: GET /api/debug/metrics
    # ========================================================================
    @router.get(
        "/debug/metrics",
        response_model=MetricsResponse,
        status_code=200,
        summary="Get aggregate metrics",
        responses={
            200: {"description": "Metrics retrieved"},
        },
    )
    async def get_metrics(request: Request) -> MetricsResponse:
        """
        Retrieve aggregate metrics.
        
        Args:
            request: FastAPI Request object (used to access app state)
            
        Returns:
            MetricsResponse with all counter values
        """
        try:
            metrics_store = getattr(request.app.state, "metrics_store", None)
            if not metrics_store:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Metrics store not initialized",
                )
            
            return await get_metrics_handler(metrics_store)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error retrieving metrics: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An unexpected error occurred.",
            )
    
    return router
