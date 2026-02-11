import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger


class SlashCommandLoader:
    """Load custom slash commands, skills, and agents from .cursor/ and .claude/ directories.

    Scans project-level and user-level directories for:
    - commands: .cursor/commands/*.md, .claude/commands/*.md
    - skills:   .cursor/skills/**/SKILL.md, .cursor/skills-cursor/**/SKILL.md
    - agents:   .cursor/agents/**/*.md

    Instead of expanding command content inline, resolve_slash_command returns
    an @path reference so cursor-agent reads the file directly.
    """

    def __init__(self, workspace_dir: Optional[str] = None):
        self.workspace_dir = workspace_dir or os.getcwd()
        self.entries: Dict[str, Dict[str, str]] = {}
        self._load_all()

    def _load_all(self):
        """Load entries in priority order (later overrides earlier for same command_id).

        Priority:
        1. Project .claude/commands/
        2. Project .cursor/commands/
        3. Project .cursor/skills/
        4. Project .cursor/agents/
        5. User .claude/commands/
        6. User .cursor/commands/
        7. User .cursor/skills/
        8. User .cursor/skills-cursor/
        9. User .cursor/agents/
        """
        workspace = Path(self.workspace_dir)
        home = Path.home()

        # Project-level
        self._load_commands_dir(workspace / ".claude" / "commands")
        self._load_commands_dir(workspace / ".cursor" / "commands")
        self._load_skills_dir(workspace / ".cursor" / "skills")
        self._load_agents_dir(workspace / ".cursor" / "agents")

        # User-level
        self._load_commands_dir(home / ".claude" / "commands")
        self._load_commands_dir(home / ".cursor" / "commands")
        self._load_skills_dir(home / ".cursor" / "skills")
        self._load_skills_dir(home / ".cursor" / "skills-cursor")
        self._load_agents_dir(home / ".cursor" / "agents")

    def _load_commands_dir(self, directory: Path):
        """Load *.md files directly in the directory as commands."""
        if not directory.exists() or not directory.is_dir():
            return
        try:
            for md_file in directory.glob("*.md"):
                self._register_entry(md_file.stem, str(md_file), "command")
        except Exception as e:
            logger.warning(f"Failed to read commands directory {directory}: {e}")

    def _load_skills_dir(self, directory: Path):
        """Recursively find SKILL.md files; command_id = immediate parent dir name."""
        if not directory.exists() or not directory.is_dir():
            return
        try:
            for skill_file in directory.rglob("SKILL.md"):
                command_id = skill_file.parent.name
                self._register_entry(command_id, str(skill_file), "skill")
        except Exception as e:
            logger.warning(f"Failed to read skills directory {directory}: {e}")

    def _load_agents_dir(self, directory: Path):
        """Load *.md files (flat and nested) from agents directory."""
        if not directory.exists() or not directory.is_dir():
            return
        try:
            for md_file in directory.rglob("*.md"):
                self._register_entry(md_file.stem, str(md_file), "agent")
        except Exception as e:
            logger.warning(f"Failed to read agents directory {directory}: {e}")

    def _register_entry(self, command_id: str, path: str, entry_type: str):
        """Register an entry, skipping empty files. Later calls override earlier ones."""
        try:
            content = Path(path).read_text(encoding="utf-8").strip()
            if not content:
                logger.debug(f"Skipping empty file: {path}")
                return
        except Exception as e:
            logger.warning(f"Failed to read {path}: {e}")
            return

        self.entries[command_id] = {"path": path, "type": entry_type}
        logger.debug(f"Loaded {entry_type}: /{command_id} from {path}")

    def _extract_title(self, filepath: str) -> Optional[str]:
        """Extract the first markdown heading (line starting with #) from the file."""
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except Exception:
            return None
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("#").strip() or None
        return None

    def get_command_labels(self) -> List[str]:
        """Return labeled entries, e.g. (command: Fix Impact Analysis) /check-fix."""
        labels: List[str] = []
        for command_id, entry in self.entries.items():
            entry_type = entry["type"]
            title = self._extract_title(entry["path"])
            if title:
                labels.append(f"({entry_type}: {title}) /{command_id}")
            else:
                labels.append(f"({entry_type}) /{command_id}")
        return labels

    def resolve_slash_command(self, text: str) -> str:
        """Resolve a slash command to an @path reference.

        If text starts with /command, replace with @<path-to-md> [args].
        Unknown commands and non-slash text pass through unchanged.
        """
        if not text.startswith("/"):
            return text

        match = re.match(r'^/(\S+)(?:\s+(.*))?$', text, re.DOTALL)
        if not match:
            return text

        command_id = match.group(1)
        args_text = match.group(2) or ""

        if command_id not in self.entries:
            logger.debug(f"/{command_id} not found in entries, passing through")
            return text

        entry = self.entries[command_id]
        path = entry["path"]
        logger.info(f"Resolving /{command_id} -> @{path}")

        if args_text:
            return f"@{path} {args_text}"
        return f"@{path}"
