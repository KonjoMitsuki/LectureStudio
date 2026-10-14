# Lecture Studio

日本語の講義PDFを、図解アニメーションとVOICEVOXナレーション付きのMP4へ変換するローカルアプリです。
仕様は [開発計画書](docs/PLAN.md)、実装状況は [TASKS](docs/TASKS.md)、実測結果は [検証記録](docs/VALIDATION.md) を参照してください。

## 必要環境

- Windows 11 + WSL2 Ubuntu。プロジェクトは `/mnt/c` ではなくWSLのLinuxファイルシステムへ配置。
- Python 3.12以上、Node.js 22.12以上（開発検証は24.13）、FFmpeg / FFprobe、7-Zip。
- ChatGPTアカウントで認証したCodex CLI。検証バージョンは0.160.1。
- 無料のVOICEVOX ENGINE。付属の導入スクリプトはCPU版0.25.2を使用。
- ENGINE・ブラウザ・依存・動画保存用に十分なディスク空き容量（導入時約8GB以上推奨）。

有料のOpenAI APIキーを使いません。CodexにはChatGPT契約の利用制限が適用されます。

Phase 0とMVPを実装済みです。検証用の日本語PDFから6分44秒の実ナレーション付きMP4を生成し、実ブラウザで再生・保存・再試行を確認しました。詳細と対象外の項目は検証記録に記載しています。

## インストール

WSL側のターミナルで実行します。Node.jsとCodex CLIは公式手順で事前に導入してください。

```bash
sudo apt update
sudo apt install python3-venv ffmpeg p7zip-full curl fonts-noto-cjk libnss3 libatk-bridge2.0-0 libgbm1 libasound2t64
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock
npm ci
npm --prefix video ci
npm --prefix frontend ci
PLAYWRIGHT_BROWSERS_PATH="$PWD/tools/playwright" npx playwright install chromium
chmod +x scripts/chromium_sandbox.py scripts/start_voicevox.sh scripts/start.sh
codex login
codex login status
```

CodexログインではChatGPT認証を選びます。ブラウザが自動で開けない場合は `codex login --device-auth` を使用してください。
npmインストールが失敗する場合は、同一フォルダで複数のインストールを同時に行わず `npx --yes npm@10.9.4 ci --prefix video` を実行します。

VOICEVOXのLinux ENGINEを導入する場合:

```bash
python3 scripts/download_voicevox.py
7z t tools/voicevox/engine.7z.001
7z x tools/voicevox/engine.7z.001 -otools/voicevox/engine -y
```

公式配布は約1.8GBです。スクリプトは取得済みの完全なバイト範囲を再利用します。
WindowsのVOICEVOX ENGINEを使用する場合はLinux版の導入は不要です。WSLから接続できるURLを `.env` の `LECTURE_VOICEVOX_URL` に指定してください。

## 起動と使用方法

インストール後は、プロジェクト直下で次の一つのコマンドを実行します。Linux版VOICEVOX ENGINEが導入済みなら一緒に起動し、Windows版など外部ENGINEが起動済みならそちらへ接続します。初回はフロントエンドも自動ビルドします。

```bash
npm start
```

起動後、Windowsのブラウザで **http://localhost:8000** を開きます。停止は同じターミナルで `Ctrl+C` です。開発時に個別起動したい場合は、`./scripts/start_voicevox.sh` と `./scripts/start.sh` を別ターミナルで実行できます。

1. 講義PDFを選択またはドラッグ。
2. 動画の長さ、解説レベル、映像スタイル、話者、読み上げ速度を選択。
3. 「動画を生成」を押す。
4. 工程別の進捗を確認し、完成した動画を再生。
5. チャプターを選んで移動し、`p.` ボタンで元のページを確認。「MP4を保存」でダウンロード。

失敗時は原因と診断情報を確認し、「保存済みの工程から再試行」を押してください。
ブラウザを閉じてもアプリを起動している間は処理が続きます。アプリ終了時の実行中ジョブは失敗状態へ移り、再起動後に再試行できます。
待機ジョブは再起動後に復元されます。1つのアプリプロセスが順番に処理するため、`--workers 1` で起動します。

