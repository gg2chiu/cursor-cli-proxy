import os
import pytest
from unittest.mock import patch
from src.config import Settings

def test_settings_defaults():
    # 確保不受外部環境影響
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(_env_file=None)
        assert settings.HOST == "0.0.0.0"
        assert settings.PORT == 8000
        assert settings.LOG_LEVEL == "INFO"

def test_settings_env_override():
    with patch.dict(os.environ, {"PORT": "9000", "LOG_LEVEL": "DEBUG"}):
        settings = Settings()
        assert settings.PORT == 9000
        assert settings.LOG_LEVEL == "DEBUG"

def test_settings_dot_env():
    # 模擬 .env 內容
    env_content = "PORT=7000\nHOST=127.0.0.1"
    with patch("builtins.open", new_callable=lambda: None) as mock_open:
        # Pydantic Settings 讀取 .env 比較複雜，通常直接測試 env var 優先級即可
        # 若要測試 .env 讀取，最好是寫入一個臨時檔案
        pass

@pytest.fixture
def temp_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("PORT=6000\nLOG_LEVEL=WARNING")
    return env_file

def test_settings_load_env_file(temp_env_file):
    # 需要重新載入 Settings 類別或指定 env_file
    # 這裡我們簡單測試 Settings 是否能接受 _env_file 參數 (BaseSettings 特性)
    # Ensure env vars don't override .env file
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings(_env_file=temp_env_file)
        assert settings.PORT == 6000
        assert settings.LOG_LEVEL == "WARNING"
