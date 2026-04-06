"""
Type aliases for the MCP Agent service.

Defines shared type aliases used throughout the codebase.
"""

from typing import Literal

# Session identifier: UUID4 string
SessionId = str

# Tool identifier: fully-qualified name (server.tool_name)
ToolId = str

# Agent decision types: what the agent decides to do next
AgentDecision = Literal["use_tool", "direct_response", "error"]
