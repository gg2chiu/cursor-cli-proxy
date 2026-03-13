# Cursor CLI Proxy

A FastAPI-based proxy server that provides an OpenAI-compatible API interface for the Cursor AI agent CLI tool. This allows you to integrate Cursor's AI capabilities into any application that supports the OpenAI API format.

## Features

- 🔄 **OpenAI API Compatibility**: Drop-in replacement for OpenAI Chat Completions and Responses API endpoints
- 💬 **Intelligent Session Management**: Automatically tracks conversation context using hash-based session matching
- 🔀 **Streaming Support**: Real-time streaming responses using Server-Sent Events (SSE)
- 🎯 **Dynamic Model Registry**: Fetch and cache available models from cursor-agent
- 🔐 **Flexible Authentication**: Support for both Authorization headers and environment variables
- 📝 **Structured Logging**: JSON-formatted logs for easy parsing and monitoring
- ⚙️ **Environment Configuration**: Customize settings via environment variables

## Installation

Clone the repository:

```bash
git clone <repository-url>
cd cursor-cli-proxy
```

### Option 1: Native Installation

#### Prerequisites

- Python 3.8 or higher
- [cursor-agent](https://cursor.com/docs/cli/overview) CLI tool installed and available in PATH


1. Create and activate a virtual environment:

```bash
python -m venv venv
source venv/bin/activate
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the server:

```bash
python -m src.main
```

### Option 2: Docker

The easiest way to run the proxy. Docker handles all dependencies including cursor-agent automatically. Cursor settings (rules, commands) should be project-based, as they will not be copied to the container.

1. Create a `.env` file for configuration:

```bash
cp .env.example .env
# Edit .env with your settings (see Configuration section)
```

2. Start the service:

```bash
docker compose up -d
```

The server will be available at `http://localhost:8000` (or `https://` if HTTPS is enabled).

**Important**: If you use custom workspace paths (`WORKSPACE_WHITELIST_*`), you need to:
1. Uncomment the corresponding volume mount in `docker-compose.yml`
2. Ensure the paths exist on your host system
3. Use absolute paths for the workspace whitelist

#### Docker Commands

```bash
# View logs
docker compose logs -f

# Stop the service
docker compose down

# Rebuild after code changes
docker compose up -d --build

# Update model list
docker compose exec cursor-cli-proxy python -m src.main --update-model

# Clear session data
docker compose exec cursor-cli-proxy python -m src.main --clear
```

#### Data Persistence

The following files are mounted as volumes for persistence:
- `sessions.json` - Session state and conversation history
- `models.json` - Cached model list from cursor-agent

## Configuration

Configure the server using environment variables. All settings have default values defined in `src/config.py`.
You can set them via a `.env` file or your shell environment.

| Variable | Default | Description |
|----------|---------|-------------|
| `CURSOR_KEY` | `None` | Default Cursor API key (optional). ⚠️ **Security Warning**: This proxy does not implement authentication. You must add your own authentication layer (e.g., API keys, OAuth, reverse proxy with auth) before exposing this service with CURSOR_KEY. |
| `HOST` | `127.0.0.1` | Server bind address. Setting this to `0.0.0.0` will expose this service to external connections. |
| `PORT` | `8000` | Server port |
| `LOG_LEVEL` | `INFO` | Logging level (DEBUG, INFO, WARNING, ERROR) |
| `ENABLE_INFO_IN_THINK` | `false` | Output session_id and skills/commands/agents in `<think>` block at start of first response |
| `ENABLE_SKILLS_IN_PROMPT` | `false` | Inject available skills/commands/agents metadata into the system prompt. |
| `ENABLE_HTTPS` | `false` | Enable HTTPS/TLS encryption |
| `HTTPS_CERT_PATH` | `""` | Path to SSL certificate file (required if HTTPS enabled) |
| `HTTPS_KEY_PATH` | `""` | Path to SSL private key file (required if HTTPS enabled) |
| `WORKSPACE_WHITELIST_1` | `None` | First allowed workspace path |
| `WORKSPACE_WHITELIST_2` | `None` | Second allowed workspace path |
| `WORKSPACE_WHITELIST_3` | `None` | Third allowed workspace path |
| `WORKSPACE_WHITELIST_4` | `None` | Fourth allowed workspace path |
| `WORKSPACE_WHITELIST_5` | `None` | Fifth allowed workspace path |

**Note**: `cursor-agent` binary must be available in your system PATH. The temporary directory is fixed at `/tmp/cursor-cli-proxy`.

Example with environment variables:

```bash
CURSOR_KEY=your-key HOST=127.0.0.1 PORT=8000 python -m src.main
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
- In the `WORKSPACE_WHITELIST_*` entries (exact match or subdirectory)

If validation fails, the tag is ignored and the default workspace is used. The `<workspace>` tag is automatically removed from the message before sending to cursor-agent.

### HTTPS Configuration

To enable HTTPS/TLS encryption:

1. **Generate SSL certificates** (choose one method):

   **Option A: Self-signed certificate (development/testing)**
   ```bash
   mkdir -p sslcert
   openssl req -x509 -newkey rsa:4096 -keyout sslcert/key.pem -out sslcert/cert.pem -days 365 -nodes -subj "/CN=localhost"
   ```

   **Option B: Using mkcert (local development, browser-trusted)**
   ```bash
   mkcert -install
   mkdir -p sslcert
   mkcert -key-file sslcert/key.pem -cert-file sslcert/cert.pem localhost 127.0.0.1
   ```

   **Option C: Let's Encrypt (production)**
   ```bash
   sudo certbot certonly --standalone -d your-domain.com
   ```

2. **Configure environment variables** in `.env`:
   ```bash
   ENABLE_HTTPS=true
   HTTPS_CERT_PATH=sslcert/cert.pem
   HTTPS_KEY_PATH=sslcert/key.pem
   ```

3. **Start the server** - it will automatically use HTTPS:
   ```bash
   python -m src.main
   ```

**Note**: When using self-signed certificates, clients may need to disable certificate verification or add the certificate to their trust store.

## Command Line Options

```bash
# Start the server
python -m src.main

# Development mode with auto-reload
python -m src.main --reload

# Fetch latest models from cursor-agent and update cache
python -m src.main --update-model

# Remove all session data and workspace directories (⚠️ irreversible)
python -m src.main --clear
```

## API Endpoints

### Chat Completions

**Endpoint**: `POST /v1/chat/completions`

**Headers**:
```
Authorization: Bearer YOUR_CURSOR_API_KEY
Content-Type: application/json
```

**Request Body**:
```json
{
  "model": "composer-1.5",
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
  "model": "composer-1.5",
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
data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"composer-1.5","choices":[{"index":0,"delta":{"content":"Hello"}}]}

data: {"id":"chatcmpl-...","object":"chat.completion.chunk","created":1234567890,"model":"composer-1.5","choices":[{"index":0,"delta":{"content":"!"}}]}

data: [DONE]
```

### Responses API

**Endpoint**: `POST /v1/responses`

An implementation of the [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create), providing the same core text generation capabilities through a modern, agent-oriented interface. The proxy's `session_id` is used as the `response_id` (prefixed with `resp_`), enabling multi-turn conversations via `previous_response_id`.

Note: It doesn't support `ENABLE_INFO_IN_THINK` yet.

### List Models

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
      "id": "composer-1.5",
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

The proxy implements intelligent session management to bridge the gap between OpenAI's stateless API and Cursor's stateful CLI:

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
      "workspace_dir": "/tmp/cursor-cli-proxy/session-uuid-...",
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

**Chat Completions**:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",  # Use https:// if HTTPS is enabled
    api_key="your-cursor-api-key"
)

response = client.chat.completions.create(
    model="composer-1.5",
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)

print(response.choices[0].message.content)
```

**Responses API**:
```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8000/v1",
    api_key="your-cursor-api-key"
)

response = client.responses.create(
    model="composer-1.5",
    input="Hello!"
)

print(response.output_text)

# Multi-turn follow-up
follow_up = client.responses.create(
    model="composer-1.5",
    input="Tell me more.",
    previous_response_id=response.id
)

print(follow_up.output_text)
```

### Node.js

**Chat Completions**:
```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',  // Use https:// if HTTPS is enabled
  apiKey: 'your-cursor-api-key',
});

const response = await client.chat.completions.create({
  model: 'composer-1.5',
  messages: [
    { role: 'user', content: 'Hello!' }
  ],
});

console.log(response.choices[0].message.content);
```

**Responses API**:
```javascript
import OpenAI from 'openai';

const client = new OpenAI({
  baseURL: 'http://localhost:8000/v1',
  apiKey: 'your-cursor-api-key',
});

const response = await client.responses.create({
  model: 'composer-1.5',
  input: 'Hello!',
});

console.log(response.output_text);
```

### cURL

**Chat Completions**:
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer your-cursor-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "composer-1.5",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": false
  }'
