import json
import hashlib
import uuid
import os
import subprocess
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone
from filelock import FileLock, Timeout
from loguru import logger
from src.config import config
from src.models import Message

class SessionManager:
    def __init__(self, storage_path: str = "sessions.json", workspace_base: Optional[str] = None):
        self.storage_path = storage_path
        # Use config.CURSOR_RELAY_BASE instead of hardcoded ".cursor-relay"
        if workspace_base is None:
            workspace_base = os.path.join(config.CURSOR_RELAY_BASE, "workspaces")
        self.workspace_base = workspace_base
        self.lock_path = f"{storage_path}.lock"
        self.lock = FileLock(self.lock_path, timeout=5)
        self._ensure_storage_exists()

    def _ensure_storage_exists(self):
        """Ensure sessions.json exists with valid structure."""
        if not os.path.exists(self.storage_path):
            try:
                with self.lock:
                    # Double check inside lock
                    if not os.path.exists(self.storage_path):
                        logger.info(f"Creating new session storage at {self.storage_path}")
                        with open(self.storage_path, "w", encoding="utf-8") as f:
                            json.dump({"sessions": {}}, f, ensure_ascii=False)
            except Timeout:
                logger.error("Timeout acquiring lock for storage creation")
                raise RuntimeError("Service busy (lock timeout)")
            except IOError as e:
                logger.error(f"Failed to initialize storage: {e}")
                raise RuntimeError(f"Storage initialization failed: {e}")

    def calculate_history_hash(self, messages: List[Any]) -> str:
        """
        Calculate SHA-256 hash of message history using canonical JSON.
        Scope: role, content.
        Supports both dict and Pydantic Message objects.
        """
        # Filter relevant fields to ensure consistency
        canonical_messages = []
        for msg in messages:
            if hasattr(msg, "model_dump"):
                # Pydantic v2
                d = msg.model_dump()
            elif hasattr(msg, "dict"):
                # Pydantic v1
                d = msg.dict()
            elif isinstance(msg, dict):
                d = msg
            else:
                continue # Skip unknown types

            clean_msg = {
                "role": d.get("role"),
                "content": d.get("content")
            }
            canonical_messages.append(clean_msg)

        # Serialize with sorted keys and minimal separators
        json_str = json.dumps(
            canonical_messages, 
            sort_keys=True, 
            separators=(',', ':')
        )
        
        return hashlib.sha256(json_str.encode('utf-8')).hexdigest()

    def load_sessions(self) -> Dict[str, Any]:
        """Load sessions with file lock."""
        try:
            with self.lock:
                if not os.path.exists(self.storage_path):
                    return {"sessions": {}}
                try:
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        return json.load(f)
                except json.JSONDecodeError:
                    logger.error("Failed to decode sessions.json, returning empty registry")
                    return {"sessions": {}}
        except Timeout:
            logger.error(f"Timeout acquiring lock for {self.storage_path}")
            raise RuntimeError("Service busy (lock timeout)")
        except IOError as e:
            logger.error(f"IOError loading sessions: {e}")
            raise RuntimeError(f"Storage error: {e}")

    def save_session(self, history_hash: str, session_data: Dict[str, Any], old_hash: Optional[str] = None):
        """
        Save a session mapping.
        If old_hash is provided, remove it (Update/Continue scenario).
        If old_hash is None, it's a new session or branching.
        """
        try:
            with self.lock:
                # Reload to get latest state
                try:
                    with open(self.storage_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except (FileNotFoundError, json.JSONDecodeError):
                    data = {"sessions": {}}

                sessions = data.get("sessions", {})

                # Remove old hash if exists
                if old_hash and old_hash in sessions:
                    del sessions[old_hash]

                # Add new hash
                sessions[history_hash] = session_data

                data["sessions"] = sessions

                with open(self.storage_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
        except Timeout:
            logger.error(f"Timeout acquiring lock for {self.storage_path}")
            raise RuntimeError("Service busy (lock timeout)")
        except IOError as e:
            logger.error(f"IOError saving session: {e}")
            raise RuntimeError(f"Storage error: {e}")

    def create_session(self, history_hash: str, title: str = "New Chat", custom_workspace: Optional[str] = None) -> str:
        """
        Create a new session by calling cursor-agent.
        Save to storage.
        
        Args:
            history_hash: Hash of message history
            title: Session title
            custom_workspace: Optional custom workspace path (must be pre-validated)
        """
        try:
            temp_dir = None
            
            if custom_workspace:
                # Use custom workspace directly
                workspace_dir = os.path.abspath(custom_workspace)
                os.makedirs(workspace_dir, exist_ok=True)
                logger.info(f"Using custom workspace directory: {workspace_dir}")
            else:
                # Create a temporary unique workspace folder
                temp_id = str(uuid.uuid4())
                temp_dir = os.path.abspath(os.path.join(self.workspace_base, f"temp_{temp_id}"))
                os.makedirs(temp_dir, exist_ok=True)
                logger.debug(f"Created temporary workspace directory: {temp_dir}")
                workspace_dir = temp_dir

            # Call cursor-agent to create a new chat
            # Output format check: The CLI returns just the UUID string on stdout
            cmd = [
                config.CURSOR_BIN,
                "create-chat",
                "--workspace", workspace_dir,
                "--sandbox", "enabled"
            ]
            
            output = subprocess.check_output(cmd, text=True).strip()
            session_id = output
            
            # If using temp directory, rename to session_id folder
            if temp_dir:
                final_workspace_dir = os.path.abspath(os.path.join(self.workspace_base, session_id))
                
                # If a folder with this session_id already exists (rare collision), we might need to handle it.
                # But normally session_id should be unique.
                if os.path.exists(final_workspace_dir) and final_workspace_dir != temp_dir:
                    logger.warning(f"Workspace directory {final_workspace_dir} already exists. Removing it.")
                    import shutil
                    shutil.rmtree(final_workspace_dir)
                
                os.rename(temp_dir, final_workspace_dir)
                workspace_dir = final_workspace_dir
                logger.debug(f"Renamed workspace directory to: {workspace_dir}")
            
            logger.info(f"Created new cursor-agent session: {session_id}")
            
            now = datetime.now(timezone.utc).isoformat()
            
            session_data = {
                "session_id": session_id,
                "title": title,
                "created_at": now,
                "updated_at": now,
                "workspace_dir": workspace_dir
            }
            
            self.save_session(history_hash, session_data)
            
            return session_id
            
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create cursor-agent session: {e}")
            # Cleanup temp_dir if it exists (only for non-custom workspace)
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
            raise RuntimeError(f"Failed to create session: {e}")
        except FileNotFoundError:
            logger.error(f"cursor-agent binary not found at {config.CURSOR_BIN}")
            raise RuntimeError(f"cursor-agent CLI not found at {config.CURSOR_BIN}")

    def update_session_hash(self, old_hash: str, new_hash: str):
        """
        Move a session from old_hash to new_hash.
        Update updated_at.
        """
        session = self.get_session_by_hash(old_hash)
        if not session:
            logger.warning(f"Attempted to update non-existent session hash: {old_hash}")
            return
        
        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.save_session(new_hash, session, old_hash=old_hash)

    def get_session_by_hash(self, history_hash: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data by history hash."""
        data = self.load_sessions()
        return data.get("sessions", {}).get(history_hash)

    def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data by session_id."""
        if not session_id:
            return None
        data = self.load_sessions()
        for session in data.get("sessions", {}).values():
            if session.get("session_id") == session_id:
                return session
        return None

    def get_hash_by_session_id(self, session_id: str) -> Optional[str]:
        """Retrieve history hash by session_id."""
        if not session_id:
            return None
        data = self.load_sessions()
        for history_hash, session in data.get("sessions", {}).items():
            if session.get("session_id") == session_id:
                return history_hash
        return None