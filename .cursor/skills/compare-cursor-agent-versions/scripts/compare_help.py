#!/usr/bin/env python3
"""
Compare cursor-agent help outputs between two versions.
"""

import argparse
import subprocess
import sys
from pathlib import Path
import re

VERSIONS_DIR = Path.home() / ".local/share/cursor-agent/versions"


def get_help_output(version: str) -> str:
    """Get help output for a specific version."""
    cursor_agent_path = VERSIONS_DIR / version / "cursor-agent"
    
    if not cursor_agent_path.exists():
        raise FileNotFoundError(f"Version not found: {version}")
    
    try:
        result = subprocess.run(
            [str(cursor_agent_path), "help"],
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"Help command timed out for version: {version}")
    except Exception as e:
        raise RuntimeError(f"Failed to run help for {version}: {e}")


def parse_help_output(help_text: str) -> dict:
    """Parse help output into structured data."""
    data = {
        "options": {},
        "commands": {}
    }
    
    # Extract options section
    options_match = re.search(r'Options:(.*?)(?=Commands:|$)', help_text, re.DOTALL)
    if options_match:
        options_text = options_match.group(1)
        # Match option lines like: -p, --print  Description (default: false)
        for match in re.finditer(r'^\s+(-[a-zA-Z],\s+)?--([a-z-]+)(?:\s+<[^>]+>)?\s+(.*?)(?=\n\s+(?:-|$)|\Z)', options_text, re.MULTILINE | re.DOTALL):
            option_name = match.group(2)
            description = match.group(3).strip().replace('\n', ' ')
            data["options"][option_name] = description
    
    # Extract commands section
    commands_match = re.search(r'Commands:(.*?)$', help_text, re.DOTALL)
    if commands_match:
        commands_text = commands_match.group(1)
        # Match command lines like: install-shell-integration  Description
        for match in re.finditer(r'^\s+([a-z-]+(?:\|[a-z-]+)?)\s+(.+?)(?=\n\s+[a-z]|\Z)', commands_text, re.MULTILINE | re.DOTALL):
            command_name = match.group(1)
            description = match.group(2).strip().replace('\n', ' ')
            data["commands"][command_name] = description
    
    return data


def compare_sections(older: dict, newer: dict, section: str) -> dict:
    """Compare a specific section between two versions."""
    older_items = set(older[section].keys())
    newer_items = set(newer[section].keys())
    
    added = newer_items - older_items
    removed = older_items - newer_items
    common = older_items & newer_items
    
    modified = {}
    for item in common:
        if older[section][item] != newer[section][item]:
            modified[item] = {
                "old": older[section][item],
                "new": newer[section][item]
            }
    
    return {
        "added": {k: newer[section][k] for k in sorted(added)},
        "removed": {k: older[section][k] for k in sorted(removed)},
        "modified": modified
    }


def format_output(older_version: str, newer_version: str, changes: dict) -> str:
    """Format comparison results."""
    output = []
    output.append("## cursor-agent 版本比較\n")
    output.append(f"**舊版本**: {older_version}")
    output.append(f"**新版本**: {newer_version}\n")
    
    has_changes = False
    
    # Options
    if changes["options"]["added"]:
        has_changes = True
        output.append("### 新增選項 (Added Options)\n")
        for opt, desc in changes["options"]["added"].items():
            output.append(f"- `--{opt}`: {desc}")
        output.append("")
    
    if changes["options"]["removed"]:
        has_changes = True
        output.append("### 移除選項 (Removed Options)\n")
        for opt, desc in changes["options"]["removed"].items():
            output.append(f"- `--{opt}`: {desc}")
        output.append("")
    
    if changes["options"]["modified"]:
        has_changes = True
        output.append("### 修改選項 (Modified Options)\n")
        for opt, descs in changes["options"]["modified"].items():
            output.append(f"- `--{opt}`:")
            output.append(f"  - 舊: {descs['old']}")
            output.append(f"  - 新: {descs['new']}")
        output.append("")
    
    # Commands
    if changes["commands"]["added"]:
        has_changes = True
        output.append("### 新增命令 (Added Commands)\n")
        for cmd, desc in changes["commands"]["added"].items():
            output.append(f"- `{cmd}`: {desc}")
        output.append("")
    
    if changes["commands"]["removed"]:
        has_changes = True
        output.append("### 移除命令 (Removed Commands)\n")
        for cmd, desc in changes["commands"]["removed"].items():
            output.append(f"- `{cmd}`: {desc}")
        output.append("")
    
    if changes["commands"]["modified"]:
        has_changes = True
        output.append("### 修改命令 (Modified Commands)\n")
        for cmd, descs in changes["commands"]["modified"].items():
            output.append(f"- `{cmd}`:")
            output.append(f"  - 舊: {descs['old']}")
            output.append(f"  - 新: {descs['new']}")
        output.append("")
    
    if not has_changes:
        output.append("**結果**: 這兩個版本的 help 輸出完全相同，沒有發現功能變更。\n")
    
    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(description="Compare cursor-agent help outputs")
    parser.add_argument("--older", required=True, help="Older version (YYYY.MM.DD-hash)")
    parser.add_argument("--newer", required=True, help="Newer version (YYYY.MM.DD-hash)")
    
    args = parser.parse_args()
    
    try:
        # Get help outputs
        older_help = get_help_output(args.older)
        newer_help = get_help_output(args.newer)
        
        # Parse outputs
        older_data = parse_help_output(older_help)
        newer_data = parse_help_output(newer_help)
        
        # Compare
        changes = {
            "options": compare_sections(older_data, newer_data, "options"),
            "commands": compare_sections(older_data, newer_data, "commands")
        }
        
        # Format and print
        result = format_output(args.older, args.newer, changes)
        print(result)
        
    except FileNotFoundError as e:
        print(f"錯誤: {e}", file=sys.stderr)
        print(f"\n可用版本:", file=sys.stderr)
        if VERSIONS_DIR.exists():
            for version in sorted(VERSIONS_DIR.iterdir(), reverse=True):
                if version.is_dir():
                    print(f"  - {version.name}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"錯誤: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
