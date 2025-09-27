# トレーシングとロギング

Agent Ethan には、ラン・ノード・ツール・LLM の各レイヤーを JSON で記録するオプションのトレーシング機能があります。設定は YAML の `meta.defaults.tracing` にまとめて記述し、ブロックを省略または `enabled: false` にすれば従来どおりトレースなしで動作します。

## クイックスタート

設定ファイルに次のようなブロックを追加します。

```yaml
meta:
  defaults:
    tracing:
      enabled: true
      sinks: ["stdout", "jsonl"]
```

有効化すると、以下のような JSON イベントが自動的に出力されます。

```json
{"ts":"2025-09-27T13:35:20.481Z","event":"run_start","run_id":"f6a0...","graph":"support_flow","level":"info"}
```

サンプルの YAML `examples/arxiv_agent.yaml` には `sinks: ["stdout"]` があらかじめ設定されているため、`examples/arxiv_example.py` を実行するとそのまま標準出力へイベントが流れます。

## 設定リファレンス

すべて `meta.defaults.tracing` 以下に配置します。

- `enabled` (`bool`, 既定 `false`) – トレーシング全体の ON/OFF。
- `sinks` (`list[str]`) – `stdout` / `jsonl` / `langsmith` / `null` の組み合わせ。
- `sample` (`float`, 既定 `1.0`) – 0.0〜1.0 のサンプリング率。
- `level` (`str`, 既定 `info`) – 記録する最小レベル（`debug` | `info` | `warn` | `error`）。
- `dir` (`str`, 既定 `./logs`) – JSONL を出力するルートディレクトリ。
- `langsmith_project` (`str | null`) – LangSmith 用のプロジェクト名（任意）。
- `max_text` (`int`, 既定 `2048`) – 文字列を切り詰める長さ。
- `deny_keys` (`list[str]`) – マスク対象のキー名。既定で `api_key`, `authorization`, `password`, `token`, `secret`, `cookie`, `session`, `client_secret`, `private_key` を含みます。

`sinks` が空、または `null` のみの場合は `NullSink` が選択され、すべてのイベントが破棄されます（サンプリングで除外されたラン向けに便利）。

### シンク一覧

- **Stdout** – 1 行 1 イベントの JSON を標準出力に書き込みます。
- **Jsonl** – `dir/<date>/<run_id>.jsonl` にラン単位の JSONL を保存します。
- **LangSmith** – LangSmith にイベントを転送します。`langsmith` のインストールと必要な環境変数が前提です。
- **Null** – すべてのイベントを破棄します。

複数指定が可能です（例: `sinks: ["stdout", "langsmith"]`）。

### サンプリングとレベル

各ラン開始時に `sample` の確率で採択され、採択されなかった場合はデコレータが `NullSink` にフォールバックします。`level: debug` を指定すると、ルーター分岐やループ完了イベントも記録されます。

### マスキングとサマリ

`deny_keys` に含まれるキーは `[REDACTED]` に置き換えられ、`Bearer ...` のような値は正規表現でマスクされます。長い文字列は `max_text` 文字で切り詰められ、サマリにはキー一覧と冒頭プレビューのみが残ります。

### イベント種別

- **Run** – `run_start` / `run_end` / `run_exception` と入出力サマリ。
- **Node** – `node_start` / `node_end` / `node_exception` とノード ID・種別・状態差分。
- **Tool** – `tool_start` / `tool_end` / `tool_exception` とツール ID・種別・入出力サマリ。
- **LLM** – `llm_start` / `llm_end` / `llm_exception` にプロバイダ名・モデル名を付与。
- **Router / Loop** – `router_decision` と `loop_complete` で分岐結果とループ回数を記録。

すべてのイベントに `ts` / `run_id` / `span_id` / `trace_id` が含まれるため実行フローを再構築できます。

## カスタム利用

コードから独自シンクを差し込みたい場合は、次のように `set_log_manager()` を利用できます。

```python
from agent_ethan.logging import LogManager, set_log_manager
from agent_ethan.logging.sinks import Sink

class ListSink(Sink):
    def __init__(self):
        self.events = []
    def emit(self, event):
        self.events.append(event)

manager = LogManager(sinks=[ListSink()], sample_rate=1.0)
set_log_manager(manager)
```

デコレータ（`@log_run`, `@log_node`, `@log_tool`, `@log_llm`）は常に現在の `LogManager` を参照するため、そのまま利用してください。

## トラブルシューティング

- **有効化したのに出力がない** – `sinks` が空になっていないか、`jsonl` を使う場合は `dir` への書き込み権限があるか確認してください。
- **LangSmith へイベントが届かない** – `langsmith` パッケージのインストールと `LANGSMITH_API_KEY` など必要な環境変数を設定してください。
- **秘匿情報が残ってしまう** – `deny_keys` に追加するか、ツール／LLM 側で値を加工してから返却してください。

トレーシングは完全に任意の機能であり、`enabled: false` または設定ブロックの削除で簡単に無効化できます。
