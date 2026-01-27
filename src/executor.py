"""
Executor for running CLI commands.
"""
import asyncio
import json
from typing import List, Optional

from loguru import logger
from src.tool_formatters import format_tool_call_start, format_tool_call_result


class Executor:
    """Responsible for executing CLI commands"""
    
    async def run_non_stream(self, cmd: List[str], cwd: Optional[str] = None, timeout: float = 300) -> str:
        """Execute command, monitor stdout, return immediately upon receiving valid JSON result"""
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
            # Read stdout chunk by chunk
            while True:
                chunk = await process.stdout.read(4096)
                if not chunk:
                    # stdout closed
                    break
                stdout_buffer += chunk
                
                # Try parsing JSON - if successful, output is complete
                try:
                    data = json.loads(stdout_buffer.decode())
                    # Successfully parsed JSON, can return immediately
                    logger.debug("Received valid JSON output, returning immediately")
                    return data.get("result", "")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # JSON is incomplete or UTF-8 characters are truncated, continue reading
                    continue
            # If no valid JSON received, return raw output
            return stdout_buffer.decode(errors='replace').strip()
        
        try:
            result = await asyncio.wait_for(read_until_json(), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Process timed out after {timeout}s, terminating...")
            raise RuntimeError(f"CLI execution timed out after {timeout}s")
        finally:
            # Cleanup: if process is still running, terminate it
            if process.returncode is None:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()

    async def run_stream(self, cmd: List[str], cwd: Optional[str] = None):
        """Execute command and stream stdout"""
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
                
                # Only process deltas of assistant type
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
                        # Received message without timestamp, treat as end, stop streaming
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
                # If not JSON, might be old version output or error message
                logger.warning(f"[Stream Line {line_count}] Failed to decode JSON: {e}, line: {line_str[:100]}")
                yield line_str
            
        logger.debug(f"Stream finished after {line_count} lines")
        await process.wait()
        
        if process.returncode != 0:
            stderr = await process.stderr.read()
            logger.error(f"Stream command failed with code {process.returncode}: {stderr.decode()}")
            raise RuntimeError(f"CLI execution failed (code {process.returncode}): {stderr.decode()}")
