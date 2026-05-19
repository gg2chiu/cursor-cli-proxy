# cursor-agent CLI Authentication Quirks

Notes on unexpected interactions between `cursor-agent`'s `--api-key`,
`--list-models` / `models`, and `-p` flags, plus where the auth token is
actually stored on disk.

- Tested version: `cursor-agent 2026.05.16-0338208`
- Platform: Linux (Ubuntu 24.04)
- Date: 2026-05-19
- Binary path: `~/.local/share/cursor-agent/versions/2026.05.16-0338208/cursor-agent`

## TL;DR

| Subcommand | Does it validate `--api-key`? | Does it persist auth token locally? |
|---|---|---|
| `models` / `--list-models` | **No** — flag is ignored | No |
| `-p "..."` | **Yes** — key must be valid | Yes, written on success |
| Interactive mode (no `-p`) | (Not tested; expected to behave like `-p`) | Same as `-p` |

- The real auth token lives at `~/.config/cursor/auth.json` (**lowercase** `cursor`).
- `~/.cursor/cli-config.json` only stores `serverConfigCache.authCacheKey`
  (a cache key), **not the token itself**.
- `--list-models` only reads local auth state; **it never uses `--api-key`
  to trigger a login**.

## 1. `--list-models` completely ignores `--api-key`

### Steps and output

Source: `terminals/5.txt` (trimmed)

```
# Check login state
❯ agent status
✓ Logged in as george.chiu@ruckusnetworks.com

# Log out
❯ agent logout
Preparing to log out...
Logging out...
✓ Logout successful
Authentication tokens removed.

# While logged out, run --list-models with a valid full key -> fails
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743eeee7864e76c1b231d --list-models
No models available for this account.

# Same key, try again -> still fails
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743eeee7864e76c1b231d --list-models
No models available for this account.

# Same key with -p -> succeeds AND persists the token locally
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743eeee7864e76c1b231d -p "Hi"
Hello! How can I help you?

# Re-run --list-models -> now it prints the full model list
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743eeee7864e76c1b231d --list-models
Available models

auto - Auto
composer-2-fast - Composer 2 Fast (default)
composer-2 - Composer 2
...
```

### Finding 1

For the `--list-models` / `models` subcommand, the `--api-key` flag is a
**no-op**: it does not authenticate against the backend, does not create
a session, and does not persist any auth state. **It only reads whatever
local auth state already exists** (i.e. `~/.config/cursor/auth.json`).

## 2. `--list-models` happily accepts fake / invalid keys

Source: second experiment (user query at 4:20pm)

```
# Valid full key + -p -> logs in and persists the token
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743eeee7864e76c1b231d -p "Hi"
Hello! How can I help you?

# Truncated (INVALID) key + --list-models -> STILL returns the full model list!
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743ee --list-models
Available models
auto - Auto
composer-2-fast - Composer 2 Fast (default)
...

# Same INVALID key + -p -> rejected immediately
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743ee -p "Hello"
⚠ Warning: The provided API key is invalid.
Please check you have the right key, create a new one, or authenticate without it.

# Same INVALID key + --list-models again -> still succeeds
❯ agent --api-key crsr_d3f58a4ea3b7a1a4ebeb1e19d10c5b4d8db294deda8743ee --list-models
Available models
auto - Auto
...

# No --api-key at all + -p -> also succeeds (uses persisted local token)
❯ agent -p "Hello"
Hello! How can I help you?
```

### Finding 2

`--list-models` returns the full model list even when given an invalid
key, because it **does not check `--api-key` at all** — it only reads
local auth state.

Only `-p` validates the key in real time (message:
`⚠ Warning: The provided API key is invalid.`).

## 3. Where the auth token actually lives

### Method

```bash
strace -f -e trace=openat,unlink,write -o /tmp/agent_strace.log \
  agent --api-key crsr_invalid_xxx -p "ping"
```

Pull out the `/home/gchiu/...` paths cursor-agent touches at startup
(filtering out node_modules, the binary itself, locale files, `*.so`,
etc.).

