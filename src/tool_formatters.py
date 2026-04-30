from typing import Callable, Optional

from loguru import logger


SUFFIX = "\n "


def _truncate(s: str, n: int) -> str:
    if len(s) > n:
        return s[: n - 3] + "..."
    return s


def _subagent_label(subagent_type: dict) -> str:
    if not isinstance(subagent_type, dict) or not subagent_type:
        return "unknown"
    return next(iter(subagent_type.keys()))


def _start_update_todos(call: dict, n: int) -> str:
    args = call.get("args", {})
    todos = args.get("todos", []) or []
    merge = args.get("merge", False)
    return f"📝 Tool #{n}: Updating {len(todos)} todos (merge={merge}){SUFFIX}"


def _start_shell(call: dict, n: int) -> str:
    args = call.get("args", {})
    command = _truncate(args.get("command", ""), 60)
    return f"💻 Tool #{n}: Shell `{command}`{SUFFIX}"


def _start_edit(call: dict, n: int) -> str:
    args = call.get("args", {})
    path = args.get("path", "unknown")
    return f"🖊️ Tool #{n}: Writing {path}{SUFFIX}"


def _start_read(call: dict, n: int) -> str:
    args = call.get("args", {})
    path = args.get("path", "unknown")
    offset = args.get("offset")
    limit = args.get("limit")
    if offset or limit:
        return f"📖 Tool #{n}: Reading {path} (offset={offset}, limit={limit}){SUFFIX}"
    return f"📖 Tool #{n}: Reading {path}{SUFFIX}"


def _start_grep(call: dict, n: int) -> str:
    args = call.get("args", {})
    pattern = _truncate(args.get("pattern", ""), 50)
    path = args.get("path", "unknown")
    return f"🔍 Tool #{n}: Grep '{pattern}' in {path}{SUFFIX}"


def _start_glob(call: dict, n: int) -> str:
    args = call.get("args", {})
    pattern = args.get("globPattern", "")
    target = args.get("targetDirectory", "")
    return f"🗂️ Tool #{n}: Glob '{pattern}' in {target}{SUFFIX}"


def _start_delete(call: dict, n: int) -> str:
    args = call.get("args", {})
    path = args.get("path", "unknown")
    return f"🗑️ Tool #{n}: Delete {path}{SUFFIX}"


def _start_web_search(call: dict, n: int) -> str:
    args = call.get("args", {})
    term = _truncate(args.get("searchTerm", ""), 80)
    return f"🌐 Tool #{n}: WebSearch '{term}'{SUFFIX}"


def _start_web_fetch(call: dict, n: int) -> str:
    args = call.get("args", {})
    url = args.get("url", "")
    return f"🌐 Tool #{n}: WebFetch {url}{SUFFIX}"


def _start_task(call: dict, n: int) -> str:
    args = call.get("args", {})
    description = _truncate(args.get("description", ""), 80)
    label = _subagent_label(args.get("subagentType", {}))
    return f"🤖 Tool #{n}: Task[{label}] {description}{SUFFIX}"


def _mcp_label(args: dict) -> str:
    """Render an MCP tool as ``MCP[provider] tool_name``.

    The ``name`` field as emitted by cursor-agent often already contains the
    provider as a prefix (e.g. ``chrome-devtools-list_pages`` for provider
    ``chrome-devtools``). Strip that redundant prefix so the label stays
    readable instead of producing ``chrome-devtools-chrome-devtools-...``.
    """
    if not args:
        return "MCP"
    tool_name = args.get("name", "unknown")
    provider = args.get("providerIdentifier", "unknown")
    if provider and provider != "unknown":
        for sep in ("-", "_", "."):
            prefix = f"{provider}{sep}"
            if tool_name.startswith(prefix):
                tool_name = tool_name[len(prefix):]
                break
    return f"MCP[{provider}] {tool_name}"


def _start_mcp(call: dict, n: int) -> str:
    args = call.get("args", {})
    return f"🔌 Tool #{n}: {_mcp_label(args)}{SUFFIX}"


_START_FORMATTERS: dict[str, Callable[[dict, int], str]] = {
    "updateTodosToolCall": _start_update_todos,
    "shellToolCall": _start_shell,
    "editToolCall": _start_edit,
    "readToolCall": _start_read,
    "grepToolCall": _start_grep,
    "globToolCall": _start_glob,
    "deleteToolCall": _start_delete,
    "webSearchToolCall": _start_web_search,
    "webFetchToolCall": _start_web_fetch,
    "taskToolCall": _start_task,
    "mcpToolCall": _start_mcp,
}


def format_tool_call_start(tool_call: dict, tool_count: int) -> Optional[str]:
    """Format tool call start information for output"""
    logger.debug(f"Tool call: {tool_call}")
    if not tool_call:
        return None

    key = next(iter(tool_call.keys()))
    call = tool_call.get(key, {}) or {}

    formatter = _START_FORMATTERS.get(key)
    if formatter is not None:
        return formatter(call, tool_count)

    return f"🔨 Tool #{tool_count}: {key}{SUFFIX}"


