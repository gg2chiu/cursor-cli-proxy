import asyncio
import subprocess
import json
import os
import re
from pathlib import Path
from typing import List, Optional, Dict
from loguru import logger
from src.config import config
from src.models import Message

class SlashCommandLoader:
    """載入和展開 .cursor/commands 和 .claude/commands 中的自定義 slash 指令"""
    
    def __init__(self, workspace_dir: Optional[str] = None):
        self.workspace_dir = workspace_dir or os.getcwd()
        self.commands: Dict[str, str] = {}
        self._load_commands()
    
    def _load_commands(self):
        """按優先順序載入指令：team < workspace-claude < workspace-cursor < user-claude < user-cursor"""
        # 優先順序從低到高
        search_paths = [
            # Workspace commands (lower priority)
            Path(self.workspace_dir) / ".claude" / "commands",
            Path(self.workspace_dir) / ".cursor" / "commands",
            # User commands (higher priority, override workspace)
            Path.home() / ".claude" / "commands",
            Path.home() / ".cursor" / "commands",
        ]
        
        for commands_dir in search_paths:
            if commands_dir.exists() and commands_dir.is_dir():
                self._load_from_directory(commands_dir)
    
    def _load_from_directory(self, directory: Path):
        """從指定目錄載入所有 .md 檔案作為指令"""
        try:
            for md_file in directory.glob("*.md"):
                command_id = md_file.stem  # 檔名（不含 .md）
                try:
                    content = md_file.read_text(encoding="utf-8").strip()
                    if content:
                        self.commands[command_id] = content
                        logger.debug(f"Loaded slash command: /{command_id} from {md_file}")
                except Exception as e:
                    logger.warning(f"Failed to load command from {md_file}: {e}")
        except Exception as e:
            logger.warning(f"Failed to read commands directory {directory}: {e}")
    
    def expand_slash_command(self, text: str) -> str:
        """
        展開 slash 指令。如果文字以 /command 開頭，嘗試替換為指令內容。
        支援參數替換：$ARGUMENTS, $1, $2, ...
        """
        text = text.strip()
        if not text.startswith("/"):
            return text
        
        # 匹配 /command 或 /command args...
        match = re.match(r'^/(\S+)(?:\s+(.*))?$', text, re.DOTALL)
        if not match:
            return text
        
        command_id = match.group(1)
        args_text = match.group(2) or ""
        
        # 檢查是否為已知的自定義指令
        if command_id not in self.commands:
            logger.debug(f"Slash command /{command_id} not found in custom commands, passing through")
            return text
        
        template = self.commands[command_id]
        logger.info(f"Expanding slash command: /{command_id}")
        
        # 解析參數（以空白分隔）
        args_list = args_text.split() if args_text else []
        
        # 替換 $ARGUMENTS
        result = template.replace("$ARGUMENTS", args_text)
        
        # 替換 $1, $2, ... (從大到小替換，避免 $10 被當成 $1 + 0)
        for i in range(len(args_list), 0, -1):
            result = result.replace(f"${i}", args_list[i - 1])
        
        # 如果模板沒有 placeholder 但有參數，附加參數到內容後面
        has_placeholders = "$ARGUMENTS" in template or any(f"${i}" in template for i in range(1, len(args_list) + 1))
        if not has_placeholders and args_text:
            result = f"{result}\n\n{args_text}"
        
        logger.debug(f"Expanded /{command_id} to {len(result)} characters")
        return result

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
        
        cmd = [
            config.CURSOR_BIN,
            "--model", self.model,
            "--api-key", self.api_key,
            "--sandbox", "enabled",
            "--approve-mcps",
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