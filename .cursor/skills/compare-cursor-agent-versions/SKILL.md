---
name: compare-cursor-agent-versions
description: Compare cursor-agent help outputs between different versions to identify new or changed features, options, and commands. Use when the user asks about cursor-agent version differences, what's new, changelog, or comparing cursor-agent versions.
---

# Compare cursor-agent Versions

## Overview

This skill helps identify changes between cursor-agent versions by comparing their help outputs. Default behavior compares the latest two versions unless specified otherwise.

## Finding Versions

Versions are stored in `~/.local/share/cursor-agent/versions/` with format `YYYY.MM.DD-hash`.

List all versions sorted by date:
```bash
ls -t ~/.local/share/cursor-agent/versions/
```

Find current active version:
```bash
ls -l $(which cursor-agent)
```

## Comparison Workflow

### 1. Determine versions to compare

**Default**: Latest two versions
```bash
versions=($(ls -t ~/.local/share/cursor-agent/versions/ | head -2))
newer="${versions[0]}"
older="${versions[1]}"
```

**User-specified**: Accept version strings from user (e.g., "2026.01.23-916f423")

### 2. Extract help output

Run help for each version:
```bash
~/.local/share/cursor-agent/versions/$VERSION/cursor-agent help
```

### 3. Compare and analyze

Use the comparison script:
```bash
python3 scripts/compare_help.py --older "$older" --newer "$newer"
```

Or manually compare by:
1. Extract Options sections
2. Extract Commands sections
3. Identify additions, removals, and modifications

## Output Format

Present changes as:

```markdown
## cursor-agent 版本比較

**舊版本**: YYYY.MM.DD-hash
**新版本**: YYYY.MM.DD-hash

### 新增選項 (Added Options)
- `--option-name`: Description

### 新增命令 (Added Commands)
- `command-name`: Description

### 移除選項 (Removed Options)
- `--option-name`: Description

### 移除命令 (Removed Commands)
- `command-name`: Description

### 修改 (Modified)
- `--option-name`: Description changed from X to Y
```

If no changes detected, report:
```markdown
## cursor-agent 版本比較

**舊版本**: YYYY.MM.DD-hash
**新版本**: YYYY.MM.DD-hash

**結果**: 這兩個版本的 help 輸出完全相同，沒有發現功能變更。
```

## Edge Cases

### Version not found
If specified version doesn't exist, list available versions and ask user to choose.

### Same version
If user specifies same version twice, explain and offer to compare with next older version.

### Help command fails
If `cursor-agent help` fails, report error and suggest checking version integrity.

## Examples

**Example 1**: Compare latest two versions
```
User: "比較最新兩個 cursor-agent 版本"
Action: Auto-detect and compare top 2 versions from ls -t
```

**Example 2**: Compare specific versions
```
User: "比較 2026.01.23-916f423 和 2025.11.25-d5b3271"
Action: Compare those specific versions
```

**Example 3**: Compare with older version
```
User: "cursor-agent 新增了什麼功能？"
Action: Compare latest with previous version (default behavior)
```

## Key Changes to Look For

When analyzing differences, focus on:
- **New flags/options**: Additional configuration options
- **Removed flags/options**: Deprecated features
- **New commands**: Additional subcommands
- **Removed commands**: Deprecated subcommands
- **Modified descriptions**: Changed behavior or documentation
- **Default value changes**: Different default settings

## Tips

- Always show version identifiers (YYYY.MM.DD-hash) in output
- Highlight breaking changes (removed options/commands)
- Group related changes together
