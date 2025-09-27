# ランタイム実行

`AgentRuntime` はグラフに従ってノードを順次実行します。

## 入口

- `build_agent_from_path(path)` – YAML ファイルからランタイムを生成。
- `build_agent_from_yaml(data, base_path)` – 既存の辞書を利用。
- `AgentRuntime.run(inputs, llm_client=None, llm_callable=None, tool_overrides=None, max_steps=None, max_subgraph_depth=None)` – グラフを実行します。`llm_client` と `llm_callable` は同時指定不可です。

## ノードの種類

### ツールノード

1. `inputs` を Jinja でレンダリング。
2. 対応するツール関数を呼び出し。
3. `error` が無ければ `map` を適用しステートを更新。
4. 出力エッジをキューに追加。

### LLM ノード

1. プロンプトテンプレートをレンダリング。
2. `LLMClient` へリクエスト送信。
3. 正常終了時に `map` を適用。`error` がある場合は失敗として扱われます。

### ルーターノード

JsonLogic で条件を評価し、マッチしたケースをキューに追加。既定ルート (`default`) があれば最後に使用します。

### ループノード

`body` ノードを最大 `max_iterations` 回実行し、各ループ後に `until` 条件を評価します。エラーが発生すると `on_error` が処理します。

### サブグラフノード

名前付きサブグラフを再帰的に呼び出します。`max_subgraph_depth` で深さを制限できます。

## エラーハンドリング

- `on_error:
    to: fallback` – 指定ノードへ遷移。
- `on_error:
    resume: true` – エッジに沿って処理を継続。
- ハンドラ未設定で失敗した場合、`NodeExecutionError` が発生し、ノード種別／プロンプト／例外内容を含むメッセージが表示されます。

## リトライとタイムアウト

`retry` と `timeout` はノード単位・ツール単位で設定でき、未指定の場合は `meta.defaults` にフォールバックします。

## ステート操作 (`map`)

- `set` – 指定キーを上書き。
- `merge` – 辞書やリストをマージ。
- `delete` – キーを削除。

テンプレート内では `state`, `inputs`, `result`, `output` などのコンテキストにアクセスできます。
