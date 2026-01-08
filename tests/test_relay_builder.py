import pytest
from src.models import Message
from src.relay import CommandBuilder

def test_build_command_basic():
    messages = [Message(role="user", content="hello")]
    builder = CommandBuilder(model="gpt-4", api_key="sk-test", messages=messages)
    cmd = builder.build()
    
    assert "--model" in cmd
    assert "gpt-4" in cmd
    assert "--api-key" in cmd
    assert "sk-test" in cmd
    assert "--sandbox" in cmd
    assert "enabled" in cmd
    assert "-p" in cmd
    assert "User: hello" in cmd[-1]

def test_build_command_with_workspace():
    messages = [Message(role="user", content="hello")]
    builder = CommandBuilder(model="gpt-4", api_key="sk-test", messages=messages, workspace_dir="/tmp/ws")
    cmd = builder.build()
    
    assert "--workspace" in cmd
    assert "/tmp/ws" in cmd
    assert "--sandbox" in cmd
    assert "enabled" in cmd

def test_system_message_merge():
    messages = [
        Message(role="system", content="You are a helper."),
        Message(role="user", content="Hi")
    ]
    builder = CommandBuilder(model="gpt-4", api_key="sk-test", messages=messages)
    cmd = builder.build()
    
    # 預期 System message 被合併到 User message
    # e.g. "System: You are a helper.\nUser: Hi"
    # Prompt 現在在最後一個元素
    prompt = cmd[-1]
    assert "You are a helper." in prompt
    assert "Hi" in prompt
