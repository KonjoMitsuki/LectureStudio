# Lecture Studio

コンピュータサイエンスの講義PDFを、初学者向けの日本語解説・図解アニメーション・字幕・VOICEVOXナレーション付きのMP4へ変換するローカルアプリです。Remotionを維持し、数式やアルゴリズム等にはManimの固定テンプレートも使用できます。
仕様は [開発計画書](docs/PLAN.md)、実装状況は [TASKS](docs/TASKS.md)、過去の実測は [検証記録](docs/VALIDATION.md)、今回の検証は [分割生成・Manim検証](docs/VALIDATION-20261021.md) を参照してください。

資料全体から先に解説項目を抽出し、各項目を台本の説明文と対応させて解説漏れを検証します。時間と解説レベルによって項目を削らず、必要なら指定の目安より動画を長くします。表紙等の解説対象外や文字を抽出できないページには理由を記録し、埋め込み画像のみの内容は網羅未確認として表示します。項目と説明箇所の対応はプロジェクトの `coverage.json` に保存します。

字幕は台本を短く区切って画面下部に表示します。切り替え時刻は台本の文字位置と実音声の長さから推定するため、読み方によって音声と少しずれる場合があります。

約6分・16分・30分の設定では、それぞれ1問・2問・3問の理解確認クイズを入れます。問題の読み上げ後に約5秒の思考時間を設け、次のシーンで正答と理由を説明します。約1分のテスト設定ではクイズを入れません。既存の動画には再生成で反映されます。

## 必要環境

- Windows 11 + WSL2 Ubuntu。プロジェクトは `/mnt/c` ではなくWSLのLinuxファイルシステムへ配置。
- Python 3.12以上、Node.js 22.12以上（開発検証は24.13）、FFmpeg / FFprobe、7-Zip。
- ChatGPTアカウントで認証したCodex CLI。今回の検証バージョンは0.163.0。
- 無料のVOICEVOX ENGINE。付属の導入スクリプトはCPU版0.25.2を使用。
- ENGINE・ブラウザ・依存・動画保存用に十分なディスク空き容量（導入時約8GB以上推奨）。

有料のOpenAI APIキーを使いません。CodexにはChatGPT契約の利用制限が適用されます。

分割生成・再開とManimの固定テンプレートを実装済みです。既存の7ページの講義PDFから41項目・53シーン、21分33秒の実ナレーション付きMP4を生成し、実ブラウザで再生・章移動・保存を確認しました。詳細と検証の限界は今回の検証記録に記載しています。

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
「処理の記録」には工程ごとの成功・失敗、所要時間、分割の完了数、Codex受信イベント数・報告済み使用トークン数、音声の作成数、動画の書き出し状況を表示します。
新しい6件を表示し、以前の記録は折りたたんでいます。「保存済みの生成物」から台本の全文も読めます。
稼働確認は約15秒ごと、画面の記録取得は約3秒ごとです。「最終稼働確認」はアプリの処理の応答、「最後の進捗更新」は工程が進んだ時刻です。
外部処理の動作確認や最後の応答、待機上限も別に表示するため、稼働確認だけを進捗とは扱いません。
「全記録を保存」で全試行の日本語ログを保存でき、再試行前の履歴も選択できます。更新後の診断ログにはPDF本文・項目タイトル・台本を記録しません。更新前に作られた履歴の抜粋は保持されます。
この記録は更新後の生成から蓄積し、ログ追加前の処理には遡って追加されません。
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
node tests/frame-cache.test.mjs
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

`.env.example` を `.env` にコピーして設定できます。主な項目は `LECTURE_VOICEVOX_URL`、`LECTURE_CODEX_TIMEOUT`、`LECTURE_RENDER_CONCURRENCY`、`LECTURE_VOICE_CONCURRENCY`（音声の同時合成数・既定2）。
Chromiumを既に導入している場合は `LECTURE_CHROMIUM_PATH` に実行ファイルの絶対パスを指定できます。

