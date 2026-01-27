# Examples

## Example 1: Compare Latest Two Versions

**User request**: "比較最新兩個 cursor-agent 版本"

**Steps**:
1. Get latest two versions:
```bash
versions=($(ls -t ~/.local/share/cursor-agent/versions/ | head -2))
older="${versions[1]}"
newer="${versions[0]}"
```

2. Run comparison:
```bash
cd ~/.cursor/skills/compare-cursor-agent-versions
python3 scripts/compare_help.py --older "$older" --newer "$newer"
```

**Sample output**:
```
## cursor-agent 版本比較

**舊版本**: 2026.01.23-6b6776e
**新版本**: 2026.01.23-916f423

**結果**: 這兩個版本的 help 輸出完全相同，沒有發現功能變更。
```

## Example 2: Compare Specific Versions

**User request**: "比較 2025.11.25-d5b3271 和 2026.01.23-916f423"

**Steps**:
```bash
cd ~/.cursor/skills/compare-cursor-agent-versions
python3 scripts/compare_help.py --older 2025.11.25-d5b3271 --newer 2026.01.23-916f423
```

**Sample output**:
```
## cursor-agent 版本比較

**舊版本**: 2025.11.25-d5b3271
**新版本**: 2026.01.23-916f423

### 新增選項 (Added Options)

- `--continue`: Resume the last chat session (default: false)
- `--list-models`: List available models and exit (default: false)
- `--mode`: Start in the given execution mode...
- `--plan`: Start in plan mode (shorthand for --mode=plan)...
- `--sandbox`: Explicitly enable or disable sandbox mode...

### 新增命令 (Added Commands)

- `about`: Display version, system, and account information
- `generate-rule|rule`: Generate a new Cursor rule with interactive
- `models`: List available models for this account
```

## Example 3: Version Across Major Updates

**User request**: "cursor-agent 從 2025 年 8 月到現在新增了什麼功能？"

**Steps**:
1. Find oldest version from August 2025:
```bash
ls -t ~/.local/share/cursor-agent/versions/ | grep "^2025.08" | tail -1
# Result: 2025.08.15-dbc8d73
```

2. Get latest version:
```bash
ls -t ~/.local/share/cursor-agent/versions/ | head -1
# Result: 2026.01.23-916f423
```

3. Run comparison:
```bash
python3 scripts/compare_help.py --older 2025.08.15-dbc8d73 --newer 2026.01.23-916f423
```

## Example 4: Invalid Version Handling

**User request**: "比較 2025.99.99-invalid 和最新版本"

**Script output**:
```
錯誤: Version not found: 2025.99.99-invalid

可用版本:
  - 2026.01.23-916f423
  - 2026.01.23-6b6776e
  - 2026.01.17-d239e66
  ...
```

**Agent response**: 列出可用版本並請使用者選擇正確的版本。

## Example 5: Manual Comparison (Without Script)

If the script fails, compare manually:

```bash
# Get help outputs
~/.local/share/cursor-agent/versions/2025.11.25-d5b3271/cursor-agent help > /tmp/old.txt
~/.local/share/cursor-agent/versions/2026.01.23-916f423/cursor-agent help > /tmp/new.txt

# Use diff to compare
diff -u /tmp/old.txt /tmp/new.txt
```

Analyze the diff output:
- Lines starting with `+` are added in newer version
- Lines starting with `-` are removed in newer version
- Focus on Options and Commands sections
