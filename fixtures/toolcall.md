# Tool Verification Prompt

Run the following verification steps in order. Each step MUST actually invoke the corresponding tool:

0. **TodoWrite** — Create 11 todo items as below and update their status as you progress.
1. **Shell** — Run `mkdir -p /tmp/tv && echo done`.
2. **Write** — Create `/tmp/tv/a.txt` with the content `hello`.
3. **Read** — Read `/tmp/tv/a.txt`.
4. **StrReplace** — Replace `hello` with `HELLO` in `/tmp/tv/a.txt`.
5. **Glob** — Find `/tmp/tv/*.txt`.
6. **Grep** — Search for `HELLO` under `/tmp/tv`.
7. **Delete** — Delete `/tmp/tv/a.txt`.
8. **WebSearch** — Query `FastAPI latest version`.
9. **WebFetch** — Fetch `https://example.com`.
10. **Task (generalPurpose)** — Dispatch a small task: report the current git branch.
11. **Task (cursor-guide)** — Ask: "How do I configure the statusline in Cursor CLI?"


## Constraints

- Do NOT commit, push, or modify git config.
- Do NOT create or update any pull requests.
- Read-only operations only on remote resources.
