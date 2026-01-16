import pytest
from unittest.mock import AsyncMock, patch
from src.relay import Executor

@pytest.mark.asyncio
async def test_run_stream_mcp_tool_call_rejected():
    """Test MCP tool calls in stream mode, including rejected tool calls"""
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    # Simulate MCP tool calls as seen in cursor-agent with --approve-mcps
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","apiKeySource":"login","cwd":"/tmp","session_id":"test-session-123","model":"Auto","permissionMode":"default"}\n',
        b'{"type":"user","message":{"role":"user","content":[{"type":"text","text":"code-review https://example.com/pr/123"}]},"session_id":"test-session-123"}\n',
        # First MCP tool call: get_pull_request (started)
        b'{"type":"tool_call","subtype":"started","call_id":"toolu_test_001","tool_call":{"mcpToolCall":{"args":{"name":"bitbucket_R1-get_pull_request","args":{"project":"TEST","repository":"repo","prId":123},"toolCallId":"toolu_test_001","providerIdentifier":"bitbucket_R1","toolName":"get_pull_request"}}},"model_call_id":"model-call-001","session_id":"test-session-123","timestamp_ms":1768455554784}\n',
        # First MCP tool call: get_pull_request (completed - rejected)
        b'{"type":"tool_call","subtype":"completed","call_id":"toolu_test_001","tool_call":{"mcpToolCall":{"result":{"rejected":{"reason":"MCP tool execution rejected by user: bitbucket_R1-get_pull_request ","isReadonly":false}}}},"model_call_id":"model-call-001","session_id":"test-session-123","timestamp_ms":1768455554931}\n',
        # Second MCP tool call: get_diff (started)
        b'{"type":"tool_call","subtype":"started","call_id":"toolu_test_002","tool_call":{"mcpToolCall":{"args":{"name":"bitbucket_R1-get_diff","args":{"project":"TEST","repository":"repo","prId":123},"toolCallId":"toolu_test_002","providerIdentifier":"bitbucket_R1","toolName":"get_diff"}}},"model_call_id":"model-call-001","session_id":"test-session-123","timestamp_ms":1768455555236}\n',
        # Second MCP tool call: get_diff (completed - rejected)
        b'{"type":"tool_call","subtype":"completed","call_id":"toolu_test_002","tool_call":{"mcpToolCall":{"result":{"rejected":{"reason":"MCP tool execution rejected by user: bitbucket_R1-get_diff ","isReadonly":false}}}},"model_call_id":"model-call-001","session_id":"test-session-123","timestamp_ms":1768455555382}\n',
        # Assistant response after tool calls were rejected
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"User rejected"}]},"session_id":"test-session-123","timestamp_ms":1768455560000}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" tool"}]},"session_id":"test-session-123","timestamp_ms":1768455560100}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" access."}]},"session_id":"test-session-123","timestamp_ms":1768455560200}\n',
        # Final result
        b'{"type":"result","subtype":"success","duration_ms":9921,"duration_api_ms":9921,"is_error":false,"result":"User rejected tool access.","session_id":"test-session-123","request_id":"test-request-001"}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
        
        # Tool call events should now output formatted info, followed by assistant messages
        expected = [
            "\n",
            "\n",
            "\n",
            "🔌 Tool #1: MCP bitbucket_R1-bitbucket_R1-get_pull_request\n ",
            "🔌 Tool #1: Rejected: MCP tool execution rejected by user: bitbucket_R1-get_pull_request \n ",
            "🔌 Tool #2: MCP bitbucket_R1-bitbucket_R1-get_diff\n ",
            "🔌 Tool #2: Rejected: MCP tool execution rejected by user: bitbucket_R1-get_diff \n ",
            "\n",
            "User rejected",
            " tool",
            " access.",
            "\n"
        ]
        assert chunks == expected

@pytest.mark.asyncio
async def test_run_stream_read_write_tool_calls():
    """Test readToolCall and writeToolCall in stream mode"""
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"claude-3.5-sonnet"}\n',
        # Read tool call
        b'{"type":"tool_call","subtype":"started","call_id":"read_001","tool_call":{"readToolCall":{"args":{"path":"src/main.py"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"read_001","tool_call":{"readToolCall":{"result":{"success":{"totalLines":223,"content":"..."}}}}}\n',
        # Write tool call
        b'{"type":"tool_call","subtype":"started","call_id":"write_001","tool_call":{"writeToolCall":{"args":{"path":"test.txt"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"write_001","tool_call":{"writeToolCall":{"result":{"success":{"linesCreated":10,"fileSize":256}}}}}\n',
        # Assistant response
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done!"}]},"timestamp_ms":123}\n',
        b'{"type":"result","duration_ms":1000}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
        
        expected = [
            "\n",
            "\n",
            "📖 Tool #1: Reading src/main.py\n ",
            "📖 Tool #1: Read 223 lines\n ",
            "🖊️ Tool #2: Creating test.txt\n ",
            "🖊️ Tool #2: Created 10 lines (256 bytes)\n ",
            "\n",
            "Done!",
            "\n"
        ]
        assert chunks == expected

