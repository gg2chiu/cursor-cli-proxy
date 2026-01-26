import asyncio
import json
import os
import re
import uuid
import hashlib
import base64
from typing import List, Optional, Tuple
from loguru import logger
from src.config import config, CURSOR_CLI_PROXY_TMP
from src.models import Message
from src.tool_formatters import format_tool_call_start, format_tool_call_result
from src.slash_command_loader import SlashCommandLoader


def save_content_to_temp_file(content: str, filename_hint: str = None, extension: str = None) -> str:
    """
    Save text content to a temporary file and return the file path.
    Uses a hash-based filename to avoid duplicates.
    """
    # Create temp directory if not exists
    os.makedirs(CURSOR_CLI_PROXY_TMP, exist_ok=True)
    
    # Generate unique filename based on content hash
    content_hash = hashlib.md5(content.encode()).hexdigest()[:12]
    
    # Determine file extension
    ext = extension or ".txt"
    if not extension and filename_hint:
        # Extract extension from filename hint
        if "." in filename_hint:
            ext = "." + filename_hint.rsplit(".", 1)[-1].lower()
            # Limit extension to reasonable ones
            if len(ext) > 10 or not ext[1:].isalnum():
                ext = ".txt"
    
    filename = f"upload_{content_hash}{ext}"
    filepath = os.path.join(CURSOR_CLI_PROXY_TMP, filename)
    
    # Write content to file
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    
    logger.debug(f"Saved text content to temp file: {filepath} ({len(content)} bytes)")
    return filepath


def save_image_to_temp_file(data_url: str) -> Optional[str]:
    """
    Save base64 image to a temporary file and return the file path.
    Supports data URLs like: data:image/jpeg;base64,/9j/4AAQ...
    """
    # Parse data URL
    if not data_url.startswith("data:"):
        logger.warning(f"Invalid data URL format: {data_url[:50]}...")
        return None
    
    try:
        # Format: data:image/jpeg;base64,<data>
        header, encoded = data_url.split(",", 1)
        
        # Extract MIME type
        mime_part = header.split(";")[0]  # data:image/jpeg
        mime_type = mime_part.split(":")[1] if ":" in mime_part else "image/png"
        
        # Determine extension from MIME type
        ext_map = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
        }
        ext = ext_map.get(mime_type, ".png")
        
        # Decode base64
        image_data = base64.b64decode(encoded)
        
        # Generate filename
        content_hash = hashlib.md5(image_data).hexdigest()[:12]
        filename = f"image_{content_hash}{ext}"
        filepath = os.path.join(CURSOR_CLI_PROXY_TMP, filename)
        
        # Create temp directory if not exists
        os.makedirs(CURSOR_CLI_PROXY_TMP, exist_ok=True)
        
        # Write image to file
        with open(filepath, "wb") as f:
            f.write(image_data)
        
        logger.debug(f"Saved image to temp file: {filepath} ({len(image_data)} bytes)")
        return filepath
        
    except Exception as e:
        logger.error(f"Failed to save image: {e}")
        return None


def extract_filename_and_content(text: str) -> Tuple[Optional[str], str]:
    """
    Try to extract filename from first line and return (filename, content).
    Pattern: "filename.ext\n<actual content>"
    Returns (None, original_text) if no filename pattern detected.
    """
    lines = text.split("\n", 1)
    if len(lines) < 2:
        return None, text
    
    first_line = lines[0].strip()
    rest_content = lines[1]
    
    # Check if first line looks like a filename (has extension, reasonable length, no spaces at start)
    if len(first_line) < 300 and "." in first_line and not first_line.startswith(" "):
        # Check if it has a valid-looking extension
        ext = first_line.rsplit(".", 1)[-1].lower()
        if len(ext) <= 10 and ext.isalnum():
            logger.debug(f"Detected filename: {first_line}")
            return first_line, rest_content
    
    return None, text


# Threshold for when to save content to file (in characters)
# Command line limit is typically 128KB-2MB, but let's be conservative
CONTENT_SIZE_THRESHOLD = 4000


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

    def _merge_messages(self) -> str:
        """合併所有對話內容成一個 Prompt，並展開 slash 指令"""
        merged = []
        has_assistant = any(msg.role == "assistant" for msg in self.messages)
        for idx, msg in enumerate(self.messages):
            # Use _get_processed_content to handle large file content
            content = self._get_processed_content(msg).strip()
            logger.debug(f"Message [{idx}] role={msg.role}, content_length={len(content)}, preview={content[:100]}")
            
            # 只對 user 訊息嘗試展開 slash 指令
            if msg.role == "user":
                expanded = self.slash_loader.expand_slash_command(content)
                if expanded != content:
                    logger.info(f"Message [{idx}] slash command expanded: {len(content)} -> {len(expanded)} chars")
                content = expanded
            
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

