import pytest
import os
import json
from unittest.mock import patch, MagicMock
from src.session_manager import SessionManager
from src.models import Message

@pytest.fixture
def session_manager(tmp_path):
    storage = tmp_path / "sessions.json"
    workspace_base = tmp_path / "workspaces"
    return SessionManager(str(storage), workspace_base=str(workspace_base))

def test_calculate_history_hash(session_manager):
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="hi")
    ]
    h1 = session_manager.calculate_history_hash(messages)
    
    messages2 = [
        Message(role="system", content="sys"),
        Message(role="user", content="hi")
    ]
    h2 = session_manager.calculate_history_hash(messages2)
    
    assert h1 == h2
    
    messages3 = [
        Message(role="user", content="hi"),
        Message(role="system", content="sys")
    ]
    h3 = session_manager.calculate_history_hash(messages3)
    
    assert h1 != h3 # Order matters

def test_calculate_history_hash_strips_think_block(session_manager):
    messages_without_think = [
        Message(role="assistant", content="Hello there.")
    ]
    messages_with_think = [
        Message(role="assistant", content="<think>\nfoo: bar\n</think>\n\nHello there.")
    ]

    h1 = session_manager.calculate_history_hash(messages_without_think)
    h2 = session_manager.calculate_history_hash(messages_with_think)

    assert h1 == h2

@patch("subprocess.check_output")
def test_create_session(mock_subprocess, session_manager):
    mock_subprocess.return_value = "test-uuid-1234\n"
    
    history_hash = "some_hash"
    session_id = session_manager.create_session(history_hash, title="Test Chat")
    
    assert session_id == "test-uuid-1234"
    
    # Verify storage
    data = session_manager.load_sessions()
    assert history_hash in data["sessions"]
    s_data = data["sessions"][history_hash]
    assert s_data["session_id"] == "test-uuid-1234"
    assert s_data["title"] == "Test Chat"
    assert "workspace_dir" in s_data
    
    # Verify directory name contains session_id
    assert s_data["workspace_dir"].endswith("test-uuid-1234")
    
    # Verify directory creation
    assert os.path.exists(s_data["workspace_dir"])
    
    # Verify subprocess call (it used a temp dir during call)
    args, kwargs = mock_subprocess.call_args
    cmd = args[0]
    assert "--workspace" in cmd
    # The workspace passed to command was the temp one
    assert "temp_" in cmd[cmd.index("--workspace") + 1]
    assert "--sandbox" in cmd
    assert "enabled" in cmd
    
    mock_subprocess.assert_called_once()

def test_update_session_hash(session_manager):
    h1 = "hash1"
    session_data = {"session_id": "sid-1", "title": "t1", "created_at": "now", "updated_at": "now"}
    session_manager.save_session(h1, session_data)
    
    h2 = "hash2"
    session_manager.update_session_hash(old_hash=h1, new_hash=h2)
    
    # h1 should be gone
    assert session_manager.get_session_by_hash(h1) is None
    
    # h2 should exist
    s2 = session_manager.get_session_by_hash(h2)
    assert s2 is not None
    assert s2["session_id"] == "sid-1"
    assert s2["updated_at"] != "now" # Should be updated timestamp (or at least different string if we mock time, but here checking key presence)

def test_storage_failure(session_manager):
    # Simulate read-only filesystem or permission error
    with patch("builtins.open", side_effect=IOError("Permission denied")):
        with pytest.raises(RuntimeError) as excinfo:
            session_manager.save_session("h", {})
        assert "Storage error" in str(excinfo.value)

from filelock import Timeout
def test_lock_timeout(session_manager):
    # Simulate lock timeout
    # We need to mock the lock object's acquire method
    session_manager.lock.acquire = MagicMock(side_effect=Timeout("lock"))
    
    # Depending on implementation, it might raise Timeout or RuntimeError
    # Current implementation doesn't catch Timeout, so it raises Timeout
    with pytest.raises(RuntimeError) as excinfo:
        session_manager.load_sessions()
    assert "lock timeout" in str(excinfo.value)
