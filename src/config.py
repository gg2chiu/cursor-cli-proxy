import shutil
import sys
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from loguru import logger

# Configure logging to output JSON to stdout
logger.remove()
logger.add(sys.stdout, format="{message}", serialize=True)

class Settings(BaseSettings):
    CURSOR_BIN: str = "cursor-agent"
    CURSOR_KEY: Optional[str] = None
    CURSOR_RELAY_BASE: str = "/tmp/.cursor-relay"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def validate_cursor_bin(self):
        # 嘗試解析 CURSOR_BIN (若它是指令名稱)
        resolved = shutil.which(self.CURSOR_BIN)
        if resolved:
            self.CURSOR_BIN = resolved
        else:
            # 若找不到，且不是絕對路徑，則發出警告
            logger.warning(f"cursor-agent binary not found at '{self.CURSOR_BIN}'. Please install it or set CURSOR_BIN.")

    def validate(self):
        self.validate_cursor_bin()
        # 更新 Log Level
        logger.remove()
        logger.add(sys.stdout, format="{message}", serialize=True, level=self.LOG_LEVEL.upper())

# 建立全域 config 物件
config = Settings()
# 我們可以選擇在 import 時自動 validate，或者保留 main.py 的呼叫。
# 為了避免重複 log，這裡先不呼叫，讓 main.py 呼叫。
# config.validate_cursor_bin()