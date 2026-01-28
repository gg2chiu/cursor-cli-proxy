"""
Tests for the <think> block that contains session_id and slash_commands
at the beginning of the first response message.

Note: These tests require ENABLE_INFO_IN_THINK=True to function.
"""
import pytest
import json
import os
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock, MagicMock
from src.main import app, session_manager, config
from src.relay import SlashCommandLoader

client = TestClient(app)


@pytest.fixture(autouse=True)
def enable_think_block():
    """Enable think block feature for all tests in this file"""
    original_value = config.ENABLE_INFO_IN_THINK
    config.ENABLE_INFO_IN_THINK = True
    yield
    config.ENABLE_INFO_IN_THINK = original_value


@pytest.fixture(autouse=True)
def clean_storage(tmp_path):
    """Use temporary storage for each test"""
    storage_file = tmp_path / "test_sessions_think.json"
    lock_file = tmp_path / "test_sessions_think.json.lock"
    
    session_manager.storage_path = str(storage_file)
    session_manager.lock_path = str(lock_file)
    from filelock import FileLock
    session_manager.lock = FileLock(session_manager.lock_path)
    session_manager._ensure_storage_exists()
    
    yield


class TestThinkBlockNonStreaming:
    """Tests for <think> block in non-streaming responses"""
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_think_block_contains_session_id(self, mock_exec, mock_check_output):
        """Test that the response contains <think> block with session_id"""
        mock_check_output.return_value = "test-session-123\n"
        
        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Hello"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        
        # Verify <think> block is present at the beginning
        assert content.startswith("<think>")
        assert "</think>" in content
        
        # Verify session_id is in the think block
        assert "Session ID: test-session-123" in content
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_think_block_contains_slash_commands(self, mock_exec, mock_check_output):
        """Test that the response contains <think> block with loaded slash commands"""
        mock_check_output.return_value = "test-session-456\n"
        
        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Hello"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        # Mock SlashCommandLoader to return specific commands
        with patch.object(SlashCommandLoader, '__init__', lambda self, workspace_dir=None: setattr(self, 'commands', {"review": "Review code", "test": "Run tests", "deploy": "Deploy app"}) or setattr(self, 'workspace_dir', workspace_dir)):
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": "Bearer test"}
            )
        
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        
        # Verify slash_commands is in the think block
        assert "Slash Commands:" in content
        assert "/review" in content
        assert "/test" in content
        assert "/deploy" in content
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_think_block_shows_none_when_no_slash_commands(self, mock_exec, mock_check_output):
        """Test that the response shows (none) when no slash commands are loaded"""
        mock_check_output.return_value = "test-session-789\n"
        
        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Hello"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        # Mock SlashCommandLoader to return empty commands
        with patch.object(SlashCommandLoader, '__init__', lambda self, workspace_dir=None: setattr(self, 'commands', {}) or setattr(self, 'workspace_dir', workspace_dir)):
            resp = client.post(
                "/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": "Bearer test"}
            )
        
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        
        # When no commands loaded, should show (none)
        assert "Slash Commands: (none)" in content
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_actual_response_follows_think_block(self, mock_exec, mock_check_output):
        """Test that the actual response content follows the <think> block"""
        mock_check_output.return_value = "test-session-abc\n"
        
        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "This is the actual response"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        
        # Verify structure: <think>...</think>\n\n[actual response]
        think_end = content.find("</think>")
        assert think_end > 0
        
        after_think = content[think_end + len("</think>"):]
        assert "This is the actual response" in after_think


