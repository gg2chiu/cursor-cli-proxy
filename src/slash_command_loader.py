import os
import re
from html import escape as xml_escape
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

    def _parse_frontmatter(self, filepath: str) -> Optional[Dict[str, str]]:
        """Extract name and description from YAML frontmatter (--- delimited block).

        Returns a dict with 'name' and/or 'description' keys, or None if no frontmatter.
        """
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except Exception:
            return None

        # Match YAML frontmatter block: starts and ends with ---
        fm_match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if not fm_match:
            return None

        fm_text = fm_match.group(1)
        result: Dict[str, str] = {}

        for line in fm_text.splitlines():
            # Match key: value (with optional quotes around value)
            kv_match = re.match(r'^(\w+)\s*:\s*(.+)$', line.strip())
            if kv_match:
                key = kv_match.group(1)
                value = kv_match.group(2).strip()
                # Strip surrounding quotes if present
                if (value.startswith('"') and value.endswith('"')) or \
                   (value.startswith("'") and value.endswith("'")):
                    value = value[1:-1]
                result[key] = value

        return result if result else None

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

        # Extract description: prefer frontmatter, fall back to first heading
        description = None
        frontmatter = self._parse_frontmatter(path)
        if frontmatter and "description" in frontmatter:
            description = frontmatter["description"]
        else:
            title = self._extract_title(path)
            if title:
                description = title

        self.entries[command_id] = {"path": path, "type": entry_type, "description": description}
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

    def get_skills_metadata_xml(self) -> str:
        """Generate an <available_skills> XML block listing all entries with metadata.

        Each entry uses its type as the XML tag name (e.g. <skill>, <command>, <agent>)
        instead of a generic tag with a <type> child. Returns empty string if
        no entries are loaded.
        """
        if not self.entries:
            return ""

        lines = ["<available_skills>"]
        for command_id, entry in self.entries.items():
            entry_type = entry["type"]
            description = xml_escape(entry.get("description") or "")
            name = xml_escape(command_id)
            location = xml_escape(entry["path"])
            lines.append(f"  <{entry_type}>")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{description}</description>")
            lines.append(f"    <location>{location}</location>")
            lines.append(f"  </{entry_type}>")
        lines.append("</available_skills>")

        return "\n".join(lines)

    def resolve_slash_command(self, text: str) -> str:
        """Resolve a slash command to an @path reference.

        If text starts with /command, replace with
        "Use this <type> @<path-to-md> [args]" where <type> is
        skill, command, or agent depending on the entry type.
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
        entry_type = entry["type"]
        logger.info(f"Resolving /{command_id} -> @{path}")

        if args_text:
            return f"Use this {entry_type} @{path} {args_text}"
        return f"Use this {entry_type} @{path}"
