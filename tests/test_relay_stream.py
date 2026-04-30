import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.config import config
from src.relay import Executor

@pytest.fixture(autouse=True)
def enable_stream_output(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_THINKING_OUTPUT", True)
    monkeypatch.setattr(config, "ENABLE_TOOL_CALL_OUTPUT", True)

@pytest.mark.asyncio
async def test_run_stream():
    executor = Executor()
    
    # Mock subprocess
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    # Simulate JSON lines from cursor-agent
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]},"timestamp_ms":123}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" World"}]},"timestamp_ms":124}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello World"}]}}\n' # Final one without timestamp should be ignored
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
            
        assert chunks == ["\n", "Hello", " World"]

@pytest.mark.asyncio
async def test_run_stream_cumulative_partials():
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    # Simulate cumulative partial output updates
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]},"timestamp_ms":123}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" World"}]},"timestamp_ms":124}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"!"}]},"timestamp_ms":125}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello World!"}]},"timestamp_ms":126}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
            
        assert chunks == ["\n", "Hello", " World", "!"]

@pytest.mark.asyncio
async def test_run_stream_thinking_delta_outputs_text():
    executor = Executor()

    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"Opus 4.7 1M Thinking"}\n',
        b'{"type":"thinking","subtype":"delta","text":" I","timestamp_ms":1777521856227}\n',
        b'{"type":"thinking","subtype":"delta","text":"\'m going to work through this verification step by step","timestamp_ms":1777521856396}\n',
        b'{"type":"thinking","subtype":"delta","text":" methodically.","timestamp_ms":1777521856464}\n',
        b'{"type":"thinking","subtype":"completed","timestamp_ms":1777521856477}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done"}]},"timestamp_ms":1777521857000}\n',
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)

        assert chunks == [
            "\n",
            "\n",
            " I",
            "'m going to work through this verification step by step",
            " methodically.",
            "\n",
            "Done",
        ]

@pytest.mark.asyncio
async def test_run_stream_skips_thinking_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_THINKING_OUTPUT", False, raising=False)
    executor = Executor()

    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"Opus 4.7 1M Thinking"}\n',
        b'{"type":"thinking","subtype":"delta","text":" hidden thinking","timestamp_ms":1777521856227}\n',
        b'{"type":"thinking","subtype":"completed","timestamp_ms":1777521856477}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Visible"}]},"timestamp_ms":1777521857000}\n',
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)

        assert chunks == ["\n", "\n", "\n", "Visible"]

@pytest.mark.asyncio
async def test_run_stream_with_tool_and_assistant_output():
    executor = Executor()
    
    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"gpt-5.2"}\n',
        b'{"type":"tool_call","subtype":"started","tool_call":{"readToolCall":{"args":{"path":"README.md"}}}}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]},"timestamp_ms":123}\n',
        b'{"type":"result","duration_ms":10}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Ignored"}]},"timestamp_ms":124}\n'
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
        
        # Now includes tool call info along with assistant messages
        assert chunks == ["\n", "\n", "📖 Tool #1: Reading README.md\n ", "\n", "Hello", "\n"]

@pytest.mark.asyncio
async def test_run_stream_skips_tool_calls_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "ENABLE_TOOL_CALL_OUTPUT", False, raising=False)
    executor = Executor()

    mock_process = AsyncMock()
    mock_process.stdout = AsyncMock()
    mock_process.stdout.__aiter__.return_value = [
        b'{"type":"system","subtype":"init","model":"gpt-5.2"}\n',
        b'{"type":"tool_call","subtype":"started","call_id":"read_001","tool_call":{"readToolCall":{"args":{"path":"README.md"}}}}\n',
        b'{"type":"tool_call","subtype":"completed","call_id":"read_001","tool_call":{"readToolCall":{"result":{"success":{"totalLines":10}}}}}\n',
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]},"timestamp_ms":123}\n',
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0

    with patch("asyncio.create_subprocess_exec", return_value=mock_process):
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)

        assert chunks == ["\n", "\n", "\n", "Hello"]
