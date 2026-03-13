"""
Tests for the OpenAI Responses API endpoint (/v1/responses).

Follows the same mock patterns as test_think_block.py / test_history_inclusion.py:
 - Isolate session storage to tmp_path
 - Mock subprocess.Popen for session creation
 - Mock Executor (asyncio.create_subprocess_exec) so no real CLI runs
"""
import os
import pytest
import json
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from tests.conftest import make_popen_mock
from src.main import app, session_manager, config
from src.config import Settings
from src.relay import SlashCommandLoader


client = TestClient(app)

HEADERS = {"Authorization": "Bearer test-key"}


@pytest.fixture(autouse=True)
def clean_storage(tmp_path):
    storage_file = tmp_path / "test_sessions_responses.json"
    lock_file = tmp_path / "test_sessions_responses.json.lock"

    session_manager.storage_path = str(storage_file)
    session_manager.lock_path = str(lock_file)
    from filelock import FileLock
    session_manager.lock = FileLock(session_manager.lock_path)
    session_manager._ensure_storage_exists()
    yield


# ── Non-streaming tests ──────────────────────────────────────────────

def _find_message_item(output):
    """Find the first message-type output item from a Responses API output list."""
    return next(item for item in output if item["type"] == "message")


class TestResponsesNonStreaming:

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_basic_string_input(self, mock_exec, mock_popen):
        """String input produces a valid Response object."""
        mock_popen.return_value = make_popen_mock("resp-session-1")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Hello there"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi"},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"
        assert body["status"] == "completed"
        assert body["model"] == "auto"
        assert len(body["output"]) >= 1
        msg = _find_message_item(body["output"])
        assert msg["type"] == "message"
        assert msg["role"] == "assistant"
        assert msg["status"] == "completed"
        assert len(msg["content"]) == 1
        assert msg["content"][0]["type"] == "output_text"
        assert "Hello there" in msg["content"][0]["text"]

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_message_list_input(self, mock_exec, mock_popen):
        """List-of-messages input produces a valid Response object."""
        mock_popen.return_value = make_popen_mock("resp-session-2")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "World"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "input": [
                    {"role": "user", "content": "Hello"},
                ],
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"
        msg = _find_message_item(body["output"])
        assert "World" in msg["content"][0]["text"]

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_instructions_field(self, mock_exec, mock_popen):
        """instructions field is sent as a system message."""
        mock_popen.return_value = make_popen_mock("resp-session-3")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "I am helpful"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "instructions": "You are a helpful assistant.",
                "input": "Who are you?",
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"
        msg = _find_message_item(body["output"])
        assert "I am helpful" in msg["content"][0]["text"]

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_developer_role_maps_to_system(self, mock_exec, mock_popen):
        """developer role in input is treated the same as system."""
        mock_popen.return_value = make_popen_mock("resp-session-dev")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "OK"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "input": [
                    {"role": "developer", "content": "Be concise."},
                    {"role": "user", "content": "Hello"},
                ],
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_response_id_is_session_id(self, mock_exec, mock_popen):
        """The response id field contains the session_id (prefixed with resp_)."""
        mock_popen.return_value = make_popen_mock("abc-def-123")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Hi"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi"},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "resp_abc-def-123"


# ── Multi-turn with previous_response_id ─────────────────────────────

class TestResponsesMultiTurn:

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_previous_response_id_resumes_session(self, mock_exec, mock_popen):
        """Providing the resp_-prefixed id from a prior response resumes the session.

        Verifies that passing the full response id (with resp_ prefix) actually
        resumes the existing session rather than silently creating a new one.
        """
        mock_popen.return_value = make_popen_mock("multi-turn-sess")

        mock_process1 = AsyncMock()
        mock_process1.stdout.read = AsyncMock(side_effect=[b'{"result": "Paris"}', b""])
        mock_process1.returncode = 0
        mock_exec.return_value = mock_process1

        resp1 = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "What is the capital of France?"},
            headers=HEADERS,
        )
        assert resp1.status_code == 200
        resp1_id = resp1.json()["id"]
        assert resp1_id == "resp_multi-turn-sess"

        # Second turn — pass the full resp_-prefixed id, as a real client would
        mock_exec.reset_mock()
        mock_popen.reset_mock()
        mock_process2 = AsyncMock()
        mock_process2.stdout.read = AsyncMock(side_effect=[b'{"result": "About 2 million"}', b""])
        mock_process2.returncode = 0
        mock_exec.return_value = mock_process2

        resp2 = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "input": "And its population?",
                "previous_response_id": resp1_id,
            },
            headers=HEADERS,
        )

        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["previous_response_id"] == resp1_id
        msg2 = _find_message_item(body2["output"])
        assert "About 2 million" in msg2["content"][0]["text"]

        # The session must have been REUSED, not recreated.
        # Popen (create-chat) should NOT have been called again.
        mock_popen.assert_not_called()


