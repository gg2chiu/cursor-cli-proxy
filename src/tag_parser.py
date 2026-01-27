"""
Tag parsing utilities for extracting workspace and session_id from messages.
"""
import os
import re
from typing import List, Optional, Tuple

from loguru import logger
from src.config import config
from src.models import Message


def parse_workspace_tag(content: str) -> Tuple[Optional[str], str]:
    """
    Extract workspace path from <workspace>...</workspace> tag in content.
    
    Returns:
        Tuple of (workspace_path, cleaned_content)
        - workspace_path: The extracted path or None if not found
        - cleaned_content: The content with the workspace tag removed
    """
    pattern = r'<workspace>\s*(.+?)\s*</workspace>'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        return None, content
    
    workspace_path = match.group(1).strip()
    # Remove the tag from content
    cleaned_content = re.sub(pattern, '', content, flags=re.DOTALL).strip()
    
    logger.debug(f"Extracted workspace tag: {workspace_path}")
    return workspace_path, cleaned_content


def parse_session_id_tag(content: str) -> Tuple[Optional[str], str]:
    """
    Extract session_id from <session_id>...</session_id> tag in content.
    
    Returns:
        Tuple of (session_id, cleaned_content)
        - session_id: The extracted session_id or None if not found
        - cleaned_content: The content with the session_id tag removed
    """
    pattern = r'<session_id>\s*(.+?)\s*</session_id>'
    match = re.search(pattern, content, re.DOTALL)
    
    if not match:
        return None, content
    
    session_id = match.group(1).strip()
    # Remove the tag from content
    cleaned_content = re.sub(pattern, '', content, flags=re.DOTALL).strip()
    
    logger.debug(f"Extracted session_id tag: {session_id}")
    return session_id, cleaned_content


def validate_workspace_path(path: Optional[str]) -> Optional[str]:
    """
    Validate that the workspace path is absolute and in the whitelist.
    
    Returns:
        The path if valid, None otherwise (with warning logged)
    """
    if not path:
        return None
    
    # Check if absolute path
    if not os.path.isabs(path):
        logger.warning(f"Workspace path '{path}' is not absolute, ignoring")
        return None
    
    # Get whitelist from config
    whitelist = config.get_workspace_whitelist()
    
    # If whitelist is empty, no custom workspace allowed
    if not whitelist:
        logger.warning(f"Workspace whitelist is empty, ignoring custom workspace '{path}'")
        return None
    
    # Check if path is in whitelist (exact match or subdirectory)
    path_normalized = os.path.normpath(path)
    for allowed_path in whitelist:
        allowed_normalized = os.path.normpath(allowed_path)
        # Check exact match or if path is under allowed path
        if path_normalized == allowed_normalized or path_normalized.startswith(allowed_normalized + os.sep):
            logger.info(f"Workspace path '{path}' validated against whitelist")
            return path
    
    logger.warning(f"Workspace path '{path}' not in whitelist, ignoring")
    return None


def extract_workspace_from_messages(messages: List[Message]) -> Tuple[Optional[str], Optional[str], List[Message]]:
    """
    Extract and validate workspace and session_id from messages (typically from system message).
    
    Returns:
        Tuple of (validated_workspace_path, session_id, cleaned_messages)
    """
    if not messages:
        return None, None, messages
    
    workspace_path = None
    session_id = None
    cleaned_messages = []
    
    for msg in messages:
        # Only look for workspace and session_id tags in system messages
        if msg.role == "system":
            cleaned_content = msg.get_text_content()
            
            # Extract workspace tag
            if workspace_path is None:
                extracted_path, cleaned_content = parse_workspace_tag(cleaned_content)
                if extracted_path:
                    workspace_path = validate_workspace_path(extracted_path)
            
            # Extract session_id tag
            if session_id is None:
                extracted_session_id, cleaned_content = parse_session_id_tag(cleaned_content)
                if extracted_session_id:
                    session_id = extracted_session_id
                    logger.info(f"Extracted custom session_id from system prompt: {session_id}")
            
            # Create new message with cleaned content
            cleaned_messages.append(Message(role=msg.role, content=cleaned_content))
        else:
            cleaned_messages.append(msg)
    
    return workspace_path, session_id, cleaned_messages
