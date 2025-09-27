# 設定リファレンス

Agent Ethan の YAML は一定の骨組みを持ちます。このドキュメントでは各セクションの役割を詳しく説明し、すぐに利用できるサンプルを豊富に掲載します。

```
meta:
  schema_version: 1
  name: research_agent
  defaults:
    llm: local:google/gemma-3-12b
    temp: 0.2
    retry:
      max_attempts: 2
      backoff: 1.0
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b

state:
  shape:
    request: str
    answer: str | null
    history: list[str]
  reducer: deepmerge
  init:
    history: []

prompts:
  partials:
    system/base: |
      You are a concise assistant.
  templates:
    respond:
      system: "{{> system/base }}"
      user: |
        {{ request }}

tools:
  - id: http_fetch
    kind: http
    impl: "tools/http_call.py#call"

graph:
  inputs: [request]
  outputs: [answer]
  nodes:
    - id: keyword
      type: tool
      uses: http_fetch
      inputs:
        url: "https://example.com/search"
        params:
          q: "{{ inputs.request }}"
      map:
        set:
          history: "{{ result['items'] }}"

    - id: answer
      type: llm
      prompt: respond
      map:
        set:
          answer: "{{ result.text }}"

  edges:
    - from: keyword
      to: answer
```

以下、各セクションを順番に掘り下げます。

---

## 1. `meta`

| フィールド | 役割 | 例 |
| ---------- | ---- | --- |
| `schema_version` | 設定フォーマットのバージョン。現在は `1`。 | `schema_version: 1` |
| `name` | エージェントの識別名。 | `name: support_agent` |
| `defaults.llm` | 既定のプロバイダとモデル。`<provider_id>:<model>` の形式。 | `defaults.llm: openai:gpt-4o-mini` |
| `defaults.temp` | LLM ノードの既定温度。 | `temp: 0.2` |
| `defaults.retry` | リトライ回数とバックオフ秒数。 | `retry:
  max_attempts: 3
  backoff: 1.5` |
| `defaults.timeout` | 既定タイムアウト (秒)。任意。 | `timeout:
  seconds: 60` |
| `providers` | プロバイダごとの設定。 | 下記参照 |

### プロバイダ例: OpenAI

```yaml
meta:
  defaults:
    llm: openai:gpt-4o-mini
  providers:
    openai:
      type: openai
      temperature: 0.3
      client_kwargs:
        api_key: "{{env.OPENAI_API_KEY}}"
      kwargs:
        max_tokens: 512
```

### プロバイダ例: OpenAI互換 (LM Studio など)

```yaml
meta:
  defaults:
    llm: local:google/gemma-3-12b
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b
      request_timeout: 120
      kwargs:
        max_tokens: 1024
```

> **環境変数プレースホルダ** – `"{{env.VAR}}"` で環境変数を参照できます。未設定の場合は `AgentRuntimeError` として即座に通知されます。

---

## 2. `state`

```yaml
state:
  shape:
    request: str
    context: list[str]
    answer: str | null
    attempts: int
  reducer: deepmerge
  init:
    context: []
    attempts: 0
```

- `shape` は管理するキーと型を宣言します。
- `reducer`
  - `deepmerge` (既定) は辞書やリストをマージ。
  - `replace` は新しい値で置き換え。
- `init` は実行開始前の初期値。`shape` に無いキーは指定できません。

---

## 3. `memory`

```yaml
memory:
  enabled: true
  type: langchain_history
  kind: redis
  session_key: session_id
  namespace: agent-ethan
  dsn: "redis://localhost:6379/0"
  k: 20
```