- Codexエラー: 表示された分類で対処します。認証エラーはアプリと同じWSLユーザーで `codex login status` を確認、利用制限は回復後に再試行。出力スキーマエラーはアプリを更新・再起動。ファイル権限エラーは通常のWSLターミナルから起動します。CLIのバージョンは `codex --version`、安全な診断分類はプロジェクトの `ai/failure.json`（分割生成では `ai/plans/<hash>/plan_failure.json`・`ai/chapters/<hash>/failure.json`）で確認できます。
- VOICEVOXエラー: `curl http://127.0.0.1:50021/version` で接続確認。ENGINEを先に起動。
- レンダリングエラー: 対象プロジェクトの `render.log` を確認。Chromium起動時の権限やLinux依存を確認。
- 画像だけのPDF: OCRは未対応。OCR済みのPDFを使用。
- 長い資料: 30MB・100ページ・抽出10万文字を上限とし、超える資料は分割。

AIの待機上限は解説項目の整理・台本生成の**1回につき15分**（`LECTURE_CODEX_TIMEOUT=900`）、動画書き出しは2時間（`LECTURE_RENDER_TIMEOUT=7200`）です。
項目抽出はページ単位、台本は見出し・トピック単位に分割します。成功した部分を検証して保存し、時間切れ・出力上限・検証失敗は該当部分をさらに二分して再試行します。認証・接続・利用枠の失敗では自動反復しません。
時間切れでもAIの受信イベントの概要（`ai/plans/**/plan_events_*.jsonl`・`ai/chapters/**/events_*.jsonl`）と動画書き出しの途中記録（`render.log`）を残します。
画面の記録は `data/lecture.db` に保存され、対象講義を削除すると一緒に削除されます。

Remotionの共有メモリ描画は通常のChromiumに合わせて無効にし、標準フレーム撮影を使います。
動きのある区間と強調・字幕の切り替えをRemotionでJPEGへ保存し、ハッシュを検証して再利用します。欠けたフレームだけを描き直し、静止区間をFFmpegで30fpsに復元します。元のフレーム時刻とWAVの実時間を保持して音声を結合します。
ブラウザのサンドボックス・Web security・サイト分離の保護は起動アダプターで維持します。
問題回避のための `--no-sandbox` や `--dangerously-bypass-approvals-and-sandbox` は使用しません。

## データの扱いと制約

抽出テキストとページ番号をCodex経由でOpenAIへ送信します。PDF本文は信頼できないデータとして扱い、シェルや命令として実行しません。
AIは定義済み図解のデータだけを生成し、JSON Schema・参照ページ・ID・表示制限を検証します。
ページ画像・埋め込み画像はローカルで参照できます。初期版のAIは画像の意味を直接解析しません。
解説には誤りがあり得るため、元資料と照合してください。

ナレーションの長さはWAVのサンプル数から測定し、シーン末尾に0.5秒の余裕を加えます。指定尺は目安で、無音の水増しはしません。
Remotionと、使用するVOICEVOX話者の利用規約・クレジット表記に従ってください。

## 分割生成とManim

動画時間に上限を設けず、全解説項目の説明を優先します。`LECTURE_PLAN_CHUNK_PAGES`（既定3）、`LECTURE_CHAPTER_TOPICS`（既定6）、`LECTURE_CHUNK_TEXT_CHARS`（既定12000）で1回の生成単位を調整できます。成功済みの分割は再検証して再利用し、失敗部分だけを再試行します。

Remotionは従来どおり使用します。Manimを追加する場合は、Cairo/Pangoの開発ライブラリを用意して同じ仮想環境へ任意依存を入れます。

```bash
sudo apt-get install libcairo2-dev libpango1.0-dev pkg-config
.venv/bin/pip install 'manim==0.19.0'
.venv/bin/python scripts/verify_manim.py
```

Manimは配列・木・グラフ・Unicode数式・計算量の固定テンプレートを描画します。AI生成PythonやTeXは実行しません。使用できなければ、同じ状態データをRemotionで表示し、`render_report.json` にフォールバックを記録します。最終映像は1920×1080・30fps、図解と字幕には独立した領域を確保します。

```bash
# 実VOICEVOXとの混在シーン検証
.venv/bin/python scripts/verify_hybrid.py
.venv/bin/python scripts/verify_hybrid.py --force-fallback
# 既存の実講義PDFから、時間上限なしで一連のサービスを検証
.venv/bin/python scripts/validate_lecture.py /absolute/path/lecture.pdf --output data/acceptance --require-manim
```

分割成果物・診断の扱い・検証の限界は [設計と検証手順](docs/generation-design.md) を参照してください。実測音声長とcue文字位置による同期は近似です。説明原文と項目の対応は検証しますが、内容の意味的な正確さや画像だけの情報の網羅は自動保証しません。
