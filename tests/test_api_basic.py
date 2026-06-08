import json
import os
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
from filelock import FileLock
from fastapi.testclient import TestClient

from src.main import app, config, session_manager
from src.model_registry import model_registry
from src.relay import Executor
from src.slash_command_loader import SlashCommandLoader
from tests.conftest import make_popen_mock

client = TestClient(app)

@pytest.fixture(autouse=True)
def isolated_session_storage(tmp_path):
    """Isolate session storage and mock subprocess.Popen to avoid real cursor-agent calls."""
    storage_file = tmp_path / "test_sessions.json"
    lock_file = tmp_path / "test_sessions.json.lock"
    session_manager.storage_path = str(storage_file)
    session_manager.lock_path = str(lock_file)
    session_manager.workspace_base = str(tmp_path / "workspaces")
    session_manager.lock = FileLock(session_manager.lock_path)
    session_manager._ensure_storage_exists()
    yield
    for f in [str(storage_file), str(lock_file)]:
        if os.path.exists(f):
            os.remove(f)

@pytest.fixture(autouse=True)
def mock_create_chat():
    """Mock subprocess.Popen so create_session never spawns a real cursor-agent process."""
    with patch("src.session_manager.subprocess.Popen") as mock_popen:
        mock_popen.return_value = make_popen_mock("mock-session-id")
        yield mock_popen

@pytest.fixture(autouse=True)
def disable_think_block():
    original_value = config.ENABLE_INFO_IN_THINK
    config.ENABLE_INFO_IN_THINK = False
    yield
    config.ENABLE_INFO_IN_THINK = original_value

def test_chat_completions_basic():
    # Mock Executor.run_non_stream
    with patch("src.relay.Executor.run_non_stream", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Hello world"
        
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "auto",
                "messages": [{"role": "user", "content": "hi"}]
            },
            headers={"Authorization": "Bearer sk-test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Hello world"
        assert data["model"] == "auto"

def test_stream_empty_executor_no_think_block_or_done():
    """When executor produces no output in stream mode, should not emit think_block, final_chunk, or [DONE]."""
    config.ENABLE_INFO_IN_THINK = True

    async def empty_stream(*args, **kwargs):
        if False:
            yield  # Async generator that yields nothing

    with patch.object(Executor, 'run_stream', side_effect=empty_stream):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}], "stream": True},
            headers={"Authorization": "Bearer sk-test"}
        )
        assert response.status_code == 200

        lines = [line for line in response.iter_lines() if line]
        content_chunks = []
        has_done = False
        has_finish_stop = False
        for line in lines:
            if line == "data: [DONE]":
                has_done = True
                continue
            if line.startswith("data: "):
                chunk = json.loads(line[6:])
                delta = chunk.get("choices", [{}])[0].get("delta", {})
                if "content" in delta:
                    content_chunks.append(delta["content"])
                fr = chunk.get("choices", [{}])[0].get("finish_reason")
                if fr == "stop":
                    has_finish_stop = True

        assert len(content_chunks) == 0, f"Expected no content chunks but got: {content_chunks}"
        assert not has_done, "Should not emit [DONE] when executor produced no output"
        assert not has_finish_stop, "Should not emit finish_reason=stop when executor produced no output"


def test_non_stream_empty_executor_no_think_block():
    """When executor returns empty content in non-stream mode, should return empty content, not think_block."""
    config.ENABLE_INFO_IN_THINK = True

    with patch("src.relay.Executor.run_non_stream", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = ""
        response = client.post(
            "/v1/chat/completions",
            json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer sk-test"}
        )
        assert response.status_code == 200
        content = response.json()["choices"][0]["message"]["content"]
        assert content == "", f"Expected empty content but got: {content[:100]}..."


def test_think_block_built_only_when_content_present():
    """think_block construction should be deferred until after executor produces content."""
    config.ENABLE_INFO_IN_THINK = True
    build_calls = []
    original_get_labels = SlashCommandLoader.get_command_labels

    def tracking_get_labels(self):
        build_calls.append("called")
        return original_get_labels(self)

    with patch.object(SlashCommandLoader, "get_command_labels", tracking_get_labels):
        # Empty executor - think block should NOT be built
        build_calls.clear()
        with patch("src.relay.Executor.run_non_stream", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ""
            client.post(
                "/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": "Bearer sk-test"}
            )
        assert len(build_calls) == 0, "get_command_labels should NOT be called when executor returns empty content"

        # Non-empty executor - think block SHOULD be built
        build_calls.clear()
        with patch("src.relay.Executor.run_non_stream", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = "Hello"
            client.post(
                "/v1/chat/completions",
                json={"model": "auto", "messages": [{"role": "user", "content": "hi"}]},
                headers={"Authorization": "Bearer sk-test"}
            )
        assert len(build_calls) == 1, "get_command_labels should be called when executor returns content"


def test_health_endpoint_all_healthy():
    """After initialization, all checks should pass."""
    model_registry.initialize()
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["checks"]["cursor_agent"] is True
    assert data["checks"]["model_registry"] is True
    assert data["checks"]["session_storage"] is True


def test_health_endpoint_degraded_when_cursor_agent_missing():
    with patch("shutil.which", return_value=None):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["cursor_agent"] is False
