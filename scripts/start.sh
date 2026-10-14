#!/usr/bin/env bash
set -euo pipefail
LECTURE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LECTURE_ROOT"
if [[ ! -x .venv/bin/uvicorn || ! -f frontend/dist/index.html ]]; then
  echo "依存をインストールし、npm run build を実行してください。READMEを参照できます。" >&2
  exit 1
fi
echo "Lecture Studio: http://localhost:8000"
echo "VOICEVOX ENGINEを先に起動してください。終了するにはCtrl+Cを押します。"
exec .venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
