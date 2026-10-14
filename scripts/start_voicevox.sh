#!/usr/bin/env bash
set -euo pipefail
LECTURE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LECTURE_ENGINE="$LECTURE_ROOT/tools/voicevox/engine/linux-cpu-x64/run"
if [[ ! -x "$LECTURE_ENGINE" || ! -s "$LECTURE_ENGINE" ]]; then
  echo "VOICEVOX ENGINEがありません。READMEのインストール手順を実行してください。" >&2
  exit 1
fi
export XDG_DATA_HOME="$LECTURE_ROOT/tools/voicevox/state"
exec "$LECTURE_ENGINE" --host 127.0.0.1 --cpu_num_threads 2 --disable_mutable_api
