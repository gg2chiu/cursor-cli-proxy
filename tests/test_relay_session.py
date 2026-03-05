from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from conftest import make_popen_mock
from src.main import app, session_manager, config
import json
import os
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def disable_think_block():
    original_value = config.ENABLE_INFO_IN_THINK
    config.ENABLE_INFO_IN_THINK = False
    yield
    config.ENABLE_INFO_IN_THINK = original_value

@pytest.fixture(autouse=True)
def clean_storage():
    session_manager.storage_path = "test_sessions.json"
    session_manager.lock_path = "test_sessions.json.lock"
    # We don't re-init lock object but it uses path string? 
    # FileLock(path) stores path. So we must update lock object.
    from filelock import FileLock
    session_manager.lock = FileLock(session_manager.lock_path)
    session_manager._ensure_storage_exists()
    
    yield
    
    if os.path.exists("test_sessions.json"):
        os.remove("test_sessions.json")
    if os.path.exists("test_sessions.json.lock"):
        os.remove("test_sessions.json.lock")

@patch("src.session_manager.subprocess.Popen")
@patch("src.executor.asyncio.create_subprocess_exec")
def test_session_flow_branching(mock_exec, mock_popen):
    # Mock create-chat
    mock_popen.return_value = make_popen_mock("session-1")
    
    # Mock executor (relay)
    mock_process = AsyncMock()
    mock_process.stdout.read.return_value = b'{"result": "Answer1"}' # Not used in run_non_stream but good to have
    mock_process.communicate.return_value = (b'{"result": "Answer1"}', b"")
    mock_process.returncode = 0
    mock_exec.return_value = mock_process
    
    # 1. New Chat
    req1 = {
        "model": "auto",
        "messages": [{"role": "user", "content": "Hi"}]
    }
    resp1 = client.post("/v1/chat/completions", json=req1, headers={"Authorization": "Bearer test"})
    assert resp1.status_code == 200
    assert resp1.json()["choices"][0]["message"]["content"] == "Answer1"
    
    # Verify session-1 created (mock_popen called)
    mock_popen.assert_called_once()
    
    # 2. Continue Chat (Resume)
    # History: User: Hi, Assistant: Answer1
    # New: User: How are you?
    mock_process.communicate.return_value = (b'{"result": "Answer2"}', b"")
    
    req2 = {
        "model": "auto",
        "messages": [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Answer1"},
            {"role": "user", "content": "How are you?"}
        ]
    }
    resp2 = client.post("/v1/chat/completions", json=req2, headers={"Authorization": "Bearer test"})
    assert resp2.status_code == 200
    # Verify no new session created (mock_popen still 1 call)
    assert mock_popen.call_count == 1
    
    # 3. Branching Chat (Fork)
    # Modify history: User: Hello (instead of Hi)
    # New: User: How are you?
    # This simulates a different conversation path
    mock_popen.return_value = make_popen_mock("session-2")
    mock_process.communicate.return_value = (b'{"result": "Answer3"}', b"")
    
    req3 = {
        "model": "auto",
        "messages": [
            {"role": "user", "content": "Hello"}, # Changed
            {"role": "assistant", "content": "Answer1"},
            {"role": "user", "content": "How are you?"}
        ]
    }
    resp3 = client.post("/v1/chat/completions", json=req3, headers={"Authorization": "Bearer test"})
    assert resp3.status_code == 200
    
    # Verify new session created (mock_popen call count 2)
    assert mock_popen.call_count == 2