class TestThinkBlockStreaming:
    """Tests for <think> block in streaming responses"""
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_think_block_is_last_chunk_in_stream(self, mock_exec, mock_check_output):
        """Test that <think> block is sent as the last chunk in streaming response"""
        mock_check_output.return_value = "stream-session-123\n"
        
        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]},"timestamp_ms":123}\n',
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" World"}]},"timestamp_ms":124}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp.status_code == 200
        
        # Collect all chunks
        chunks = []
        for line in resp.iter_lines():
            if line and line.startswith("data: ") and line != "data: [DONE]":
                chunk_data = json.loads(line[6:])
                if "choices" in chunk_data and chunk_data["choices"]:
                    delta = chunk_data["choices"][0].get("delta", {})
                    if "content" in delta:
                        chunks.append(delta["content"])
        
        # Last chunk should contain the <think> block
        assert len(chunks) > 0
        last_chunk = chunks[-1]
        assert "<think>" in last_chunk
        assert "Session ID: stream-session-123" in last_chunk
        assert "</think>" in last_chunk
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_subsequent_chunks_do_not_contain_think_block(self, mock_exec, mock_check_output):
        """Test that subsequent chunks do not contain <think> block"""
        mock_check_output.return_value = "stream-session-456\n"
        
        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"First"}]},"timestamp_ms":123}\n',
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" Second"}]},"timestamp_ms":124}\n',
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" Third"}]},"timestamp_ms":125}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp.status_code == 200
        
        # Collect all chunks
        chunks = []
        for line in resp.iter_lines():
            if line and line.startswith("data: ") and line != "data: [DONE]":
                chunk_data = json.loads(line[6:])
                if "choices" in chunk_data and chunk_data["choices"]:
                    delta = chunk_data["choices"][0].get("delta", {})
                    if "content" in delta:
                        chunks.append(delta["content"])
        
        assert len(chunks) > 0
        
        # Last chunk has <think>
        assert "<think>" in chunks[-1]
        
        # All previous chunks should NOT have <think>
        for chunk in chunks[:-1]:
            assert "<think>" not in chunk
            assert "</think>" not in chunk


class TestThinkBlockOnlyFirstMessage:
    """Tests to verify <think> block only appears in first assistant message (new session only)"""
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_new_session_has_think_block(self, mock_exec, mock_check_output):
        """Test that new session has <think> block at the start"""
        mock_check_output.return_value = "session-first\n"
        mock_process1 = AsyncMock()
        mock_process1.stdout.read = AsyncMock(side_effect=[b'{"result": "Response 1"}', b""])
        mock_process1.returncode = 0
        mock_exec.return_value = mock_process1
        
        resp1 = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "first question"}]},
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp1.status_code == 200
        content1 = resp1.json()["choices"][0]["message"]["content"]
        assert content1.startswith("<think>")
        assert "Session ID: session-first" in content1
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_resumed_session_no_think_block(self, mock_exec, mock_check_output):
        """Test that resumed session (is_session_hit=True) does NOT have <think> block"""
        # First request - create new session
        mock_check_output.return_value = "session-resume-test\n"
        mock_process1 = AsyncMock()
        mock_process1.stdout.read = AsyncMock(side_effect=[b'{"result": "Response 1"}', b""])
        mock_process1.returncode = 0
        mock_exec.return_value = mock_process1
        
        resp1 = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "first question"}]},
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp1.status_code == 200
        content1 = resp1.json()["choices"][0]["message"]["content"]
        # First response should have think block
        assert "<think>" in content1
        
        # Second request (continuing conversation - session hit)
        mock_exec.reset_mock()
        mock_process2 = AsyncMock()
        mock_process2.stdout.read = AsyncMock(side_effect=[b'{"result": "Response 2"}', b""])
        mock_process2.returncode = 0
        mock_exec.return_value = mock_process2
        
        # Remove the think block from content1 for the assistant message in history
        clean_content1 = content1.split("</think>\n\n", 1)[-1] if "</think>" in content1 else content1
        
        resp2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [
                    {"role": "user", "content": "first question"},
                    {"role": "assistant", "content": clean_content1},
                    {"role": "user", "content": "second question"}
                ]
            },
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp2.status_code == 200
        content2 = resp2.json()["choices"][0]["message"]["content"]
        
        # Second response should NOT have <think> block (session resumed)
        assert not content2.startswith("<think>")
        assert "<think>" not in content2
    
    @patch("src.session_manager.subprocess.check_output")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_think_block_only_at_response_start(self, mock_exec, mock_check_output):
        """Test that <think> block only appears at the very start of response, not in the middle"""
        mock_check_output.return_value = "test-session-xyz\n"
        
        mock_process = AsyncMock()
        # Simulate a response that might contain <think> text naturally
        mock_process.stdout.read = AsyncMock(
            side_effect=[b'{"result": "Let me think about that. <think> is not a valid HTML tag."}', b""]
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process
        
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test"}
        )
        
        assert resp.status_code == 200
        content = resp.json()["choices"][0]["message"]["content"]
        
        # Should start with the injected <think> block
        assert content.startswith("<think>")
        
        # The injected block should have session_id
        first_think_end = content.find("</think>")
        first_think_block = content[:first_think_end + len("</think>")]
        assert "Session ID: test-session-xyz" in first_think_block
        
        # The actual response content follows after
        after_block = content[first_think_end + len("</think>"):]
        assert "Let me think about that" in after_block
