# ツールと拡張

ツールは YAML の `tools:` セクションで宣言し、グラフ上の `tool` ノードから呼び出します。HTTP や MCP、LangChain ツール、Python 関数、サブグラフなどを統一的な形式で扱えます。

## 1. YAML でツールを宣言する

```yaml
tools:
  - id: http_fetch
    kind: http
    impl: "tools/http_call.py#call"
    config:
      method: GET
      timeout: 15

  - id: keyword_fallback
    kind: python
    impl: "../agent_ethan/tools/arxiv_keywords.py#fallback_keywords"
    retry:
      max_attempts: 3
      backoff: 2

  - id: github_repo
    kind: mcp
    impl: "mcp://github"
    config:
      repository: "owner/repo"
      token: "{{env.GITHUB_TOKEN}}"

  - id: summarize_subgraph
    kind: subgraph
    impl: "summarize"
```

| kind | 説明 |
| ---- | ---- |
| `http` | 内蔵の HTTP アダプタを利用。`inputs` に HTTP メソッドや URL を渡します。 |
| `python` | `<モジュール>#<関数>` を読み込んで実行します。パスは YAML からの相対パス。 |
| `mcp` | Model Context Protocol サーバへ接続します。`impl` に `mcp://github` のような URI を指定。 |
| `subgraph` | `subgraphs:` に定義したグラフをツールとして公開します。 |
| `langchain` | LangChain の `BaseTool` クラスを (`mode: class`) でインスタンス化し、標準レスポンスへ変換します。 |

## 2. グラフからツールを呼び出す

```yaml
- id: repo_issues
  type: tool
  uses: github_repo
  inputs:
    action: "list_issues"
    filters:
      labels: ["bug"]
  map:
    set:
      open_issues: "{{ result.json['items'] }}"
```

- `uses` は `tools:` に宣言した ID を参照します。
- `inputs` は Jinja でレンダリングされた辞書がそのままツールに渡されます。
- `result` はツールの標準レスポンス (`status`, `json`, `text`, `items`, `result`, `error`) です。

## 3. MCP 例: GitHub MCP サーバ

GitHub MCP サーバを利用する場合の例:

```yaml
meta:
  providers: {}

tools:
  - id: github
    kind: mcp
    impl: "mcp://github"
    config:
      repository: "openai/openai-cookbook"
      token: "{{env.GITHUB_TOKEN}}"

  - id: list_prs
    kind: tool
    uses: github
    inputs:
      action: "pulls.list"
      params:
        state: "open"
    map:
      set:
        pull_requests: "{{ result.json['items'] }}"
```

MCP サーバ側が標準的なレスポンス形式 (`status` / `result` / `error`) を返せば、LLM ノードや他のツールと同様に扱えます。

## 4. 同梱 Python ツール

| ツール | 説明 |
| ------ | ---- |
| `tools/local_rag.py#search` | RAG サンプルのローカル検索 |
| `tools/arxiv_local.py#search` | arXiv Atom API へ複数クエリでアクセス |
| `tools/arxiv_local.py#download` | PDF をリダイレクト追跡付きで保存し、メタデータを付与 |
| `tools/arxiv_filter.py#parse_selection` | LLM 出力の JSON を解析。失敗時はキーワード一致で選別 |
| `tools/arxiv_keywords.py#fallback_keywords` | LLM キーワードが無い場合にヒューリスティック生成 |
| `tools/arxiv_summary.py#fallback_summary` | 取得済み論文を事実ベースで列挙 |
| `tools/json_utils.py#parse_object` | 文字列 JSON を辞書に変換 |
| `agent_ethan/tools/mock_tools.py` | テスト用 (`echo`, `increment`, `failing`) |

### LangChain のツールを使う（任意）

薄いアダプタ経由で LangChain が提供する豊富なツール群を利用できます（本体には同梱しません）。`langchain` / `langchain-community`（およびツール固有の依存）を各自インストールし、ツール定義でアダプタを参照してインポートパスと入力を渡してください。

## 5. カスタム Python ツールの規約

ツールは次のキーを含む辞書を返す必要があります。

```python
from typing import Any, Dict

ToolOutput = Dict[str, Any]

def my_tool(*, text: str) -> ToolOutput:
    processed = text.upper()
    return {
        "status": 200,
        "json": {"processed": processed},
        "text": processed,
        "items": None,
        "result": {"processed": processed},
        "error": None,
    }
```

