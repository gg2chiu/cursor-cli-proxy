from typing import Optional
from loguru import logger


def format_tool_call_start(tool_call: dict, tool_count: int) -> Optional[str]:
    """Format tool call start information for output"""
    logger.debug(f"Tool call: {tool_call}")
    # Handle writeToolCall
    if "writeToolCall" in tool_call:
        args = tool_call["writeToolCall"].get("args", {})
        path = args.get("path", "unknown")
        return f"🖊️ Tool #{tool_count}: Creating {path}\n "
    
    # Handle readToolCall
    elif "readToolCall" in tool_call:
        args = tool_call["readToolCall"].get("args", {})
        path = args.get("path", "unknown")
        offset = args.get("offset")
        limit = args.get("limit")
        if offset or limit:
            return f"📖 Tool #{tool_count}: Reading {path} (offset={offset}, limit={limit})\n "
        return f"📖 Tool #{tool_count}: Reading {path}\n "
    
    # Handle grepToolCall
    elif "grepToolCall" in tool_call:
        args = tool_call["grepToolCall"].get("args", {})
        pattern = args.get("pattern", "")
        path = args.get("path", "unknown")
        # Truncate pattern if too long
        if len(pattern) > 50:
            pattern = pattern[:47] + "..."
        return f"🔍 Tool #{tool_count}: Grep '{pattern}' in {path}\n "
    
    # Handle shellToolCall
    elif "shellToolCall" in tool_call:
        args = tool_call["shellToolCall"].get("args", {})
        command = args.get("command", "")
        # Truncate command if too long
        if len(command) > 60:
            command = command[:57] + "..."
        return f"💻 Tool #{tool_count}: Shell `{command}`\n "
    
    # Handle mcpToolCall
    elif "mcpToolCall" in tool_call:
        mcp_args = tool_call["mcpToolCall"].get("args", {})
        tool_name = mcp_args.get("name", "unknown")
        provider = mcp_args.get("providerIdentifier", "unknown")
        return f"🔌 Tool #{tool_count}: MCP {provider}-{tool_name}\n "
    
    # Handle other/unknown tool calls
    else:
        # Process any tool call by using the first key
        if tool_call:
            key = next(iter(tool_call.keys()))
            args = tool_call[key].get("args", {})
            return f"🔨 Tool #{tool_count}: {key} \n "
    
    return None


def format_tool_call_result(tool_call: dict, tool_number: Optional[int] = None) -> Optional[str]:
    """Format tool call result information for output"""
    tool_prefix = f"Tool #{tool_number}: " if tool_number else ""
    
    # Handle writeToolCall result
    if "writeToolCall" in tool_call:
        result = tool_call["writeToolCall"].get("result", {})
        if "success" in result:
            success = result["success"]
            lines = success.get("linesCreated", 0)
            size = success.get("fileSize", 0)
            return f"🖊️ {tool_prefix}Created {lines} lines ({size} bytes)\n "
        elif "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            return f"🖊️ {tool_prefix}Error: {error_msg}\n "
    
    # Handle readToolCall result
    elif "readToolCall" in tool_call:
        result = tool_call["readToolCall"].get("result", {})
        if "success" in result:
            success = result["success"]
            total_lines = success.get("totalLines", 0)
            lines_read = success.get("linesRead", 0)
            if lines_read and lines_read != total_lines:
                return f"📖 {tool_prefix}Read {lines_read}/{total_lines} lines\n "
            return f"📖 {tool_prefix}Read {total_lines} lines\n "
        elif "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            return f"📖 {tool_prefix}Error: {error_msg}\n "
    
    # Handle grepToolCall result
    elif "grepToolCall" in tool_call:
        result = tool_call["grepToolCall"].get("result", {})
        if "success" in result:
            success = result["success"]
            match_count = success.get("matchCount", 0)
            line_count = success.get("lineCount", 0)
            return f"🔍 {tool_prefix}Found {match_count} matches in {line_count} lines\n "
        elif "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            return f"🔍 {tool_prefix}Error: {error_msg}\n "
    
    # Handle shellToolCall result
    elif "shellToolCall" in tool_call:
        result = tool_call["shellToolCall"].get("result", {})
        if "success" in result:
            success = result["success"]
            exit_code = success.get("exitCode", 0)
            if exit_code == 0:
                return f"💻 {tool_prefix}Command completed (exit code: {exit_code})\n "
            else:
                return f"💻 {tool_prefix}Command failed (exit code: {exit_code})\n "
        elif "error" in result:
            error_msg = result["error"].get("message", "Unknown error")
            return f"💻 {tool_prefix}Error: {error_msg}\n "
    
    # Handle mcpToolCall result
    elif "mcpToolCall" in tool_call:
        result = tool_call["mcpToolCall"].get("result", {})
        if "rejected" in result:
            reason = result["rejected"].get("reason", "Unknown reason")
            return f"🔌 {tool_prefix}Rejected: {reason}\n "
        elif "success" in result:
            return f"🔌 {tool_prefix}Completed\n "
        elif "error" in result:
            error_msg = result.get("error", {}).get("message", "Unknown error")
            return f"🔌 {tool_prefix}Error: {error_msg}\n "
    
    # Handle other/unknown tool calls
    else:
        # Process any tool call by using the first key
        if tool_call:
            key = next(iter(tool_call.keys()))
            result = tool_call[key].get("result", {})
            if "rejected" in result:
                reason = result["rejected"].get("reason", "Unknown reason")
                return f"🔨 {tool_prefix}Rejected: {reason}\n "
            elif "success" in result:
                return f"🔨 {tool_prefix}Completed\n "
            elif "error" in result:
                error_msg = result["error"].get("message", "Unknown error")
                return f"🔨 {tool_prefix}Error: {error_msg}\n "
    
    return None
