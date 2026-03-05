import pytest
import os
from unittest.mock import patch, MagicMock
from src.models import ChatCompletionRequest, Message
from src.model_registry import model_registry


def make_popen_mock(session_id: str, poll_returncode=None) -> MagicMock:
    """Create a mock subprocess.Popen that simulates cursor-agent create-chat.

    Args:
        poll_returncode: Value returned by poll() before we terminate the process.
            None means the process is still running (normal success case).
            A positive int (e.g. 1) means the process already exited with an error.
    """
    mock = MagicMock()
    mock.stdout.readline.return_value = f"{session_id}\n"
    mock.wait.return_value = None
    mock.poll.return_value = poll_returncode
    return mock

@pytest.fixture(autouse=True)
def reset_registry(tmp_path):
    # Create a temp file path for testing
    temp_cache = tmp_path / "test_models.json"
    
    # Patch the CACHE_FILE constant in the module
    with patch("src.model_registry.CACHE_FILE", str(temp_cache)):
        model_registry.reset()
        yield
        model_registry.reset()
        # Temp file is automatically cleaned up by tmp_path, but we can be explicit if we want
        # but pytest handles tmp_path cleanup.

@pytest.fixture
def valid_request():
    return ChatCompletionRequest(
        model="claude-3-opus",
        messages=[{"role": "user", "content": "Hello"}]
    )
