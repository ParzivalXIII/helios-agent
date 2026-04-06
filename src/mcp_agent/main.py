"""
Main FastAPI application factory.

Creates and configures the FastAPI app with lifespan startup/shutdown,
Redis connection, LLM client, agent graph, and API router registration.
"""

import logging
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
from fastapi import FastAPI

from mcp_agent.settings import Settings
from mcp_agent.logging.setup import configure_logging
from mcp_agent.session.store import SessionStore
from mcp_agent.llm import LlmClient
from mcp_agent.agent.graph import build_agent_graph
from mcp_agent.api.router import create_api_router
from mcp_agent.mcp.aggregator import MCPAggregator

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager for startup and shutdown.
    
    Startup:
    - Initialize settings from environment
    - Configure logging
    - Connect to Redis
    - Create LLM client
    - Discover MCP tools and build tool registry
    - Build agent graph with tool context
    - Store in app.state for handlers
    
    Shutdown:
    - Close Redis connection
    - Close LLM client
    """
    # ========================================================================
    # STARTUP
    # ========================================================================
    logger.info("Starting MCP Agent service...")
    
    # Initialize settings
    settings = Settings()
    logger.info(f"Loaded settings: max_turns={settings.max_turns}, "
                f"session_ttl={settings.session_ttl_seconds}s")
    
    # Configure logging
    configure_logging(settings)
    logger.info(f"Logging configured: level={settings.log_level}")
    
    # Connect to Redis
    try:
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        # Test connection
        await redis_client.ping()
        logger.info(f"Connected to Redis: {settings.redis_url}")
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise
    
    # Create session store
    session_store = SessionStore(redis_client)
    logger.info("Session store initialized")
    
    # Create LLM client
    try:
        llm_client = LlmClient(settings)
        logger.info(f"LLM client initialized: {settings.llm_model}")
    except Exception as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        raise
    
    # Discover MCP tools (T029 addition)
    tool_registry = None
    try:
        logger.info("Discovering MCP tools from configured servers...")
        aggregator = MCPAggregator(settings)
        tool_registry = await aggregator.discover_all()
        tool_count = tool_registry.count()
        logger.info(f"✓ MCP discovery complete: {tool_count} tools registered")
    except Exception as e:
        logger.error(f"MCP tool discovery failed: {e}")
        # Continue startup but log warning - agent can operate without tools
        logger.warning("Agent will operate without tool support")
        from mcp_agent.mcp.registry import ToolRegistry
        tool_registry = ToolRegistry()
    
    # Build agent graph
    try:
        agent_graph = build_agent_graph(llm_client, settings)
        logger.info("Agent graph compiled and ready")
    except Exception as e:
        logger.error(f"Failed to build agent graph: {e}")
        raise
    
    # Store in app.state
    app.state.settings = settings
    app.state.session_store = session_store
    app.state.llm_client = llm_client
    app.state.agent_graph = agent_graph
    app.state.tool_registry = tool_registry  # T029 addition
    
    logger.info("✓ MCP Agent service started successfully")
    
    yield
    
    # ========================================================================
    # SHUTDOWN
    # ========================================================================
    logger.info("Shutting down MCP Agent service...")
    
    try:
        await redis_client.aclose()
        logger.info("Redis connection closed")
    except Exception as e:
        logger.warning(f"Error closing Redis connection: {e}")
    
    try:
        await llm_client.aclose()
        logger.info("LLM client closed")
    except Exception as e:
        logger.warning(f"Error closing LLM client: {e}")
    
    logger.info("✓ MCP Agent service shut down")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        FastAPI: Configured app instance ready for uvicorn
    """
    app = FastAPI(
        title="MCP Agent",
        description="Multi-turn agent with tool orchestration",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # Include API router
    router = create_api_router()
    app.include_router(router)
    
    # Root endpoint for health check
    @app.get("/", tags=["health"])
    async def root():
        """Root endpoint."""
        return {"status": "ok", "service": "mcp-agent"}
    
    logger.info("FastAPI app created")
    
    return app


# Create app instance for uvicorn import
app = create_app()
