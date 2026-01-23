import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from src.config import Settings
from src.main import app, session_manager
from src.relay import parse_session_id_tag, extract_workspace_from_messages
from src.models import Message
from fastapi.testclient import TestClient
from datetime import datetime, timezone


@pytest.fixture(autouse=True)
def clean_session_storage(tmp_path):
    storage = tmp_path / "test_sessions_session_id.json"
    session_manager.storage_path = str(storage)
    session_manager.lock_path = f"{storage}.lock"
    from filelock import FileLock
    session_manager.lock = FileLock(session_manager.lock_path)
    session_manager._ensure_storage_exists()
    yield
    if os.path.exists(session_manager.storage_path):
        os.remove(session_manager.storage_path)
    if os.path.exists(session_manager.lock_path):
        os.remove(session_manager.lock_path)


class TestParseSessionIdTag:
    """Tests for parse_session_id_tag function"""
    
    def test_parse_session_id_tag_found(self):
        content = "Hello <session_id>my-custom-session-123</session_id> world"
        session_id, cleaned = parse_session_id_tag(content)
        
        assert session_id == "my-custom-session-123"
        assert cleaned == "Hello  world"
    
    def test_parse_session_id_tag_not_found(self):
        content = "Hello world without any tag"
        session_id, cleaned = parse_session_id_tag(content)
        
        assert session_id is None
        assert cleaned == content
    
    def test_parse_session_id_tag_with_whitespace(self):
        content = "<session_id>  my-session-id  </session_id>"
        session_id, cleaned = parse_session_id_tag(content)
        
        assert session_id == "my-session-id"
        assert cleaned == ""
    
    def test_parse_session_id_tag_multiline(self):
        content = """System prompt here.
<session_id>test-session-abc</session_id>
More instructions."""
        session_id, cleaned = parse_session_id_tag(content)
        
        assert session_id == "test-session-abc"
        assert "System prompt here." in cleaned
        assert "More instructions." in cleaned
        assert "<session_id>" not in cleaned


class TestExtractSessionIdFromMessages:
    """Tests for session_id extraction from messages"""
    
    def test_extract_session_id_from_system_message(self):
        messages = [
            Message(role="system", content="<session_id>custom-session-id</session_id>\nYou are helpful"),
            Message(role="user", content="Hello")
        ]
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home"}, clear=False):
            settings = Settings(_env_file=None)
            with patch("src.relay.config", settings):
                workspace, session_id, cleaned = extract_workspace_from_messages(messages)
        
        assert session_id == "custom-session-id"
        assert workspace is None
        assert "<session_id>" not in cleaned[0].content
        assert "You are helpful" in cleaned[0].content
    
    def test_extract_both_workspace_and_session_id(self):
        messages = [
            Message(role="system", content="<workspace>/home/user/project</workspace><session_id>my-session</session_id>\nYou are helpful"),
            Message(role="user", content="Hello")
        ]
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/user"}, clear=False):
            settings = Settings(_env_file=None)
            with patch("src.relay.config", settings):
                workspace, session_id, cleaned = extract_workspace_from_messages(messages)
        
        assert workspace == "/home/user/project"
        assert session_id == "my-session"
        assert "<workspace>" not in cleaned[0].content
        assert "<session_id>" not in cleaned[0].content
        assert "You are helpful" in cleaned[0].content
    
    def test_extract_ignores_user_message_session_id(self):
        """Session_id tag in user message should be ignored"""
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="<session_id>user-session</session_id> Hello")
        ]
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home"}, clear=False):
            settings = Settings(_env_file=None)
            with patch("src.relay.config", settings):
                workspace, session_id, cleaned = extract_workspace_from_messages(messages)
        
        # Should not extract from user message
        assert session_id is None
        # User message content unchanged
        assert "<session_id>" in cleaned[1].content


class TestSessionIdPromptBehavior:
    """Tests for session_id behavior in chat completions"""

    @patch("src.relay.asyncio.create_subprocess_exec")
    def test_custom_session_id_sends_last_message_only(self, mock_exec):
        """When custom session_id is provided, only the last message should be sent"""
        client = TestClient(app)
        # Mock executor (relay)
        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Response"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        # Seed session storage with the custom session_id
        session_id = "my-custom-session"
        session_manager.save_session(
            "custom-session-hash",
            {
                "session_id": session_id,
                "title": "Custom Session",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "workspace_dir": "/tmp/custom-session-workspace"
            }
        )
        
        # Request with custom session_id in system prompt
        req = {
            "model": "auto",
            "messages": [
                {"role": "system", "content": "<session_id>my-custom-session</session_id>\nYou are a helpful assistant."},
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi there"},
                {"role": "user", "content": "How are you?"}
            ]
        }
        
        resp = client.post("/v1/chat/completions", json=req, headers={"Authorization": "Bearer test"})
        
        assert resp.status_code == 200
        
        # Check what was passed to create_subprocess_exec
        args, kwargs = mock_exec.call_args
        cmd = args
        
        # Find the prompt in the command list (it's the last element)
        prompt = cmd[-1]
        
        # Only the last message should be sent
        assert "How are you?" in prompt
        assert "Hello" not in prompt
        assert "Hi there" not in prompt
        assert "You are a helpful assistant" not in prompt
        
        # Verify it uses the custom session ID
        assert "--resume" in cmd
        assert "my-custom-session" in cmd

    @patch("src.relay.asyncio.create_subprocess_exec")
    def test_nonexistent_custom_session_id_keeps_system_prompt(self, mock_exec):
        """When custom session_id does not exist, system prompt should be kept"""
        client = TestClient(app)
        # Mock executor (relay)
        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Response"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        req = {
            "model": "auto",
            "messages": [
                {"role": "system", "content": "<session_id>missing-session</session_id>\nYou are a helpful assistant."},
                {"role": "user", "content": "Hello"}
            ]
        }
        
        resp = client.post("/v1/chat/completions", json=req, headers={"Authorization": "Bearer test"})
        
        assert resp.status_code == 200
        
        args, kwargs = mock_exec.call_args
        cmd = args
        prompt = cmd[-1]
        
        # System prompt should remain (no SYSTEM prefix if no assistant messages)
        assert "You are a helpful assistant." in prompt
        # Custom session_id should not be used
        assert "missing-session" not in cmd
