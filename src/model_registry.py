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

    _CLAUDE_PREFIXES = ("opus-", "sonnet-")

    def __init__(self):
        pass

    @staticmethod
    def to_display_id(model_id: str) -> str:
        """Add 'claude-' prefix to Claude model IDs for API display."""
        if model_id.startswith(ModelRegistry._CLAUDE_PREFIXES) and not model_id.startswith("claude-"):
            return f"claude-{model_id}"
        return model_id

    @staticmethod
    def to_cli_id(model_id: str) -> str:
        """Strip 'claude-' prefix so the CLI receives the original ID."""
        if model_id.startswith("claude-"):
            return model_id[len("claude-"):]
        return model_id

    @property
    def default_models(self) -> List[Model]:
        return [
            Model(id="auto", owned_by="cursor"),
            Model(id="composer-1", owned_by="cursor"),
            Model(id="gpt-5.1", owned_by="openai"),
            Model(id="sonnet-4.5", owned_by="anthropic")
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
            
            from src.config import CURSOR_BIN
            cmd = [CURSOR_BIN, "models"]
            # Use provided api_key or fall back to config
            key_to_use = api_key or config.CURSOR_KEY
            if key_to_use:
                cmd.extend(['--api-key', key_to_use])

            # Run the command and capture stdout
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False 
            )
            
            # The models command outputs to stdout
            stdout_output = result.stdout
            
            models = self._parse_models(stdout_output)
            # Save to file if we got valid models
            self.save_to_file(models)
            return models
            
        except FileNotFoundError:
            from src.config import CURSOR_BIN
            logger.error(f"cursor-agent executable not found at {CURSOR_BIN}. Using fallback model list.")
            return self.default_models
        except Exception as e:
            logger.error(f"Error fetching models: {e}. Using fallback model list.")
            return self.default_models

    def _parse_models(self, output: str) -> List[Model]:
        """Parse the models output to extract model information.
        
        Expected format:
        Available models
        
        model-id - Model Name (optional tags)
        model-id2 - Model Name 2
        ...
        """
        if not output:
            logger.warning("Empty output from CLI. Using fallback.")
            return self.default_models
        
        models = []
        lines = output.strip().split('\n')
        
        # Skip header lines and empty lines
        parsing = False
        for line in lines:
            line = line.strip()
            
            # Start parsing after "Available models" header
            if "Available models" in line:
                parsing = True
                continue
            
            # Skip empty lines and tip lines
            if not line or line.startswith("Tip:") or line.startswith("Loading"):
                continue
            
            # Skip ANSI escape sequences lines
            if line.startswith('[') and ('K' in line or 'G' in line or 'A' in line):
                continue
            
            if parsing:
                # Parse line format: "model-id - Model Name (optional)"
                match = re.match(r'^([a-zA-Z0-9._-]+)\s+-\s+(.+)$', line)
                if match:
                    model_id = match.group(1)
                    model_name = match.group(2).strip()
                    # Remove trailing status tags like (default), (current), (current, default)
                    # but keep model name parts like (Thinking)
                    model_name = re.sub(r'\s+\([^)]*?\b(?:default|current)\b[^)]*?\)$', '', model_name).strip()
                    models.append(Model(id=model_id, owned_by="cursor", name=model_name))
                else:
                    logger.debug(f"Skipping unparseable line: {line}")
        
        if not models:
            logger.warning("Could not parse any models from CLI output. Using fallback.")
            logger.debug(f"CLI Output: {output}")
            return self.default_models
        
        logger.info(f"Successfully parsed {len(models)} models from CLI.")
        return models

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
                
        return [m.model_copy(update={"id": self.to_display_id(m.id)}) for m in self._models]

    def refresh(self, api_key: Optional[str] = None) -> List[Model]:
        """Force refresh the model list."""
        self._models = self.fetch_models(api_key=api_key)
        return self._models

    def reset(self):
        """Reset the registry state (FOR TESTING ONLY)."""
        self._models = None

# Global instance
model_registry = ModelRegistry()
