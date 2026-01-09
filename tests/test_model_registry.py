import pytest
from unittest.mock import patch, MagicMock
from src.model_registry import ModelRegistry, Model
import subprocess

@pytest.fixture
def registry():
    return ModelRegistry()

def test_fetch_models_success(registry):
    """測試成功解析 CLI 輸出"""
    mock_stdout = """Available models

model-a - Model A
model-b - Model B (default)
model-c - Model C

Tip: use --model <id> to switch."""
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, 
            stderr="",
            stdout=mock_stdout
        )
        
        models = registry.fetch_models()
        
        assert len(models) == 3
        assert models[0].id == "model-a"
        assert models[0].name == "Model A"
        assert models[1].id == "model-b"
        assert models[1].name == "Model B"
        assert models[2].id == "model-c"
        assert models[2].name == "Model C"
        assert models[0].owned_by == "cursor"

def test_fetch_models_cli_error(registry):
    """測試 CLI 執行失敗 (fallback)"""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        models = registry.fetch_models()
        
        # Should fallback to default list
        assert len(models) > 0
        ids = [m.id for m in models]
        assert "auto" in ids

def test_fetch_models_malformed_output(registry):
    """測試無法解析的輸出 (fallback)"""
    mock_stdout = "Some unexpected error message without model list."
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, 
            stderr="",
            stdout=mock_stdout
        )
        
        models = registry.fetch_models()
        
        # Should fallback to default list
        assert len(models) > 0
        ids = [m.id for m in models]
        assert "auto" in ids

def test_fetch_models_with_api_key(registry):
    """測試 fetch_models 是否正確傳遞 --api-key"""
    mock_stdout = """Available models

model-k - Model K"""
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, 
            stderr="",
            stdout=mock_stdout
        )
        
        registry.fetch_models(api_key="test-key-123")
        
        # Check if --api-key was in the command arguments
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert "--api-key" in cmd
        assert "test-key-123" in cmd

def test_caching_mechanism(registry):
    """測試快取機制"""
    mock_stdout = """Available models

cached-model - Cached Model"""
    
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0, 
            stderr="",
            stdout=mock_stdout
        )
        
        # Explicitly trigger update to fetch from CLI and populate cache/file
        registry.initialize(update=True)
        
        # First call
        models1 = registry.get_models()
        assert models1[0].id == "cached-model"
        assert mock_run.call_count == 1
        
        # Second call should use cache (memory or file, but memory is faster)
        models2 = registry.get_models()
        assert models2[0].id == "cached-model"
        assert mock_run.call_count == 1  # Still 1
