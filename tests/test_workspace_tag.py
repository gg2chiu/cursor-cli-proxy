import os
import pytest
from unittest.mock import patch, MagicMock
from src.config import Settings
from src.relay import parse_workspace_tag, validate_workspace_path, extract_workspace_from_messages
from src.models import Message
from src.session_manager import SessionManager


def build_settings():
    return Settings(_env_file=None)


class TestParseWorkspaceTag:
    """Tests for parse_workspace_tag function"""
    
    def test_parse_workspace_tag_found(self):
        content = "Hello <workspace>/home/user/project</workspace> world"
        path, cleaned = parse_workspace_tag(content)
        
        assert path == "/home/user/project"
        assert cleaned == "Hello  world"
    
    def test_parse_workspace_tag_not_found(self):
        content = "Hello world without any tag"
        path, cleaned = parse_workspace_tag(content)
        
        assert path is None
        assert cleaned == content
    
    def test_parse_workspace_tag_with_whitespace(self):
        content = "<workspace>  /home/user/project  </workspace>"
        path, cleaned = parse_workspace_tag(content)
        
        assert path == "/home/user/project"
        assert cleaned == ""
    
    def test_parse_workspace_tag_multiline(self):
        content = """System prompt here.
<workspace>/path/to/workspace</workspace>
More instructions."""
        path, cleaned = parse_workspace_tag(content)
        
        assert path == "/path/to/workspace"
        assert "System prompt here." in cleaned
        assert "More instructions." in cleaned
        assert "<workspace>" not in cleaned
    
    def test_parse_workspace_tag_only_first_match(self):
        content = "<workspace>/first/path</workspace> and <workspace>/second/path</workspace>"
        path, cleaned = parse_workspace_tag(content)
        
        # Should get first match
        assert path == "/first/path"
        # Should remove all matches
        assert "<workspace>" not in cleaned


class TestValidateWorkspacePath:
    """Tests for validate_workspace_path function"""
    
    def test_validate_none_path(self):
        assert validate_workspace_path(None) is None
    
    def test_validate_empty_path(self):
        assert validate_workspace_path("") is None
    
    def test_validate_relative_path_rejected(self):
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/user"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                result = validate_workspace_path("relative/path")
                assert result is None
    
    def test_validate_empty_whitelist(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = build_settings()
            with patch("src.relay.config", settings):
                result = validate_workspace_path("/some/path")
                assert result is None
    
    def test_validate_path_in_whitelist_exact(self):
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/user/project"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                result = validate_workspace_path("/home/user/project")
                assert result == "/home/user/project"
    
    def test_validate_path_in_whitelist_subdirectory(self):
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/user"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                result = validate_workspace_path("/home/user/project/subdir")
                assert result == "/home/user/project/subdir"
    
    def test_validate_path_not_in_whitelist(self):
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/allowed"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                result = validate_workspace_path("/home/notallowed/project")
                assert result is None
    
    def test_validate_multiple_whitelist_entries(self):
        with patch.dict(
            os.environ,
            {
                "WORKSPACE_WHITELIST_1": "/home/user1",
                "WORKSPACE_WHITELIST_2": "/home/user2",
                "WORKSPACE_WHITELIST_3": "/opt/projects",
            },
            clear=False,
        ):
            settings = build_settings()
            with patch("src.relay.config", settings):
                # First entry
                assert validate_workspace_path("/home/user1/proj") == "/home/user1/proj"
                # Second entry
                assert validate_workspace_path("/home/user2") == "/home/user2"
                # Third entry
                assert validate_workspace_path("/opt/projects/app") == "/opt/projects/app"
                # Not in list
                assert validate_workspace_path("/home/user3") is None


class TestExtractWorkspaceFromMessages:
    """Tests for extract_workspace_from_messages function"""
    
    def test_extract_empty_messages(self):
        workspace, session_id, messages = extract_workspace_from_messages([])
        assert workspace is None
        assert session_id is None
        assert messages == []
    
    def test_extract_no_workspace_tag(self):
        messages = [
            Message(role="system", content="You are a helpful assistant"),
            Message(role="user", content="Hello")
        ]
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                workspace, session_id, cleaned = extract_workspace_from_messages(messages)
        
        assert workspace is None
        assert session_id is None
        assert len(cleaned) == 2
        assert cleaned[0].content == "You are a helpful assistant"
    
    def test_extract_workspace_from_system_message(self):
        messages = [
            Message(role="system", content="<workspace>/home/user/project</workspace>\nYou are helpful"),
            Message(role="user", content="Hello")
        ]
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/user"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                workspace, session_id, cleaned = extract_workspace_from_messages(messages)
        
        assert workspace == "/home/user/project"
        assert session_id is None
        assert "<workspace>" not in cleaned[0].content
        assert "You are helpful" in cleaned[0].content
    
    def test_extract_ignores_user_message_workspace(self):
        """Workspace tag in user message should be ignored"""
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="<workspace>/home/user/project</workspace> Hello")
        ]
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/user"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                workspace, session_id, cleaned = extract_workspace_from_messages(messages)
        
        # Should not extract from user message
        assert workspace is None
        assert session_id is None
        # User message content unchanged
        assert "<workspace>" in cleaned[1].content
    
    def test_extract_invalid_workspace_returns_none(self):
        """Invalid workspace (not in whitelist) should return None"""
        messages = [
            Message(role="system", content="<workspace>/not/allowed</workspace>\nYou are helpful"),
            Message(role="user", content="Hello")
        ]
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/allowed"}, clear=False):
            settings = build_settings()
            with patch("src.relay.config", settings):
                workspace, session_id, cleaned = extract_workspace_from_messages(messages)
        
        # Should not validate
        assert workspace is None
        assert session_id is None
        # Content should still be cleaned
        assert "<workspace>" not in cleaned[0].content