- `enabled` – `true` で会話履歴同期を有効化。`false` の場合はセクションごと無視されます。
- `type` – 現状サポートされるのは `langchain_history` のみです。LangChain の `BaseChatMessageHistory` 実装を利用します。
- `kind` – バックエンド種別。`inmemory`, `file`, `redis`, `sqlite`, `postgres`, `custom` を指定できます。
- `session_key` – 会話セッションを識別するキー。まず `inputs` から探し、無ければ `state` を参照します。既定は `session_id`。
- `namespace` – 任意。共有ストレージで衝突を避けるためのプレフィックス。
- `dsn` – `redis` / `sqlite` / `postgres` 用の接続文字列。
- `path` – `file` バックエンドで利用するパス。YAML ファイルからの相対指定も可能です。
- `table` – SQL 系バックエンドで利用するテーブル名 (省略可)。
- `k` – 直近の履歴数。`state.messages_window` にも同じ数だけ公開されます。
- `config` – バックエンド固有の追加設定。`kind: custom` を使う場合は `config.impl` にヒストリー生成関数 (もしくはクラス) を指定してください。

> **State 要件** – `memory` を有効化する際は `state.shape` / `state.init` に `messages` (list) を追加してください。ランタイムはグラフ実行前に履歴を読み込み、実行後に追記されたメッセージをバックエンドへ書き戻します。

## 4. `prompts`

```yaml
prompts:
  partials:
    system/base: |
      You are a helpful assistant.
    user/header: |
      Provide clear, concise answers.
  templates:
    qa:
      system: "{{> system/base }}"
      user: |
        {{> user/header }}
        Question: {{ request }}
        Context:
        {%- for item in context %}
        - {{ item }}
        {%- endfor %}
    qa_with_assistant:
      system: "{{> system/base }}"
      assistant: "前回の回答: {{ last_answer }}"
      user: |
        追質問: {{ request }}
```

- パーシャルは `{{> name }}` で挿入できます。
- テンプレートは `system` / `user` / `assistant` または `messages` 配列を持てます。
- `{{ ... }}` の式には `state`, `inputs`, `result`, `output` などのコンテキストが渡されます。

---

## 5. `tools`

```yaml
tools:
  - id: http_fetch
    kind: http
    impl: "tools/http_call.py#call"
    config:
      timeout: 30

  - id: keyword_local
    kind: python
    impl: "../agent_ethan/tools/arxiv_keywords.py#fallback_keywords"
    retry:
      max_attempts: 3
      backoff: 2

  - id: keyword_remote
    kind: mcp
    impl: "mcp://keyword-service"
```

| フィールド | 説明 |
| ---------- | ---- |
| `id` | ノードから参照する識別子。 |
| `kind` | `python` / `http` / `mcp` / `subgraph` / `langchain`。 |
| `mode` | 省略可。`class` を指定すると関数ではなくクラスをインスタンス化して利用します。 |
| `impl` | モジュールパス＋属性名 (`path/to/module.py#function_or_class`)。MCP の場合は URI。 |
| `config` | 任意の設定値。ツール呼び出し時に渡されます。 |
| `retry` / `timeout` | ツール単位の上書き設定。 |

> YAML が `examples/` にある場合、`../agent_ethan/tools/...` のように指定してください (互換のため `../agent_ethan/tools/...` も解決されます)。

> **LangChain RAG** – `kind: langchain` で `tools/langchain_rag.py#ChromaRetrievalQATool` を指定すると、OpenAI 埋め込み + Chroma を使った RAG を YAML からそのまま呼び出せます (`examples/langchain_rag_agent.yaml` を参照)。

`mode: class` を指定すると `impl` で指したクラスを `config.init` (任意) で初期化し、そのインスタンスをツールとして呼び出します。`kind: langchain` の場合は LangChain の `BaseTool` を継承したクラスが必要で、`config.input_key` を設定すると、描画された入力のうち特定のキーだけを `invoke` に渡せます。未指定時はペイロード全体を辞書として渡します。

---

## 6. `graph`

### 6.1 入出力

```yaml
graph:
  inputs: [request]
  outputs: [answer, downloads]
  max_steps: 400
  timeout:
    seconds: 180
```

