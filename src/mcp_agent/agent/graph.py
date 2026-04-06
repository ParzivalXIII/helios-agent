"""
LangGraph agent graph construction and compilation.

Builds the state graph with all nodes and conditional edges, then compiles
it for use in chat handlers.
"""

import logging
from functools import partial

from langgraph.graph import StateGraph, END

from mcp_agent.agent.state import AgentState
from mcp_agent.agent import nodes
from mcp_agent.agent.edges import (
    route_decide_action,
    route_tool_result,
    route_evaluate_result,
)
from mcp_agent.llm import LlmClient
from mcp_agent.settings import Settings

logger = logging.getLogger(__name__)


def build_agent_graph(llm_client: LlmClient, settings: Settings) -> "CompiledGraph":
    """
    Build and compile the LangGraph agent state graph.
    
    Graph structure:
    - START → node_think
    - node_think → node_decide_action (unconditional)
    - node_decide_action → (route_decide_action)
      - → node_invoke_tool
      - → node_direct_response
      - → node_error
    - node_invoke_tool → node_tool_result (unconditional, Phase 4+)
    - node_tool_result → (route_tool_result)
      - → node_evaluate_result
      - → node_error
    - node_evaluate_result → (route_evaluate_result)
      - → node_respond
      - → node_error
    - node_direct_response → node_respond (unconditional)
    - node_error → node_respond (unconditional)
    - node_respond → END (unconditional)
    
    Args:
        llm_client: LlmClient instance for LLM calls
        settings: Settings instance for configuration
        
    Returns:
        Compiled StateGraph ready for invocation
    """
    # Create the state graph with AgentState as the state type
    graph = StateGraph(AgentState)
    
    # Add all nodes
    # Partial functions to inject dependencies into nodes
    graph.add_node(
        "node_think",
        partial(nodes.node_think, llm_client=llm_client, settings=settings),
    )
    graph.add_node("node_decide_action", nodes.node_decide_action)
    graph.add_node(
        "node_invoke_tool",
        nodes.node_invoke_tool,
    )  # Placeholder for Phase 4
    graph.add_node("node_tool_result", nodes.node_tool_result)
    graph.add_node("node_evaluate_result", nodes.node_evaluate_result)
    graph.add_node("node_direct_response", partial(nodes.node_direct_response, llm_client=llm_client))
    graph.add_node("node_error", nodes.node_error)
    graph.add_node("node_respond", nodes.node_respond)
    
    # Add edges
    # START → node_think
    graph.set_entry_point("node_think")
    
    # node_think → node_decide_action (unconditional)
    graph.add_edge("node_think", "node_decide_action")
    
    # node_decide_action → (conditional routing)
    graph.add_conditional_edges(
        "node_decide_action",
        route_decide_action,
        {
            "node_invoke_tool": "node_invoke_tool",
            "node_direct_response": "node_direct_response",
            "node_error": "node_error",
        },
    )
    
    # node_invoke_tool → node_tool_result (unconditional)
    graph.add_edge("node_invoke_tool", "node_tool_result")
    
    # node_tool_result → (conditional routing)
    graph.add_conditional_edges(
        "node_tool_result",
        route_tool_result,
        {
            "node_evaluate_result": "node_evaluate_result",
            "node_error": "node_error",
        },
    )
    
    # node_evaluate_result → (conditional routing)
    graph.add_conditional_edges(
        "node_evaluate_result",
        route_evaluate_result,
        {
            "node_respond": "node_respond",
            "node_error": "node_error",
        },
    )
    
    # node_direct_response → node_respond (unconditional)
    graph.add_edge("node_direct_response", "node_respond")
    
    # node_error → node_respond (unconditional)
    graph.add_edge("node_error", "node_respond")
    
    # node_respond → END
    graph.add_edge("node_respond", END)
    
    # Compile the graph
    compiled = graph.compile()
    
    logger.info("Agent graph compiled with 8 nodes and 3 conditional edges")
    
    return compiled
