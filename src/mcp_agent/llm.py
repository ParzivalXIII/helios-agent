"""
Standalone LLM client module for OpenRouter API integration.

Provides a LlmClient wrapper around langchain-openai's ChatOpenAI,
with OpenRouter API endpoint support and error handling.
"""

import logging
from typing import Any

from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    BaseMessage,
)
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from mcp_agent.settings import Settings

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Raised when LLM provider returns an error response."""
    pass


class LlmClient:
    """
    Async LLM client for OpenRouter API using langchain-openai.
    
    Wraps ChatOpenAI to provide a simple interface for completing
    conversations via the OpenRouter API endpoint.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize the LLM client.
        
        Args:
            settings: Settings instance with openrouter_base_url,
                     llm_model, and openrouter_api_key
        """
        self.settings = settings
        self.llm = ChatOpenAI(
            base_url=settings.openrouter_base_url,
            model=settings.llm_model,
            api_key=SecretStr(settings.openrouter_api_key),
            timeout=30,
        )
    
    async def complete(self, messages: list[dict]) -> str:
        """
        Request a completion from the LLM provider.
        
        Sends a list of messages to the LLM provider and returns the
        generated response text.
        
        Args:
            messages: List of message dicts with 'role' and 'content' keys
                     Format: [{"role": "user"|"assistant"|"system", "content": "..."}]
            
        Returns:
            The assistant's response text
            
        Raises:
            LLMProviderError: If the provider returns an error
        """
        try:
            # Convert dict messages to LangChain message objects
            lc_messages: list[BaseMessage] = []
            for msg in messages:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                
                if role == "system":
                    lc_messages.append(SystemMessage(content=content))
                elif role == "user":
                    lc_messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    lc_messages.append(AIMessage(content=content))
                elif role == "tool":
                    # Tool results are treated as human messages in LangChain
                    lc_messages.append(HumanMessage(content=content))
                else:
                    lc_messages.append(HumanMessage(content=content))
            
            # Call LLM with converted messages
            response = await self.llm.ainvoke(lc_messages)
            
            # Extract text content from response
            # response.content can be a string or list, we need to handle both
            content = response.content
            if isinstance(content, list):
                # If content is a list of dicts or other types, stringify it
                content = str(content)
            content = str(content) if content else ""
            
            if not content:
                raise LLMProviderError("LLM returned empty response")
            
            logger.debug(f"LLM responded with {len(content)} characters")
            return content
        
        except LLMProviderError:
            raise
        except Exception as e:
            logger.error(f"LLM provider error: {type(e).__name__}: {e}")
            raise LLMProviderError(
                f"LLM provider error: {str(e)}",
            ) from e
    
    async def aclose(self) -> None:
        """Close the LLM client connection (no-op for compatibility)."""
        # ChatOpenAI manages connections internally via httpx client pool
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.aclose()
