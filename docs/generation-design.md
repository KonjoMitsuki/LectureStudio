# 分割生成と描画の設計

## 診断から分かったこと

既存コードは全PDFの本文・項目一覧を再度まとめて送り、最大160シーンの台本を一度に生成していた。保存済みの計画以外に台本途中の再利用単位がなかった。既存の100ページの試行には出力64,393トークンの完了イベントがあり、別のJSONLには分類情報のないエラーイベント5件が残っていた。旧記録には発生時刻や詳細分類がなく、当該停止の原因を一つに確定することはできない。

HEADの旧実装と変更後を同じ入力で比較した。5MiBの1行は旧実装でValueError、17MiBの連続出力は旧実装でRuntimeErrorとなり、変更後は両方が終了コード0で完了した（`data/process-limit-reproduction.json`）。上限・時間切れ・中断で子プロセス群が停止することもテストで確認する。通常サンドボックスでのCodex状態ディレクトリ書込み警告と、APIテストのスレッド通知停止は、この開発環境で別途確認した制約。保護設定を無効化せず、通常の実行環境で検証する。

## 生成と再開

1. 全ページを先頭から順に、最大3ページ・目安12,000文字ずつ計画化する。単一ページの本文は切り捨てない。本文のない分割は空の項目一覧を許可し、結合した全体には説明可能な項目が必要。
2. 原文抜粋・実在ページ・全ページの検査を通った計画を保存し、全体で項目IDを振り直す。
3. PDFから抽出した見出し境界と最大6項目を目安に台本を分ける。同じページに多数の項目があっても分割可能。各分割は関係ページの全文と担当項目だけを受け取る。
4. JSON・参照・cue・クイズ数・項目対応を検査してから `validated.json` を原子的に保存する。
5. 時間切れ・出力上限・繰返す検証失敗は当該部分を二分する。認証・利用枠・接続などは自動で反復しない。分割済みの親は再実行せず、成功した子を再利用する。
6. 全分割を結合してシーンIDを振り直し、全項目の説明文と参照ページを再検査する。

成果物のキーは生成バージョン・入力・設定・プロンプトから計算する。成功した部分も読込時に再検証する。旧形式の台本は引き続き読めるが、生成設定のキャッシュは新バージョンで更新される。

`ai/plans/<hash>/` と `ai/chapters/<hash>/` は非公開の生成成果物。回答JSONには本文・台本が含まれる。`ai/chapters.json` は完了数と失敗位置を持ち、再試行は既存の「保存済みの工程から再試行」から行える。

動画時間の上限はない。1200項目・12,000シーン等の入力／構造上の資源上限を超えた場合は、内容を削って成功扱いにせずエラーにする。scene IDは3〜6桁で、既存の3桁IDとの互換性を保つ。

## 安全な進捗

`codex exec --json` を起動直後から読み、イベント種別・許可された項目種別・非負整数のトークン使用量だけをJSONLへ即時保存する。生のCLI標準出力は保持しない。プロセス経過時間・出力バイト数・最後の出力・イベント件数・分割完了数・報告済み使用量を別々に管理する。

使用量は完了した呼出しの累計で、処理中の未報告トークン・契約の残量・料金を推測しない。エラー分類も固定ラベルに変換してから保存する。診断DB、エラーJSON、render.logにはPDF本文・項目タイトル・台本・任意の外部エラーメッセージを新たに記録しない。更新前に作られた履歴は変更しないため、旧履歴には従来の抜粋が残り得る。

## 音声と再試行

音声合成は `LECTURE_VOICE_CONCURRENCY`（既定2、1〜8）で同時実行数を制限する。終了順によらず元のシーン順に整列し、同じ本文の合成は一つのタスクを共有して音声キャッシュへの同時書込みを避ける。失敗・中断では待機中のタスクもキャンセルし、成功済みWAVを再利用する。VOICEVOX起動スクリプトは本文を含み得るENGINEのアクセスログを保存せず、アプリの安全な件数・状態で稼働を確認する。

## 固定テンプレートと同期

各シーンは `renderer=remotion|manim` と任意の `animation` を持つ。旧シーンの既定値はRemotion。animationはarray、tree、graph、formula、complexityと状態スナップショットだけを受け取り、型・長さ・数値・参照・木の連結性・循環・cueを検査する。

Manimはリポジトリ内の固定Pythonファイルだけを実行する。AI生成Python、eval、動的import、AIのTeXを実行しない。数式はPango TextでUnicode平文を表示し、TeXコンパイラを必要としない。計算量曲線は定義済みの数値関数のみ。

図解MP4は1696×480・30fpsで音声シーンのフレーム数に合わせる。Remotionでタイトル・字幕・出典と従来図解を描画し、FFmpegでManimを左112・上300の領域に合成する。字幕は上816から開始し、図解下端780との間に36pxを確保する。Manimクリップの尺・H.264・解像度・fpsを検査してから合成する。最後に1920×1080・30fps・H.264/AACと総尺を再検査する。

Remotionの描画とFFmpegのエンコードは分離している。実際に変化する20フレームの表示区間、強調・字幕・状態の切替えとフェードだけをJPEGへ描画し、原子的に保存する。`frame_cache/<hash>/` のキーには構成・動画ソース・依存ロックを含め、各画像のSHA-256を再検証する。中断・破損時は欠けたフレームだけを再描画する。画像列の時刻をFFmpegで元の30fpsタイムラインへ復元してから音声と結合する。JPEGは非公開の映像成果物であり、診断ログではない。

Manimが起動・描画・検査に失敗した場合は同じ状態スナップショットをRemotionの固定図解で表示する。`render_report.json` に実際の方式とフォールバック理由を記録する。正常なManimクリップは再検査して再利用する。

音声と状態遷移・字幕の同期は、実測WAV長と台本中のcueの文字位置による近似であり、音素レベルの強制アラインメントではない。網羅性検査は抽出項目と説明原文の対応を保証し、元資料からの抽出漏れ・説明の意味的正しさ・図だけの内容まで自動保証しない。

## 検証コマンド

```bash
.venv/bin/python -m pytest -q
node tests/timeline.test.mjs
node tests/frame-cache.test.mjs
video/node_modules/.bin/tsc -p video/tsconfig.json
npm --prefix frontend run build
PLAYWRIGHT_BROWSERS_PATH="$PWD/tools/playwright" npx playwright test tests/e2e/diagnostics.spec.ts
.venv/bin/python scripts/verify_manim.py
# 実VOICEVOXが必要
.venv/bin/python scripts/verify_hybrid.py
.venv/bin/python scripts/verify_hybrid.py --force-fallback
# 実Codex・実VOICEVOX・ブラウザが必要。入力は既存の講義PDF、成果物は別領域へ保存
.venv/bin/python scripts/validate_lecture.py /absolute/path/lecture.pdf --output data/acceptance --require-manim
# 完成済みの検証データを別ポートで開き、実ブラウザ操作を確認
LECTURE_DATA_DIR="$PWD/data/acceptance" .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
# 別ターミナル
PLAYWRIGHT_BROWSERS_PATH="$PWD/tools/playwright" node scripts/verify_browser.mjs data/acceptance http://127.0.0.1:8001
```

公式のイベント仕様と描画仕様は [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)、[Manim Text](https://docs.manim.community/en/stable/guides/using_text.html) を参照。
