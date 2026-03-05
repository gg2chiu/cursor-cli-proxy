"""Tests for Executor process cleanup behavior."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from src.executor import Executor


class AsyncIterLines:
    """Async iterator over a list of byte lines, for mocking process.stdout."""
    def __init__(self, lines):
        self._iter = iter(lines)
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def make_mock_process(returncode=None):
    """Create a mock asyncio subprocess."""
    process = AsyncMock()
    process.pid = 12345
    process.terminate = MagicMock()
    process.kill = MagicMock()
    type(process).returncode = PropertyMock(return_value=returncode)
    process.wait = AsyncMock()
    process.stdout = AsyncMock()
    process.stderr = AsyncMock()
    process.stderr.read = AsyncMock(return_value=b"")
    return process


class TestTerminateProcess:
    """Tests for _terminate_process graceful shutdown logic."""

    @pytest.fixture
    def executor(self):
        return Executor()

    async def test_skips_already_exited_process(self, executor):
        process = make_mock_process(returncode=0)

        await executor._terminate_process(process)

        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    async def test_tries_sigterm_first(self, executor):
        process = make_mock_process(returncode=None)
        # After terminate + wait, process exits
        async def fake_wait():
            type(process).returncode = PropertyMock(return_value=0)
        process.wait = AsyncMock(side_effect=fake_wait)

        await executor._terminate_process(process)

        process.terminate.assert_called_once()
        process.kill.assert_not_called()

    async def test_escalates_to_sigkill_after_sigterm_timeout(self, executor):
        process = make_mock_process(returncode=None)
        call_count = 0

        async def fake_wait():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            type(process).returncode = PropertyMock(return_value=-9)

        process.wait = AsyncMock(side_effect=fake_wait)

        await executor._terminate_process(process)

        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    async def test_logs_warning_if_sigkill_also_times_out(self, executor):
        process = make_mock_process(returncode=None)
        process.wait = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("src.executor.logger") as mock_logger:
            await executor._terminate_process(process)

            process.terminate.assert_called_once()
            process.kill.assert_called_once()
            mock_logger.error.assert_called_once()
            assert "12345" in mock_logger.error.call_args[0][0]


class TestRunNonStreamCleanup:
    """Tests that run_non_stream cleans up the process properly."""

    @pytest.fixture
    def executor(self):
        return Executor()

    @patch("src.executor.asyncio.create_subprocess_exec")
    async def test_terminates_process_after_getting_result(self, mock_create, executor):
        process = make_mock_process(returncode=None)
        process.stdout.read = AsyncMock(side_effect=[b'{"result": "ok"}', b""])
        mock_create.return_value = process

        async def fake_wait():
            type(process).returncode = PropertyMock(return_value=0)
        process.wait = AsyncMock(side_effect=fake_wait)

        result = await executor.run_non_stream(["test"])
        assert result == "ok"
        process.terminate.assert_called_once()

    @patch("src.executor.asyncio.create_subprocess_exec")
    async def test_terminates_process_on_timeout(self, mock_create, executor):
        process = make_mock_process(returncode=None)

        async def hang_forever(*args):
            await asyncio.sleep(999)
        process.stdout.read = AsyncMock(side_effect=hang_forever)
        mock_create.return_value = process

        async def fake_wait():
            type(process).returncode = PropertyMock(return_value=-15)
        process.wait = AsyncMock(side_effect=fake_wait)

        with pytest.raises(RuntimeError, match="timed out"):
            await executor.run_non_stream(["test"], timeout=0.1)

        process.terminate.assert_called_once()


class TestRunStreamCleanup:
    """Tests that run_stream raises on unkillable (zombie) processes."""

    @pytest.fixture
    def executor(self):
        return Executor()

    @patch("src.executor.asyncio.create_subprocess_exec")
    async def test_stream_warns_on_zombie_process(self, mock_create, executor):
        """If process.returncode is still None after cleanup, run_stream warns but does not raise."""
        process = make_mock_process(returncode=None)
        process.stdout = AsyncIterLines([b'{"type":"result","duration_ms":100}\n'])
        process.wait = AsyncMock(side_effect=asyncio.TimeoutError())
        process.stderr.read = AsyncMock(return_value=b"")
        mock_create.return_value = process

        chunks = []
        with patch("src.executor.logger") as mock_logger:
            async for chunk in executor.run_stream(["test"]):
                chunks.append(chunk)
            mock_logger.warning.assert_any_call(
                f"Process {process.pid} could not be terminated and may still be running"
            )

    @patch("src.executor.asyncio.create_subprocess_exec")
    async def test_stream_ok_on_normal_exit(self, mock_create, executor):
        """Normal exit (returncode 0) should not raise."""
        process = make_mock_process(returncode=None)
        process.stdout = AsyncIterLines([b'{"type":"result","duration_ms":100}\n'])

        async def fake_wait():
            type(process).returncode = PropertyMock(return_value=0)
        process.wait = AsyncMock(side_effect=fake_wait)
        process.stderr.read = AsyncMock(return_value=b"")
        mock_create.return_value = process

        chunks = []
        async for chunk in executor.run_stream(["test"]):
            chunks.append(chunk)

    @patch("src.executor.asyncio.create_subprocess_exec")
    async def test_stream_ok_on_sigkill_exit(self, mock_create, executor):
        """SIGKILL exit (returncode -9) should not raise."""
        process = make_mock_process(returncode=None)
        process.stdout = AsyncIterLines([b'{"type":"result","duration_ms":100}\n'])
        call_count = 0

        async def fake_wait():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise asyncio.TimeoutError()
            type(process).returncode = PropertyMock(return_value=-9)
        process.wait = AsyncMock(side_effect=fake_wait)
        process.stderr.read = AsyncMock(return_value=b"")
        mock_create.return_value = process

        chunks = []
        async for chunk in executor.run_stream(["test"]):
            chunks.append(chunk)
