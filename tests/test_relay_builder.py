import pytest
from src.models import Message
from src.relay import CommandBuilder


def test_build_command_basic():
    messages = [Message(role="user", content="hello")]
    builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
    cmd = builder.build()
    
    assert "--model" in cmd
    assert "auto" in cmd
    assert "--api-key" in cmd
    assert "sk-test" in cmd
    assert "--print" in cmd
    assert "hello" in cmd[-1]

def test_build_command_with_workspace():
    messages = [Message(role="user", content="hello")]
    builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages, workspace_dir="/tmp/ws")
    cmd = builder.build()
    
    assert "--workspace" in cmd
    assert "/tmp/ws" in cmd


def test_build_command_without_api_key():
    """When api_key is empty/None, --api-key must be omitted (rely on cursor-agent login)."""
    messages = [Message(role="user", content="hello")]

    builder_none = CommandBuilder(model="auto", api_key=None, messages=messages)
    cmd_none = builder_none.build()
    assert "--api-key" not in cmd_none
    assert "--print" in cmd_none
    assert "hello" in cmd_none[-1]

    builder_empty = CommandBuilder(model="auto", api_key="", messages=messages)
    cmd_empty = builder_empty.build()
    assert "--api-key" not in cmd_empty

def test_system_message_merge():
    messages = [
        Message(role="system", content="You are a helper."),
        Message(role="user", content="Hi")
    ]
    builder = CommandBuilder(model="auto", api_key="sk-test", messages=messages)
    cmd = builder.build()
    
    # 預期 System message 被合併到 User message
    # e.g. "You are a helper.\n\nHi"
    # There is no 'SYSTEM:', 'USER:', prefix in the prompt
    prompt = cmd[-1]
    assert prompt == "You are a helper.\n\nHi"
    assert "SYSTEM:" not in prompt
    assert "USER:" not in prompt
