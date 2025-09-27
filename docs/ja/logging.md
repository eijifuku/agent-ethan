# トレーシングとロギング

Agent Ethan には、ラン・ノード・ツール・LLM の各レイヤーを JSON で記録するオプションのトレーシング機能が用意されています。既定では無効になっており、環境変数で明示的に有効化します。

## クイックスタート

```bash
export AE_TRACE_ENABLED=true
export AE_TRACE_SINKS=stdout,jsonl
python -m agent_ethan.examples.simple_agent
```

トレーシングを有効にすると、次のようなイベントが自動的に出力されます。

```json
{"ts":"2025-09-27T13:35:20.481Z","event":"run_start","run_id":"f6a0...","graph":"support_flow","level":"info"}
```

## 設定リファレンス

- `AE_TRACE_ENABLED` – トレーシング全体の ON/OFF（既定は `false`）。
- `AE_TRACE_SINKS` – カンマ区切りでシンクを指定（`stdout` / `jsonl` / `langsmith` / `null`）。
- `AE_TRACE_SAMPLE` – サンプリング率 `0.0`〜`1.0`（既定 `1.0`）。
- `AE_TRACE_LEVEL` – 記録する最小レベル（`debug` / `info` / `warn` / `error`。既定は `info`）。
- `AE_TRACE_DIR` – JSONL を保存するルートディレクトリ（既定 `./logs`）。
- `AE_TRACE_LANGSMITH_PROJECT` – LangSmith 用のプロジェクト名（任意）。
- `AE_TRACE_MAX_TEXT` – 長い文字列を切り詰める長さ（既定 `2048`）。
- `AE_TRACE_DENY_KEYS` – 追加でマスクしたいキー名をカンマ区切りで指定。

`AE_TRACE_SINKS` が空、または `null` の場合は `NullSink` が選択され、サンプリングで除外されたランなどは完全に破棄されます。

### シンク一覧

- **Stdout** – 1 行 1 イベントの JSON を標準出力に書き込みます。
- **Jsonl** – `AE_TRACE_DIR/<date>/<run_id>.jsonl` にラン単位の JSONL を出力します。
- **LangSmith** – LangSmith にイベントを転送します。`langsmith` パッケージが存在しない場合は警告のみ表示し、自動で無効化されます。
- **Null** – すべてのイベントを破棄します（サンプリングや検証用途に便利）。

複数指定が可能です（例: `AE_TRACE_SINKS=stdout,langsmith`）。

### サンプリングとレベル

各ラン開始時に `AE_TRACE_SAMPLE` の確率で採択され、採択されなかった場合は `NullSink` がインストールされます。そのため、デコレータのオーバーヘッドは最小限です。レベルはイベント生成後に適用されます。`AE_TRACE_LEVEL=debug` にするとルーター分岐やループ完了イベントも記録されます。

### マスキングとサマリ

デフォルトで `api_key` や `token` などのキーは `[REDACTED]` に置き換えられ、`Bearer ...` のような値は正規表現でマスクされます。`AE_TRACE_DENY_KEYS=client_secret,my_secret` のように追加キーを指定できます。長い文字列は `AE_TRACE_MAX_TEXT` 文字で切り詰められ、サマリにはキー一覧や先頭プレビューのみが含まれます。

### イベント種別

ランタイムの主要な入口／出口にデコレータが適用されています。

- **Run** – `run_start` / `run_end` / `run_exception` と入力・出力サマリ。
- **Node** – `node_start` / `node_end` / `node_exception` としてノード ID・種別・状態差分を記録。
- **Tool** – `tool_start` / `tool_end` / `tool_exception` でツール ID・種別・入出力サマリを記録。
- **LLM** – `llm_start` / `llm_end` / `llm_exception` にプロバイダ名・モデル名を付与。
- **Router / Loop** – `router_decision` と `loop_complete` で分岐結果とループ回数を追跡。

全イベントには `ts` / `run_id` / `span_id` / `trace_id` が含まれ、スパンはツール・LLM 呼び出し単位でネストします。

## カスタム利用

`agent_ethan.logging` モジュールは `configure_from_env()` と `set_log_manager()` を公開しており、テストなどで任意のシンクを差し込めます。

```python
from agent_ethan.logging import LogManager, set_log_manager
from agent_ethan.logging.sinks import Sink

class ListSink(Sink):
    def __init__(self):
        self.events = []
    def emit(self, event):
        self.events.append(event)

sink = ListSink()
set_log_manager(LogManager(sinks=[sink], sample_rate=1.0))
```

既存のデコレータはそのままで、アクティブな `LogManager` を自動的に参照します。無効化時には即座に抜けるため、通常運用への影響は最小です。

## トラブルシューティング

- **有効化したのに出力がない** – `AE_TRACE_SINKS` が空になっていないか確認し、`AE_TRACE_DIR` への書き込み権限をチェックしてください。
- **LangSmith へイベントが届かない** – `pip install langsmith` と API キーなど必要な環境変数が設定されているか確認してください。
- **秘匿情報が残ってしまう** – `AE_TRACE_DENY_KEYS` で追加マスクするか、ツール／LLM 側で事前に値を伏せて返却してください。

トレーシングは完全に任意機能であり、`AE_TRACE_ENABLED` を設定しない限り従来どおりの挙動になります。
