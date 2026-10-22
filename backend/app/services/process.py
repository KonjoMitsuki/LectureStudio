"""Subprocesses use argument arrays and bounded lifetime; kill entire process groups."""
import asyncio
import os
import signal
from pathlib import Path
from .diagnostics import current_log


class ProcessOutputLimit(RuntimeError):
    """A fixed, content-free error suitable for diagnostics."""


async def run_process(args: list[str], *, cwd: Path, timeout: int, stdin: str | None = None,
                      env: dict | None = None, on_line=None, on_stderr=None,
                      capture_output: bool = True, max_line_bytes: int = 8 * 1024 * 1024,
                      max_output_bytes: int = 64 * 1024 * 1024) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
        limit=64 * 1024,
    )
    log = current_log.get()
    if log:
        log.process_started(proc, timeout)
    async def collect(stream, callback=None):
        parts = []
        total, pending = 0, bytearray()
        def deliver(line):
            decoded = line.decode("utf-8", errors="replace")
            if capture_output:
                parts.append(decoded)
            if callback:
                callback(decoded)
        while chunk := await stream.read(64 * 1024):
            total += len(chunk)
            if total > max_output_bytes:
                raise ProcessOutputLimit("プロセスの出力総量が上限を超えました")
            if log:
                log.process_output(len(chunk))
            pending.extend(chunk)
            while (end := pending.find(b"\n")) >= 0:
                if end + 1 > max_line_bytes:
                    raise ProcessOutputLimit("プロセスの出力行が上限を超えました")
                deliver(pending[:end + 1])
                del pending[:end + 1]
            if len(pending) > max_line_bytes:
                raise ProcessOutputLimit("プロセスの出力行が上限を超えました")
        if pending:
            deliver(pending)
        return "".join(parts)

    async def communicate():
        readers = [asyncio.create_task(collect(proc.stdout, on_line)), asyncio.create_task(collect(proc.stderr, on_stderr))]
        async def write_input():
            try:
                proc.stdin.write(stdin.encode())
                await proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass  # Preserve the CLI's real startup error instead of a pipe error.
            finally:
                proc.stdin.close()
        tasks = readers + ([asyncio.create_task(write_input())] if stdin else [])
        try:
            results = await asyncio.gather(*tasks)
            out, err = results[:2]
            await proc.wait()
            return proc.returncode, out, err
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    try:
        result = await asyncio.wait_for(communicate(), timeout)
        if log:
            log.process_finished("completed" if proc.returncode == 0 else "failed", proc.returncode)
        return result
    except BaseException as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        if log:
            status = "timeout" if isinstance(exc, TimeoutError) else "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed"
            log.process_finished(status, proc.returncode)
        raise
