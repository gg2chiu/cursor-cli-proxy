# AGENTS.md - Instructions for AI Agents

This file provides instructions and guidelines for AI agents working on this codebase.

## Development Methodology

### Test-Driven Development (TDD)

**IMPORTANT**: This project follows Test-Driven Development. When implementing new features or fixing bugs, follow this workflow:

1. **Write Tests First** - Before writing any implementation code, write failing tests that define the expected behavior
2. **Run Tests (Red)** - Verify the tests fail as expected
3. **Implement Code** - Write the minimum code necessary to make the tests pass
4. **Run Tests (Green)** - Verify all tests pass
5. **Refactor** - Clean up the code while keeping tests green

```bash
# TDD Workflow Example:

# Step 1: Write test first in tests/test_new_feature.py
# Step 2: Run test - should FAIL (Red)
./venv/bin/python -m pytest tests/test_new_feature.py -v

# Step 3: Implement the feature in src/
# Step 4: Run test - should PASS (Green)
./venv/bin/python -m pytest tests/test_new_feature.py -v

# Step 5: Refactor if needed, ensure tests still pass
./venv/bin/python -m pytest -v
```

### TDD Guidelines

- **New Features**: Always start by writing tests that describe the expected behavior
- **Bug Fixes**: First write a test that reproduces the bug, then fix it
- **Refactoring**: Ensure existing tests pass before and after refactoring
- **Test Location**: Place tests in `tests/` directory with `test_` prefix
- **Test Naming**: Use descriptive names like `test_session_manager_creates_new_session`

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

## Configuration Management

### Adding New Configuration Items

**IMPORTANT**: When adding new configuration items to `src/config.py`, you MUST also update these related files to keep them synchronized:

1. **`src/config.py`** - Add the setting to the `Settings` class with type and default value
2. **`.env.example`** - Add the environment variable with documentation and example value
3. **`docker-compose.yml`** - Add the environment variable mapping in the `environment` section

Example workflow when adding a new config `MY_NEW_SETTING`:

```python
# 1. src/config.py - Add to Settings class
class Settings(BaseSettings):
    # ... existing settings ...
    MY_NEW_SETTING: str = "default_value"  # Add with type hint and default
```

```bash
# 2. .env.example - Add with documentation
# Description of what MY_NEW_SETTING does
MY_NEW_SETTING=default_value
```

```yaml
# 3. docker-compose.yml - Add to environment section
environment:
  # ... existing variables ...
  - MY_NEW_SETTING=${MY_NEW_SETTING:-default_value}
```

### Environment Variables

Configuration is done via environment variables. See `.env.example` for available options:

- `CURSOR_KEY` - Default Cursor API key
- `HOST` / `PORT` - Server binding
- `LOG_LEVEL` - Logging verbosity
- `ENABLE_INFO_IN_THINK` - Output session info in think block
- `ENABLE_HTTPS` / `HTTPS_CERT_PATH` / `HTTPS_KEY_PATH` - HTTPS configuration
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
