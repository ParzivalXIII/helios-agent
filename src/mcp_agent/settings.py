"""
Configuration settings for the MCP Agent service.

Loads all environment variables from .env file using Pydantic BaseSettings.
All settings are validated at startup and raise errors if required variables are missing.
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # LLM Configuration
    llm_base_url: str
    """Base URL of the LLM provider (e.g., https://openrouter.ai/api/v1)."""

    llm_model: str
    """Model identifier (e.g., 'openai/gpt-4', 'anthropic/claude-opus')."""

    # Redis Configuration
    redis_url: str
    """Redis connection string (e.g., 'redis://localhost:6379/0')."""

    # Agent Behavior
    max_turns: int = 5
    """Maximum number of turns before rejecting further requests in a session."""

    session_ttl_seconds: int = 3600
    """Redis session TTL in seconds (default 1 hour)."""

    tool_timeout_ms: int = 5000
    """Tool execution timeout in milliseconds."""

    # Logging
    log_level: str = "INFO"
    """Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""

    # MCP Configuration
    mcp_config_path: str
    """Path to mcp_servers.yaml configuration file."""

    class Config:
        """Pydantic settings configuration."""

        env_file = ".env"
        case_sensitive = False
