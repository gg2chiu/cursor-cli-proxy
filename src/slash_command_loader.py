import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from loguru import logger


class SlashCommandLoader:
    """Load and expand custom slash commands from .cursor/commands and .claude/commands."""

    def __init__(self, workspace_dir: Optional[str] = None):
        self.workspace_dir = workspace_dir or os.getcwd()
        self.commands: Dict[str, str] = {}
        self._load_commands()

    def _load_commands(self):
        """Load commands in priority order: workspace-claude < workspace-cursor < user-claude < user-cursor."""
        search_paths = [
            Path(self.workspace_dir) / ".claude" / "commands",
            Path(self.workspace_dir) / ".cursor" / "commands",
            Path.home() / ".claude" / "commands",
            Path.home() / ".cursor" / "commands",
        ]

        for commands_dir in search_paths:
            if commands_dir.exists() and commands_dir.is_dir():
                self._load_from_directory(commands_dir)

    def _load_from_directory(self, directory: Path):
        """Load all .md files in the directory as slash commands."""
        try:
            for md_file in directory.glob("*.md"):
                command_id = md_file.stem
                try:
                    content = md_file.read_text(encoding="utf-8").strip()
                    if content:
                        self.commands[command_id] = content
                        logger.debug(f"Loaded slash command: /{command_id} from {md_file}")
                except Exception as e:
                    logger.warning(f"Failed to load command from {md_file}: {e}")
        except Exception as e:
            logger.warning(f"Failed to read commands directory {directory}: {e}")

    def _extract_title(self, content: str) -> Optional[str]:
        """Extract a title from command content (prefer first markdown heading)."""
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                return line.lstrip("#").strip() or None
            return line
        return None

    def get_command_labels(self) -> List[str]:
        """Return labeled slash commands, e.g. (Fix Impact Analysis) /check-fix."""
        labels: List[str] = []
        for command_id, content in self.commands.items():
            title = self._extract_title(content or "")
            if title:
                labels.append(f"({title}) /{command_id}")
            else:
                labels.append(f"/{command_id}")
        return labels

    def expand_slash_command(self, text: str) -> str:
        """
        Expand a slash command. If text starts with /command, replace it with command content.
        Supports parameter replacement: $ARGUMENTS, $1, $2, ...
        """
        if not text.startswith("/"):
            return text

        match = re.match(r'^/(\S+)(?:\s+(.*))?$', text, re.DOTALL)
        if not match:
            return text

        command_id = match.group(1)
        args_text = match.group(2) or ""

        if command_id not in self.commands:
            logger.debug(f"Slash command /{command_id} not found in custom commands, passing through")
            return text

        template = self.commands[command_id]
        logger.info(f"Expanding slash command: /{command_id}")

        args_list = args_text.split() if args_text else []

        result = template.replace("$ARGUMENTS", args_text)

        for i in range(len(args_list), 0, -1):
            result = result.replace(f"${i}", args_list[i - 1])

        has_placeholders = "$ARGUMENTS" in template or any(
            f"${i}" in template for i in range(1, len(args_list) + 1)
        )
        if not has_placeholders and args_text:
            result = f"{result}\n\n{args_text}"

        logger.debug(f"Expanded /{command_id} to {len(result)} characters")
        return result