class Executor:
    """負責執行 CLI 指令"""
    
    async def run_non_stream(self, cmd: List[str], cwd: Optional[str] = None, timeout: float = 300) -> str:
        """執行指令，監控 stdout，收到有效 JSON 結果後立即返回"""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            limit=1024 * 1024 * 10,  # 10MB
        )
        
        stdout_buffer = b""
        
        async def read_until_json():
            nonlocal stdout_buffer
            # 逐塊讀取 stdout
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    # stdout 關閉了
                    break
                stdout_buffer += chunk
                
                # 嘗試解析 JSON - 如果成功，表示輸出完成
                try:
                    data = json.loads(stdout_buffer.decode())
                    # 成功解析 JSON，可以立即返回
                    logger.debug("Received valid JSON output, returning immediately")
                    return data.get("result", "")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # JSON 還不完整或 UTF-8 字符被截斷，繼續讀取
                    continue
            # 如果沒有收到有效 JSON，返回原始輸出
            return stdout_buffer.decode(errors='replace').strip()
        
        try:
            result = await asyncio.wait_for(read_until_json(), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Process timed out after {timeout}s, terminating...")
            raise RuntimeError(f"CLI execution timed out after {timeout}s")
        finally:
            # 清理：如果進程還在跑，終止它
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    async def run_stream(self, cmd: List[str], cwd: Optional[str] = None):
        """執行指令並串流回傳 stdout"""
        logger.debug(f"Starting stream command: {cmd}")
        if cwd:
            logger.debug(f"Working directory: {cwd}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            limit=1024 * 1024 * 1, # 1MB
        )
        
        line_count = 0
        tool_count = 0
        call_id_to_tool_number = {}  # Track call_id -> tool_number mapping
        last_full_text = ""
        last_type = None
        
        async for line in process.stdout:
            line_str = line.decode().strip()
            if not line_str:
                continue
            
            line_count += 1
            
            try:
                data = json.loads(line_str)
                logger.debug(f"[Stream Line {line_count}] Received JSON type: {data.get('type')}")
                
                # 只處理 assistant 類型的 delta
                event_type = data.get("type")
                if event_type != last_type:
                    logger.debug(f"[Stream Line {line_count}] Event type changed.")
                    last_full_text = ""
                    yield "\n"
                if event_type == "assistant":
                    if "timestamp_ms" in data:
                        content_list = data.get("message", {}).get("content", [])
                        logger.debug(f"[Stream Line {line_count}] Content list has {len(content_list)} items")
                        
                        # Accumulate all text content from this message
                        full_text = ""
                        for idx, item in enumerate(content_list):
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                full_text += text
                                logger.debug(f"[Stream Line {line_count}] Item {idx}: text = {text}")
                        
                        if not full_text:
                            continue
                        if last_full_text != full_text:
                            logger.debug(f"[Stream Line {line_count}] Content reset detected, yielding {full_text}")
                            yield full_text

                        last_full_text += full_text
                    else:
                        # 收到沒有 timestamp 的訊息，視為結尾，停止串流
                        logger.debug(f"[Stream Line {line_count}] Received assistant message without timestamp, ending stream")

                elif event_type == "system":
                    subtype = data.get("subtype")
                    if subtype == "init":
                        model = data.get("model", "unknown")
                        logger.debug(f"[Stream Line {line_count}] System init, model={model}")
                    else:
                        logger.debug(f"[Stream Line {line_count}] System event subtype={subtype}")
                elif event_type == "thinking":
                    # Handle thinking messages - extract and stream thinking content
                    yield "."
                elif event_type == "tool_call":
                    subtype = data.get("subtype")
                    call_id = data.get("call_id")
                    tool_call = data.get("tool_call", {})
                    logger.debug(f"[Stream Line {line_count}] Tool call event subtype={subtype}, call_id={call_id}, keys={list(tool_call.keys())}")
                    
                    # Format and yield tool call information
                    if subtype == "started":
                        tool_count += 1
                        # Remember the mapping from call_id to tool_number
                        if call_id:
                            call_id_to_tool_number[call_id] = tool_count
                        tool_info = format_tool_call_start(tool_call, tool_count)
                        if tool_info:
                            yield tool_info
                    elif subtype == "completed":
                        # Look up the tool_number for this call_id
                        tool_number = call_id_to_tool_number.get(call_id) if call_id else None
                        tool_result = format_tool_call_result(tool_call, tool_number)
                        if tool_result:
                            yield tool_result
                elif event_type == "result":
                    duration_ms = data.get("duration_ms")
                    logger.debug(f"[Stream Line {line_count}] Result event duration_ms={duration_ms}, ending stream")
                    break
                else:
                    logger.debug(f"[Stream Line {line_count}] Skipping unknown message type={event_type}")

                last_type = event_type

            except json.JSONDecodeError as e:
                # 如果不是 JSON，可能是舊版本的輸出或錯誤訊息
                logger.warning(f"[Stream Line {line_count}] Failed to decode JSON: {e}, line: {line_str[:100]}")
                yield line_str
            
        logger.debug(f"Stream finished after {line_count} lines")
        await process.wait()
        
        if process.returncode != 0:
            stderr = await process.stderr.read()
            logger.error(f"Stream command failed with code {process.returncode}: {stderr.decode()}")
            raise RuntimeError(f"CLI execution failed (code {process.returncode}): {stderr.decode()}")