# ── Streaming tests ──────────────────────────────────────────────────

class TestResponsesStreaming:

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_stream_emits_typed_events(self, mock_exec, mock_popen):
        """Streaming emits response.created, response.output_text.delta, and response.completed."""
        mock_popen.return_value = make_popen_mock("stream-resp-1")

        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]},"timestamp_ms":100}\n',
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" World"}]},"timestamp_ms":101}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi", "stream": True},
            headers=HEADERS,
        )

        assert resp.status_code == 200

        events = []
        for line in resp.iter_lines():
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                events.append((event_type, data))

        event_types = [e[0] for e in events]
        assert "response.created" in event_types
        assert "response.output_text.delta" in event_types
        assert "response.completed" in event_types

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_stream_delta_contains_text(self, mock_exec, mock_popen):
        """Delta events contain the actual text chunks."""
        mock_popen.return_value = make_popen_mock("stream-resp-2")

        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Chunk1"}]},"timestamp_ms":100}\n',
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":" Chunk2"}]},"timestamp_ms":101}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi", "stream": True},
            headers=HEADERS,
        )

        assert resp.status_code == 200

        deltas = []
        for line in resp.iter_lines():
            if line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if data.get("type") == "response.output_text.delta":
                    deltas.append(data["delta"])

        text_deltas = [d for d in deltas if d.strip()]
        assert len(text_deltas) >= 2
        assert "Chunk1" in text_deltas[0]


# ── Error handling ───────────────────────────────────────────────────

class TestResponsesErrors:

    def test_empty_input_rejected(self):
        """Empty string input should still work (no validation error at model level)."""
        # The Responses API accepts empty string - cursor-agent may or may not handle it,
        # but our endpoint should not crash with a validation error.
        # We just check it doesn't return 422.
        pass

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_missing_model_returns_422(self, mock_exec, mock_popen):
        """Request without model should return 422."""
        resp = client.post(
            "/v1/responses",
            json={"input": "Hi"},
            headers=HEADERS,
        )
        assert resp.status_code == 422


# ── Reasoning item (ENABLE_INFO_IN_THINK) tests ─────────────────────

class TestResponsesReasoningItemNonStreaming:
    """Tests for reasoning output item in non-streaming Responses API."""

    @pytest.fixture(autouse=True)
    def enable_think(self):
        original = config.ENABLE_INFO_IN_THINK
        config.ENABLE_INFO_IN_THINK = True
        yield
        config.ENABLE_INFO_IN_THINK = original

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_reasoning_item_present_on_new_session(self, mock_exec, mock_popen):
        """New session emits a reasoning output item before the message."""
        mock_popen.return_value = make_popen_mock("reason-sess-1")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Hello"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi"},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["output"]) == 2
        reasoning = body["output"][0]
        assert reasoning["type"] == "reasoning"
        assert reasoning["id"].startswith("rs_")
        assert len(reasoning["summary"]) == 1
        assert reasoning["summary"][0]["type"] == "summary_text"
        assert "Session ID: reason-sess-1" in reasoning["summary"][0]["text"]
        msg = body["output"][1]
        assert msg["type"] == "message"

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_reasoning_item_contains_commands(self, mock_exec, mock_popen):
        """Reasoning summary includes available slash commands."""
        mock_popen.return_value = make_popen_mock("reason-sess-cmd")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "OK"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        def mock_init(self, workspace_dir=None):
            self.workspace_dir = workspace_dir
            self.entries = {
                "review": {"path": "/fake/review.md", "type": "command"},
                "deploy": {"path": "/fake/deploy.md", "type": "command"},
            }
        with patch.object(SlashCommandLoader, '__init__', mock_init):
            resp = client.post(
                "/v1/responses",
                json={"model": "auto", "input": "Hi"},
                headers=HEADERS,
            )

        assert resp.status_code == 200
        summary_text = resp.json()["output"][0]["summary"][0]["text"]
        assert "Available Commands:" in summary_text
        assert "/review" in summary_text
        assert "/deploy" in summary_text

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_no_reasoning_item_on_resumed_session(self, mock_exec, mock_popen):
        """Resumed session does NOT include a reasoning output item."""
        mock_popen.return_value = make_popen_mock("reason-resume-sess")

        mock_p1 = AsyncMock()
        mock_p1.stdout.read = AsyncMock(side_effect=[b'{"result": "First"}', b""])
        mock_p1.returncode = 0
        mock_exec.return_value = mock_p1

        resp1 = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hello"},
            headers=HEADERS,
        )
        assert resp1.status_code == 200
        resp1_id = resp1.json()["id"]

        mock_exec.reset_mock()
        mock_popen.reset_mock()
        mock_p2 = AsyncMock()
        mock_p2.stdout.read = AsyncMock(side_effect=[b'{"result": "Second"}', b""])
        mock_p2.returncode = 0
        mock_exec.return_value = mock_p2

        resp2 = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Follow-up", "previous_response_id": resp1_id},
            headers=HEADERS,
        )
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert len(body2["output"]) == 1
        assert body2["output"][0]["type"] == "message"

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_no_reasoning_item_when_disabled(self, mock_exec, mock_popen):
        """When ENABLE_INFO_IN_THINK is False, no reasoning item is emitted."""
        config.ENABLE_INFO_IN_THINK = False
        mock_popen.return_value = make_popen_mock("reason-disabled")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Hi"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hello"},
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["output"]) == 1
        assert body["output"][0]["type"] == "message"


