"""CLI entry point for Cursor CLI Proxy."""
import json
import os
import shutil
import sys

import uvicorn

from src.config import config, logger
from src.model_registry import model_registry


def main() -> None:
    """Parse CLI args and run update-model, clear, or uvicorn server."""
    import argparse

    parser = argparse.ArgumentParser(description="Cursor CLI Proxy")
    parser.add_argument("--update-model", action="store_true", help="Update model list from cursor-agent and exit")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument("--clear", action="store_true", help="Clear sessions.json and temporary directory and exit")

    args, _ = parser.parse_known_args()

    if args.update_model:
        _run_update_model()
        return

    if args.clear:
        _run_clear()
        return

    _run_server(reload=args.reload)


def _run_update_model() -> None:
    try:
        logger.info("Updating model list from cursor-agent...")
        model_registry.initialize(update=True)
        logger.info("✓ Model list updated successfully!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error updating model list: {e}")
        sys.exit(1)


def _run_clear() -> None:
    try:
        sessions_file = "sessions.json"
        if os.path.exists(sessions_file):
            logger.info(f"Clearing {sessions_file}...")
            with open(sessions_file, "w", encoding="utf-8") as f:
                json.dump({"sessions": {}}, f, ensure_ascii=False, indent=2)
            logger.info(f"✓ {sessions_file} cleared successfully")
        else:
            logger.info(f"{sessions_file} does not exist, skipping")

        lock_file = "sessions.json.lock"
        if os.path.exists(lock_file):
            logger.info(f"Removing {lock_file}...")
            os.remove(lock_file)
            logger.info(f"✓ {lock_file} removed successfully")

        from src.config import CURSOR_CLI_PROXY_TMP
        relay_dir = CURSOR_CLI_PROXY_TMP
        if os.path.exists(relay_dir):
            logger.info(f"Removing {relay_dir} directory...")
            shutil.rmtree(relay_dir)
            logger.info(f"✓ {relay_dir} directory removed successfully")
        else:
            logger.info(f"{relay_dir} directory does not exist, skipping")

        logger.info("All session data cleared successfully!")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error clearing session data: {e}")
        sys.exit(1)


def _run_server(reload: bool = False) -> None:
    uvicorn_kwargs = {
        "host": config.HOST,
        "port": config.PORT,
        "log_level": config.LOG_LEVEL.lower(),
        "reload": reload,
    }

    if config.ENABLE_HTTPS:
        if not config.HTTPS_CERT_PATH:
            logger.error("HTTPS is enabled but HTTPS_CERT_PATH is not configured")
            sys.exit(1)
        if not config.HTTPS_KEY_PATH:
            logger.error("HTTPS is enabled but HTTPS_KEY_PATH is not configured")
            sys.exit(1)
        if not os.path.exists(config.HTTPS_CERT_PATH):
            logger.error(f"HTTPS certificate not found: {config.HTTPS_CERT_PATH}")
            sys.exit(1)
        if not os.path.exists(config.HTTPS_KEY_PATH):
            logger.error(f"HTTPS key not found: {config.HTTPS_KEY_PATH}")
            sys.exit(1)
        uvicorn_kwargs["ssl_certfile"] = config.HTTPS_CERT_PATH
        uvicorn_kwargs["ssl_keyfile"] = config.HTTPS_KEY_PATH
        logger.info(f"HTTPS enabled with cert: {config.HTTPS_CERT_PATH}")

    uvicorn.run("src.main:app", **uvicorn_kwargs)
