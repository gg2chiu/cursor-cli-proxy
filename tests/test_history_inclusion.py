from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from src.main import app, session_manager
import json
import os
import pytest

client = TestClient(app)

@pytest.fixture(autouse=True)
def clean_storage():
    session_manager.storage_path = "test_sessions_history.json"
    session_manager.lock_path = "test_sessions_history.json.lock"
    from filelock import FileLock
    session_manager.lock = FileLock(session_manager.lock_path)
    session_manager._ensure_storage_exists()
    
    yield
    
    if os.path.exists("test_sessions_history.json"):
        os.remove("test_sessions_history.json")
    if os.path.exists("test_sessions_history.json.lock"):
        os.remove("test_sessions_history.json.lock")

@patch("src.session_manager.subprocess.check_output")
@patch("src.relay.asyncio.create_subprocess_exec")
def test_new_session_includes_full_history(mock_exec, mock_check_output):
    # Mock create-chat to return a specific session ID
    mock_check_output.return_value = "new-session-id\n"
    
    # Mock executor (relay)
    mock_process = AsyncMock()
    mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "History Received"}', b""])
    mock_process.returncode = 0
    mock_exec.return_value = mock_process
    
    # Provide a request with history that we haven't seen before
    req = {
        "model": "auto",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."}, 
            {"role": "user", "content": "Question 1"},
            {"role": "assistant", "content": "Answer 1"},
            {"role": "user", "content": "Question 2"}
        ]
    }
    
    resp = client.post("/v1/chat/completions", json=req, headers={"Authorization": "Bearer test"})
    
    assert resp.status_code == 200
    
    # Check what was passed to create_subprocess_exec
    # It should contain the full history formatted in the prompt
    args, kwargs = mock_exec.call_args
    cmd = args
    
    # Find the prompt in the command list (it's the last element)
    prompt = cmd[-1]
    
    assert "SYSTEM: You are a helpful assistant." in prompt
    assert "USER: Question 1" in prompt
    assert "ASSISTANT: Answer 1" in prompt
    assert "USER: Question 2" in prompt
    
    # Verify it also has --resume with the new session ID
    assert "--resume" in cmd
    assert "new-session-id" in cmd

@patch("src.session_manager.subprocess.check_output")
@patch("src.relay.asyncio.create_subprocess_exec")
def test_resume_session_includes_only_last_message(mock_exec, mock_check_output):
    # 1. Create a session first
    mock_check_output.return_value = "existing-session-id\n"
    mock_process = AsyncMock()
    mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Response 1"}', b""])
    mock_process.returncode = 0
    mock_exec.return_value = mock_process
    
    history_messages = [
        {"role": "system", "content": "Sys"},
        {"role": "user", "content": "Q1"}
    ]
    
    # Initial request to set up session
    client.post("/v1/chat/completions", json= {
        "model": "auto",
        "messages": history_messages
    }, headers={"Authorization": "Bearer test"})
    
    # Reset mocks for the actual test turn
    mock_exec.reset_mock()
    
    # Set up the mock for the second call
    mock_process2 = AsyncMock()
    mock_process2.stdout.read = AsyncMock(side_effect=[b'{"result": "Response 2"}', b""])
    mock_process2.returncode = 0
    mock_exec.return_value = mock_process2
    
    # 2. Continue the session
    # The history hash should match the one we just updated
    # After first response, hash is calculated from: [Sys, Q1, Response 1]
    req2 = {
        "model": "auto",
        "messages": [
            {"role": "system", "content": "Sys"},
            {"role": "user", "content": "Q1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Q2"}
        ]
    }
    
    client.post("/v1/chat/completions", json=req2, headers={"Authorization": "Bearer test"})
    
    # Verify only Q2 was sent
    args, kwargs = mock_exec.call_args
    cmd = args
    prompt = cmd[-1]
    
    assert "Q2" in prompt
    assert "USER:" not in prompt
    assert "Sys" not in prompt
    assert "Q1" not in prompt
    assert "Response 1" not in prompt
    
    # Verify --resume existing-session-id was used
    assert "--resume" in cmd
    assert "existing-session-id" in cmd
