"""
API route registration for the MCP Agent service.

Defines all REST endpoints for the chat API, session management,
health checks, and diagnostics.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, status

from mcp_agent.api.models import ChatRequest, ChatResponse, ErrorResponse
from mcp_agent.api.handlers import chat_handler
from mcp_agent.session.store import SessionStore
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
            # Get dependencies from app state
            store = request.app.state.session_store
            llm_client = request.app.state.llm_client
            graph = request.app.state.agent_graph
            settings = request.app.state.settings
            
            # Call handler
            response = await chat_handler(
                request=request_body,
                store=store,
                llm_client=llm_client,
                graph=graph,
                settings=settings,
            )
            
            logger.info(
                f"Chat request completed for session {response.session_id}: "
                f"turn {response.turn_count}, duration {response.duration_ms}ms"
            )
            
            return response
        
        except ValueError as e:
            # Validation error
            logger.warning(f"Validation error: {e}")
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error_code": "validation_error",
                    "message": str(e),
                    "severity_level": "error",
                },
            )
        
        except Exception as e:
            # Other errors
            logger.exception(f"Unexpected error in chat endpoint: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error_code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "severity_level": "critical",
                },
            )
    
    # ========================================================================
    # Additional endpoints (T033-T037) will be added here in Phase 6 (US4)
    # ========================================================================
    
    return router
