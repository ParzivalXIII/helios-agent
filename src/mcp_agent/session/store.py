"""
Session store implementation using Redis.

Provides AsyncSessionStore for managing AgentState persistence in Redis with
automatic TTL, write locks, and serialization/deserialization.
"""

import json
import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

from mcp_agent.agent.state import AgentState
from mcp_agent.session.models import dataclass_to_dict, dict_to_agent_state

logger = logging.getLogger(__name__)


class SessionStore:
    """
    Redis-based session store for AgentState persistence.
    
    Handles:
    - Serialization to/from JSON via session.models helpers
    - Per-session write locks using SET NX EX pattern
    - Automatic TTL on session keys
    - Lock timeout of 30 seconds (hardcoded per spec)
    """
    
    LOCK_TIMEOUT_SECONDS = 30
    """Write lock timeout in seconds (SET EX 30)"""
    
    def __init__(self, redis_client: aioredis.Redis):
        """
        Initialize the session store.
        
        Args:
            redis_client: Connected aioredis.Redis instance
        """
        self.redis = redis_client
    
    async def get(self, session_id: str) -> AgentState | None:
        """
        Retrieve a session from Redis.
        
        Args:
            session_id: The session identifier
            
        Returns:
            AgentState if found, None if not found or expired
        """
        key = f"session:{session_id}"
        try:
            json_str = await self.redis.get(key)
            if json_str is None:
                return None
            
            data = json.loads(json_str)
            state = dict_to_agent_state(data)
            return state
        except json.JSONDecodeError as e:
            logger.error(f"Failed to deserialize session {session_id}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving session {session_id} from Redis: {e}")
            raise
    
    async def set(self, session_id: str, state: AgentState, ttl: int) -> None:
        """
        Store a session in Redis with automatic expiration.
        
        Args:
            session_id: The session identifier
            state: The AgentState to persist
            ttl: Time-to-live in seconds
            
        Raises:
            RuntimeError: If Redis operation fails
        """
        key = f"session:{session_id}"
        try:
            state_dict = dataclass_to_dict(state)
            json_str = json.dumps(state_dict)
            
            # SET with EX (expire in seconds)
            await self.redis.set(key, json_str, ex=ttl)
            logger.debug(f"Session {session_id} stored in Redis with TTL {ttl}s")
        except Exception as e:
            logger.error(f"Error storing session {session_id} to Redis: {e}")
            raise RuntimeError(f"Failed to persist session: {e}")
    
    async def delete(self, session_id: str) -> None:
        """
        Delete a session from Redis.
        
        Args:
            session_id: The session identifier
        """
        key = f"session:{session_id}"
        try:
            await self.redis.delete(key)
            logger.debug(f"Session {session_id} deleted from Redis")
        except Exception as e:
            logger.error(f"Error deleting session {session_id} from Redis: {e}")
            raise
    
    async def acquire_lock(self, session_id: str, timeout_ms: int) -> bool:
        """
        Acquire an exclusive write lock for a session.
        
        Uses Redis SET NX EX pattern with a 30-second timeout to prevent
        concurrent writes to the same session.
        
        Args:
            session_id: The session identifier
            timeout_ms: Timeout in milliseconds (not used in SET command, 
                       but passed for API consistency)
            
        Returns:
            True if lock acquired, False if already locked
        """
        lock_key = f"session:lock:{session_id}"
        try:
            # SET NX EX 30: Set only if not exists, expire in 30 seconds
            result = await self.redis.set(
                lock_key,
                "locked",
                nx=True,
                ex=self.LOCK_TIMEOUT_SECONDS,
            )
            
            if result:
                logger.debug(f"Lock acquired for session {session_id}")
            else:
                logger.warning(f"Failed to acquire lock for session {session_id}")
            
            return result is not None
        except Exception as e:
            logger.error(f"Error acquiring lock for session {session_id}: {e}")
            raise
    
    async def release_lock(self, session_id: str) -> None:
        """
        Release an exclusive write lock for a session.
        
        Args:
            session_id: The session identifier
        """
        lock_key = f"session:lock:{session_id}"
        try:
            await self.redis.delete(lock_key)
            logger.debug(f"Lock released for session {session_id}")
        except Exception as e:
            logger.error(f"Error releasing lock for session {session_id}: {e}")
            raise


# Exception classes for session operations
class SessionNotFoundError(Exception):
    """Raised when a session cannot be found in Redis."""
    pass


class SessionExpiredError(Exception):
    """Raised when a session has expired (TTL elapsed)."""
    pass


class SessionLockedError(Exception):
    """Raised when a session is locked by another concurrent request."""
    pass