ライブラリから既存動画を再生・再生成・削除できます。削除はその講義のPDFと動画を削除し、共有音声キャッシュを保持します。
工程・ジョブ・設定・シーン・音声の索引は `data/lecture.db`、成果物は `data/projects/<id>/` に保存します。

開発時はターミナルで `npm run dev` を実行すると、Viteからバックエンドへ `/api` をプロキシします。

## 技術検証の実行

ターミナル1でENGINEを起動:

```bash
./scripts/start_voicevox.sh
```

ターミナル2で実際の日本語PDFから動画を生成:

```bash
.venv/bin/python scripts/make_sample_pdf.py
.venv/bin/python scripts/phase0.py
# 別のPDFを使う場合
.venv/bin/python scripts/phase0.py /absolute/path/lecture.pdf
```

生成動画は `data/phase0/video.mp4`、台本は `lecture.json`、ページ参照は `pages/`、実測メタデータは `video_metadata.json` に保存します。
成功時にPASSが表示されます。失敗時は台本と音声が保持され、同じコマンドで再利用されます。

## テスト

```bash
.venv/bin/python -m pytest -q
node tests/timeline.test.mjs
video/node_modules/.bin/tsc -p video/tsconfig.json
# 起動済みの実アプリ・実ENGINEを使うブラウザE2E（5〜10分動画を実生成）
PLAYWRIGHT_BROWSERS_PATH="$PWD/tools/playwright" npm run test:e2e
# アップロード・生成済みの同一講義から検証を継続する場合
LECTURE_E2E_PROJECT_ID=your_project_id PLAYWRIGHT_BROWSERS_PATH="$PWD/tools/playwright" npm run test:e2e
# 実Codexを使うプロンプト注入検証（契約の利用量を消費）
.venv/bin/python scripts/security_probe.py
# 動画の制作プレビュー
npm run video:studio
```

テスト内のモックVOICEVOX成功と、実ENGINEによる動画生成成功は検証記録で区別します。
Codexから実行している場合、外側のサンドボックスがスレッド間通知を制限するとAPIテストが停止することがあります。通常のWSLターミナルで同じコマンドを実行してください。アプリ・モデル側の保護設定を変更する必要はありません。

## 設定と障害調査

`.env.example` を `.env` にコピーして設定できます。主な項目は `LECTURE_VOICEVOX_URL`、`LECTURE_CODEX_TIMEOUT`、`LECTURE_RENDER_CONCURRENCY`。
Chromiumを既に導入している場合は `LECTURE_CHROMIUM_PATH` に実行ファイルの絶対パスを指定できます。

- Codexエラー: `codex login status` と `codex --version` を確認。認証期限切れは再ログイン、利用制限は回復後に再試行。
- VOICEVOXエラー: `curl http://127.0.0.1:50021/version` で接続確認。ENGINEを先に起動。
- レンダリングエラー: 対象プロジェクトの `render.log` を確認。Chromium起動時の権限やLinux依存を確認。
- 画像だけのPDF: OCRは未対応。OCR済みのPDFを使用。
- 長い資料: 30MB・100ページ・抽出10万文字を上限とし、超える資料は分割。

Remotionの共有メモリ描画は通常のChromiumに合わせて無効にし、標準フレーム撮影を使います。
動きのあるフレームと強調切り替えのフレームをRemotionで描き、静止区間をFFmpegで30fpsに復元します。元のフレーム時刻とWAVの実時間を保持して音声を結合します。
ブラウザのサンドボックス・Web security・サイト分離の保護は起動アダプターで維持します。
問題回避のための `--no-sandbox` や `--dangerously-bypass-approvals-and-sandbox` は使用しません。

## データの扱いと制約

抽出テキストとページ番号をCodex経由でOpenAIへ送信します。PDF本文は信頼できないデータとして扱い、シェルや命令として実行しません。
AIは定義済み図解のデータだけを生成し、JSON Schema・参照ページ・ID・表示制限を検証します。
ページ画像・埋め込み画像はローカルで参照できます。初期版のAIは画像の意味を直接解析しません。
解説には誤りがあり得るため、元資料と照合してください。

ナレーションの長さはWAVのサンプル数から測定し、シーン末尾に0.5秒の余裕を加えます。指定尺は目安で、無音の水増しはしません。
Remotionと、使用するVOICEVOX話者の利用規約・クレジット表記に従ってください。
