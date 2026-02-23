import pytest
from unittest.mock import patch, MagicMock
from src.model_registry import ModelRegistry, Model


@pytest.fixture
def registry():
    reg = ModelRegistry()
    reg.reset()
    return reg


class TestToDisplayId:
    def test_opus_gets_claude_prefix(self):
        assert ModelRegistry.to_display_id("opus-4.6") == "claude-opus-4.6"

    def test_opus_thinking_gets_claude_prefix(self):
        assert ModelRegistry.to_display_id("opus-4.6-thinking") == "claude-opus-4.6-thinking"

    def test_sonnet_gets_claude_prefix(self):
        assert ModelRegistry.to_display_id("sonnet-4.5") == "claude-sonnet-4.5"

    def test_sonnet_thinking_gets_claude_prefix(self):
        assert ModelRegistry.to_display_id("sonnet-4.5-thinking") == "claude-sonnet-4.5-thinking"

    def test_gpt_unchanged(self):
        assert ModelRegistry.to_display_id("gpt-5.2") == "gpt-5.2"

    def test_auto_unchanged(self):
        assert ModelRegistry.to_display_id("auto") == "auto"

    def test_gemini_unchanged(self):
        assert ModelRegistry.to_display_id("gemini-3-pro") == "gemini-3-pro"

    def test_already_prefixed_not_doubled(self):
        assert ModelRegistry.to_display_id("claude-opus-4.6") == "claude-opus-4.6"


class TestToCliId:
    def test_strips_claude_prefix_from_opus(self):
        assert ModelRegistry.to_cli_id("claude-opus-4.6") == "opus-4.6"

    def test_strips_claude_prefix_from_sonnet(self):
        assert ModelRegistry.to_cli_id("claude-sonnet-4.5-thinking") == "sonnet-4.5-thinking"

    def test_gpt_unchanged(self):
        assert ModelRegistry.to_cli_id("gpt-5.2") == "gpt-5.2"

    def test_auto_unchanged(self):
        assert ModelRegistry.to_cli_id("auto") == "auto"

    def test_bare_opus_unchanged(self):
        assert ModelRegistry.to_cli_id("opus-4.6") == "opus-4.6"


class TestRoundTrip:
    @pytest.mark.parametrize("model_id", [
        "opus-4.6",
        "opus-4.6-thinking",
        "sonnet-4.5",
        "sonnet-4.5-thinking",
        "gpt-5.2",
        "auto",
        "gemini-3-pro",
        "composer-1",
    ])
    def test_round_trip(self, model_id):
        assert ModelRegistry.to_cli_id(ModelRegistry.to_display_id(model_id)) == model_id


class TestGetModelsDisplayIds:
    def test_get_models_returns_prefixed_claude_ids(self, registry):
        registry._models = [
            Model(id="auto", owned_by="cursor"),
            Model(id="opus-4.6", owned_by="cursor", name="Claude 4.6 Opus"),
            Model(id="sonnet-4.5", owned_by="cursor", name="Claude 4.5 Sonnet"),
            Model(id="gpt-5.2", owned_by="openai", name="GPT-5.2"),
        ]

        models = registry.get_models()
        ids = [m.id for m in models]

        assert "auto" in ids
        assert "claude-opus-4.6" in ids
        assert "claude-sonnet-4.5" in ids
        assert "gpt-5.2" in ids
        assert "opus-4.6" not in ids
        assert "sonnet-4.5" not in ids

    def test_internal_models_unchanged(self, registry):
        """Verify _models cache is not mutated by get_models."""
        registry._models = [
            Model(id="opus-4.6", owned_by="cursor"),
        ]

        registry.get_models()

        assert registry._models[0].id == "opus-4.6"
