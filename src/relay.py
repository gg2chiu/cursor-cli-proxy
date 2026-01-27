"""
Relay module - Facade for backward compatibility.

This module re-exports all public interfaces from the refactored modules:
- temp_file_handler: File saving utilities
- tag_parser: Workspace and session_id tag parsing
- command_builder: CLI command construction
- executor: CLI command execution
"""
from src.temp_file_handler import (
    save_content_to_temp_file,
    save_image_to_temp_file,
    extract_filename_and_content,
    CONTENT_SIZE_THRESHOLD,
)
from src.tag_parser import (
    parse_workspace_tag,
    parse_session_id_tag,
    validate_workspace_path,
    extract_workspace_from_messages,
)
from src.command_builder import CommandBuilder
from src.executor import Executor

# Re-export for backward compatibility
from src.slash_command_loader import SlashCommandLoader

__all__ = [
    # temp_file_handler
    "save_content_to_temp_file",
    "save_image_to_temp_file",
    "extract_filename_and_content",
    "CONTENT_SIZE_THRESHOLD",
    # tag_parser
    "parse_workspace_tag",
    "parse_session_id_tag",
    "validate_workspace_path",
    "extract_workspace_from_messages",
    # command_builder
    "CommandBuilder",
    # executor
    "Executor",
    # slash_command_loader (re-export)
    "SlashCommandLoader",
]
