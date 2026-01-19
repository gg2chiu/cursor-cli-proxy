# Cursor CLI Proxy

A FastAPI-based proxy server that provides an OpenAI-compatible API interface for the Cursor AI agent CLI tool. This allows you to integrate Cursor's AI capabilities into any application that supports the OpenAI API format.

## Features

- 🔄 **OpenAI API Compatibility**: Drop-in replacement for OpenAI API endpoints
- 💬 **Intelligent Session Management**: Automatically tracks conversation context using hash-based session matching
- 🔀 **Streaming Support**: Real-time streaming responses using Server-Sent Events (SSE)
- 🎯 **Dynamic Model Registry**: Fetch and cache available models from cursor-agent
- 🔐 **Flexible Authentication**: Support for both Authorization headers and environment variables
- 📝 **Structured Logging**: JSON-formatted logs for easy parsing and monitoring
- ⚙️ **Environment Configuration**: Customize settings via `.env` file

## Prerequisites

- Python 3.8 or higher
- [cursor-agent](https://www.cursor.com/) CLI tool installed and available in PATH
- Valid Cursor API key (if required by your cursor-agent installation)

## Installation

1. Clone the repository:

```bash
git clone <repository-url>
cd cursor-cli-proxy
```

2. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Create a `.env` file for configuration:

```bash
cp .env.example .env  # If example exists, or create new file
```

## Configuration

Configure the relay server using environment variables or a `.env` file in the project root:

| Variable | Default | Description |
|----------|---------|-------------|
| `CURSOR_BIN` | `cursor-agent` | Path to cursor-agent executable |
| `CURSOR_KEY` | `None` | Default Cursor API key (optional) |
| `CURSOR_RELAY_BASE` | `/tmp/.cursor-relay` | Base directory for session workspaces |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `WORKSPACE_WHITELIST` | `None` | Comma-separated list of allowed workspace paths |

Example `.env` file:

```env
CURSOR_BIN=cursor-agent
CURSOR_KEY=your-cursor-api-key-here
HOST=127.0.0.1
PORT=8000
LOG_LEVEL=INFO
WORKSPACE_WHITELIST=/home/user/projects,/opt/workspace
```

### Custom Workspace Support

Clients can specify a custom workspace directory in the system prompt using the `<workspace>` tag:

```json
{
  "messages": [
    {
      "role": "system",
      "content": "<workspace>/home/user/projects/my-app</workspace>\nYou are a helpful assistant."
    },
    {"role": "user", "content": "Hello!"}
  ]
}
```

The workspace path must be:
- An **absolute path**
- In the `WORKSPACE_WHITELIST` (exact match or subdirectory)

If validation fails, the tag is ignored and the default workspace is used. The `<workspace>` tag is automatically removed from the message before sending to cursor-agent.

## Usage

### Starting the Server

Start the relay server:

```bash
python -m src.main
```

The server will be available at `http://localhost:8000` (or your configured HOST:PORT).

### Development Mode with Auto-Reload

For development, enable auto-reload on code changes:

```bash
python -m src.main --reload
```

### Command Line Options

#### Update Model List

Fetch the latest available models from cursor-agent and update the cache:

```bash
python -m src.main --update-model
```

This command will:
- Query cursor-agent for available models
- Update `models.json` cache file
- Exit after completion

#### Clear Session Data

Remove all session data and workspace directories:

```bash
python -m src.main --clear
```

This command will:
- Clear `sessions.json` (reset to empty)
- Remove `sessions.json.lock` file
- Delete the entire `CURSOR_RELAY_BASE` directory
- Exit after completion

**⚠️ Warning**: This operation is irreversible!

## API Endpoints

### Chat Completions

Create a chat completion using the OpenAI-compatible format.

**Endpoint**: `POST /v1/chat/completions`

**Headers**:
```
Authorization: Bearer YOUR_CURSOR_API_KEY
Content-Type: application/json
```

**Request Body**:
```json
{
  "model": "claude-3.5-sonnet",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello, how are you?"}
  ],
  "stream": false
}
```

**Response** (non-streaming):
```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "claude-3.5-sonnet",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "I'm doing well, thank you for asking!"
      },
      "finish_reason": "stop"
    }
  ]
}
```

**Streaming Response** (when `stream: true`):
```
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"claude-3.5-sonnet","choices":[{"index":0,"delta":{"content":"Hello"}}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"claude-3.5-sonnet","choices":[{"index":0,"delta":{"content":"!"}}]}

data: [DONE]
```

### List Models

Get a list of available models.

**Endpoint**: `GET /v1/models`

**Headers**:
```
Authorization: Bearer YOUR_CURSOR_API_KEY
```

**Response**:
```json
{
  "object": "list",
  "data": [
    {
      "id": "claude-3.5-sonnet",
      "object": "model",
      "created": 1234567890,
      "owned_by": "cursor"
    },
    {
      "id": "gpt-4o",
      "object": "model",
      "created": 1234567890,
      "owned_by": "cursor"
    }
  ]
}
```

## Session Management

The relay server implements intelligent session management to bridge the gap between OpenAI's stateless API and Cursor's stateful CLI:

### How It Works

1. **Hash-Based Matching**: Each conversation history is hashed using SHA-256
2. **Session Creation**: New conversations create a new session with a unique ID
3. **Session Resumption**: Subsequent requests with matching history resume the existing session
4. **Context Optimization**: 
   - New sessions receive the full message history
   - Resumed sessions only receive the latest message (context is already loaded)

### Session Storage

Sessions are stored in `sessions.json` in the project root:

```json
{
  "sessions": {
    "abc123...": {
      "session_id": "session-uuid-...",
      "history_hash": "abc123...",
      "title": "Hello, how are you?",
      "workspace_dir": "/tmp/.cursor-relay/session-uuid-...",
      "created_at": "2026-01-07T10:30:00Z",
      "updated_at": "2026-01-07T10:35:00Z"
    }
  }
}
```

### Session Lifecycle

```
Request → Hash History → Match Found?
                          ├─ Yes → Resume Session → Send Last Message Only
                          └─ No  → Create Session → Send Full History
                                                  ↓
                                          Get Response
                                                  ↓
                                       Update Hash (includes new turn)
```

## Using with OpenAI SDKs

### Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-cursor-api-key"
)