```

**Responses API**:
```bash
curl -X POST http://localhost:8000/v1/responses \
  -H "Authorization: Bearer your-cursor-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "composer-1.5",
    "input": "Hello!",
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
├── requirements.txt         # Python dependencies
├── sessions.json            # Session storage (auto-generated)
└── models.json              # Model cache (auto-generated)
```

### Running Tests

```bash
pip install -e ".[test]"
pytest
```

## Troubleshooting

### Docker Issues

- **Container fails to start**: Check logs with `docker compose logs -f`, verify `.env` values, ensure port 8000 is free.
- **Workspace access errors**: Ensure paths are absolute, uncomment the corresponding volume mount in `docker-compose.yml`, and verify host directory permissions.

### HTTPS Certificate Errors

- Verify certificate files exist at the configured paths
- Ensure certificate and key match: compare outputs of `openssl x509 -noout -modulus -in cert.pem | openssl md5` and `openssl rsa -noout -modulus -in key.pem | openssl md5`
- For self-signed certificates, clients need to use `-k` (curl) or disable SSL verification

### cursor-agent Not Found

Ensure cursor-agent is installed and in your PATH: `which cursor-agent`

### Authentication Errors (401)

- Verify your Cursor API key is valid
- Check the `Authorization` header format: `Bearer YOUR_KEY`
- Or set `CURSOR_KEY` environment variable as default

### Session Issues

- Clear session data: `python -m src.main --clear`
- Check `sessions.json` for corruption
- Ensure `/tmp/cursor-cli-proxy` has write permissions

## License

MIT
