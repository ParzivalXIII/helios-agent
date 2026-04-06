"""
Input validation functions for the API.

Provides validators for session IDs and messages used throughout the service.
"""

import re


def validate_session_id(value: str) -> str:
    """
    Validate a session ID against UUID4 format.

    Args:
        value: The session ID to validate.

    Returns:
        The validated session ID.

    Raises:
        ValueError: If the session ID is not a valid UUID4 format.
    """
    uuid4_pattern = r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
    if not re.match(uuid4_pattern, value, re.IGNORECASE):
        raise ValueError(f"Invalid session ID format: {value}. Expected UUID4.")
    return value


def validate_message(value: str) -> str:
    """
    Validate a message for length constraints.

    Args:
        value: The message to validate.

    Returns:
        The validated message.

    Raises:
        ValueError: If the message is empty or exceeds 4096 characters.
    """
    if not value or len(value) < 1:
        raise ValueError("Message cannot be empty.")
    if len(value) > 4096:
        raise ValueError(f"Message exceeds maximum length (4096 chars): {len(value)}")
    return value
