"""Unit tests for src/tool_formatters.py.

Fixtures are inlined snippets distilled from test/output/run.jsonl,
which is a real cursor-agent stream-json transcript.
"""
from src.tool_formatters import format_tool_call_start, format_tool_call_result


def test_update_todos_start_formats_count_and_merge():
    tool_call = {
        "updateTodosToolCall": {
            "args": {
                "todos": [{"id": str(i)} for i in range(11)],
                "merge": False,
            }
        }
    }
    assert format_tool_call_start(tool_call, 1) == "📝 Tool #1: Updating 11 todos (merge=False)\n "


def test_update_todos_completed_tally():
    tool_call = {
        "updateTodosToolCall": {
            "args": {"todos": [], "merge": True},
            "result": {
                "success": {
                    "todos": [
                        {"status": "TODO_STATUS_COMPLETED"},
                        {"status": "TODO_STATUS_COMPLETED"},
                        {"status": "TODO_STATUS_IN_PROGRESS"},
                        {"status": "TODO_STATUS_PENDING"},
                    ],
                    "totalCount": 4,
                    "wasMerge": True,
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 1) == "📝 Tool #1: Todos 2/4 done (1 in progress)\n "


def test_shell_start_truncates_long_command():
    tool_call = {
        "shellToolCall": {
            "args": {"command": "mkdir -p /tmp/tv && echo done"}
        }
    }
    assert format_tool_call_start(tool_call, 2) == "💻 Tool #2: Shell `mkdir -p /tmp/tv && echo done`\n "


def test_shell_completed_success():
    tool_call = {
        "shellToolCall": {
            "args": {"command": "echo done"},
            "result": {
                "success": {
                    "command": "echo done",
                    "exitCode": 0,
                    "stdout": "done\n",
                    "stderr": "",
                    "executionTime": 527,
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 2) == "💻 Tool #2: Command completed (exit code: 0)\n "


def test_edit_start_neutral_verb():
    tool_call = {
        "editToolCall": {
            "args": {"path": "/tmp/tv/a.txt", "streamContent": "hello"}
        }
    }
    assert format_tool_call_start(tool_call, 3) == "🖊️ Tool #3: Writing /tmp/tv/a.txt\n "


def test_edit_completed_create_no_before_content():
    tool_call = {
        "editToolCall": {
            "args": {"path": "/tmp/tv/a.txt", "streamContent": "hello"},
            "result": {
                "success": {
                    "path": "/tmp/tv/a.txt",
                    "linesAdded": 1,
                    "linesRemoved": 1,
                    "diffString": "--- /dev/null\n+++ b//tmp/tv/a.txt\n@@ -1 +1 @@\n-\n+hello",
                    "afterFullFileContent": "hello",
                    "message": "Wrote contents to /tmp/tv/a.txt",
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 3) == "🖊️ Tool #3: Created /tmp/tv/a.txt (+1/-1 lines)\n "


def test_edit_completed_edit_with_before_content():
    tool_call = {
        "editToolCall": {
            "args": {"path": "/tmp/tv/a.txt", "streamContent": "HELLO"},
            "result": {
                "success": {
                    "path": "/tmp/tv/a.txt",
                    "linesAdded": 1,
                    "linesRemoved": 1,
                    "beforeFullFileContent": "hello",
                    "afterFullFileContent": "HELLO",
                    "message": "The file /tmp/tv/a.txt has been updated.",
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 3) == "🖊️ Tool #3: Edited /tmp/tv/a.txt (+1/-1 lines)\n "


def test_read_start_no_offset():
    tool_call = {"readToolCall": {"args": {"path": "/tmp/tv/a.txt"}}}
    assert format_tool_call_start(tool_call, 4) == "📖 Tool #4: Reading /tmp/tv/a.txt\n "


def test_read_completed_full_file():
    tool_call = {
        "readToolCall": {
            "args": {"path": "/tmp/tv/a.txt"},
            "result": {
                "success": {
                    "content": "hello",
                    "isEmpty": False,
                    "exceededLimit": False,
                    "totalLines": 1,
                    "fileSize": 5,
                    "path": "/tmp/tv/a.txt",
                    "readRange": {"startLine": 1, "endLine": 1},
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 4) == "📖 Tool #4: Read 1 lines (5 bytes)\n "


def test_read_completed_partial_range():
    tool_call = {
        "readToolCall": {
            "args": {"path": "/tmp/file.py"},
            "result": {
                "success": {
                    "totalLines": 200,
                    "fileSize": 5000,
                    "path": "/tmp/file.py",
                    "readRange": {"startLine": 10, "endLine": 60},
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 4) == "📖 Tool #4: Read lines 10-60 of 200 (5000 bytes)\n "


def test_glob_start():
    tool_call = {
        "globToolCall": {
            "args": {"targetDirectory": "/tmp/tv", "globPattern": "*.txt"}
        }
    }
    assert format_tool_call_start(tool_call, 5) == "🗂️ Tool #5: Glob '*.txt' in /tmp/tv\n "


def test_glob_completed():
    tool_call = {
        "globToolCall": {
            "args": {"targetDirectory": "/tmp/tv", "globPattern": "*.txt"},
            "result": {
                "success": {
                    "pattern": "",
                    "path": "/tmp/tv",
                    "files": ["a.txt"],
                    "totalFiles": 1,
                    "clientTruncated": False,
                    "ripgrepTruncated": False,
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 5) == "🗂️ Tool #5: Found 1 files\n "


def test_grep_start():
    tool_call = {
        "grepToolCall": {
            "args": {"pattern": "HELLO", "path": "/tmp/tv"}
        }
    }
    assert format_tool_call_start(tool_call, 6) == "🔍 Tool #6: Grep 'HELLO' in /tmp/tv\n "


def test_grep_completed_workspace_results():
    tool_call = {
        "grepToolCall": {
            "args": {"pattern": "HELLO", "path": "/tmp/tv"},
            "result": {
                "success": {
                    "pattern": "HELLO",
                    "path": "/tmp/tv",
                    "outputMode": "content",
                    "workspaceResults": {
                        "/home/gchiu/workspace/cursor-cli-proxy": {
                            "content": {
                                "matches": [
                                    {
                                        "file": "../../../../tmp/tv/a.txt",
                                        "matches": [
                                            {"lineNumber": 1, "content": "HELLO"}
                                        ],
                                    }
                                ],
                                "totalLines": 1,
                                "totalMatchedLines": 1,
                            }
                        }
                    },
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 6) == "🔍 Tool #6: Found 1 matches in 1 files\n "


def test_delete_start():
    tool_call = {"deleteToolCall": {"args": {"path": "/tmp/tv/a.txt"}}}
    assert format_tool_call_start(tool_call, 7) == "🗑️ Tool #7: Delete /tmp/tv/a.txt\n "


def test_delete_completed():
    tool_call = {
        "deleteToolCall": {
            "args": {"path": "/tmp/tv/a.txt"},
            "result": {
                "success": {
                    "path": "/tmp/tv/a.txt",
                    "deletedFile": "/tmp/tv/a.txt",
                    "fileSize": "5",
                    "prevContent": "HELLO",
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 7) == "🗑️ Tool #7: Deleted /tmp/tv/a.txt (5 bytes)\n "


def test_websearch_start():
    tool_call = {
        "webSearchToolCall": {
            "args": {"searchTerm": "FastAPI latest version 2026"}
        }
    }
    assert format_tool_call_start(tool_call, 8) == "🌐 Tool #8: WebSearch 'FastAPI latest version 2026'\n "


def test_websearch_completed():
    tool_call = {
        "webSearchToolCall": {
            "args": {"searchTerm": "FastAPI latest version 2026"},
            "result": {
                "success": {
                    "references": [
                        {"title": "Web search results", "url": "", "chunk": "..."}
                    ]
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 8) == "🌐 Tool #8: WebSearch returned 1 references\n "


def test_webfetch_start():
    tool_call = {
        "webFetchToolCall": {
            "args": {"url": "https://example.com"}
        }
    }
    assert format_tool_call_start(tool_call, 9) == "🌐 Tool #9: WebFetch https://example.com\n "


def test_webfetch_completed():
    tool_call = {
        "webFetchToolCall": {
            "args": {"url": "https://example.com"},
            "result": {
                "success": {
                    "url": "https://example.com",
                    "markdown": "Example Domain\n\n# Example Domain\n\nThis domain is for use in documentation examples without needing permission.",
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 9) == "🌐 Tool #9: WebFetch fetched 110 chars\n "


def test_task_start_general_purpose():
    tool_call = {
        "taskToolCall": {
            "args": {
                "description": "Report current git branch",
                "prompt": "Run git branch ...",
                "subagentType": {"unspecified": {}},
            }
        }
    }
    assert format_tool_call_start(tool_call, 10) == "🤖 Tool #10: Task[unspecified] Report current git branch\n "


def test_task_start_cursor_guide():
    tool_call = {
        "taskToolCall": {
            "args": {
                "description": "Cursor CLI statusline configuration",
                "subagentType": {"cursorGuide": {}},
            }
        }
    }
    assert format_tool_call_start(tool_call, 11) == "🤖 Tool #11: Task[cursorGuide] Cursor CLI statusline configuration\n "


def test_task_completed():
    tool_call = {
        "taskToolCall": {
            "args": {
                "description": "Report current git branch",
                "subagentType": {"unspecified": {}},
            },
            "result": {
                "success": {
                    "conversationSteps": [{"toolCall": {}}, {"assistantMessage": {}}],
                    "agentId": "abc",
                    "isBackground": False,
                    "durationMs": "3105",
                }
            },
        }
    }
    assert format_tool_call_result(tool_call, 10) == "🤖 Tool #10: Task completed (2 steps, 3105ms)\n "


def test_unknown_tool_falls_back_to_generic_start():
    tool_call = {"someNewToolCall": {"args": {}}}
    assert format_tool_call_start(tool_call, 12) == "🔨 Tool #12: someNewToolCall\n "


def test_unknown_tool_falls_back_to_generic_result():
    tool_call = {"someNewToolCall": {"args": {}, "result": {"success": {}}}}
    assert format_tool_call_result(tool_call, 12) == "🔨 Tool #12: Completed\n "


def test_mcp_start_strips_duplicate_provider_prefix():
    tool_call = {
        "mcpToolCall": {
            "args": {
                "name": "chrome-devtools-list_pages",
                "providerIdentifier": "chrome-devtools",
            }
        }
    }
    assert format_tool_call_start(tool_call, 1) == "🔌 Tool #1: MCP[chrome-devtools] list_pages\n "


def test_mcp_start_keeps_name_when_no_prefix():
    tool_call = {
        "mcpToolCall": {
            "args": {
                "name": "get_pull_request",
                "providerIdentifier": "bitbucket_R1",
            }
        }
    }
    assert format_tool_call_start(tool_call, 1) == "🔌 Tool #1: MCP[bitbucket_R1] get_pull_request\n "


def test_mcp_result_completed_includes_tool_label():
    tool_call = {
        "mcpToolCall": {
            "args": {
                "name": "chrome-devtools-navigate_page",
                "providerIdentifier": "chrome-devtools",
            },
            "result": {"success": {}},
        }
    }
    assert format_tool_call_result(tool_call, 2) == "🔌 Tool #2: MCP[chrome-devtools] navigate_page completed\n "


def test_mcp_result_rejected_includes_tool_label():
    tool_call = {
        "mcpToolCall": {
            "args": {
                "name": "chrome-devtools-take_screenshot",
                "providerIdentifier": "chrome-devtools",
            },
            "result": {"rejected": {"reason": "denied by user"}},
        }
    }
    assert format_tool_call_result(tool_call, 3) == "🔌 Tool #3: MCP[chrome-devtools] take_screenshot rejected: denied by user\n "


def test_mcp_result_rejected_without_args_falls_back():
    tool_call = {
        "mcpToolCall": {
            "result": {"rejected": {"reason": "denied by user"}}
        }
    }
    assert format_tool_call_result(tool_call, 1) == "🔌 Tool #1: MCP rejected: denied by user\n "
