import pytest
import os
from unittest.mock import patch
from src.models import ChatCompletionRequest, Message
from src.model_registry import model_registry

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
