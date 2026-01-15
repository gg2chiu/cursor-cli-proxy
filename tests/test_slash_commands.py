import pytest
import os
from pathlib import Path
from src.models import Message
from src.relay import CommandBuilder, SlashCommandLoader


def test_slash_command_loader_basic(tmp_path):
    """測試基本的 slash 指令載入"""
    # 創建測試用的指令目錄和檔案
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    
    test_cmd = commands_dir / "test.md"
    test_cmd.write_text("This is a test command")
    
    # 載入指令
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    
    # 驗證指令已載入
    assert "test" in loader.commands
    assert loader.commands["test"] == "This is a test command"


def test_slash_command_expansion_basic(tmp_path):
    """測試基本的 slash 指令展開"""
    # 創建測試用的指令
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    
    (commands_dir / "greet.md").write_text("Hello, how can I help you?")
    
    # 測試展開
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.expand_slash_command("/greet")
    
    assert result == "Hello, how can I help you?"


def test_slash_command_expansion_with_arguments(tmp_path):
    """測試帶參數的 slash 指令展開"""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    
    # 創建使用 $ARGUMENTS 的指令
    (commands_dir / "ask.md").write_text("Question: $ARGUMENTS\n\nPlease answer this.")
    
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.expand_slash_command("/ask What is Python?")
    
    assert "Question: What is Python?" in result
    assert "Please answer this." in result


def test_slash_command_expansion_with_positional_args(tmp_path):
    """測試位置參數 $1, $2 的替換"""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    
    (commands_dir / "translate.md").write_text("Translate '$1' from $2 to $3")
    
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.expand_slash_command("/translate hello English Chinese")
    
    assert result == "Translate 'hello' from English to Chinese"


def test_slash_command_not_found(tmp_path):
    """測試不存在的 slash 指令應保持原樣"""
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.expand_slash_command("/nonexistent")
    
    assert result == "/nonexistent"


def test_non_slash_text_unchanged(tmp_path):
    """測試非 slash 指令的文字應保持原樣"""
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.expand_slash_command("Hello world")
    
    assert result == "Hello world"


def test_slash_command_priority(tmp_path):
    """測試指令載入優先順序：user > workspace"""
    # 創建 workspace 指令
    workspace_dir = tmp_path / ".cursor" / "commands"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "cmd.md").write_text("workspace command")
    
    # 創建 user 指令（模擬 home 目錄）
    user_dir = tmp_path / "home" / ".cursor" / "commands"
    user_dir.mkdir(parents=True)
    (user_dir / "cmd.md").write_text("user command")
    
    # 暫時修改 home 目錄
    original_home = os.environ.get('HOME')
    try:
        os.environ['HOME'] = str(tmp_path / "home")
        loader = SlashCommandLoader(workspace_dir=str(tmp_path))
        
        # user 指令應該覆蓋 workspace 指令
        assert loader.commands["cmd"] == "user command"
    finally:
        if original_home:
            os.environ['HOME'] = original_home


def test_command_builder_expands_slash_commands(tmp_path):
    """測試 CommandBuilder 會自動展開 user 訊息中的 slash 指令"""
    # 創建測試指令
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "hello.md").write_text("Hello! I'm here to help.")
    
    # 建立包含 slash 指令的訊息
    messages = [Message(role="user", content="/hello")]
    builder = CommandBuilder(
        model="auto", 
        api_key="sk-test", 
        messages=messages,
        workspace_dir=str(tmp_path)
    )
    
    cmd = builder.build()
    prompt = cmd[-1]
    
    # 驗證指令已展開
    assert "Hello! I'm here to help." in prompt
    assert "/hello" not in prompt


def test_command_builder_only_expands_user_messages(tmp_path):
    """測試只有 user 訊息會展開 slash 指令，assistant 訊息不會"""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "test.md").write_text("Test command content")
    
    messages = [
        Message(role="user", content="/test"),
        Message(role="assistant", content="/test should not expand")
    ]
    builder = CommandBuilder(
        model="auto",
        api_key="sk-test",
        messages=messages,
        workspace_dir=str(tmp_path)
    )
    
    cmd = builder.build()
    prompt = cmd[-1]
    
    # user 的 /test 應該展開
    assert "Test command content" in prompt
    # assistant 的 /test 應該保持原樣
    assert "/test should not expand" in prompt


def test_slash_command_with_no_args_but_template_has_placeholders(tmp_path):
    """測試指令模板有 placeholder 但沒有提供參數的情況"""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    
    (commands_dir / "greet.md").write_text("Hello $1, welcome to $2!")
    
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.expand_slash_command("/greet")
    
    # 參數未提供時，placeholder 應該被留空或保留
    assert "Hello" in result
    assert "welcome to" in result


def test_slash_command_loader_handles_multiple_directories(tmp_path):
    """測試從多個目錄載入指令"""
    # 創建 .cursor/commands
    cursor_dir = tmp_path / ".cursor" / "commands"
    cursor_dir.mkdir(parents=True)
    (cursor_dir / "cursor_cmd.md").write_text("Cursor command")
    
    # 創建 .claude/commands
    claude_dir = tmp_path / ".claude" / "commands"
    claude_dir.mkdir(parents=True)
    (claude_dir / "claude_cmd.md").write_text("Claude command")
    
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    
    # 兩個指令都應該被載入
    assert "cursor_cmd" in loader.commands
    assert "claude_cmd" in loader.commands
    assert loader.commands["cursor_cmd"] == "Cursor command"
    assert loader.commands["claude_cmd"] == "Claude command"


def test_slash_command_with_multiline_content(tmp_path):
    """測試多行內容的 slash 指令"""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    
    multiline_content = """# Review Code

Please review the following code:

$ARGUMENTS

Focus on:
- Code quality
- Best practices
- Potential bugs"""
    
    (commands_dir / "review.md").write_text(multiline_content)
    
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.expand_slash_command("/review def foo(): pass")
    
    assert "# Review Code" in result
    assert "def foo(): pass" in result
    assert "Code quality" in result
