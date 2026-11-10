"""External-process execution: timeouts, cancellation and missing tools (07 Section 14)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from scene_reconstruction.exceptions import (
    EXTERNAL_TOOL_UNAVAILABLE,
    TOOL_TIMEOUT,
    SceneCancelled,
    ToolError,
)
from scene_reconstruction.runner import CommandRunner, resolve_executable, tail_log


def _python_script(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "probe.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_runs_a_command_and_captures_its_log(tmp_path):
    runner = CommandRunner(poll_interval_seconds=0.05)
    log = tmp_path / "probe.log"
    outcome = runner.run(
        [sys.executable, "-c", "print('hello'); print('world')"],
        cwd=tmp_path,
        timeout=30,
        log_path=log,
    )
    assert outcome.succeeded is True
    assert outcome.exit_code == 0
    assert "hello" in log.read_text(encoding="utf-8")
    assert "world" in tail_log(log)


def test_returns_a_non_zero_exit_code_instead_of_raising(tmp_path):
    runner = CommandRunner(poll_interval_seconds=0.05)
    outcome = runner.run(
        [sys.executable, "-c", "raise SystemExit(3)"],
        cwd=tmp_path,
        timeout=30,
        log_path=tmp_path / "probe.log",
    )
    assert outcome.exit_code == 3
    assert outcome.succeeded is False


def test_times_out_and_kills_the_process(tmp_path):
    script = _python_script(tmp_path, "import time\nprint('started', flush=True)\ntime.sleep(30)\n")
    runner = CommandRunner(poll_interval_seconds=0.05, terminate_grace_seconds=1)
    started = time.monotonic()
    with pytest.raises(ToolError) as exc:
        runner.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            timeout=1,
            log_path=tmp_path / "probe.log",
        )
    assert exc.value.error_code == TOOL_TIMEOUT
    assert time.monotonic() - started < 15
    assert "started" in (tmp_path / "probe.log").read_text(encoding="utf-8")


def test_cancellation_terminates_the_process_and_propagates(tmp_path):
    script = _python_script(tmp_path, "import time\nprint('started', flush=True)\ntime.sleep(30)\n")
    runner = CommandRunner(poll_interval_seconds=0.05, terminate_grace_seconds=1)

    def on_poll() -> None:
        raise SceneCancelled("cancelled")

    with pytest.raises(SceneCancelled):
        runner.run(
            [sys.executable, str(script)],
            cwd=tmp_path,
            timeout=60,
            log_path=tmp_path / "probe.log",
            on_poll=on_poll,
        )


def test_heartbeat_hook_is_called_while_the_process_runs(tmp_path):
    script = _python_script(tmp_path, "import time\ntime.sleep(0.6)\n")
    calls = {"count": 0}

    def on_poll() -> None:
        calls["count"] += 1

    runner = CommandRunner(poll_interval_seconds=0.05)
    runner.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        timeout=30,
        log_path=tmp_path / "probe.log",
        on_poll=on_poll,
    )
    assert calls["count"] >= 1


def test_missing_tool_is_reported_stably(tmp_path):
    runner = CommandRunner()
    with pytest.raises(ToolError) as exc:
        runner.run(
            [str(tmp_path / "does-not-exist")],
            cwd=tmp_path,
            timeout=10,
            log_path=tmp_path / "probe.log",
        )
    assert exc.value.error_code == EXTERNAL_TOOL_UNAVAILABLE


def test_searches_path_for_a_bare_command():
    resolved = resolve_executable("python")
    assert Path(resolved).is_file()


def test_absolute_executable_must_exist(tmp_path):
    with pytest.raises(ToolError):
        resolve_executable(str(tmp_path / "nope"))


def test_empty_command_is_rejected(tmp_path):
    with pytest.raises(ToolError):
        CommandRunner().run([], cwd=tmp_path, timeout=1, log_path=tmp_path / "x.log")
