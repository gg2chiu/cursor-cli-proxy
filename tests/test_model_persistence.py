import pytest
import os
import json
from unittest.mock import patch, MagicMock
import src.model_registry as model_registry_module
from src.model_registry import model_registry, ModelRegistry

@pytest.fixture
def registry():
    return ModelRegistry()

def test_save_models_creates_file(registry):
    """Verify that models are saved to models.json."""
    mock_stdout = """Available models

persistence-test-model - Persistence Test Model"""
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, 
            stderr="",
            stdout=mock_stdout
        )
        
        # Trigger fetch and save
        registry.fetch_models()
        
        # Use the patched CACHE_FILE from the module
        cache_file = model_registry_module.CACHE_FILE
        assert os.path.exists(cache_file)
        
        with open(cache_file, "r") as f:
            data = json.load(f)
            assert len(data) == 1
            assert data[0]["id"] == "persistence-test-model"
            assert data[0]["name"] == "Persistence Test Model"

def test_load_models_from_file(registry):
    """Verify that models are loaded from models.json."""
    cache_file = model_registry_module.CACHE_FILE
    
    # Create a dummy models.json at the patched location
    dummy_data = [{"id": "loaded-from-file", "owned_by": "test", "object": "model"}]
    with open(cache_file, "w") as f:
        json.dump(dummy_data, f)
        
    # Reset registry to ensure no memory cache
    registry.reset()
    
    # Initialize without update (should load from file)
    registry.initialize(update=False)
    
    models = registry.get_models()
    assert len(models) == 1
    assert models[0].id == "loaded-from-file"

def test_corrupt_file_handling(registry):
    """Verify handling of corrupt JSON file."""
    cache_file = model_registry_module.CACHE_FILE
    
    with open(cache_file, "w") as f:
        f.write("{invalid-json")
        
    registry.reset()
    registry.initialize(update=False)
    
    # Should fallback to default models
    models = registry.get_models()
    assert len(models) > 0
    assert "auto" in [m.id for m in models]
