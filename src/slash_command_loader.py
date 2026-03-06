import json
import os
import re
from html import escape as xml_escape
from pathlib import Path
from typing import Dict, List, Optional, Sequence
from loguru import logger

PLUGIN_COMMAND_EXTENSIONS = ("*.md", "*.mdc", "*.markdown", "*.txt")


class SlashCommandLoader:
    """Load custom slash commands, skills, and agents from .cursor/, .claude/, and plugin directories.

    Scans plugin, project-level, and user-level directories for:
    - commands: .cursor/commands/*.md, .claude/commands/*.md, plugins commands/
    - skills:   .cursor/skills/**/SKILL.md, .cursor/skills-cursor/**/SKILL.md, plugins skills/
    - agents:   .cursor/agents/**/*.md, plugins agents/

    Instead of expanding command content inline, resolve_slash_command returns
    an @path reference so cursor-agent reads the file directly.
    """

    def __init__(self, workspace_dir: Optional[str] = None):
        self.workspace_dir = workspace_dir or os.getcwd()
        self.entries: Dict[str, Dict[str, str]] = {}
        self._current_plugin_name: Optional[str] = None
        self._current_source: Optional[str] = None
        self._load_all()

    def _load_all(self):
        """Load entries in priority order (later overrides earlier for same command_id).

        Priority:
        1.  User-level plugins (~/.cursor/plugins/cache/, ~/.cursor/plugins/local/)
        2.  Project-level plugins (<workspace>/.cursor/plugins/)
        3.  Project .claude/commands/
        4.  Project .cursor/commands/
        5.  Project .cursor/skills/
        6.  Project .cursor/agents/
        7.  User .claude/commands/
        8.  User .cursor/commands/
        9.  User .cursor/skills/
        10. User .cursor/skills-cursor/
        11. User .cursor/agents/
        """
        workspace = Path(self.workspace_dir)
        home = Path.home()

        # Plugins (lowest priority, source tracked per-plugin via _current_plugin_name)
        self._load_plugins_from(home / ".cursor" / "plugins")
        self._load_plugins_from(workspace / ".cursor" / "plugins")

        # Project-level
        self._current_source = "project"
        self._load_commands_dir(workspace / ".claude" / "commands")
        self._load_commands_dir(workspace / ".cursor" / "commands")
        self._load_skills_dir(workspace / ".cursor" / "skills")
        self._load_agents_dir(workspace / ".cursor" / "agents")

        # User-level
        self._current_source = "user"
        self._load_commands_dir(home / ".claude" / "commands")
        self._load_commands_dir(home / ".cursor" / "commands")
        self._load_skills_dir(home / ".cursor" / "skills")
        self._load_skills_dir(home / ".cursor" / "skills-cursor")
        self._load_agents_dir(home / ".cursor" / "agents")
        self._current_source = None

    def _load_commands_dir(self, directory: Path, extensions: Sequence[str] = ("*.md",)):
        """Load command files directly in the directory. Extensions default to *.md only."""
        if not directory.exists() or not directory.is_dir():
            return
        try:
            seen = set()
            for pattern in extensions:
                for cmd_file in directory.glob(pattern):
                    if cmd_file in seen:
                        continue
                    seen.add(cmd_file)
                    self._register_entry(cmd_file.stem, str(cmd_file), "command")
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

    # ---- Plugin loading ----

    def _load_plugins_from(self, plugins_base: Path):
        """Discover and load all plugins under a plugins base directory.

        Scans cache/, local/, and top-level subdirectories for plugin manifests
        (.cursor-plugin/plugin.json).
        """
        if not plugins_base.exists() or not plugins_base.is_dir():
            return
        for plugin_dir in self._find_plugin_dirs(plugins_base):
            self._load_single_plugin(plugin_dir)

    def _find_plugin_dirs(self, base: Path) -> List[Path]:
        """Recursively find directories containing .cursor-plugin/plugin.json."""
        results: List[Path] = []
        if not base.exists() or not base.is_dir():
            return results
        try:
            for manifest in base.rglob(".cursor-plugin/plugin.json"):
                results.append(manifest.parent.parent)
        except Exception as e:
            logger.warning(f"Failed to scan for plugins in {base}: {e}")
        return results

    def _load_single_plugin(self, plugin_dir: Path):
        """Load commands, skills, and agents from a single plugin directory."""
        manifest_path = plugin_dir / ".cursor-plugin" / "plugin.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Skipping plugin at {plugin_dir}: failed to read manifest: {e}")
            return

        plugin_name = manifest.get("name", plugin_dir.name)
        logger.debug(f"Loading plugin '{plugin_name}' from {plugin_dir}")

        self._current_plugin_name = plugin_name
        try:
            self._load_plugin_component(
                plugin_dir, manifest, "skills", self._load_skills_dir, "skills"
            )
            self._load_plugin_component(
                plugin_dir, manifest, "commands", self._load_plugin_commands_dir, "commands"
            )
            self._load_plugin_component(
                plugin_dir, manifest, "agents", self._load_agents_dir, "agents"
            )
        finally:
            self._current_plugin_name = None

    def _load_plugin_component(self, plugin_dir, manifest, key, loader_fn, default_subdir):
        """Resolve manifest paths (string or list) for a component and invoke the loader."""
        paths_spec = manifest.get(key)
        if paths_spec is None:
            # Fall back to default subdirectory
            default_dir = plugin_dir / default_subdir
            if default_dir.exists():
                loader_fn(default_dir)
            return

        if isinstance(paths_spec, str):
            paths_spec = [paths_spec]

        for rel_path in paths_spec:
            resolved = plugin_dir / rel_path
            if resolved.exists():
                loader_fn(resolved)

    def _load_plugin_commands_dir(self, directory: Path):
        """Load plugin commands with extended extension support."""
        self._load_commands_dir(directory, extensions=PLUGIN_COMMAND_EXTENSIONS)

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

        self.entries[command_id] = {
            "path": path, "type": entry_type, "description": description,
            "plugin": self._current_plugin_name,
            "source": self._current_source,
        }
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
        """Return labeled entries, e.g. (command [superpowers]: Brainstorm) /brainstorm."""
        labels: List[str] = []
        for command_id, entry in self.entries.items():
            entry_type = entry["type"]
            plugin = entry.get("plugin")
            source = entry.get("source")
            origin_tag = f" [{plugin}]" if plugin else (f" [{source}]" if source else "")
            title = self._extract_title(entry["path"])
            if title:
                labels.append(f"({entry_type}{origin_tag}: {title}) /{command_id}")
            else:
                labels.append(f"({entry_type}{origin_tag}) /{command_id}")
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
            plugin = entry.get("plugin")
            source = entry.get("source")
            lines.append(f"  <{entry_type}>")
            lines.append(f"    <name>{name}</name>")
            lines.append(f"    <description>{description}</description>")
            lines.append(f"    <location>{location}</location>")
            if plugin:
                lines.append(f"    <plugin>{xml_escape(plugin)}</plugin>")
            elif source:
                lines.append(f"    <source>{xml_escape(source)}</source>")
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