### Key strace excerpt

```
openat(AT_FDCWD, "/home/gchiu/.config/cursor/auth.json", O_RDONLY|O_CLOEXEC) = -1 ENOENT
openat(AT_FDCWD, "/home/gchiu/.config/cursor/auth.json", O_RDONLY|O_CLOEXEC) = -1 ENOENT
openat(AT_FDCWD, "/home/gchiu/.cursor/cli-config.json", O_RDONLY|O_CLOEXEC) = 29
openat(AT_FDCWD, "/home/gchiu/.cursor/statsig-cache.json", O_RDONLY|O_CLOEXEC) = 29
```

(The process was logged out at the time, so `auth.json` is ENOENT.)

### Three directories that are easy to confuse

| Path | Owner | Contents |
|---|---|---|
| `~/.config/cursor/` (**lowercase**) | cursor-agent CLI | `auth.json` (**token itself**), `prompt_history.json` |
| `~/.config/Cursor/` (capital C) | Cursor IDE desktop app | Electron app data, `User/globalStorage/state.vscdb` |
| `~/.cursor/` | Shared | `cli-config.json`, `agent-cli-state.json`, `statsig-cache.json`, `chats/`, `projects/`, `plans/`, ... |

In `~/.cursor/cli-config.json`, the value
`serverConfigCache.authCacheKey: "auth:auth0|user_..."` is only a
**cache key (identifier)** for the token — the token body is not stored
there.

The `agent logout` message
"✓ Logout successful / Authentication tokens removed." corresponds to
deleting `~/.config/cursor/auth.json`.

### Quick verification script

```bash
ls -la ~/.config/cursor/        # Before login (no auth.json)
agent --api-key crsr_xxx -p "Hi"
ls -la ~/.config/cursor/        # After login an auth.json appears
agent logout
ls -la ~/.config/cursor/        # auth.json is removed
```

## 4. Impact on this project

### 4.1 `src/model_registry.py::fetch_models()` fails on a clean environment

Current implementation:

```python
cmd = [CURSOR_BIN, "models"]
key_to_use = api_key or config.CURSOR_KEY
if key_to_use:
    cmd.extend(['--api-key', key_to_use])
result = subprocess.run(cmd, capture_output=True, text=True, check=False)
```

Based on the observations above, this command will always print
`No models available for this account.` whenever
`~/.config/cursor/auth.json` does not exist (for example, a freshly
built Docker container, a CI runner, or a host that has just run
`agent logout`). `_parse_models()` will treat that as empty output and
fall back to `default_models` (only 4 models).

Worse is the "false success" case: if the environment already has an
`auth.json` left over from another user, `models` will happily print
that other user's model list, even when the `CURSOR_KEY` we pass in is
wrong.

### 4.2 Proposed two-stage fix

Not implemented in this note — recording the direction only:

1. **Ping stage**: if `key_to_use` is non-empty, first run
   `agent --api-key <key> -p "ping"` to write the token into
   `~/.config/cursor/auth.json`, and inspect stdout/stderr for
   `The provided API key is invalid.`. If invalid, fall back
   immediately and do not proceed.
2. **Fetch stage**: run `agent models` (no need to pass `--api-key`
   since it is ignored).

### 4.3 Docker / containerization notes

To preserve cursor-agent's login state inside a container, mount
`~/.config/cursor/` (lowercase), **not** `~/.cursor/`:

```yaml
# docker-compose.yml example
volumes:
  - ~/.config/cursor:/root/.config/cursor   # <- token lives here
  - ~/.cursor/cli-config.json:/root/.cursor/cli-config.json:ro  # optional: server config cache
```

Mounting only `~/.cursor/` will not preserve the login state.

## 5. Related artifacts

- `terminals/5.txt`: full console log of `agent status` / `agent logout`
  and the various `--api-key` attempts.
- This file: `fixtures/cursor-agent-auth-quirks.md`.
