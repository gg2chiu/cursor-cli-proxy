import asyncio
import json
import os
import re
from typing import List, Optional, Tuple
from loguru import logger
from src.config import config
from src.models import Message
from src.tool_formatters import format_tool_call_start, format_tool_call_result
from src.slash_command_loader import SlashCommandLoader


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
            cleaned_content = msg.content
            
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

    def _merge_messages(self) -> str:
        """合併所有對話內容成一個 Prompt，並展開 slash 指令"""
        merged = []
        has_assistant = any(msg.role == "assistant" for msg in self.messages)
        for idx, msg in enumerate(self.messages):
            content = msg.content
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