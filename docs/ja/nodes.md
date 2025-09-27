# ノード一覧

このドキュメントでは Agent Ethan の各ノードタイプについて、必須フィールド・挙動・利用例を詳しく解説します。サンプルをコピーして自身の YAML に組み込んでください。

## ツールノード (`type: tool`)

### 用途
- Python 関数や HTTP エンドポイント、MCP サービス、サブグラフを呼び出す。
- 構造化データを扱い、ステートを更新する。

### 必須フィールド
| フィールド | 説明 |
| ---------- | ---- |
| `id` | ノード識別子 |
| `type` | 常に `tool` |
| `uses` | `tools:` で宣言したツール ID |

### 任意フィールド
`name`, `description`, `retry`, `timeout`, `on_error`, `inputs`, `map`

### サンプル
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
        queries: ["{{ state.keywords }}"]
```

- `inputs` は Jinja でレンダリングされ、ツール関数にキーワード引数として渡されます。
- `result` は標準化されたツールレスポンス (`status`, `json`, `text`, `items`, `error`) を表します。

---

## LLM ノード (`type: llm`)

### 用途
- プロンプトテンプレートをレンダリングして LLM へリクエスト。
- 応答をステートへ反映。

### 必須フィールド
`id`, `type: llm`, `prompt`

### サンプル
```yaml
- id: draft
  type: llm
  prompt: respond
  retry:
    max_attempts: 3
    backoff: 1
  timeout:
    seconds: 45
  map:
    set:
      draft_answer: "{{ result.text }}"
```

---

## ルーターノード (`type: router`)

JsonLogic を使って分岐させます。複数ケースが同時に真になる場合は、該当するエッジが全てキューに追加されます。

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

---

## ループノード (`type: loop`)

同じノードを条件付きで繰り返します。

```yaml
- id: refine_loop
  type: loop
  body: draft
  until:
    ">": ["{{ state.score }}", 0.75]
  max_iterations: 4
```

- `until` が真になるか `max_iterations` に達すると停止。
- ループ内部でエラーが発生した場合は `on_error` の設定に従います。

---

## サブグラフノード (`type: subgraph`)

宣言済みのサブグラフを呼び出し、入力と出力をやり取りします。

```yaml
subgraphs:
  summarize:
    inputs: [text]
    outputs: [summary]
    nodes:
      - id: llm
        type: llm
        prompt: summarize
        map:
          set:
            summary: "{{ result.text }}"
    edges: []

- id: summary_step
  type: subgraph
  graph: summarize
  inputs:
    text: "{{ state.answer }}"
```

---

## Noop ノード (`type: noop`)

外部呼び出しを行わず、ステートだけを操作します。

```yaml
- id: cleanup
  type: noop
  map:
    delete:
      - draft_answer
    merge:
      audit:
        actions: ["cleanup"]
```

---

## `on_error` の扱い

全てのノードタイプで `on_error` を設定できます。

```yaml
on_error:
  to: fallback_node
```

- 失敗時に特定ノードへ遷移。

```yaml
on_error:
  resume: true
```

- 失敗後も既定のエッジに従って進行。

`NodeExecutionError` にはノード ID、種類、プロンプト／ツール、例外詳細が含まれるため、トラブルシューティングが容易です。

---

## `map` チートシート

| 指示 | 役割 | 例 |
| ---- | ---- | --- |
| `set` | 値を代入 | `set: {answer: "{{ result.text }}"}` |
| `merge` | 辞書やリストをマージ | `merge: {history: {entries: ["{{ result.text }}"]}}` |
| `delete` | キーを削除 | `delete: [temporary_token]` |

`state`, `inputs`, `result`, `output` にアクセス可能です。

---

この一覧と [設定リファレンス](configuration.md)、[ランタイム実行](runtime.md) を併用すれば、ノードの意味を理解しながら YAML を構築できます。