| キー | 説明 |
| ---- | ---- |
| `status` | 数値ステータスコード (例: 200)。 |
| `json` | メインの返り値。任意の辞書や配列。 |
| `text` | 文字列形式の出力。任意。 |
| `items` | リスト形式で返したい場合に利用。 |
| `result` | 互換性のための別名 (通常は `json` と同じ)。 |
| `error` | `None` なら成功。失敗時はエラー情報を設定。 |

YAML 側での宣言:

```yaml
- id: my_tool
  kind: python
  impl: "custom/my_module.py#my_tool"
```

### エラーの通知

```python
return {
    "status": 500,
    "json": None,
    "text": None,
    "items": None,
    "result": None,
    "error": {"message": "timeout", "type": "upstream_error"},
}
```

`error` が真になると `on_error` に従って処理が遷移します。

## 6. LangChain クラスツール

LangChain のツールクラスを直接指定する場合は、`mode: class` を設定し、クラスを継承した `BaseTool` を指します。必要なオプション依存を別途インストールしてください。OpenAI 埋め込み + Chroma を使った RAG 例では以下を追加します。

```
pip install langchain-openai chromadb
```

```yaml
tools:
  - id: serp_search
    kind: langchain
    mode: class
    impl: "my_project.langchain_tools#SerpAPITool"
    config:
      init:
        serpapi_api_key: "{{env.SERPAPI_API_KEY}}"
      input_key: "query"

- id: research
  type: tool
  uses: serp_search
  inputs:
    query: "{{ inputs.topic }}"
  map:
    set:
      search_results: "{{ result['items'] or [] }}"
```

- `config.init` (任意) でクラスのコンストラクタに渡すキーワード引数を指定します。
- `config.input_key` (任意) を設定すると、レンダリングされた入力のうち該当キーのみを `invoke` に渡します。未指定のときは辞書全体を渡します。
- 戻り値はランタイム側で標準のツールレスポンス形式 (`status`, `json`, `text`, `items`, `result`, `error`) に整形されます。
- 追加依存なしで実行できる最小例は `examples/langchain_list_dir_agent.yaml` を参照してください (`ListDirectoryTool` を利用)。
- LangChain の Chroma + OpenAI 埋め込みを利用した RAG 構成は `examples/langchain_rag_agent.yaml` と `tools/langchain_rag.py#ChromaRetrievalQATool` を参照してください。

## 7. LangChain ツールで RAG を構築する

ランタイムを書き換えずに RAG を構成したい場合は、LangChain のベクターストアやチェーンをツールクラスで包みます。リポジトリ同梱の `ChromaRetrievalQATool` は、ローカルファイルを読み込み、OpenAI 埋め込みで Chroma ベクターストアを生成し、`RetrievalQA` で回答を生成します。

```yaml
tools:
  - id: knowledge_base
    kind: langchain
    mode: class
    impl: "../agent_ethan/tools/langchain_rag.py#ChromaRetrievalQATool"
    config:
      init:
        corpus_path: "./examples/corpus"
        glob: "*.md"
        collection_name: "agent-ethan-docs"
        persist_directory: "./examples/chroma_store"
        embedding_model: "text-embedding-3-small"
        llm_model: "gpt-4o-mini"
        top_k: 4

- id: retrieve
  type: tool
  uses: knowledge_base
  inputs:
    query: "{{ query }}"
  map:
    set:
      sources: "{{ result['items'] }}"
      preliminary_answer: "{{ result['json']['answer'] }}"
```

`examples/langchain_rag_agent.yaml` では上記ツールの結果を LLM ノードに渡して最終回答を整形しています。グラフ制御やエラーハンドリングは既存ランタイムのまま活用できます。

LangChain 側で独自にベクターストアやツールを管理している場合は、`tool_overrides` で YAML のプレースホルダーツールを上書きする方法もあります。`examples/langchain_rag_vectorstore_example.py` が `VectorStoreQATool` を構築し、`qa_tool` を実行時に差し替える具体例です。

## 8. 実行時オーバーライド

```python
runtime.run(
    inputs,
    tool_overrides={"github_repo": fake_github},
)
```

テストやスタブ化に便利です。

## 9. よくあるパターン

- **デコレータ**: ログ出力やメトリクス用のラッパーを噛ませて、最終的に標準形式の辞書を返します。
- **環境変数**: 認証情報は `config` と `{{env.VAR}}` で渡し、YAML にベタ書きしない。
- **サブグラフ連携**: `kind: subgraph` を活用して複数ステップの処理をツール化し、LLM からも使い回す。

以上を踏まえれば、HTTP API や MCP サーバ、LangChain ツール、自作の Python コードを一貫した形でエージェントに組み込めます。