response = client.chat.completions.create(
    model="claude-3.5-sonnet",
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)

print(response.choices[0].message.content)
```

### Node.js

```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'your-cursor-api-key',
});

const response = await client.chat.completions.create({
  model: 'claude-3.5-sonnet',
  messages: [
    { role: 'user', content: 'Hello!' }
  ],
});

console.log(response.choices[0].message.content);
```

### cURL

```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer your-cursor-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3.5-sonnet",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": false
  }'
```

## Development

### Project Structure

```
cursor-cli-proxy/
├── src/
│   ├── main.py              # FastAPI application and entry point
│   ├── config.py            # Configuration and settings
│   ├── models.py            # Pydantic data models
│   ├── relay.py             # Command builder and executor
│   ├── model_registry.py    # Model list management
│   └── session_manager.py   # Session tracking and persistence
├── tests/                   # Test suite
├── specs/                   # Feature specifications
├── requirements.txt         # Python dependencies
├── .env                     # Environment configuration (create this)
├── sessions.json            # Session storage (auto-generated)
└── models.json              # Model cache (auto-generated)
```

### Running Tests

First, ensure test dependencies are installed:

```bash
pip install -e ".[test]"
```

Then run the tests:

```bash
pytest
```

### Logging

The server outputs structured JSON logs to stdout:

```json
{
  "text": "Received chat completion request for model: claude-3.5-sonnet, stream=False",
  "record": {
    "elapsed": {...},
    "exception": null,
    "extra": {},
    "file": {"name": "main.py", "path": "..."},
    "function": "chat_completions",
    "level": {"icon": "ℹ️", "name": "INFO", "no": 20},
    "line": 47,
    "message": "Received chat completion request for model: claude-3.5-sonnet, stream=False",
    "module": "main",
    "name": "src.main",
    "process": {"id": 12345, "name": "MainProcess"},
    "thread": {"id": 67890, "name": "MainThread"},
    "time": {"repr": "2026-01-07 10:30:00.123456+08:00", "timestamp": 1736218200.123456}
  }
}
```

## Troubleshooting

### cursor-agent not found

If you see `cursor-agent binary not found`, ensure:
1. cursor-agent is installed: Check Cursor app documentation
2. It's in your PATH: `which cursor-agent` or `where cursor-agent`
3. Or set `CURSOR_BIN` to the full path in `.env`

### Authentication errors

If you receive 401 errors:
1. Verify your Cursor API key is valid
2. Check the `Authorization` header format: `Bearer YOUR_KEY`
3. Or set `CURSOR_KEY` in `.env` to use as default

### Session issues

If conversations aren't resuming correctly:
1. Clear session data: `python -m src.main --clear`
2. Check `sessions.json` for corruption
3. Ensure the `CURSOR_RELAY_BASE` directory (default: `/tmp/.cursor-relay`) has write permissions

## License

[Your License Here]

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Support

For issues and questions, please open an issue on the GitHub repository.