@pytest.mark.asyncio
async def test_run_stream_tool_call_errors():
    """Test tool call error handling in stream mode"""
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"claude-3.5-sonnet"}\n',
        # Read tool call with error
        b'{"type":"tool_call","subtype":"started","call_id":"read_001","tool_call":{"readToolCall":{"args":{"path":"nonexistent.txt"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"read_001","tool_call":{"readToolCall":{"result":{"error":{"message":"File not found"}}}}}\n',
        # Write tool call with error
        b'{"type":"tool_call","subtype":"started","call_id":"write_001","tool_call":{"writeToolCall":{"args":{"path":"/root/test.txt"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"write_001","tool_call":{"writeToolCall":{"result":{"error":{"message":"Permission denied"}}}}}\n',
        # Assistant response
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Encountered errors"}]},"timestamp_ms":123}\n',
        b'{"type":"result","duration_ms":1000}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
        
        expected = [
            "\n",
            "\n",
            "📖 Tool #1: Reading nonexistent.txt\n ",
            "📖 Tool #1: Error: File not found\n ",
            "🖊️ Tool #2: Creating /root/test.txt\n ",
            "🖊️ Tool #2: Error: Permission denied\n ",
            "\n",
            "Encountered errors",
            "\n"
        ]
        assert chunks == expected

@pytest.mark.asyncio
async def test_run_stream_generic_tool_calls():
    """Test generic/unknown tool call types in stream mode"""
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"claude-3.5-sonnet"}\n',
        # Unknown tool call with name in args
        b'{"type":"tool_call","subtype":"started","call_id":"custom_001","tool_call":{"executeToolCall":{"args":{"name":"deploy_script","target":"production"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"custom_001","tool_call":{"executeToolCall":{"result":{"success":{"status":"deployed"}}}}}\n',
        # Unknown tool call with path in args
        b'{"type":"tool_call","subtype":"started","call_id":"custom_002","tool_call":{"analyzeToolCall":{"args":{"path":"src/main.py"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"custom_002","tool_call":{"analyzeToolCall":{"result":{"error":{"message":"Analysis failed"}}}}}\n',
        # Unknown tool call with no common args
        b'{"type":"tool_call","subtype":"started","call_id":"custom_003","tool_call":{"customCall":{"args":{"data":"test"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"custom_003","tool_call":{"customCall":{"result":{"rejected":{"reason":"User cancelled"}}}}}\n',
        # Assistant response
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Tools executed"}]},"timestamp_ms":123}\n',
        b'{"type":"result","duration_ms":1000}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
        
        expected = [
            "\n",
            "\n",
            '🔨 Tool #1: executeToolCall \n ',
            "🔨 Tool #1: Completed\n ",
            '🔨 Tool #2: analyzeToolCall \n ',
            "🔨 Tool #2: Error: Analysis failed\n ",
            '🔨 Tool #3: customCall \n ',
            "🔨 Tool #3: Rejected: User cancelled\n ",
            "\n",
            "Tools executed",
            "\n"
        ]
        assert chunks == expected

@pytest.mark.asyncio
async def test_run_stream_arbitrary_tool_names():
    """Test tool calls with arbitrary names (no ToolCall/Call suffix)"""
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"claude-3.5-sonnet"}\n',
        # Tool with no suffix
        b'{"type":"tool_call","subtype":"started","call_id":"t1","tool_call":{"someCustomTool":{"args":{"input":"data","value":123}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"t1","tool_call":{"someCustomTool":{"result":{"success":{"output":"ok"}}}}}\n',
        # Tool with empty args
        b'{"type":"tool_call","subtype":"started","call_id":"t2","tool_call":{"anotherTool":{"args":{}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"t2","tool_call":{"anotherTool":{"result":{"error":{"message":"Failed"}}}}}\n',
        # Assistant response
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Complete"}]},"timestamp_ms":123}\n',
        b'{"type":"result","duration_ms":1000}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
        
        expected = [
            "\n",
            "\n",
            '🔨 Tool #1: someCustomTool \n ',
            "🔨 Tool #1: Completed\n ",
            '🔨 Tool #2: anotherTool \n ',
            "🔨 Tool #2: Error: Failed\n ",
            "\n",
            "Complete",
            "\n"
        ]
        assert chunks == expected

@pytest.mark.asyncio
async def test_run_stream_interleaved_tool_calls():
    """Test tool calls that are interleaved (two starts, then two completions)"""
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"claude-3.5-sonnet"}\n',
        # First tool starts
        b'{"type":"tool_call","subtype":"started","call_id":"call_001","tool_call":{"readToolCall":{"args":{"path":"file1.txt"}}}}\n',
        # Second tool starts (before first completes)
        b'{"type":"tool_call","subtype":"started","call_id":"call_002","tool_call":{"readToolCall":{"args":{"path":"file2.txt"}}}}\n',
        # First tool completes
        b'{"type":"tool_call","subtype":"completed","call_id":"call_001","tool_call":{"readToolCall":{"result":{"success":{"totalLines":100}}}}}\n',
        # Second tool completes
        b'{"type":"tool_call","subtype":"completed","call_id":"call_002","tool_call":{"readToolCall":{"result":{"success":{"totalLines":200}}}}}\n',
        # Assistant response
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Read both files"}]},"timestamp_ms":123}\n',
        b'{"type":"result","duration_ms":1000}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
        
        expected = [
            "\n",
            "\n",
            "📖 Tool #1: Reading file1.txt\n ",
            "📖 Tool #2: Reading file2.txt\n ",
            "📖 Tool #1: Read 100 lines\n ",  # Note: Tool #1 completes first
            "📖 Tool #2: Read 200 lines\n ",  # Then Tool #2 completes
            "\n",
            "Read both files",
            "\n"
        ]
        assert chunks == expected
