import os
import shutil
import sys
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict
from loguru import logger

# Configure logging to output text to stdout
logger.remove()
logger.add(sys.stdout, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")

# Constants
CURSOR_BIN = "cursor-agent"
CURSOR_CLI_PROXY_TMP = "/tmp/cursor-cli-proxy"

class Settings(BaseSettings):
    CURSOR_KEY: Optional[str] = None
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"
    WORKSPACE_WHITELIST_1: Optional[str] = None
    WORKSPACE_WHITELIST_2: Optional[str] = None
    WORKSPACE_WHITELIST_3: Optional[str] = None
    WORKSPACE_WHITELIST_4: Optional[str] = None
    WORKSPACE_WHITELIST_5: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_workspace_whitelist(self) -> List[str]:
        entries = [
            self.WORKSPACE_WHITELIST_1,
            self.WORKSPACE_WHITELIST_2,
            self.WORKSPACE_WHITELIST_3,
            self.WORKSPACE_WHITELIST_4,
            self.WORKSPACE_WHITELIST_5,
        ]
        return [p.strip() for p in entries if p and p.strip()]
    
    def validate_cursor_bin(self):
        # Try to resolve CURSOR_BIN (if it is a command name)
        if not shutil.which(CURSOR_BIN):
            raise FileNotFoundError(f"cursor-agent executable not found. Please install it.")

    def validate(self):
        self.validate_cursor_bin()
        # Update Log Level
        logger.remove()
        logger.add(sys.stdout, format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}", level=self.LOG_LEVEL.upper())

# 建立全域 config 物件
config = Settings()