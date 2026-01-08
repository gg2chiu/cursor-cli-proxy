import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.relay import Executor

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
        b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"[FULL]"}]}}\n' # Final one without timestamp should be ignored
    ]
    mock_process.wait.return_value = 0
    mock_process.returncode = 0
    
    with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
        chunks = []
        async for chunk in executor.run_stream(["cmd"]):
            chunks.append(chunk)
            
        assert chunks == ["Hello", " World"]