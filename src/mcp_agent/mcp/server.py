"""
Built-in FastMCP server with example tools.

Provides in-process MCP server running within the agent application,
with example tools for demonstration and testing.
"""

from fastmcp import mcp


# Initialize the MCP server
server = mcp.Server("internal-tools")


@server.tool()
def echo_tool(message: str) -> str:
    """
    Echo tool that repeats back the input message.
    
    A simple demonstration tool useful for testing tool orchestration
    and message flow through the agent.
    
    Args:
        message: The message to echo back.
        
    Returns:
        The echoed message.
    """
    return message


@server.tool()
def reverse_tool(text: str) -> str:
    """
    Reverse tool that reverses the input text.
    
    Demonstrates text processing capability.
    
    Args:
        text: The text to reverse.
        
    Returns:
        The reversed text.
    """
    return text[::-1]


@server.tool()
def length_tool(text: str) -> int:
    """
    Length tool that returns the length of input text.
    
    Demonstrates returning numeric output.
    
    Args:
        text: The text to measure.
        
    Returns:
        The number of characters in the text.
    """
    return len(text)


async def list_tools():
    """
    List all available tools provided by this server.
    
    Returns:
        List of tool definitions with metadata.
    """
    return [
        {
            "name": "echo_tool",
            "description": "Echo tool that repeats back the input message",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "The message to echo back"
                    }
                },
                "required": ["message"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "The echoed message"
                    }
                }
            }
        },
        {
            "name": "reverse_tool",
            "description": "Reverse tool that reverses the input text",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to reverse"
                    }
                },
                "required": ["text"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "description": "The reversed text"
                    }
                }
            }
        },
        {
            "name": "length_tool",
            "description": "Length tool that returns the length of input text",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to measure"
                    }
                },
                "required": ["text"]
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "integer",
                        "description": "The number of characters"
                    }
                }
            }
        }
    ]
