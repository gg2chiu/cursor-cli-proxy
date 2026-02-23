"""
Command builder for constructing CLI commands.
"""
from typing import List, Optional

from loguru import logger
from src.models import Message
from src.slash_command_loader import SlashCommandLoader
from src.temp_file_handler import (
    save_content_to_temp_file,
    save_image_to_temp_file,
    extract_filename_and_content,
    CONTENT_SIZE_THRESHOLD,
)


class CommandBuilder:
    def __init__(self, model: str, api_key: str, messages: List[Message], session_id: Optional[str] = None, workspace_dir: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        self.messages = messages
        self.session_id = session_id
        self.workspace_dir = workspace_dir
        self.slash_loader = SlashCommandLoader(workspace_dir)

    def _process_content_part(self, text: str) -> str:
        """
        Process a single content part. If it's large file content, save to temp file
        and return @filepath reference. Otherwise return the text as-is.
        """
        # Check if content is large enough to warrant saving to file
        if len(text) > CONTENT_SIZE_THRESHOLD:
            # Try to extract filename and actual content
            filename_hint, actual_content = extract_filename_and_content(text)
            
            # Save only the actual content (not the filename line) to temp file
            filepath = save_content_to_temp_file(actual_content, filename_hint)
            logger.info(f"Saved large content ({len(actual_content)} chars) to temp file: {filepath}")
            
            # Return reference with filename context if available
            if filename_hint:
                return f"File '{filename_hint}': @{filepath}"
            return f"@{filepath}"
        
        return text

    def _process_image_part(self, image_url: str) -> str:
        """
        Process an image content part. Save base64 image to temp file
        and return @filepath reference.
        """
        if image_url.startswith("data:"):
            filepath = save_image_to_temp_file(image_url)
            if filepath:
                logger.info(f"Saved image to temp file: {filepath}")
                return f"@{filepath}"
            return "[Image - failed to process]"
        elif image_url.startswith("http"):
            # For URL images, just pass the URL (cursor-agent might support it)
            return f"[Image URL: {image_url}]"
        return "[Image - unsupported format]"

    def _get_processed_content(self, msg: Message) -> str:
        """
        Get message content, processing large content parts into @filepath references.
        """
        if isinstance(msg.content, str):
            return self._process_content_part(msg.content)
        
        # Handle list content (multimodal)
        texts = []
        for part in msg.content:
            if hasattr(part, 'type'):
                part_type = part.type
                if part_type == "text":
                    text = part.text if hasattr(part, 'text') else ""
                    texts.append(self._process_content_part(text))
                elif part_type == "image_url":
                    # Get the URL from image_url object
                    image_url_obj = part.image_url if hasattr(part, 'image_url') else None
                    if image_url_obj:
                        url = image_url_obj.url if hasattr(image_url_obj, 'url') else ""
                        texts.append(self._process_image_part(url))
                    else:
                        texts.append("[Image - missing URL]")
            elif isinstance(part, dict):
                part_type = part.get("type")
                if part_type == "text":
                    text = part.get("text", "")
                    texts.append(self._process_content_part(text))
                elif part_type == "image_url":
                    image_url_data = part.get("image_url", {})
                    url = image_url_data.get("url", "") if isinstance(image_url_data, dict) else ""
                    texts.append(self._process_image_part(url))
        
        return "\n".join(texts)

    def _get_raw_content(self, msg: Message) -> str:
        """Get message content as plain text without temp file processing."""
        if isinstance(msg.content, str):
            return msg.content
        texts = []
        for part in msg.content:
            if hasattr(part, 'type') and part.type == "text":
                texts.append(part.text if hasattr(part, 'text') else "")
            elif isinstance(part, dict) and part.get("type") == "text":
                texts.append(part.get("text", ""))
        return "\n".join(texts)

    def _merge_messages(self) -> str:
        """Merge all conversation content into a single Prompt and expand slash commands"""
        merged = []
        has_assistant = any(msg.role == "assistant" for msg in self.messages)
        for idx, msg in enumerate(self.messages):
            # Only apply temp-file processing to user messages (file uploads).
            # System/assistant messages are instructions or context that must stay inline.
            if msg.role == "user":
                content = self._get_processed_content(msg).strip()
            else:
                content = self._get_raw_content(msg).strip()
            logger.debug(f"Message [{idx}] role={msg.role}, content_length={len(content)}, preview={content[:100]}")
            
            # Only try to expand slash commands for user messages
            if msg.role == "user":
                resolved = self.slash_loader.resolve_slash_command(content)
                if resolved != content:
                    logger.info(f"Message [{idx}] slash command resolved: {content[:50]} -> {resolved[:80]}")
                content = resolved
            
            if has_assistant:
                content = f"{msg.role.upper()}: {content}"

            merged.append(content)
        
        result = "\n\n".join(merged)
        logger.debug(f"Merged {len(self.messages)} messages into {len(result)} characters")
        return result

    def build(self, stream: bool = False) -> List[str]:
        prompt = self._merge_messages()
        
        from src.config import CURSOR_BIN
        cmd = [
            CURSOR_BIN,
            "--model", self.model,
            "--api-key", self.api_key,
            "--sandbox", "enabled",
            "--approve-mcps",
            "--force", # "approve-mcps" has a bug. We still need the "force" option to run the MCP tools.
            "--print",
        ]
        
        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        
        if self.workspace_dir:
            cmd.extend(["--workspace", self.workspace_dir])
        
        if stream:
            cmd.extend(["--output-format", "stream-json", "--stream-partial-output"])
        else:
            cmd.extend(["--output-format", "json"])
            
        cmd.append(prompt)
        return cmd
