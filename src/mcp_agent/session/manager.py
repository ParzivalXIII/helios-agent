"""
Session manager with context manager support.

Provides SessionManager for loading or creating sessions, managing lifecycle
with automatic lock acquisition and release, and handling session expiration.
"""

import logging
import uuid
from datetime import datetime, timezone

from mcp_agent.agent.state import AgentState, Message
from mcp_agent.session.store import (
    SessionLockedError,
    SessionNotFoundError,
    SessionExpiredError,
    SessionStore,
)
from mcp_agent.settings import Settings

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Context manager for session lifecycle management.
    
    Handles:
    - Creating new sessions with UUID4 identifiers
    - Loading existing sessions from Redis
    - Checking for session expiration based on TTL
    - Acquiring and releasing write locks automatically
    - Proper cleanup in case of errors
    """
    
    def __init__(self, store: SessionStore, session_id: str | None = None):
        """
        Initialize session manager.
        
        Args:
            store: SessionStore instance for Redis operations
            session_id: Existing session ID to load, or None to create new
        """
        self.store = store
        self.session_id = session_id
        self.state: AgentState | None = None
        self._lock_acquired = False
    
    async def load_or_create(self, settings: Settings) -> AgentState:
        """
        Load an existing session or create a new one.
        
        If session_id is None, creates a new session with a UUID4 identifier.
        If session_id is provided, loads from Redis. If not found or expired,
        returns an error state.
        
        Args:
            settings: Settings instance for TTL configuration
            
        Returns:
            AgentState: The loaded or newly created session state
        """
        if self.session_id is None:
            # Create new session
            self.session_id = str(uuid.uuid4())
            now = datetime.now(timezone.utc)
            self.state = AgentState(
                session_id=self.session_id,
                created_at=now,
                last_activity=now,
            )
            logger.info(f"Created new session {self.session_id}")
        else:
            # Load existing session
            self.state = await self.store.get(self.session_id)
            
            if self.state is None:
                # Session not found or expired
                logger.warning(f"Session {self.session_id} not found in Redis")
                raise SessionNotFoundError(f"Session {self.session_id} not found")
            
            # Check if session has expired (last activity > TTL)
            now = datetime.now(timezone.utc)
            elapsed = (now - self.state.last_activity).total_seconds()
            if elapsed > settings.session_ttl_seconds:
                logger.warning(
                    f"Session {self.session_id} expired after {elapsed}s"
                    f" (TTL: {settings.session_ttl_seconds}s)"
                )
                raise SessionExpiredError(
                    f"Session {self.session_id} expired"
                )
        
        return self.state
    
    async def __aenter__(self) -> AgentState:
        """
        Enter async context manager.
        
        Loads or creates session and acquires write lock.
        
        Returns:
            AgentState: The session state
            
        Raises:
            SessionNotFoundError: If session ID provided but not found
            SessionExpiredError: If session has expired
            SessionLockedError: If lock cannot be acquired
        """
        # Note: Settings instance should be created/passed by the caller
        # For now, we'll use a simple approach of creating it inline
        from mcp_agent.settings import Settings
        settings = Settings()
        
        # Load or create state
        self.state = await self.load_or_create(settings)
        
        # Acquire lock
        lock_acquired = await self.store.acquire_lock(
            self.session_id,
            timeout_ms=self.store.LOCK_TIMEOUT_SECONDS * 1000,
        )
        
        if not lock_acquired:
            logger.warning(f"Failed to acquire lock for session {self.session_id}")
            raise SessionLockedError(
                f"Session {self.session_id} is locked by another request"
            )
        
        self._lock_acquired = True
        logger.debug(f"Session {self.session_id} context manager entered")
        return self.state
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Exit async context manager.
        
        Always releases the lock, even if an exception occurred.
        
        Args:
            exc_type: Exception type if one was raised
            exc_val: Exception instance if one was raised
            exc_tb: Exception traceback if one was raised
        """
        try:
            if self._lock_acquired:
                await self.store.release_lock(self.session_id)
                self._lock_acquired = False
                logger.debug(f"Session {self.session_id} context manager exited")
        except Exception as e:
            logger.error(f"Error releasing lock for session {self.session_id}: {e}")
            # Don't re-raise; lock will expire after 30s anyway
        
        # Don't suppress exceptions from the with block
        return False