- `inputs` は `run()` 呼び出し時に必須。
- `outputs` は完了時に存在していなければエラー。
- `max_steps` はグラフ全体のステップ上限 (既定 200)。超えると `AgentRuntimeError` が発生します。
- `timeout` はグラフ全体のタイムアウトを設定します (`seconds` などを指定)。

### 6.2 ノードタイプ別サンプル

#### ツールノード

```yaml
- id: search
  type: tool
  uses: http_fetch
  inputs:
    method: GET
    url: "https://api.example.com/search"
    params:
      q: "{{ state.keywords }}"
  map:
    set:
      search_results: "{{ result['items'] or [] }}"
    merge:
      history:
        results: "{{ result['items'] or [] }}"
```

`map` は `set` / `merge` / `delete` を同時に利用できます。

```yaml
map:
  set:
    answer.text: "{{ result.text }}"
    answer.tokens: "{{ result.json.usage.total_tokens }}"
  merge:
    history:
      entries: ["{{ result.text }}"]
  delete:
    - draft_answer
```

#### LLM ノード

```yaml
- id: draft
  type: llm
  prompt: qa
  retry:
    max_attempts: 3
    backoff: 1
  timeout:
    seconds: 45
  map:
    set:
      draft_answer: "{{ result.text }}"
```

#### ルーターノード

```yaml
- id: branch
  type: router
  cases:
    - when:
        ">": ["{{ state.score }}", 0.8]
      to: approve
    - when:
        "<": ["{{ state.score }}", 0.5]
      to: reject
  default: refine
```

#### ループノード

```yaml
- id: retry_loop
  type: loop
  body: draft
  until:
    ">": ["{{ state.score }}", 0.7]
  max_iterations: 3
```

#### サブグラフノード

```yaml
- id: summarize
  type: subgraph
  graph: summary_subgraph
  inputs:
    text: "{{ state.draft_answer }}"
```

#### Noop ノード

```yaml
- id: stash
  type: noop
  map:
    set:
      history: "{{ history + [state.answer] }}"
```

### 6.3 エッジ

```yaml
edges:
  - from: keyword
    to: filter
    when:
      "!!": "{{ state.search_results }}"
  - from: filter
    to: fallback
    when:
      "==": ["{{ state.relevant_ids | length }}", 0]
```

### 6.4 `on_error`

```yaml
- id: filter
  type: llm
  prompt: filter_results
  on_error:
    to: heuristic_filter

- id: summary
  type: llm
  prompt: summarize
  on_error:
    resume: true
```

- `to` を指定するとフォールバックノードへジャンプします。
- `resume: true` の場合はエラー後も既定のエッジに沿って処理を続行します。

---

## 7. サブグラフ

再利用したい処理を `subgraphs:` にまとめます。

```yaml
subgraphs:
  summarize:
    inputs: [text]
    outputs: [summary]
    nodes:
      - id: respond
        type: llm
        prompt: respond
        map:
          set:
            summary: "{{ result.text }}"
    edges: []
```

サブグラフノードから呼び出すときは `graph` と `inputs` を指定します。

---

## 8. 応用パターン

- **環境変数をプロンプトに埋め込む**: `"{{env.LANG_PREFIX}} {{ request }}"` など。
- **ステートのデバッグ**: ツールの結果を `debug.*` のようなキーに保存して解析。
- **テスト時のツール差し替え**: `runtime.run(..., tool_overrides={"arxiv_search": fake_search})`。
- **フォールバックチェーン**: `on_error: resume` とヒューリスティックツールを組み合わせて堅牢なパイプラインを構築。

---

## 9. 完成例: arXiv 研究エージェント

`examples/arxiv_agent.yaml` と同等のフル構成です。

