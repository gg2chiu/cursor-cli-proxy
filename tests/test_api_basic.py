from fastapi.testclient import TestClient
from src.main import app, config
from src.relay import Executor
from unittest.mock import AsyncMock, patch

client = TestClient(app)

def test_chat_completions_basic():
    # Mock Executor.run_non_stream
    with patch("src.relay.Executor.run_non_stream", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Hello world"
        
        response = client.post(
            "/v1/chat/completions",
            json={
                "model": "gpt-4",
                "messages": [{"role": "user", "content": "hi"}]
            },
            headers={"Authorization": "Bearer sk-test"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["choices"][0]["message"]["content"] == "Hello world"
        assert data["model"] == "gpt-4"

def test_chat_completions_missing_auth():
    # Force CURSOR_KEY to be None so that auth is actually checked
    with patch.object(config, 'CURSOR_KEY', None):
        response = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert response.status_code == 401
