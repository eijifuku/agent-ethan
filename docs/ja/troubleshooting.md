# トラブルシューティング

## 環境変数が未設定

```
AgentRuntimeError: environment variable 'OPENAI_API_KEY' is not set
```

実行前に環境変数を設定してください。

```bash
export OPENAI_API_KEY=sk-your-key
```

## ノード失敗時のエラー

```
NodeExecutionError: node 'filter' failed without on_error handler: ...
```

`on_error` を設定するか、バックエンド (例: OpenAI API) が利用できるか確認します。

## JSON 解析エラー

LLM が JSON を返さなくても `tools/arxiv_filter.py#parse_selection` がキーワード一致でフォールバックします。`state.relevance_raw` を確認すると入力内容を把握できます。

## テストがファイルを見つけられない

YAML 内の `impl` パスは YAML ファイルからの相対パスです。`examples/` 配下では `../agent_ethan/tools/...` のように指定してください。

## 調査のヒント

- `max_steps` を小さくして途中で停止し、ステートを確認する。
- ツール内で `logging` を有効にして入出力を記録する。
- `tool_overrides` で疑似データを注入し、外部依存を切り離してテストする。
