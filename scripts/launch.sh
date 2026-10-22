#!/usr/bin/env bash
set -Eeuo pipefail

LECTURE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$LECTURE_ROOT"

# Avoid starting a second worker against the same SQLite database when the app
# is already serving requests (for example, after running `npm start` twice).
if curl --silent --fail --max-time 1 http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "Lecture Studioはすでに起動しています: http://localhost:8000"
  exit 0
fi

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Python依存がありません。READMEのインストール手順を先に実行してください。" >&2
  exit 1
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "フロントエンド依存がありません。READMEのインストール手順を先に実行してください。" >&2
  exit 1
fi
if [[ ! -d frontend/dist ]]; then
  echo "初回ビルドを実行します..."
  npm run build
fi

LECTURE_ENGINE_PID=""
lecture_cleanup() {
  if [[ -n "$LECTURE_ENGINE_PID" ]] && kill -0 "$LECTURE_ENGINE_PID" 2>/dev/null; then
    echo "VOICEVOX ENGINEを終了しています..."
    kill "$LECTURE_ENGINE_PID" 2>/dev/null || true
    wait "$LECTURE_ENGINE_PID" 2>/dev/null || true
  fi
}
trap lecture_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

LECTURE_VOICEVOX_URL="${LECTURE_VOICEVOX_URL:-http://127.0.0.1:50021}"
export LECTURE_VOICEVOX_URL
if ! curl --silent --fail --max-time 1 "${LECTURE_VOICEVOX_URL%/}/version" >/dev/null 2>&1; then
  LECTURE_ENGINE="$LECTURE_ROOT/tools/voicevox/engine/linux-cpu-x64/run"
  if [[ "$LECTURE_VOICEVOX_URL" != "http://127.0.0.1:50021" && "$LECTURE_VOICEVOX_URL" != "http://localhost:50021" ]]; then
    echo "設定されたVOICEVOX ENGINEに接続できません: $LECTURE_VOICEVOX_URL" >&2
    echo "ENGINEを起動し、.envのLECTURE_VOICEVOX_URLを確認してください。" >&2
    exit 1
  fi
  if [[ ! -x "$LECTURE_ENGINE" ]]; then
    echo "VOICEVOX ENGINEが見つかりません。READMEの導入手順を実行するか、外部ENGINEを起動してください。" >&2
    exit 1
  fi
  mkdir -p "$LECTURE_ROOT/tools/voicevox/state"
  echo "VOICEVOX ENGINEを起動しています..."
  XDG_DATA_HOME="$LECTURE_ROOT/tools/voicevox/state" "$LECTURE_ENGINE" \
    --host 127.0.0.1 --cpu_num_threads 2 --disable_mutable_api > /dev/null 2>&1 &
  LECTURE_ENGINE_PID=$!
  for _ in $(seq 1 90); do
    if curl --silent --fail --max-time 1 "${LECTURE_VOICEVOX_URL%/}/version" >/dev/null 2>&1; then
      break
    fi
    if ! kill -0 "$LECTURE_ENGINE_PID" 2>/dev/null; then
      # A different ENGINE may have won the port bind while this process was starting.
      if curl --silent --fail --max-time 1 "${LECTURE_VOICEVOX_URL%/}/version" >/dev/null 2>&1; then
        LECTURE_ENGINE_PID=""
        break
      fi
      echo "VOICEVOX ENGINEが起動に失敗しました。" >&2
      exit 1
    fi
    sleep 1
  done
  if ! curl --silent --fail --max-time 1 "${LECTURE_VOICEVOX_URL%/}/version" >/dev/null 2>&1; then
    echo "VOICEVOX ENGINEの起動を待ちましたが応答がありません。" >&2
    exit 1
  fi
else
  echo "起動済みのVOICEVOX ENGINEを使用します。"
fi

echo "Lecture Studioを起動します: http://localhost:8000"
echo "終了するにはCtrl+Cを押してください。"
.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --workers 1
