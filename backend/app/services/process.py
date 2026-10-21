"""Subprocesses use argument arrays and bounded lifetime; kill entire process groups."""
import asyncio
import os
import signal
from pathlib import Path
from .diagnostics import current_log


async def run_process(args: list[str], *, cwd: Path, timeout: int, stdin: str | None = None,
                      env: dict | None = None, on_line=None, on_stderr=None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
        limit=4 * 1024 * 1024,
    )
    log = current_log.get()
    if log:
        log.process_started(proc, timeout)
    async def collect(stream, callback=None):
        parts = []
        total = 0
        while line := await stream.readline():
            decoded = line.decode("utf-8", errors="replace")
            total += len(line)
            if total > 16 * 1024 * 1024:
                raise RuntimeError("プロセスの出力が上限を超えました")
            parts.append(decoded)
            if log:
                log.process_output()
            if callback:
                callback(decoded)
        return "".join(parts)

    async def communicate():
        readers = [asyncio.create_task(collect(proc.stdout, on_line)), asyncio.create_task(collect(proc.stderr, on_stderr))]
        try:
            if stdin:
                proc.stdin.write(stdin.encode())
                await proc.stdin.drain()
                proc.stdin.close()
            out, err = await asyncio.gather(*readers)
            await proc.wait()
            return proc.returncode, out, err
        finally:
            for reader in readers:
                reader.cancel()
            await asyncio.gather(*readers, return_exceptions=True)
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
