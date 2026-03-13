"""Cursor CLI Proxy - FastAPI application entry point."""
from fastapi import FastAPI

from src.config import config
from src.model_registry import model_registry
from src.routes import chat_completions, health, models, responses
from src.routes.common import session_manager  # noqa: F401 — re-exported for backward compat

# Ensure config validation
config.validate()

# Initialize ModelRegistry (load from cache file or use defaults)
model_registry.initialize()

app = FastAPI(title="Cursor CLI Proxy")

app.include_router(health.router)
app.include_router(models.router)
app.include_router(chat_completions.router)
app.include_router(responses.router)

if __name__ == "__main__":
    from src.cli import main
    main()
