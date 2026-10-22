import asyncio
import sys

import pytest

from backend.app.services.process import ProcessOutputLimit, run_process


async def test_long_jsonl_line_over_old_stream_limit_is_delivered(tmp_path):
    lengths = []
    code, out, err = await run_process([sys.executable, '-c',
        'import sys; sys.stdout.write("x" * (5 * 1024 * 1024) + "\\n")'], cwd=tmp_path,
        timeout=10, on_line=lambda line: lengths.append(len(line)), capture_output=False)
    assert code == 0 and out == err == ''
    assert lengths == [5 * 1024 * 1024 + 1]


async def test_line_limit_terminates_process_without_exposing_content(tmp_path):
    with pytest.raises(ProcessOutputLimit, match='出力行') as error:
        await run_process([sys.executable, '-c',
            'import sys,time; sys.stdout.write("private" * 10000); sys.stdout.flush(); time.sleep(20)'],
            cwd=tmp_path, timeout=5, max_line_bytes=1024)
    assert 'private' not in str(error.value)


async def test_streaming_output_over_old_total_limit_without_retention(tmp_path):
    count = 0
    def line(value):
        nonlocal count
        count += 1
    code, out, err = await run_process([sys.executable, '-c',
        'import sys; [sys.stdout.write("x" * 65535 + "\\n") for _ in range(270)]'],
        cwd=tmp_path, timeout=10, on_line=line, capture_output=False)
    assert code == 0 and count == 270 and out == err == ''


async def test_output_limit_kills_process_group(tmp_path):
    pidfile = tmp_path / 'pid'
    script = ('import subprocess,sys,time,pathlib; '
        'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"]); '
        f'pathlib.Path({str(pidfile)!r}).write_text(str(p.pid)); '
        'print("x" * 10000,flush=True); time.sleep(30)')
    with pytest.raises(ProcessOutputLimit):
        await run_process([sys.executable, '-c', script], cwd=tmp_path, timeout=5, max_output_bytes=100)
    import os
    pid = int(pidfile.read_text())
    for _ in range(100):
        try:
            state = __import__('pathlib').Path(f'/proc/{pid}/stat').read_text().split()[2]
        except FileNotFoundError:
            break
        if state == 'Z':
            break
        await asyncio.sleep(.01)
    else:
        pytest.fail('child process remained alive')


async def test_output_failure_is_not_blocked_by_a_child_that_never_reads_stdin(tmp_path):
    from time import monotonic
    started = monotonic()
    with pytest.raises(ProcessOutputLimit):
        await run_process([sys.executable, '-c',
            'import time; print("x" * 10000,flush=True); time.sleep(30)'], cwd=tmp_path,
            timeout=5, stdin='private input' * 100000, max_output_bytes=100)
    assert monotonic() - started < 2