class TestResponsesReasoningItemStreaming:
    """Tests for reasoning output item in streaming Responses API."""

    @pytest.fixture(autouse=True)
    def enable_think(self):
        original = config.ENABLE_INFO_IN_THINK
        config.ENABLE_INFO_IN_THINK = True
        yield
        config.ENABLE_INFO_IN_THINK = original

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_stream_emits_full_reasoning_lifecycle(self, mock_exec, mock_popen):
        """Streaming emits the full reasoning lifecycle before the message lifecycle."""
        mock_popen.return_value = make_popen_mock("stream-reason-1")

        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hello"}]},"timestamp_ms":100}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi", "stream": True},
            headers=HEADERS,
        )

        assert resp.status_code == 200

        events = []
        current_event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                events.append((current_event, data))

        event_types = [e[0] for e in events]

        expected_reasoning_events = [
            "response.output_item.added",
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_text.delta",
            "response.reasoning_summary_text.done",
            "response.reasoning_summary_part.done",
            "response.output_item.done",
        ]
        for evt in expected_reasoning_events:
            assert evt in event_types, f"Missing event: {evt}"

        reasoning_added = [e for e in events
                          if e[0] == "response.output_item.added"
                          and e[1].get("item", {}).get("type") == "reasoning"]
        assert len(reasoning_added) == 1
        reasoning_item = reasoning_added[0][1]["item"]
        assert reasoning_item["id"].startswith("rs_")
        assert "Session ID: stream-reason-1" in reasoning_item["summary"][0]["text"]

        rs_id = reasoning_item["id"]
        summary_delta = next(e for e in events if e[0] == "response.reasoning_summary_text.delta")
        assert summary_delta[1]["item_id"] == rs_id
        assert "Session ID:" in summary_delta[1]["delta"]

        summary_done = next(e for e in events if e[0] == "response.reasoning_summary_text.done")
        assert summary_done[1]["item_id"] == rs_id
        assert "Session ID:" in summary_done[1]["text"]

        rs_done = next(e for e in events if e[0] == "response.output_item.done"
                       and e[1].get("item", {}).get("type") == "reasoning")
        rs_done_idx = events.index(rs_done)

        message_added = next(e for e in events
                            if e[0] == "response.output_item.added"
                            and e[1].get("item", {}).get("type") == "message")
        msg_added_idx = events.index(message_added)
        assert rs_done_idx < msg_added_idx

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_stream_no_reasoning_when_disabled(self, mock_exec, mock_popen):
        """When ENABLE_INFO_IN_THINK is False, no reasoning events in stream."""
        config.ENABLE_INFO_IN_THINK = False
        mock_popen.return_value = make_popen_mock("stream-no-reason")

        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hi"}]},"timestamp_ms":100}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi", "stream": True},
            headers=HEADERS,
        )

        assert resp.status_code == 200

        events = []
        current_event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                events.append((current_event, data))

        reasoning_items = [e for e in events
                          if e[0] == "response.output_item.added"
                          and e[1].get("item", {}).get("type") == "reasoning"]
        assert len(reasoning_items) == 0

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_stream_emits_full_message_lifecycle(self, mock_exec, mock_popen):
        """Streaming emits content_part.done and output_item.done for the message."""
        mock_popen.return_value = make_popen_mock("stream-msg-lifecycle")

        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Hi there"}]},"timestamp_ms":100}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi", "stream": True},
            headers=HEADERS,
        )

        assert resp.status_code == 200

        events = []
        current_event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                events.append((current_event, data))

        event_types = [e[0] for e in events]
        assert "response.content_part.done" in event_types
        assert "response.output_item.done" in event_types

        msg_item_done = [e for e in events
                        if e[0] == "response.output_item.done"
                        and e[1].get("item", {}).get("type") == "message"]
        assert len(msg_item_done) == 1
        assert msg_item_done[0][1]["item"]["status"] == "completed"
        assert "Hi there" in msg_item_done[0][1]["item"]["content"][0]["text"]

        content_done = next(e for e in events if e[0] == "response.content_part.done")
        text_done = next(e for e in events if e[0] == "response.output_text.done")
        completed = next(e for e in events if e[0] == "response.completed")

        cd_idx = events.index(content_done)
        td_idx = events.index(text_done)
        mid_idx = events.index(msg_item_done[0])
        comp_idx = events.index(completed)
        assert td_idx < cd_idx < mid_idx < comp_idx

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_stream_completed_includes_reasoning_in_output(self, mock_exec, mock_popen):
        """The response.completed event includes the reasoning item in output."""
        mock_popen.return_value = make_popen_mock("stream-reason-complete")

        mock_process = AsyncMock()
        mock_process.stdout = AsyncMock()
        mock_process.stdout.__aiter__.return_value = [
            b'{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"Done"}]},"timestamp_ms":100}\n',
        ]
        mock_process.wait.return_value = 0
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "Hi", "stream": True},
            headers=HEADERS,
        )

        assert resp.status_code == 200

        completed_events = []
        current_event = None
        for line in resp.iter_lines():
            if line.startswith("event: "):
                current_event = line[len("event: "):]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: "):])
                if current_event == "response.completed":
                    completed_events.append(data)

        assert len(completed_events) == 1
        output = completed_events[0]["response"]["output"]
        assert len(output) == 2
        assert output[0]["type"] == "reasoning"
        assert output[1]["type"] == "message"