```yaml
meta:
  schema_version: 1
  name: lightgbm_researcher
  defaults:
    llm: local:google/gemma-3-12b
    retry:
      max_attempts: 2
      backoff: 1
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b

state:
  shape:
    request: str
    keywords: str | null
    keywords_llm: str | null
    search_results: list[dict]
    relevance_raw: str | null
    relevant_ids: list[str]
    downloads: list[dict]
    summary: str | null
  reducer: deepmerge
  init:
    relevant_ids: []
    downloads: []
    keywords: ""
    keywords_llm: ""
    relevance_raw: ""

prompts:
  partials:
    sys/filter: |
      Return valid JSON with keys "relevant_ids" and "reason".
  templates:
    keyword:
      system: "Generate concise keywords for arXiv search."
      user: "{{ request }}"
    filter:
      system: "{{> sys/filter }}"
      user: |
        Request: {{ request }}
        Candidates:
        {%- for item in search_results %}
        - id: {{ item.id }} | title: {{ item.title }}
        {%- endfor %}
    summary:
      system: "Provide a factual report of downloaded papers."
      user: |
        Papers:
        {%- for paper in downloads %}
        - {{ paper.id }}: {{ paper.title }} ({{ paper.path }})
        {%- endfor %}

tools:
  - id: keyword_fallback
    kind: python
    impl: "../agent_ethan/tools/arxiv_keywords.py#fallback_keywords"
  - id: arxiv_search
    kind: python
    impl: "../agent_ethan/tools/arxiv_local.py#search"
  - id: arxiv_select
    kind: python
    impl: "../agent_ethan/tools/arxiv_filter.py#parse_selection"
  - id: arxiv_download
    kind: python
    impl: "../agent_ethan/tools/arxiv_local.py#download"
  - id: summary_fallback
    kind: python
    impl: "../agent_ethan/tools/arxiv_summary.py#fallback_summary"

graph:
  inputs: [request]
  outputs: [keywords, downloads, summary]
  nodes:
    - id: keyword_llm
      type: llm
      prompt: keyword
      on_error:
        resume: true
      map:
        set:
          keywords_llm: "{{ result.text.strip() }}"

    - id: keyword_ensure
      type: tool
      uses: keyword_fallback
      inputs:
        request: "{{ state.request }}"
        llm_keywords: "{{ state.keywords_llm }}"
      map:
        set:
          keywords: "{{ result.json['keywords'] }}"

    - id: search
      type: tool
      uses: arxiv_search
      inputs:
        query: "{{ state.keywords }}"
      map:
        set:
          search_results: "{{ result.json['items'] }}"

    - id: filter
      type: llm
      prompt: filter
      on_error:
        resume: true
      map:
        set:
          relevance_raw: "{{ result.text }}"

    - id: parse
      type: tool
      uses: arxiv_select
      inputs:
        raw_text: "{{ state.relevance_raw | default('') }}"
        search_results: "{{ state.search_results }}"
        keywords: "{{ state.keywords }}"
        max_results: 5
      map:
        set:
          relevant_ids: "{{ result.json['relevant_ids'] }}"
          rationale: "{{ result.json['reason'] }}"

    - id: download
      type: tool
      uses: arxiv_download
      inputs:
        paper_ids: "{{ state.relevant_ids }}"
        search_results: "{{ state.search_results }}"
      map:
        set:
          downloads: "{{ result.json['downloads'] }}"

    - id: summary_llm
      type: llm
      prompt: summary
      on_error:
        resume: true
      map:
        set:
          summary: "{{ result.text.strip() }}"

    - id: summary_ensure
      type: tool
      uses: summary_fallback
      inputs:
        downloads: "{{ state.downloads }}"
        llm_summary: "{{ state.summary }}"
      map:
        set:
          summary: "{{ result.json['summary'] }}"

  edges:
    - from: keyword_llm
      to: keyword_ensure
    - from: keyword_ensure
      to: search
    - from: search
      to: filter
    - from: filter
      to: parse
    - from: parse
      to: download
    - from: download
      to: summary_llm
    - from: summary_llm
      to: summary_ensure
```

この例では LLM の失敗時にもツールによるフォールバックで処理を継続できる構成になっています。自分のユースケースに合わせてセクションを差し替えながら利用してください。
