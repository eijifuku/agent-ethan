# Agent Ethan
Agent Ethan は LLM を中核に、ツール呼び出し・条件分岐・ループ・サブグラフを宣言的な YAML で編成する“エージェント実行フレームワーク”です。プロンプト生成から外部ツール実行、結果の状態反映までを一貫して自動化します。コードを書く代わりに YAML を記述するだけで LLM とツールを組み合わせられる「ほぼノーコード」の開発体験を目指しています。JsonLogic 条件分岐を含むグラフ実行、スキーマ検証、ツール／プロバイダアダプタ (LM Studio などの OpenAI 互換 API 対応) が同梱されています。

> ⚠️ 重要なお知らせ（ノーサポート／PR不可／問い合わせ不可）
>
> 本リポジトリは基本的に個人利用を目的としています。ライセンスの範囲で自由に利用できますが、作者は以下を提供しません。
> - いかなる保証・責任も負いません
> - サポートや問い合わせ対応は行いません
> - Pull Request／Issue の受け付けは行いません
>
> ご利用は自己責任でお願いします。

Agent Ethan は宣言的な YAML を実行可能なワークフローへ変換します。構成要素は次の通りです。

1. **メタ情報** – スキーマ版・エージェント名・既定の LLM プロバイダ／モデル・リトライ／タイムアウト・プロバイダ固有設定
2. **ステート** – グラフ全体で扱う型付きフィールドと初期化・マージ戦略（`deepmerge` / `replace`）
3. **プロンプト** – パーシャルとテンプレート（Jinja）を LLM ノードでレンダリング
4. **ツール** – Python コール／HTTP／MCP へマップする宣言的ハンドル。LangChain に含まれるツールも利用可能です（別途インストール）。
5. **RAG** - LangChainのRetrievalQAツール経由でRAGの利用が可能
6. **グラフ** – ノード（LLM／ツール／ルーター／ループ／サブグラフ／noop）とエッジで実行・分岐を表現
7. **サブグラフ** – 再利用可能な部分グラフ（任意）

YAML は `agent_ethan.schema` の Pydantic モデルで検証され、`agent_ethan.builder` がツール／プロバイダを解決して `AgentRuntime` を構築します。ランタイムはリトライ／タイムアウト／`on_error` を考慮しながら順次ノードを実行します。

各ノードの仕様は [docs/ja/nodes.md](docs/ja/nodes.md)、YAML 全体の解説は [docs/ja/configuration.md](docs/ja/configuration.md) を参照してください。

## インストール

```bash
# GitHub からインストール（推奨）
pip install git+https://github.com/eijifuku/agent-ethan.git

# ローカルにクローンして開発モードでインストール
git clone https://github.com/eijifuku/agent-ethan.git
cd agent-ethan
pip install -e .
```

## クイックスタート

```python
from agent_ethan.builder import build_agent_from_path

runtime = build_agent_from_path("examples/rag_agent.yaml")
state = runtime.run({"query": "こんにちは"})
print(state["answer"])
```

もう少し複雑なエンドツーエンドのサンプルは [docs/ja/examples.md](docs/ja/examples.md) を参照してください。

上記コードが実行する最小の YAML 定義例:

```yaml
meta:
  schema_version: 1
  name: demo
  defaults:
    llm: local:google/gemma-3-12b
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b

state:
  shape:
    query: str
    context: list[dict]
    answer: str | null
  reducer: deepmerge
  init:
    context: []

prompts:
  partials:
    sys: |
      あなたは簡潔に日本語で答えるアシスタントです。
  templates:
    answer:
      system: "{{> sys }}"
      user: |
        質問: {{ query }}
        コンテキスト: {{ context }}

tools:
  - id: local_search
    kind: python
    impl: "tools/local_rag.py#search"

graph:
  inputs: [query]
  outputs: [answer]
  nodes:
    - id: search
      type: tool
      uses: local_search
      inputs:
        query: "{{ query }}"
      map:
        set:
          context: "{{ result['items'] }}"

    - id: generate
      type: llm
      prompt: answer
      map:
        set:
          answer: "{{ output.text }}"

  edges:
    - from: search
      to: generate
```

- **会話履歴の有効化** – LangChain の履歴アダプタを使ってマルチターン対応にできます:

```yaml
memory:
  enabled: true
  type: langchain_history
  kind: file
  path: "./data/history-{session_id}.jsonl"
  session_key: session_id
  k: 20

state:
  shape:
    messages: list[dict]
    session_id: str | null
  init:
    messages: []
    session_id: null
```

詳細は `examples/memory_agent.yaml` および `docs/ja/configuration.md` を参照してください (Redis や SQLite、独自実装のアダプタも利用可能です)。

- 例を実行する前に `OPENAI_COMPATIBLE_BASE_URL` などのプロバイダ用環境変数をセットしてください。
- `python examples/arxiv_example.py "lightgbm 時系列 特徴量エンジニアリング"` を実行すると、関連論文の PDF をダウンロードし、取得結果のサマリーを生成します。
- OpenAI を利用する場合は `OPENAI_API_KEY` を設定し、`meta.defaults.llm: openai:gpt-4o-mini` と `providers.openai` セクションを YAML に追加してください (詳細は `docs/ja/providers.md` を参照)。
- `python examples/langchain_rag_example.py` で LangChain + Chroma + OpenAI 埋め込みによる RAG 構成を体験できます (事前に `pip install langchain-openai chromadb` と `OPENAI_API_KEY` の設定が必要)。
- `python examples/langchain_rag_vectorstore_example.py` では、LangChain 標準の `VectorStoreQATool` を `tool_overrides` で差し込むパターンを確認できます。

## テスト

```bash
python -m unittest
```

## ドキュメント

詳細ガイドは [docs/en/index.md](docs/en/index.md)（英語）と [docs/ja/index.md](docs/ja/index.md)（日本語）を参照してください。

## ライセンス

詳細は [LICENSE](LICENSE) を確認してください。