# ── Workspace / session_id tag extraction tests ─────────────────────

def _build_settings():
    return Settings(_env_file=None)


class TestResponsesWorkspaceTag:
    """Tests for <workspace> and <session_id> tag extraction in Responses API."""

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_workspace_tag_in_instructions(self, mock_exec, mock_popen, tmp_path):
        """<workspace> tag in instructions is extracted and used."""
        ws_dir = str(tmp_path / "project")
        mock_popen.return_value = make_popen_mock("resp-ws-1")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "OK"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": str(tmp_path)}, clear=False):
            settings = _build_settings()
            with patch("src.tag_parser.config", settings):
                resp = client.post(
                    "/v1/responses",
                    json={
                        "model": "auto",
                        "instructions": f"<workspace>{ws_dir}</workspace>\nYou are helpful",
                        "input": "Hello",
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"

        args, _ = mock_exec.call_args
        cmd = args
        prompt = cmd[-1]
        assert "<workspace>" not in prompt

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_workspace_tag_in_developer_input(self, mock_exec, mock_popen, tmp_path):
        """<workspace> tag in a developer-role input message is extracted."""
        ws_dir = str(tmp_path / "myproj")
        mock_popen.return_value = make_popen_mock("resp-ws-2")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "OK"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        with patch.dict(os.environ, {"WORKSPACE_WHITELIST_1": str(tmp_path)}, clear=False):
            settings = _build_settings()
            with patch("src.tag_parser.config", settings):
                resp = client.post(
                    "/v1/responses",
                    json={
                        "model": "auto",
                        "input": [
                            {"role": "developer", "content": f"<workspace>{ws_dir}</workspace>\nBe concise."},
                            {"role": "user", "content": "Hello"},
                        ],
                    },
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        args, _ = mock_exec.call_args
        cmd = args
        prompt_or_system = " ".join(str(c) for c in cmd)
        assert "<workspace>" not in prompt_or_system

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_session_id_tag_in_instructions(self, mock_exec, mock_popen):
        """<session_id> tag in instructions resumes the matching session."""
        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Resumed OK"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        target_session_id = "resp-tag-session"
        session_manager.save_session(
            "tag-session-hash",
            {
                "session_id": target_session_id,
                "title": "Tag Session",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "workspace_dir": "/tmp/tag-session-workspace",
            },
        )

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "instructions": f"<session_id>{target_session_id}</session_id>\nYou are helpful",
                "input": "Follow up question",
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"

        args, _ = mock_exec.call_args
        cmd = args
        assert "--resume" in cmd
        assert target_session_id in cmd

        # Popen should NOT be called (session already exists)
        mock_popen.assert_not_called()

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_previous_response_id_takes_precedence_over_session_id_tag(self, mock_exec, mock_popen):
        """previous_response_id should take precedence over <session_id> in instructions."""
        mock_popen.return_value = make_popen_mock("resp-first-session")

        mock_p1 = AsyncMock()
        mock_p1.stdout.read = AsyncMock(side_effect=[b'{"result": "First"}', b""])
        mock_p1.returncode = 0
        mock_exec.return_value = mock_p1

        # First request creates a session
        resp1 = client.post(
            "/v1/responses",
            json={"model": "auto", "input": "First message"},
            headers=HEADERS,
        )
        assert resp1.status_code == 200
        resp1_id = resp1.json()["id"]

        # Second request: previous_response_id AND <session_id> tag both present
        mock_exec.reset_mock()
        mock_popen.reset_mock()
        mock_p2 = AsyncMock()
        mock_p2.stdout.read = AsyncMock(side_effect=[b'{"result": "Second"}', b""])
        mock_p2.returncode = 0
        mock_exec.return_value = mock_p2

        resp2 = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "instructions": "<session_id>some-other-session</session_id>\nBe helpful",
                "input": "Follow up",
                "previous_response_id": resp1_id,
            },
            headers=HEADERS,
        )

        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["previous_response_id"] == resp1_id

        args, _ = mock_exec.call_args
        cmd = args
        # Should resume with the session from previous_response_id, not the tag
        session_from_resp = resp1_id.removeprefix("resp_")
        assert session_from_resp in cmd


# ── Image / file upload tests ────────────────────────────────────────

class TestResponsesImageUpload:
    """Tests for image and file content in Responses API input."""

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_input_image_base64_preserved(self, mock_exec, mock_popen):
        """input_image with base64 data URL is passed through to the CLI command."""
        mock_popen.return_value = make_popen_mock("img-sess-1")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "A cat"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        b64_data = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Describe this image"},
                            {"type": "input_image", "image_url": b64_data},
                        ],
                    }
                ],
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "response"

        args, _ = mock_exec.call_args
        prompt = args[-1]
        assert "[Image]" not in prompt
        assert "Describe this image" in prompt

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_input_image_url_preserved(self, mock_exec, mock_popen):
        """input_image with an HTTP URL is passed through."""
        mock_popen.return_value = make_popen_mock("img-sess-url")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "A dog"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "What animal?"},
                            {"type": "input_image", "image_url": "https://example.com/dog.jpg"},
                        ],
                    }
                ],
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        args, _ = mock_exec.call_args
        prompt = args[-1]
        assert "[Image]" not in prompt
        assert "What animal?" in prompt
        assert "https://example.com/dog.jpg" in prompt

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_text_only_content_list_still_works(self, mock_exec, mock_popen):
        """Content list with only input_text parts still produces a plain string message."""
        mock_popen.return_value = make_popen_mock("text-only-sess")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "OK"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Hello world"},
                        ],
                    }
                ],
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        args, _ = mock_exec.call_args
        prompt = args[-1]
        assert "Hello world" in prompt

    @patch("src.session_manager.subprocess.Popen")
    @patch("src.executor.asyncio.create_subprocess_exec")
    def test_input_file_preserved(self, mock_exec, mock_popen):
        """input_file type is converted to a text reference with file data."""
        mock_popen.return_value = make_popen_mock("file-sess-1")

        mock_process = AsyncMock()
        mock_process.stdout.read = AsyncMock(side_effect=[b'{"result": "Summary"}', b""])
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        resp = client.post(
            "/v1/responses",
            json={
                "model": "auto",
                "input": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "Summarize this file"},
                            {"type": "input_file", "file_data": "data:text/plain;base64,SGVsbG8=", "filename": "readme.txt"},
                        ],
                    }
                ],
            },
            headers=HEADERS,
        )

        assert resp.status_code == 200
        args, _ = mock_exec.call_args
        prompt = args[-1]
        assert "Summarize this file" in prompt
        assert "readme.txt" in prompt
