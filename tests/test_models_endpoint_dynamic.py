import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.main import app
from src.model_registry import model_registry

client = TestClient(app)

def test_list_models_dynamic():
    """Integration test: /v1/models should return models from registry."""
    from src.models import Model
    
    # Mock the get_models method of the global registry instance
    mock_models = [
        Model(id="dynamic-model-1", owned_by="cursor"),
        Model(id="dynamic-model-2", owned_by="cursor")
    ]
    
    # We need to patch where main.py imports or uses the registry
    # Since main.py likely imports 'model_registry' instance, we patch the instance method
    with patch.object(model_registry, 'get_models', return_value=mock_models) as mock_get:
        response = client.get("/v1/models", headers={"Authorization": "Bearer sk-test"})
        
        assert response.status_code == 200
        # Verify that get_models was called with an api_key (from verify_auth)
        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        assert "api_key" in kwargs
        
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) == 2
        assert data["data"][0]["id"] == "dynamic-model-1"
        assert data["data"][1]["id"] == "dynamic-model-2"

def test_list_models_fallback_integration():
    """Integration test: Verify fallback behavior when CLI fails."""
    # Force registry to use default models (simulate clean state)
    model_registry._models = None
    
    # Patch subprocess to fail, triggering fallback
    with patch("subprocess.run", side_effect=FileNotFoundError):
        # This will trigger fetch_models() internally
        response = client.get("/v1/models", headers={"Authorization": "Bearer sk-test"})
        
        assert response.status_code == 200
        data = response.json()
        
        # Should contain default models (e.g., auto)
        ids = [m["id"] for m in data["data"]]
        assert "auto" in ids
