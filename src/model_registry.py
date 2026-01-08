import subprocess
import re
import json
import os
from typing import List, Optional
from loguru import logger
from src.models import Model
from src.config import config

CACHE_FILE = "models.json"

class ModelRegistry:
    _instance = None
    _models: Optional[List[Model]] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelRegistry, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Singleton init usually doesn't do much if __new__ handles instance
        # But for clarity we can rely on _models being None initially
        pass

    @property
    def default_models(self) -> List[Model]:
        return [
            Model(id="cursor-small", owned_by="cursor"),
            Model(id="cursor-large", owned_by="cursor"),
            Model(id="gpt-3.5-turbo", owned_by="openai"),
            Model(id="gpt-4", owned_by="openai"),
            Model(id="gpt-4o", owned_by="openai"),
            Model(id="claude-3-opus", owned_by="anthropic"),
            Model(id="claude-3.5-sonnet", owned_by="anthropic"),
        ]

    def save_to_file(self, models: List[Model]):
        """Save models to JSON file."""
        try:
            data = [m.model_dump() for m in models]
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Saved {len(models)} models to {CACHE_FILE}")
        except Exception as e:
            logger.error(f"Failed to save models to file: {e}")

    def load_from_file(self) -> bool:
        """Load models from JSON file. Returns True if successful."""
        if not os.path.exists(CACHE_FILE):
            return False
            
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            self._models = [Model(**item) for item in data]
            logger.debug(f"Loaded {len(self._models)} models from {CACHE_FILE}")
            return True
        except Exception as e:
            logger.error(f"Failed to load models from file: {e}")
            return False

    def fetch_models(self, api_key: Optional[str] = None) -> List[Model]:
        """Fetch models from CLI, fallback to default on error."""
        try:
            logger.info("Fetching models from cursor-agent CLI...")
            
            cmd = [config.CURSOR_BIN, '--model', 'fake']
            # Use provided api_key or fall back to config
            key_to_use = api_key or config.CURSOR_KEY
            if key_to_use:
                cmd.extend(['--api-key', key_to_use])

            # Run the command expecting failure (exit code 1) but capturing stderr
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False 
            )
            
            # Even if returncode is not 0, we expect useful info in stderr
            stderr_output = result.stderr
            
            models = self._parse_models(stderr_output)
            # Save to file if we got valid models (and not just fallback defaults from parsing error)
            # _parse_models returns default_models on failure. 
            # We should check if the result is different or just trust the process.
            # But simpler: just save whatever we got, as _parse_models handles fallback.
            # Actually, if _parse_models returns defaults, saving them is fine too.
            self.save_to_file(models)
            return models
            
        except FileNotFoundError:
            logger.error(f"cursor-agent executable not found at {config.CURSOR_BIN}. Using fallback model list.")
            return self.default_models
        except Exception as e:
            logger.error(f"Error fetching models: {e}. Using fallback model list.")
            return self.default_models

    def _parse_models(self, stderr_output: str) -> List[Model]:
        """Parse the stderr output to extract model names."""
        # Expected format: "Cannot use this model: fake. Available models: model1, model2, ..."
        match = re.search(r"Available models:\s*(.*)", stderr_output, re.DOTALL)
        
        if not match:
            logger.warning("Could not parse model list from CLI output. Using fallback.")
            logger.debug(f"CLI Output: {stderr_output}")
            return self.default_models
            
        model_str = match.group(1).strip()
        # Split by comma and strip whitespace
        model_ids = [m.strip() for m in model_str.split(',') if m.strip()]
        
        if not model_ids:
            logger.warning("Parsed empty model list. Using fallback.")
            return self.default_models
            
        logger.info(f"Successfully parsed {len(model_ids)} models from CLI.")
        return [Model(id=mid, owned_by="cursor") for mid in model_ids]

    def initialize(self, update: bool = False):
        """Initialize the registry.
        
        Args:
            update: If True, force fetch from CLI and save.
                    If False, try to load from file.
        """
        if update:
            logger.info("Forcing model update from CLI...")
            self._models = self.fetch_models()
        else:
            if not self.load_from_file():
                logger.info("No cache file found or load failed. Using default models.")
                self._models = self.default_models

    def get_models(self, api_key: Optional[str] = None) -> List[Model]:
        """Get models, using cache if available."""
        if self._models is None:
            # If not initialized, try loading from file first
            if not self.load_from_file():
                # If that fails, maybe fetch? 
                # But requirement says "only update it while with main args".
                # So if no file, we fallback to defaults.
                # However, if api_key is provided and we are here, maybe we should fetch?
                # But that violates "only update...".
                # So we stick to defaults if no file.
                self._models = self.default_models
                
        return self._models

    def refresh(self, api_key: Optional[str] = None) -> List[Model]:
        """Force refresh the model list."""
        self._models = self.fetch_models(api_key=api_key)
        return self._models

    def reset(self):
        """Reset the registry state (FOR TESTING ONLY)."""
        self._models = None

# Global instance
model_registry = ModelRegistry()