class TestConfigWorkspaceWhitelist:
    """Tests for config WORKSPACE_WHITELIST_*"""
    
    def test_whitelist_not_set(self):
        with patch.dict(os.environ, {}, clear=True):
            settings = build_settings()
            assert settings.get_workspace_whitelist() == []
    
    def test_whitelist_single_path(self):
        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": "/home/user/projects"}, clear=False):
            settings = build_settings()
            assert settings.get_workspace_whitelist() == ["/home/user/projects"]
    
    def test_whitelist_multiple_paths(self):
        with patch.dict(
            os.environ,
            {
                "WORKSPACE_WHITELIST_1": "/path1",
                "WORKSPACE_WHITELIST_2": "/path2",
                "WORKSPACE_WHITELIST_3": "/path3",
            },
            clear=False,
        ):
            settings = build_settings()
            assert settings.get_workspace_whitelist() == ["/path1", "/path2", "/path3"]
    
    def test_whitelist_strips_whitespace(self):
        with patch.dict(
            os.environ,
            {
                "WORKSPACE_WHITELIST_1": " /path1 ",
                "WORKSPACE_WHITELIST_2": " /path2 ",
                "WORKSPACE_WHITELIST_3": " /path3 ",
            },
            clear=False,
        ):
            settings = build_settings()
            assert settings.get_workspace_whitelist() == ["/path1", "/path2", "/path3"]
    
    def test_whitelist_ignores_empty_entries(self):
        with patch.dict(
            os.environ,
            {
                "WORKSPACE_WHITELIST_1": "/path1",
                "WORKSPACE_WHITELIST_2": "",
                "WORKSPACE_WHITELIST_3": "/path2",
            },
            clear=False,
        ):
            settings = build_settings()
            assert settings.get_workspace_whitelist() == ["/path1", "/path2"]


class TestSessionManagerCustomWorkspace:
    """Tests for SessionManager with custom workspace"""
    
    @pytest.fixture
    def session_manager(self, tmp_path):
        storage = tmp_path / "sessions.json"
        workspace_base = tmp_path / "workspaces"
        return SessionManager(str(storage), workspace_base=str(workspace_base))
    
    @patch("subprocess.check_output")
    def test_create_session_with_custom_workspace(self, mock_subprocess, session_manager, tmp_path):
        mock_subprocess.return_value = "test-uuid-custom\n"
        
        custom_ws = tmp_path / "custom_workspace"
        history_hash = "custom_hash"
        session_id = session_manager.create_session(
            history_hash, 
            title="Custom WS Session",
            custom_workspace=str(custom_ws)
        )
        
        assert session_id == "test-uuid-custom"
        
        # Verify storage
        data = session_manager.load_sessions()
        assert history_hash in data["sessions"]
        s_data = data["sessions"][history_hash]
        
        # Workspace should be the custom one, not renamed
        assert str(custom_ws) in s_data["workspace_dir"]
        
        # Verify directory creation
        assert os.path.exists(s_data["workspace_dir"])
        
        # Verify subprocess call used custom workspace
        args, kwargs = mock_subprocess.call_args
        cmd = args[0]
        ws_index = cmd.index("--workspace")
        assert str(custom_ws) in cmd[ws_index + 1]
    
    @patch("subprocess.check_output")
    def test_create_session_without_custom_workspace(self, mock_subprocess, session_manager, tmp_path):
        mock_subprocess.return_value = "test-uuid-default\n"
        
        history_hash = "default_hash"
        session_id = session_manager.create_session(
            history_hash, 
            title="Default WS Session"
        )
        
        assert session_id == "test-uuid-default"
        
        # Verify storage
        data = session_manager.load_sessions()
        s_data = data["sessions"][history_hash]
        
        # Workspace should be renamed to session_id folder
        assert s_data["workspace_dir"].endswith("test-uuid-default")
