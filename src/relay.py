import asyncio
import subprocess
import json
from typing import List, Optional
from loguru import logger
from src.config import config
from src.models import Message

class CommandBuilder:
    def __init__(self, model: str, api_key: str, messages: List[Message], session_id: Optional[str] = None, workspace_dir: Optional[str] = None):
        self.model = model
        self.api_key = api_key
        self.messages = messages
        self.session_id = session_id
        self.workspace_dir = workspace_dir

    def _merge_messages(self) -> str:
        """合併所有對話內容成一個 Prompt"""
        merged = []
        for msg in self.messages:
            role_label = msg.role.capitalize()
            merged.append(f"{role_label}: {msg.content}")
        return "\n".join(merged)

    def build(self, stream: bool = False) -> List[str]:
        prompt = self._merge_messages()
        
        cmd = [
            config.CURSOR_BIN,
            "--model", self.model,
            "--api-key", self.api_key,
            "--sandbox", "enabled",
            "--approve-mcps", "true",
            "-p",
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
    
    async def run_non_stream(self, cmd: List[str], cwd: Optional[str] = None) -> str:
        """執行指令並等待完成，回傳 stdout"""
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            raise RuntimeError(f"CLI execution failed (code {process.returncode}): {error_msg}")
            
        try:
            data = json.loads(stdout.decode())
            return data.get("result", "")
        except json.JSONDecodeError:
            # Fallback to raw stdout if not JSON
            return stdout.decode().strip()

    async def run_stream(self, cmd: List[str], cwd: Optional[str] = None):
        """執行指令並串流回傳 stdout"""
        logger.debug(f"Starting stream command: {cmd}")
        if cwd:
            logger.debug(f"Working directory: {cwd}")
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd
        )
        
        seen_content = {}  # Track seen content by message index to detect duplicates
        line_count = 0
        message_count = 0
        
        async for line in process.stdout:
            line_str = line.decode().strip()
            if not line_str:
                continue
            
            line_count += 1
            
            try:
                data = json.loads(line_str)
                logger.debug(f"[Stream Line {line_count}] Received JSON type: {data.get('type')}")
                
                # 只處理 assistant 類型的 delta
                if data.get("type") == "assistant":
                    if "timestamp_ms" in data:
                        content_list = data.get("message", {}).get("content", [])
                        logger.debug(f"[Stream Line {line_count}] Content list has {len(content_list)} items")
                        
                        # Accumulate all text content from this message
                        full_text = ""
                        for idx, item in enumerate(content_list):
                            if item.get("type") == "text":
                                text = item.get("text", "")
                                full_text += text
                                logger.debug(f"[Stream Line {line_count}] Item {idx}: text length = {len(text)}")
                        
                        # Create a unique key for this message content
                        content_key = full_text
                        
                        # Check if we've seen this exact content before
                        if content_key and content_key not in seen_content:
                            message_count += 1
                            seen_content[content_key] = message_count
                            logger.debug(f"[Stream Line {line_count}] New message #{message_count}, yielding {len(full_text)} bytes")
                            yield full_text
                        else:
                            logger.debug(f"[Stream Line {line_count}] Duplicate content detected, skipping (seen as message #{seen_content.get(content_key, 'unknown')})")
                    else:
                        # 收到沒有 timestamp 的訊息，視為結尾，停止串流
                        logger.debug(f"[Stream Line {line_count}] Received assistant message without timestamp, ending stream")
                        break
                else:
                    logger.debug(f"[Stream Line {line_count}] Skipping non-assistant message")
            except json.JSONDecodeError as e:
                # 如果不是 JSON，可能是舊版本的輸出或錯誤訊息
                logger.warning(f"[Stream Line {line_count}] Failed to decode JSON: {e}, line: {line_str[:100]}")
                yield line_str
            
        logger.debug(f"Stream finished after {line_count} lines, yielded {message_count} unique messages")
        await process.wait()
        
        if process.returncode != 0:
            stderr = await process.stderr.read()
            logger.error(f"Stream command failed with code {process.returncode}: {stderr.decode()}")
            raise RuntimeError(f"CLI execution failed (code {process.returncode}): {stderr.decode()}")