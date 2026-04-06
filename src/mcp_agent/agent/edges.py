"""
Edge routing functions for the LangGraph agent graph.

Conditional routing based on agent state to determine graph flow transitions.
All returned node names must exactly match node names in the graph.
"""

import logging

from mcp_agent.agent.state import AgentState

logger = logging.getLogger(__name__)


def route_decide_action(state: AgentState) -> str:
    """
    Route after node_decide_action based on the decision made.
    
    Routes to:
    - "node_invoke_tool": if current_decision is "use_tool" (Phase 4+)
    - "node_direct_response": if current_decision is "direct_response"
    - "node_error": if current_decision is "error"
    
    Args:
        state: Current agent state
        
    Returns:
        Next node name: "node_invoke_tool" | "node_direct_response" | "node_error"
    """
    decision = state.current_decision
    
    if decision == "use_tool":
        logger.debug(f"Routing to node_invoke_tool (tool: {state.selected_tool_id})")
        return "node_invoke_tool"
    elif decision == "direct_response":
        logger.debug("Routing to node_direct_response")
        return "node_direct_response"
    elif decision == "error":
        logger.debug("Routing to node_error")
        return "node_error"
    else:
        logger.warning(f"Unknown decision: {decision}; routing to node_error")
        return "node_error"


def route_tool_result(state: AgentState) -> str:
    """
    Route after node_tool_result based on tool execution outcome.
    
    In Phase 4, this routes based on tool success/failure:
    - "node_evaluate_result": if tool succeeded
    - "node_error": if tool failed after retries
    
    For now (Phase 3), this is not called since tools are not used.
    
    Args:
        state: Current agent state
        
    Returns:
        Next node name: "node_evaluate_result" | "node_error"
    """
    # Check the most recent tool call if any
    if state.tool_calls_this_turn:
        latest_call = state.tool_calls_this_turn[-1]
        
        if latest_call.status == "success":
            logger.debug("Tool succeeded; routing to node_evaluate_result")
            return "node_evaluate_result"
        else:
            logger.debug(f"Tool failed with status {latest_call.status}; routing to node_error")
            return "node_error"
    else:
        # No tool calls; should not happen if we reached this node
        logger.warning("No tool calls found; routing to node_error")
        return "node_error"


def route_evaluate_result(state: AgentState) -> str:
    """
    Route after node_evaluate_result based on final synthesis.
    
    In Phase 4, routes based on whether a final answer was synthesized:
    - "node_respond": if evaluation succeeded
    - "node_error": if evaluation failed
    
    For now (Phase 3), this is not called since tools are not used.
    
    Args:
        state: Current agent state
        
    Returns:
        Next node name: "node_respond" | "node_error"
    """
    # Check if current_decision was set to error during evaluation
    if state.current_decision == "error":
        logger.debug("Evaluation failed; routing to node_error")
        return "node_error"
    else:
        logger.debug("Evaluation succeeded; routing to node_respond")
        return "node_respond"
