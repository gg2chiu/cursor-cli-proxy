import pytest
import os
from pathlib import Path
from src.models import Message
from src.relay import CommandBuilder, SlashCommandLoader


@pytest.fixture(autouse=True)
def isolate_home(tmp_path, monkeypatch):
    """Isolate tests from real user-level ~/.cursor/ entries by setting HOME to tmp_path/home."""
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))


# ============================================================
# Loading tests: commands, skills, agents
# ============================================================

def test_loads_commands_from_cursor_dir(tmp_path):
    """Commands from .cursor/commands/ should be loaded with type='command'."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "greet.md").write_text("Hello!")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "greet" in loader.entries
    assert loader.entries["greet"]["type"] == "command"
    assert loader.entries["greet"]["path"] == str(commands_dir / "greet.md")


def test_loads_commands_from_claude_dir(tmp_path):
    """Commands from .claude/commands/ should also be loaded (legacy support)."""
    commands_dir = tmp_path / ".claude" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "legacy.md").write_text("Legacy command")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "legacy" in loader.entries
    assert loader.entries["legacy"]["type"] == "command"
    assert loader.entries["legacy"]["path"] == str(commands_dir / "legacy.md")


def test_loads_skills_from_skill_dir(tmp_path):
    """Skills from .cursor/skills/**/SKILL.md should be loaded with type='skill'."""
    skill_dir = tmp_path / ".cursor" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# My Skill\nDo something useful.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "my-skill" in loader.entries
    assert loader.entries["my-skill"]["type"] == "skill"
    assert loader.entries["my-skill"]["path"] == str(skill_file)


def test_loads_nested_skills(tmp_path):
    """Deeply nested skills like skills/superpowers/brainstorming/SKILL.md should use parent dir name."""
    skill_dir = tmp_path / ".cursor" / "skills" / "superpowers" / "brainstorming"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Brainstorming\nGenerate ideas.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "brainstorming" in loader.entries
    assert loader.entries["brainstorming"]["type"] == "skill"
    assert loader.entries["brainstorming"]["path"] == str(skill_file)


def test_loads_skills_cursor_dir(tmp_path):
    """Skills from ~/.cursor/skills-cursor/**/SKILL.md should be loaded."""
    # autouse fixture sets HOME to tmp_path/home
    home = tmp_path / "home"
    skill_dir = home / ".cursor" / "skills-cursor" / "create-rule"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Create Rule\nCreate a new rule.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "create-rule" in loader.entries
    assert loader.entries["create-rule"]["type"] == "skill"
    assert loader.entries["create-rule"]["path"] == str(skill_file)


def test_loads_agents_from_agents_dir(tmp_path):
    """Agents from .cursor/agents/*.md should be loaded with type='agent'."""
    agents_dir = tmp_path / ".cursor" / "agents"
    agents_dir.mkdir(parents=True)
    agent_file = agents_dir / "find-importers.md"
    agent_file.write_text("# Find Importers\nFind all importers.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "find-importers" in loader.entries
    assert loader.entries["find-importers"]["type"] == "agent"
    assert loader.entries["find-importers"]["path"] == str(agent_file)


def test_loads_nested_agents(tmp_path):
    """Nested agents like agents/superpowers/code-reviewer.md should be loaded."""
    agent_dir = tmp_path / ".cursor" / "agents" / "superpowers"
    agent_dir.mkdir(parents=True)
    agent_file = agent_dir / "code-reviewer.md"
    agent_file.write_text("# Code Reviewer\nReview code.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "code-reviewer" in loader.entries
    assert loader.entries["code-reviewer"]["type"] == "agent"
    assert loader.entries["code-reviewer"]["path"] == str(agent_file)


def test_loads_all_types_together(tmp_path):
    """Commands, skills, and agents should all load in a single loader."""
    # Command
    cmd_dir = tmp_path / ".cursor" / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "my-cmd.md").write_text("A command")

    # Skill
    skill_dir = tmp_path / ".cursor" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("A skill")

    # Agent
    agent_dir = tmp_path / ".cursor" / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "my-agent.md").write_text("An agent")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert loader.entries["my-cmd"]["type"] == "command"
    assert loader.entries["my-skill"]["type"] == "skill"
    assert loader.entries["my-agent"]["type"] == "agent"


# ============================================================
# Skill naming: command_id from parent directory
# ============================================================

def test_skill_id_from_parent_dir(tmp_path):
    """Skill command_id should be the immediate parent dir of SKILL.md, not the full path."""
    skill_dir = tmp_path / ".cursor" / "skills" / "deep" / "nested" / "my-special-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Special")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    # command_id should be "my-special-skill", not "deep" or "nested"
    assert "my-special-skill" in loader.entries
    assert loader.entries["my-special-skill"]["type"] == "skill"


def test_non_skill_md_files_in_skills_dir_ignored(tmp_path):
    """Only SKILL.md should be loaded from skills dirs, not other .md files."""
    skill_dir = tmp_path / ".cursor" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("The skill")
    (skill_dir / "examples.md").write_text("Some examples")
    (skill_dir / "reference.md").write_text("References")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    # Only my-skill should be loaded (from SKILL.md), not examples or reference
    assert "my-skill" in loader.entries
    assert "examples" not in loader.entries
    assert "reference" not in loader.entries


# ============================================================
# resolve_slash_command: returns @path instead of content
# ============================================================

def test_resolve_returns_at_path(tmp_path):
    """Resolving a command should return 'Use this <type> @<path>' to the .md file."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "testcc.md").write_text("Test content")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.resolve_slash_command("/testcc")

    expected_path = str(commands_dir / "testcc.md")
    assert result == f"Use this command @{expected_path}"


def test_resolve_with_args(tmp_path):
    """Args after the command should be appended after the @path."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "ask.md").write_text("Question template")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.resolve_slash_command("/ask What is Python?")

    expected_path = str(commands_dir / "ask.md")
    assert result == f"Use this command @{expected_path} What is Python?"


def test_resolve_unknown_command_passthrough(tmp_path):
    """Unknown slash commands should pass through unchanged."""
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.resolve_slash_command("/nonexistent")

    assert result == "/nonexistent"


def test_resolve_non_slash_unchanged(tmp_path):
    """Non-slash text should pass through unchanged."""
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.resolve_slash_command("Hello world")

    assert result == "Hello world"


def test_resolve_skill(tmp_path):
    """Resolving a skill command should return 'Use this skill @path' to its SKILL.md."""
    skill_dir = tmp_path / ".cursor" / "skills" / "brainstorming"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Brainstorming")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.resolve_slash_command("/brainstorming")

    assert result == f"Use this skill @{skill_file}"


def test_resolve_agent(tmp_path):
    """Resolving an agent command should return 'Use this agent @path' to its .md file."""
    agents_dir = tmp_path / ".cursor" / "agents"
    agents_dir.mkdir(parents=True)
    agent_file = agents_dir / "find-importers.md"
    agent_file.write_text("# Find Importers")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader.resolve_slash_command("/find-importers")

    assert result == f"Use this agent @{agent_file}"


# ============================================================
# Priority: user-level overrides project-level
# ============================================================

def test_user_overrides_project(tmp_path):
    """User-level entries should override project-level entries with the same ID."""
    # Project-level command
    project_cmd_dir = tmp_path / ".cursor" / "commands"
    project_cmd_dir.mkdir(parents=True)
    (project_cmd_dir / "cmd.md").write_text("project version")

    # User-level command (HOME is tmp_path/home via autouse fixture)
    home = tmp_path / "home"
    user_cmd_dir = home / ".cursor" / "commands"
    user_cmd_dir.mkdir(parents=True)
    user_cmd_file = user_cmd_dir / "cmd.md"
    user_cmd_file.write_text("user version")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    # User version wins
    assert loader.entries["cmd"]["path"] == str(user_cmd_file)


def test_agent_overrides_skill_same_id(tmp_path):
    """Within the same level, agents (loaded later) override skills with the same ID."""
    # Skill
    skill_dir = tmp_path / ".cursor" / "skills" / "myname"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("skill version")

    # Agent with same name
    agent_dir = tmp_path / ".cursor" / "agents"
    agent_dir.mkdir(parents=True)
    agent_file = agent_dir / "myname.md"
    agent_file.write_text("agent version")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    # Agent should win (loaded later in priority order)
    assert loader.entries["myname"]["type"] == "agent"
    assert loader.entries["myname"]["path"] == str(agent_file)


# ============================================================
# get_command_labels: shows type
# ============================================================

def test_get_command_labels_shows_type(tmp_path):
    """Labels should include the entry type, e.g. (command: Title) /id."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "review.md").write_text("# Review Code\nReview the code.")

    skill_dir = tmp_path / ".cursor" / "skills" / "debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# Debug Helper\nHelp debug.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    labels = loader.get_command_labels()

    # Should contain type prefix
    assert any("command:" in label and "/review" in label for label in labels)
    assert any("skill:" in label and "/debug" in label for label in labels)


def test_get_command_labels_with_frontmatter(tmp_path):
    """Title extraction should skip YAML frontmatter and find the first # heading."""
    skill_dir = tmp_path / ".cursor" / "skills" / "brainstorming"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: some desc\n---\n\n# Brainstorming Ideas Into Designs\n\n## Overview\n"
    )

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    labels = loader.get_command_labels()

    assert any("Brainstorming Ideas Into Designs" in label and "/brainstorming" in label for label in labels)


def test_get_command_labels_without_title(tmp_path):
    """Labels for entries without a title should still show the type and command_id."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    # No markdown heading, just plain text
    (commands_dir / "plain.md").write_text("just some text without heading")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    labels = loader.get_command_labels()

    # Should still appear with type (no title => "(command) /plain")
    assert any("(command)" in label and "/plain" in label for label in labels)


# ============================================================
# CommandBuilder integration
# ============================================================

def test_command_builder_uses_resolve(tmp_path):
    """CommandBuilder should use resolve_slash_command (not expand) for user messages."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "hello.md").write_text("Hello! I'm here to help.")

    messages = [Message(role="user", content="/hello")]
    builder = CommandBuilder(
        model="auto",
        api_key="sk-test",
        messages=messages,
        workspace_dir=str(tmp_path),
    )

    cmd = builder.build()
    prompt = cmd[-1]

    expected_path = str(commands_dir / "hello.md")
    # Should contain @path reference, not expanded content
    assert f"@{expected_path}" in prompt
    # Should NOT contain the expanded content
    assert "Hello! I'm here to help." not in prompt


def test_command_builder_only_resolves_user_messages(tmp_path):
    """Only user messages should have slash commands resolved; assistant messages should not."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "test.md").write_text("Test command content")

    messages = [
        Message(role="user", content="/test"),
        Message(role="assistant", content="/test should not resolve"),
    ]
    builder = CommandBuilder(
        model="auto",
        api_key="sk-test",
        messages=messages,
        workspace_dir=str(tmp_path),
    )

    cmd = builder.build()
    prompt = cmd[-1]

    expected_path = str(commands_dir / "test.md")
    # User /test should be resolved to @path
    assert f"@{expected_path}" in prompt
    # Assistant /test should stay as-is
    assert "/test should not resolve" in prompt


# ============================================================
# Edge cases
# ============================================================

def test_empty_workspace_no_crash(tmp_path):
    """Loader should handle workspaces with no .cursor or .claude dirs."""
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    assert loader.entries == {}
    assert loader.get_command_labels() == []
    assert loader.resolve_slash_command("hello") == "hello"


def test_empty_md_files_ignored(tmp_path):
    """Empty .md files should not be loaded."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "empty.md").write_text("")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    assert "empty" not in loader.entries


# ============================================================
# Frontmatter parsing: _parse_frontmatter
# ============================================================

def test_parse_frontmatter_with_yaml(tmp_path):
    """_parse_frontmatter should extract name and description from YAML frontmatter."""
    skill_dir = tmp_path / ".cursor" / "skills" / "brainstorming"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        "---\nname: brainstorming\ndescription: Explores user intent and design.\n---\n\n# Brainstorming\n"
    )

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader._parse_frontmatter(str(skill_file))

    assert result is not None
    assert result["name"] == "brainstorming"
    assert result["description"] == "Explores user intent and design."


def test_parse_frontmatter_without_yaml(tmp_path):
    """_parse_frontmatter should return None when no YAML frontmatter exists."""
    skill_dir = tmp_path / ".cursor" / "skills" / "simple"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text("# Simple Skill\nJust a heading, no frontmatter.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader._parse_frontmatter(str(skill_file))

    assert result is None


def test_parse_frontmatter_with_quoted_description(tmp_path):
    """_parse_frontmatter should handle quoted description values."""
    skill_dir = tmp_path / ".cursor" / "skills" / "quoted"
    skill_dir.mkdir(parents=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        '---\nname: quoted\ndescription: "A description with special: chars"\n---\n\n# Quoted\n'
    )

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    result = loader._parse_frontmatter(str(skill_file))

    assert result is not None
    assert result["description"] == "A description with special: chars"


# ============================================================
# Description stored in entries
# ============================================================

def test_description_stored_in_entries_from_frontmatter(tmp_path):
    """Entries should store description from YAML frontmatter when available."""
    skill_dir = tmp_path / ".cursor" / "skills" / "my-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: Does useful things.\n---\n\n# My Skill\n"
    )

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "my-skill" in loader.entries
    assert loader.entries["my-skill"]["description"] == "Does useful things."


def test_description_falls_back_to_title(tmp_path):
    """When no frontmatter, description should fall back to the first # heading."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "review.md").write_text("# Review Code\nReview the code.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "review" in loader.entries
    assert loader.entries["review"]["description"] == "Review Code"


def test_description_none_when_no_frontmatter_no_heading(tmp_path):
    """When no frontmatter and no heading, description should be None."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "plain.md").write_text("just some plain text")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))

    assert "plain" in loader.entries
    assert loader.entries["plain"]["description"] is None


# ============================================================
# get_skills_metadata_xml
# ============================================================

def test_get_skills_metadata_xml_contains_all_types(tmp_path):
    """get_skills_metadata_xml should include commands, skills, and agents."""
    # Command
    cmd_dir = tmp_path / ".cursor" / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "review.md").write_text("# Review Code\nReview the code.")

    # Skill with frontmatter
    skill_dir = tmp_path / ".cursor" / "skills" / "brainstorming"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: Explore ideas before coding.\n---\n\n# Brainstorming\n"
    )

    # Agent
    agent_dir = tmp_path / ".cursor" / "agents"
    agent_dir.mkdir(parents=True)
    (agent_dir / "finder.md").write_text("# Finder Agent\nFinds things.")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    xml = loader.get_skills_metadata_xml()

    assert "<available_skills>" in xml
    assert "</available_skills>" in xml

    # Check command entry uses <command> tag
    assert "<command>" in xml
    assert "</command>" in xml
    assert "<name>review</name>" in xml
    assert "<description>Review Code</description>" in xml

    # Check skill entry uses <skill> tag (with frontmatter description)
    assert "<skill>" in xml
    assert "</skill>" in xml
    assert "<name>brainstorming</name>" in xml
    assert "<description>Explore ideas before coding.</description>" in xml

    # Check agent entry uses <agent> tag
    assert "<agent>" in xml
    assert "</agent>" in xml
    assert "<name>finder</name>" in xml
    assert "<description>Finder Agent</description>" in xml

    # Verify no <type> child tags exist
    assert "<type>" not in xml

    # Check location paths are present
    assert f"<location>{cmd_dir / 'review.md'}</location>" in xml
    assert f"<location>{skill_dir / 'SKILL.md'}</location>" in xml
    assert f"<location>{agent_dir / 'finder.md'}</location>" in xml


def test_get_skills_metadata_xml_empty_workspace(tmp_path):
    """get_skills_metadata_xml should return empty string when no entries exist."""
    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    xml = loader.get_skills_metadata_xml()

    assert xml == ""


def test_get_skills_metadata_xml_omits_description_when_none(tmp_path):
    """Entries with no description should still appear but with empty description."""
    commands_dir = tmp_path / ".cursor" / "commands"
    commands_dir.mkdir(parents=True)
    (commands_dir / "plain.md").write_text("just text, no heading")

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    xml = loader.get_skills_metadata_xml()

    assert "<command>" in xml
    assert "</command>" in xml
    assert "<name>plain</name>" in xml
    # description tag should still be present but empty
    assert "<description></description>" in xml


def test_get_skills_metadata_xml_escapes_special_chars(tmp_path):
    """XML special characters in description should be escaped."""
    skill_dir = tmp_path / ".cursor" / "skills" / "data-tool"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        '---\nname: data-tool\ndescription: "Handles <input> & <output> for \"data\" processing"\n---\n\n# Data Tool\n'
    )

    loader = SlashCommandLoader(workspace_dir=str(tmp_path))
    xml = loader.get_skills_metadata_xml()

    # & must be escaped as &amp;, < as &lt;, > as &gt;
    assert "&amp;" in xml
    assert "&lt;input&gt;" in xml
    assert "&lt;output&gt;" in xml
    # Raw unescaped characters must NOT appear in description value
    assert "<input>" not in xml
    assert "<output>" not in xml


# ============================================================
# Integration: skills XML injection in prompt (main.py logic)
# ============================================================

def test_skills_xml_injected_for_new_session(tmp_path):
    """When ENABLE_SKILLS_IN_PROMPT is True and session is new, skills XML should be prepended."""
    from src.config import config

    # Set up a skill
    skill_dir = tmp_path / ".cursor" / "skills" / "brainstorming"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: Explore ideas.\n---\n\n# Brainstorming\n"
    )

    original_value = config.ENABLE_SKILLS_IN_PROMPT
    config.ENABLE_SKILLS_IN_PROMPT = True
    try:
        # Simulate what main.py does for a new session
        is_session_hit = False
        messages_to_send = [Message(role="user", content="hello")]

        if config.ENABLE_SKILLS_IN_PROMPT and not is_session_hit:
            skills_loader = SlashCommandLoader(str(tmp_path))
            skills_xml = skills_loader.get_skills_metadata_xml()
            if skills_xml:
                skills_message = Message(role="system", content=skills_xml)
                messages_to_send = [skills_message] + messages_to_send

        # First message should be the skills system message
        assert len(messages_to_send) == 2
        assert messages_to_send[0].role == "system"
        content = messages_to_send[0].get_text_content()
        assert "<available_skills>" in content
        assert "<name>brainstorming</name>" in content
        assert "<description>Explore ideas.</description>" in content
    finally:
        config.ENABLE_SKILLS_IN_PROMPT = original_value


def test_skills_xml_skipped_for_resumed_session(tmp_path):
    """When is_session_hit is True, skills XML should NOT be injected."""
    from src.config import config

    skill_dir = tmp_path / ".cursor" / "skills" / "brainstorming"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: Explore ideas.\n---\n\n# Brainstorming\n"
    )

    original_value = config.ENABLE_SKILLS_IN_PROMPT
    config.ENABLE_SKILLS_IN_PROMPT = True
    try:
        # Simulate what main.py does for a resumed session
        is_session_hit = True
        messages_to_send = [Message(role="user", content="follow-up")]

        if config.ENABLE_SKILLS_IN_PROMPT and not is_session_hit:
            skills_loader = SlashCommandLoader(str(tmp_path))
            skills_xml = skills_loader.get_skills_metadata_xml()
            if skills_xml:
                skills_message = Message(role="system", content=skills_xml)
                messages_to_send = [skills_message] + messages_to_send

        # Should remain as-is, no injection
        assert len(messages_to_send) == 1
        assert messages_to_send[0].role == "user"
        assert "<available_skills>" not in messages_to_send[0].get_text_content()
    finally:
        config.ENABLE_SKILLS_IN_PROMPT = original_value


def test_skills_xml_skipped_when_disabled(tmp_path):
    """When ENABLE_SKILLS_IN_PROMPT is False, skills XML should NOT be injected."""
    from src.config import config

    skill_dir = tmp_path / ".cursor" / "skills" / "brainstorming"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: brainstorming\ndescription: Explore ideas.\n---\n\n# Brainstorming\n"
    )

    original_value = config.ENABLE_SKILLS_IN_PROMPT
    config.ENABLE_SKILLS_IN_PROMPT = False
    try:
        is_session_hit = False
        messages_to_send = [Message(role="user", content="hello")]

        if config.ENABLE_SKILLS_IN_PROMPT and not is_session_hit:
            skills_loader = SlashCommandLoader(str(tmp_path))
            skills_xml = skills_loader.get_skills_metadata_xml()
            if skills_xml:
                skills_message = Message(role="system", content=skills_xml)
                messages_to_send = [skills_message] + messages_to_send

        # Should remain as-is, no injection
        assert len(messages_to_send) == 1
        assert messages_to_send[0].role == "user"
    finally:
        config.ENABLE_SKILLS_IN_PROMPT = original_value