def _result_update_todos(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        success = result["success"]
        todos = success.get("todos", []) or []
        total = success.get("totalCount", len(todos))
        completed = sum(1 for t in todos if t.get("status") == "TODO_STATUS_COMPLETED")
        in_progress = sum(1 for t in todos if t.get("status") == "TODO_STATUS_IN_PROGRESS")
        return f"📝 {prefix}Todos {completed}/{total} done ({in_progress} in progress){SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"📝 {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_shell(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        exit_code = result["success"].get("exitCode", 0)
        verb = "completed" if exit_code == 0 else "failed"
        return f"💻 {prefix}Command {verb} (exit code: {exit_code}){SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"💻 {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_edit(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        success = result["success"]
        path = success.get("path", "unknown")
        added = success.get("linesAdded", 0)
        removed = success.get("linesRemoved", 0)
        verb = "Edited" if "beforeFullFileContent" in success else "Created"
        return f"🖊️ {prefix}{verb} {path} (+{added}/-{removed} lines){SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🖊️ {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_read(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        success = result["success"]
        total_lines = success.get("totalLines", 0)
        file_size = success.get("fileSize")
        read_range = success.get("readRange") or {}
        start = read_range.get("startLine")
        end = read_range.get("endLine")
        size_suffix = f" ({file_size} bytes)" if file_size else ""

        if start is not None and end is not None and (start != 1 or end != total_lines):
            return f"📖 {prefix}Read lines {start}-{end} of {total_lines}{size_suffix}{SUFFIX}"
        return f"📖 {prefix}Read {total_lines} lines{size_suffix}{SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"📖 {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_grep(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        success = result["success"]
        workspace_results = success.get("workspaceResults", {}) or {}
        match_files = 0
        total_matches = 0
        for ws in workspace_results.values():
            content = (ws or {}).get("content", {}) or {}
            matches = content.get("matches", []) or []
            match_files += len(matches)
            total_matches += content.get("totalMatchedLines", 0)
        return f"🔍 {prefix}Found {total_matches} matches in {match_files} files{SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🔍 {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_glob(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        total = result["success"].get("totalFiles", 0)
        return f"🗂️ {prefix}Found {total} files{SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🗂️ {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_delete(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        success = result["success"]
        path = success.get("deletedFile") or success.get("path", "unknown")
        size = success.get("fileSize", 0)
        return f"🗑️ {prefix}Deleted {path} ({size} bytes){SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🗑️ {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_web_search(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        refs = result["success"].get("references", []) or []
        return f"🌐 {prefix}WebSearch returned {len(refs)} references{SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🌐 {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_web_fetch(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        markdown = result["success"].get("markdown", "") or ""
        return f"🌐 {prefix}WebFetch fetched {len(markdown)} chars{SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🌐 {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_task(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    if "success" in result:
        success = result["success"]
        steps = success.get("conversationSteps", []) or []
        duration = success.get("durationMs", "?")
        return f"🤖 {prefix}Task completed ({len(steps)} steps, {duration}ms){SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🤖 {prefix}Error: {msg}{SUFFIX}"
    return None


def _result_mcp(call: dict, prefix: str) -> Optional[str]:
    result = call.get("result", {})
    label = _mcp_label(call.get("args", {}))
    if "rejected" in result:
        reason = result["rejected"].get("reason", "Unknown reason")
        return f"🔌 {prefix}{label} rejected: {reason}{SUFFIX}"
    if "success" in result:
        return f"🔌 {prefix}{label} completed{SUFFIX}"
    if "error" in result:
        msg = result.get("error", {}).get("message", "Unknown error")
        return f"🔌 {prefix}{label} error: {msg}{SUFFIX}"
    return None


_RESULT_FORMATTERS: dict[str, Callable[[dict, str], Optional[str]]] = {
    "updateTodosToolCall": _result_update_todos,
    "shellToolCall": _result_shell,
    "editToolCall": _result_edit,
    "readToolCall": _result_read,
    "grepToolCall": _result_grep,
    "globToolCall": _result_glob,
    "deleteToolCall": _result_delete,
    "webSearchToolCall": _result_web_search,
    "webFetchToolCall": _result_web_fetch,
    "taskToolCall": _result_task,
    "mcpToolCall": _result_mcp,
}


def format_tool_call_result(tool_call: dict, tool_number: Optional[int] = None) -> Optional[str]:
    """Format tool call result information for output"""
    if not tool_call:
        return None

    prefix = f"Tool #{tool_number}: " if tool_number else ""
    key = next(iter(tool_call.keys()))
    call = tool_call.get(key, {}) or {}

    formatter = _RESULT_FORMATTERS.get(key)
    if formatter is not None:
        formatted = formatter(call, prefix)
        if formatted is not None:
            return formatted

    result = call.get("result", {})
    if "rejected" in result:
        reason = result["rejected"].get("reason", "Unknown reason")
        return f"🔨 {prefix}Rejected: {reason}{SUFFIX}"
    if "success" in result:
        return f"🔨 {prefix}Completed{SUFFIX}"
    if "error" in result:
        msg = result["error"].get("message", "Unknown error")
        return f"🔨 {prefix}Error: {msg}{SUFFIX}"

    return None
