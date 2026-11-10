"""Controlled external-process execution (07 Section 14).

COLMAP and OpenMVS are invoked with argument arrays, an explicit working
directory, a timeout, captured output and cooperative cancellation. No shell is
involved, so a filename or configuration value can never become a command.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .exceptions import EXTERNAL_TOOL_UNAVAILABLE, TOOL_TIMEOUT, ToolError

logger = logging.getLogger(__name__)

# How often the runner checks the timeout and calls the heartbeat hook.
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_TERMINATE_GRACE_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """What one external process did."""

    command: tuple[str, ...]
    exit_code: int
    duration_seconds: float
    log_path: Path
    timed_out: bool = False

    @property
    def succeeded(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def resolve_executable(command: str) -> str:
    """Resolve an executable path, raising a stable error when it is missing."""
    candidate = Path(command)
    if candidate.is_absolute() or os.sep in command:
        if not candidate.is_file():
            raise ToolError(EXTERNAL_TOOL_UNAVAILABLE, "A required reconstruction tool is missing.")
        if not os.access(candidate, os.X_OK):
            raise ToolError(
                EXTERNAL_TOOL_UNAVAILABLE, "A required reconstruction tool is not executable."
            )
        return str(candidate)
    located = shutil.which(command)
    if located is None:
        raise ToolError(EXTERNAL_TOOL_UNAVAILABLE, "A required reconstruction tool is unavailable.")
    return located


class CommandRunner:
    """Run one external command with a timeout, a log file and cancellation."""

    def __init__(
        self,
        *,
        poll_interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
        terminate_grace_seconds: float = DEFAULT_TERMINATE_GRACE_SECONDS,
    ) -> None:
        self._poll_interval = max(0.05, poll_interval_seconds)
        self._grace = max(0.0, terminate_grace_seconds)

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        timeout: int,
        log_path: Path,
        on_poll: Callable[[], None] | None = None,
    ) -> CommandOutcome:
        """Execute ``command``; raise on timeout, cancellation or a missing tool.

        A non-zero exit code is *returned*, not raised: the caller maps it to the
        stage-specific error code in the specification.
        """
        if not command:
            raise ToolError(EXTERNAL_TOOL_UNAVAILABLE, "No command was supplied.")
        resolved = [resolve_executable(command[0]), *[str(part) for part in command[1:]]]
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        started = time.monotonic()
        with log_path.open("a", encoding="utf-8", errors="replace") as log_file:
            log_file.write(f"\n# {time.strftime('%Y-%m-%dT%H:%M:%S')} {shlex.join(resolved)}\n")
            log_file.flush()
            try:
                process = subprocess.Popen(  # noqa: S603 - argument array, no shell
                    resolved,
                    cwd=str(cwd),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    text=True,
                    start_new_session=True,
                )
            except OSError as exc:
                raise ToolError(
                    EXTERNAL_TOOL_UNAVAILABLE, "A required reconstruction tool could not start."
                ) from exc

            timed_out = False
            while True:
                try:
                    exit_code = process.wait(timeout=self._poll_interval)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started > timeout:
                        timed_out = True
                        self._terminate(process)
                        exit_code = process.returncode if process.returncode is not None else -1
                        break
                    if on_poll is not None:
                        try:
                            on_poll()
                        except BaseException:
                            # Any heartbeat/cancellation/budget failure stops the
                            # process group before the error propagates.
                            self._terminate(process)
                            raise

        duration = round(time.monotonic() - started, 3)
        if timed_out:
            logger.error(
                "scene_tool_timeout",
                extra={
                    "operation": "scene_reconstruction",
                    "tool": Path(resolved[0]).name,
                    "timeout_seconds": timeout,
                },
            )
            raise ToolError(
                TOOL_TIMEOUT, "A reconstruction stage exceeded its configured time limit."
            )
        return CommandOutcome(
            command=tuple(resolved),
            exit_code=exit_code,
            duration_seconds=duration,
            log_path=log_path,
            timed_out=False,
        )

    def _terminate(self, process: subprocess.Popen[str]) -> None:
        """Terminate the whole process group, then kill it after a grace period."""
        if process.poll() is not None:
            return
        try:
            if hasattr(os, "killpg"):
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            else:  # pragma: no cover - POSIX only in the worker image
                process.terminate()
            process.wait(timeout=self._grace)
        except subprocess.TimeoutExpired:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                else:  # pragma: no cover
                    process.kill()
            except ProcessLookupError:
                return
            process.wait(timeout=self._grace)
        except ProcessLookupError:
            return


def tail_log(path: Path, *, lines: int = 20, max_characters: int = 4000) -> str:
    """Return the tail of a tool log for the worker log, never for the API."""
    try:
        content = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = "\n".join(content.splitlines()[-lines:])
    return tail[-max_characters:]


__all__ = [
    "CommandOutcome",
    "CommandRunner",
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "resolve_executable",
    "tail_log",
]
