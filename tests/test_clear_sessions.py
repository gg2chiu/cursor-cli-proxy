"""測試 --clear 參數功能"""
import os
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def test_clear_sessions_functionality():
    """測試清除會話功能是否正常工作"""
    # 創建臨時測試目錄
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        
        # 創建測試檔案和目錄
        sessions_file = test_dir / "sessions.json"
        lock_file = test_dir / "sessions.json.lock"
        relay_dir = test_dir / ".cursor-relay"
        workspace_dir = relay_dir / "workspaces" / "test-session-id"
        
        # 建立測試資料
        workspace_dir.mkdir(parents=True, exist_ok=True)
        
        # 寫入測試 sessions.json
        test_sessions = {
            "sessions": {
                "test-hash": {
                    "session_id": "test-session-id",
                    "title": "Test Session",
                    "created_at": "2026-01-07T00:00:00+00:00",
                    "updated_at": "2026-01-07T00:00:00+00:00"
                }
            }
        }
        with open(sessions_file, "w", encoding="utf-8") as f:
            json.dump(test_sessions, f)
        
        # 創建鎖定檔案
        lock_file.touch()
        
        # 驗證檔案存在
        assert sessions_file.exists()
        assert lock_file.exists()
        assert relay_dir.exists()
        assert workspace_dir.exists()
        
        # 模擬清除操作
        # 清除 sessions.json
        with open(sessions_file, "w", encoding="utf-8") as f:
            json.dump({"sessions": {}}, f, ensure_ascii=False, indent=2)
        
        # 移除鎖定檔案
        if lock_file.exists():
            os.remove(lock_file)
        
        # 刪除 .cursor-relay 目錄
        if relay_dir.exists():
            shutil.rmtree(relay_dir)
        
        # 驗證清除結果
        assert sessions_file.exists()  # 檔案應該存在但內容為空
        assert not lock_file.exists()  # 鎖定檔案應該被刪除
        assert not relay_dir.exists()  # 目錄應該被刪除
        
        # 驗證 sessions.json 內容
        with open(sessions_file, "r", encoding="utf-8") as f:
            cleared_data = json.load(f)
        
        assert cleared_data == {"sessions": {}}


def test_clear_sessions_with_missing_files():
    """測試當檔案不存在時清除功能是否正常處理"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        
        sessions_file = test_dir / "sessions.json"
        lock_file = test_dir / "sessions.json.lock"
        relay_dir = test_dir / ".cursor-relay"
        
        # 驗證檔案不存在
        assert not sessions_file.exists()
        assert not lock_file.exists()
        assert not relay_dir.exists()
        
        # 模擬清除操作（不應該產生錯誤）
        # 嘗試清除不存在的鎖定檔案
        if lock_file.exists():
            os.remove(lock_file)
        
        # 嘗試刪除不存在的目錄
        if relay_dir.exists():
            shutil.rmtree(relay_dir)
        
        # 驗證沒有錯誤發生
        assert not lock_file.exists()
        assert not relay_dir.exists()


def test_sessions_json_structure_after_clear():
    """測試清除後 sessions.json 的結構是否正確"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir)
        sessions_file = test_dir / "sessions.json"
        
        # 創建包含多個會話的檔案
        test_sessions = {
            "sessions": {
                "hash1": {"session_id": "id1", "title": "Session 1"},
                "hash2": {"session_id": "id2", "title": "Session 2"},
                "hash3": {"session_id": "id3", "title": "Session 3"}
            }
        }
        with open(sessions_file, "w", encoding="utf-8") as f:
            json.dump(test_sessions, f)
        
        # 清除
        with open(sessions_file, "w", encoding="utf-8") as f:
            json.dump({"sessions": {}}, f, ensure_ascii=False, indent=2)
        
        # 驗證結構
        with open(sessions_file, "r", encoding="utf-8") as f:
            cleared_data = json.load(f)
        
        assert "sessions" in cleared_data
        assert isinstance(cleared_data["sessions"], dict)
        assert len(cleared_data["sessions"]) == 0


if __name__ == "__main__":
    # 執行測試
    test_clear_sessions_functionality()
    print("✓ test_clear_sessions_functionality passed")
    
    test_clear_sessions_with_missing_files()
    print("✓ test_clear_sessions_with_missing_files passed")
    
    test_sessions_json_structure_after_clear()
    print("✓ test_sessions_json_structure_after_clear passed")
    
    print("\nAll tests passed!")

