#!/usr/bin/env python3
"""Keep Chromium sandboxing enabled even when a renderer supplies disable flags.

Remotion 4's launcher unconditionally supplies --no-sandbox. This executable
adapter removes that flag rather than changing the dependency or weakening
browser protections. The actual browser is selected by the server, never AI.
"""
import os
import sys
from pathlib import Path

browser = os.environ.get("LECTURE_CHROMIUM_PATH")
if not browser or not Path(browser).is_file():
    sys.exit("LECTURE_CHROMIUM_PATH must name an installed Chromium executable")
blocked = {"--no-sandbox", "--disable-setuid-sandbox", "--no-zygote", "--disable-web-security",
           "--ignore-certificate-errors", "--allow-running-insecure-content", "--disable-site-isolation-trials",
           "--disable-ipc-flooding-protection", "--disable-client-side-phishing-detection", "--enable-unsafe-webgpu"}
protected_features = {"IsolateOrigins", "site-per-process", "LocalNetworkAccessChecks",
                      "BlockInsecurePrivateNetworkRequests", "PrivateNetworkAccessSendPreflights",
                      "PrivateNetworkAccessRespectPreflightResults"}
args = []
for arg in sys.argv[1:]:
    if arg == "--disable-dev-shm-usage" and os.environ.get("LECTURE_BROWSER_USE_SHM") == "1":
        continue
    if arg.split("=", 1)[0] in blocked:
        continue
    if arg.startswith("--disable-features="):
        features = [f for f in arg.split("=", 1)[1].split(",") if f not in protected_features]
        if features:
            args.append("--disable-features=" + ",".join(features))
    else:
        args.append(arg)
os.execv(browser, [browser, *args])
