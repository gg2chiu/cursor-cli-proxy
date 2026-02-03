# AGENTS.md - Instructions for AI Agents

This file provides instructions and guidelines for AI agents working on this codebase.

## Python Environment

### Virtual Environment (venv)

**IMPORTANT**: This project uses a Python virtual environment. Always use the Python interpreter and tools from the venv's `bin` directory.

```bash
# Correct - use venv Python
./venv/bin/python -m src.main
./venv/bin/python -m pytest
./venv/bin/pip install -r requirements.txt

# Incorrect - do NOT use system Python directly
python -m src.main  # Wrong!
python3 -m pytest   # Wrong!
pip install ...     # Wrong!
```

### Setting Up the Environment

If the venv doesn't exist, create it first:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/pip install -e ".[test]"  # Install test dependencies
```

### Activating the Virtual Environment

If you need to run multiple commands, you can activate the venv:

```bash
source venv/bin/activate
# Now 'python' and 'pip' will use the venv versions
```

## Running the Application

```bash
# Start the server
./venv/bin/python -m src.main

# Start with auto-reload (development)
./venv/bin/python -m src.main --reload

# Update model list
./venv/bin/python -m src.main --update-model

# Clear session data
./venv/bin/python -m src.main --clear
```

## Running Tests

```bash
# Run all tests
./venv/bin/python -m pytest

# Run with verbose output
./venv/bin/python -m pytest -v

# Run specific test file
./venv/bin/python -m pytest tests/test_config.py

# Run specific test
./venv/bin/python -m pytest tests/test_config.py::test_function_name
```

## Project Structure

```
cursor-cli-proxy/
├── src/                     # Source code
│   ├── main.py              # FastAPI application entry point
│   ├── config.py            # Configuration and settings
│   ├── models.py            # Pydantic data models
│   ├── relay.py             # Command builder and executor
│   ├── model_registry.py    # Model list management
│   └── session_manager.py   # Session tracking
├── tests/                   # Test suite (pytest)
├── requirements.txt         # Python dependencies
├── pyproject.toml           # Project metadata and build config
└── pytest.ini               # Pytest configuration
```

## Code Style and Conventions

- This project uses Python 3.8+ compatible code
- FastAPI for the web framework
- Pydantic for data validation
- Pytest for testing with pytest-asyncio for async tests
- Loguru for logging

## Dependencies

When adding new dependencies:

1. Add to `requirements.txt` with version pins
2. Also add to `pyproject.toml` if it's a core dependency
3. Install with: `./venv/bin/pip install -r requirements.txt`

## Environment Variables

Configuration is done via environment variables. See `.env.example` for available options:

- `CURSOR_KEY` - Default Cursor API key
- `HOST` / `PORT` - Server binding
- `LOG_LEVEL` - Logging verbosity
- `WORKSPACE_WHITELIST_*` - Allowed workspace paths

## Docker Alternative

If working with Docker instead of native Python:

```bash
# Build and start
docker compose up -d

# View logs
docker compose logs -f

# Run commands inside container
docker compose exec cursor-cli-proxy python -m src.main --update-model
```
