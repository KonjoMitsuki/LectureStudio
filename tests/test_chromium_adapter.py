import json
import os
from pathlib import Path
import subprocess


def test_renderer_flags_cannot_disable_browser_protection(tmp_path):
    fake = tmp_path / 'browser'
    capture = tmp_path / 'args.json'
    fake.write_text('#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\nPath(' + repr(str(capture)) + ').write_text(json.dumps(sys.argv[1:]))\n')
    fake.chmod(0o755)
    wrapper = Path(__file__).resolve().parents[1] / 'scripts/chromium_sandbox.py'
    env = {**os.environ, 'LECTURE_CHROMIUM_PATH': str(fake)}
    subprocess.run([str(wrapper), '--no-sandbox', '--disable-setuid-sandbox', '--no-zygote',
        '--disable-web-security', '--ignore-certificate-errors', '--allow-running-insecure-content',
        '--disable-features=IsolateOrigins,site-per-process,Translate,LocalNetworkAccessChecks',
        '--headless=new', '--remote-debugging-port=0'], env=env, check=True, timeout=5)
    args = json.loads(capture.read_text())
    assert args == ['--disable-features=Translate', '--headless=new', '--remote-debugging-port=0']
