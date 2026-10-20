# 技術調査（2026-10-13）

## Codex CLI

公式資料:

- [非対話実行](https://learn.chatgpt.com/docs/non-interactive-mode)
- [CLI reference](https://developers.openai.com/codex/cli/reference)
- [設定リファレンス](https://learn.chatgpt.com/docs/config-file/config-reference)
- [認証](https://developers.openai.com/codex/auth)

実環境は `codex-cli 0.160.1`、`codex login status` は `Logged in using ChatGPT`。
`codex exec` はstdinの `-`、`--json`、`--output-schema`、`-o`、`--ephemeral`、`--ignore-user-config` に対応。

`--json` の出力は講義JSONではなく実行イベントJSONL。最終応答を `-o` に保存し、JSON SchemaとPydanticで再検証する。
資料本文はJSONエンコードしてstdinの末尾に付与し、ファイルやシェルコマンドとして扱わない。

実装コマンドでは `--sandbox read-only` と `-a never` を使用し、shell/apps/plugins/browser/computer/multi_agent/skill_searchを無効にする。
画像参照・画像生成・目標・記憶ツールも無効にし、追加の実Codexプローブで動作を確認した。
`--ignore-user-config` でユーザーの任意MCP設定をロードせず、`web_search=disabled`、`project_doc_max_bytes=0` とする。
保存済みのChatGPT認証は再利用する。`forced_login_method=chatgpt` を指定し、子プロセスからAPIキー環境変数を除外する。
CLIのホームは変更せず、認証情報をコピー・出力しない。`--dangerously-bypass-approvals-and-sandbox` は使用しない。

CLIはモデル実行とは別に自身の状態ディレクトリへ書き込む。Codexの外側の実行制限ではホームが読み取り専用だったため、承認された通常ホスト実行で検証した。これはモデル側のread-onlyサンドボックスを変更しない。
モデル一覧更新のタイムアウト警告が出たが、最終JSON生成とSchema検証は成功した。

### 2026-10-15: 台本生成だけが失敗する問題

通常ホストの `codex-cli 0.162.1` に既存の台本スキーマを最小入力で渡すと、
HTTP 400 / `invalid_json_schema` が再現した。サーバーは `required` に
`coverage` が含まれていないため拒否していた。Pydanticは既定値がある項目を
必須から外すが、[Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)
は全プロパティを必須とする。送信用スキーマではルートと `$defs` を含むすべての
オブジェクトの `required` を補完する。既存成果物の読み込み時の既定値・検証は維持する。

`--json` のサーバーエラーはstderrではなくstdoutの `error` / `turn.failed` に入る。
両方から固定の安全な分類を判定し、スキーマ・権限・認証・接続・利用制限を区別する。
生エラーメッセージ・PDF本文・認証情報は診断ファイルへ保存しない。
以前の「ホームの読み取り専用」という診断は外側のエージェント環境での失敗であり、
通常ターミナルで実行された本ジョブのスキーマ拒否とは別の問題だった。

修正後は通常ホストで `CodexCLIAnalyzer._generate` から最小1シーンの実台本生成と
`validate_lecture` が成功した。関連テスト64件が通過。56ページの元ジョブ全体と
音声・動画生成はこの修正の確認では再実行していない。

## 採用する公式APIとSkill

- Remotion: ローカル `remotion-create` / `remotion-render` Skill。blankテンプレートを `video/` に保持。
  [renderMedia](https://www.remotion.dev/docs/renderer/render-media)、[動的メタデータ](https://www.remotion.dev/docs/dynamic-metadata)、[useCurrentFrame](https://www.remotion.dev/docs/use-current-frame)。
  アニメーションは全てフレームから計算し、CSS時間依存アニメーションを動画で使わない。
- VOICEVOX: [公式ENGINE API](https://voicevox.github.io/voicevox_engine/api/)、[公式リポジトリ](https://github.com/VOICEVOX/voicevox_engine)。
  `/audio_query` → speedScale変更 → `/synthesis`。PCM WAVのサンプル数から表示フレームを算出する。
- FastAPI: [UploadFile](https://fastapi.tiangolo.com/tutorial/request-files/)、[lifespan](https://fastapi.tiangolo.com/advanced/events/)。
  リクエストから長時間処理を分離し、SQLiteに工程を保存する単一ワーカーを使う。
- React: ローカルVercel React Skill。非同期処理をイベントで開始し、ポーリングの中断・後始末を実装。動画エンジンをUIにバンドルしない。
- Playwright: [公式テスト手順](https://playwright.dev/docs/intro)。実ブラウザと実サービスによるE2Eを、APIテストの代替にしない。

## ローカル運用と費用

サーバーとENGINEは127.0.0.1へバインドする。追加の有料APIを使用しない。
ChatGPT契約のCodex利用制限は適用されるため、自動リトライは構造不正の1回に限定する。
[Remotionライセンス](https://www.remotion.dev/docs/license) は利用者の規模・用途に応じて確認する。
音声の利用時は選択したVOICEVOX話者の規約・クレジット表記に従う。

## MVPの限界

OCR、図表の意味の画像認識、音声辞書、台本編集は後続Phase。
AIには抽出テキストとページ番号を送信する。ページ画像と埋め込み図はローカル参照用に保存する。
文字抽出の不完全なページを警告し、画像PDFのみの場合は明確なエラーとする。
推定尺は音声速度や読み方によって変動する。無音で尺を引き伸ばさず実音声の尺を表示する。
