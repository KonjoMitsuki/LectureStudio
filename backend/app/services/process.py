"""Subprocesses use argument arrays and bounded lifetime; kill entire process groups."""
import asyncio
import os
import signal
from pathlib import Path


async def run_process(args: list[str], *, cwd: Path, timeout: int, stdin: str | None = None,
                      env: dict | None = None, on_line=None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, start_new_session=True,
        limit=4 * 1024 * 1024,
    )
    async def collect(stream, callback=None):
        parts = []
        total = 0
        while line := await stream.readline():
            decoded = line.decode("utf-8", errors="replace")
            total += len(line)
            if total > 16 * 1024 * 1024:
                raise RuntimeError("プロセスの出力が上限を超えました")
            parts.append(decoded)
            if callback:
                callback(decoded)
        return "".join(parts)

    async def communicate():
        if stdin:
            proc.stdin.write(stdin.encode())
            await proc.stdin.drain()
            proc.stdin.close()
        out, err = await asyncio.gather(collect(proc.stdout, on_line), collect(proc.stderr))
        await proc.wait()
        return proc.returncode, out, err
    try:
        return await asyncio.wait_for(communicate(), timeout)
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        raise
