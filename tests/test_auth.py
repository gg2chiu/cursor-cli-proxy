"""Unit tests for verify_auth (PROXY_PASSWORD-based authentication).

These call verify_auth directly (not through the FastAPI app), so they are not
affected by the dependency override in conftest.py.
"""
import pytest
from unittest.mock import patch

from fastapi import HTTPException

from src.config import config
from src.routes.common import verify_auth

PASSWORD = "s3cret-pass"


@pytest.mark.asyncio
async def test_missing_proxy_password_returns_500():
    """When PROXY_PASSWORD is not configured, every request is rejected with 500."""
    with patch.object(config, "PROXY_PASSWORD", None):
        with pytest.raises(HTTPException) as exc:
            await verify_auth(authorization=f"Bearer {PASSWORD}")
        assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_empty_proxy_password_treated_as_unset():
    """An empty/quoted PROXY_PASSWORD is treated as unset and rejected with 500."""
    with patch.object(config, "PROXY_PASSWORD", '""'):
        with pytest.raises(HTTPException) as exc:
            await verify_auth(authorization=f"Bearer {PASSWORD}")
        assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_correct_password_returns_cursor_key():
    """Correct password returns CURSOR_KEY for use with cursor-agent."""
    with patch.object(config, "PROXY_PASSWORD", PASSWORD), \
         patch.object(config, "CURSOR_KEY", "sk-real-cursor-key"):
        result = await verify_auth(authorization=f"Bearer {PASSWORD}")
        assert result == "sk-real-cursor-key"


@pytest.mark.asyncio
async def test_correct_password_no_cursor_key_returns_none():
    """Correct password with no CURSOR_KEY returns None (rely on cursor-agent login)."""
    with patch.object(config, "PROXY_PASSWORD", PASSWORD), \
         patch.object(config, "CURSOR_KEY", None):
        result = await verify_auth(authorization=f"Bearer {PASSWORD}")
        assert result is None


@pytest.mark.asyncio
async def test_correct_password_empty_cursor_key_returns_none():
    """Quoted/empty CURSOR_KEY is treated as unset and returns None."""
    with patch.object(config, "PROXY_PASSWORD", PASSWORD), \
         patch.object(config, "CURSOR_KEY", '""'):
        result = await verify_auth(authorization=f"Bearer {PASSWORD}")
        assert result is None


@pytest.mark.asyncio
async def test_wrong_password_returns_401():
    with patch.object(config, "PROXY_PASSWORD", PASSWORD):
        with pytest.raises(HTTPException) as exc:
            await verify_auth(authorization="Bearer wrong-password")
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_missing_authorization_header_returns_401():
    with patch.object(config, "PROXY_PASSWORD", PASSWORD):
        with pytest.raises(HTTPException) as exc:
            await verify_auth(authorization=None)
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_non_bearer_authorization_returns_401():
    with patch.object(config, "PROXY_PASSWORD", PASSWORD):
        with pytest.raises(HTTPException) as exc:
            await verify_auth(authorization=PASSWORD)
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_empty_bearer_token_returns_401():
    with patch.object(config, "PROXY_PASSWORD", PASSWORD):
        with pytest.raises(HTTPException) as exc:
            await verify_auth(authorization="Bearer ")
        assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_client_token_is_not_used_as_cursor_key():
    """The client token (password) must never be used as the cursor-agent key."""
    with patch.object(config, "PROXY_PASSWORD", PASSWORD), \
         patch.object(config, "CURSOR_KEY", None):
        result = await verify_auth(authorization=f"Bearer {PASSWORD}")
        assert result != PASSWORD
