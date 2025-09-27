# サンプル集

## RAG ワークフロー (`examples/rag_agent.yaml`)

ローカルコーパスを検索して回答を生成する最小例です。

```bash
python examples/example.py
```

`tools/local_rag.py#search` が疑似検索結果を返し、LLM ノードがプロンプトにコンテキストを埋め込みます。

## 会話履歴デモ (`examples/memory_agent.yaml`)

LangChain のチャット履歴をアダプタ経由で再利用するサンプルです。

### 特徴

- `memory` セクションで `state.messages` を LangChain の履歴バックエンドに同期します。
- ユーザ発話ノードと簡易返信ノードのみで構成され、仕組みの確認に最適です。
- 既定では `examples/data/history-<session>.jsonl` に保存されます。`kind` を切り替えるだけで Redis や SQLite なども利用できます。

### 実行

```bash
python examples/memory_example.py
```

同じ `session_id` で 2 回実行すると履歴が復元され、異なるセッションではクリーンな状態から開始されることを確認できます。

## LangChain RAG (`examples/langchain_rag_agent.yaml`)

LangChain の Chroma ベクターストアと OpenAI 埋め込みをツール経由で呼び出し、ローカルファイルから回答を生成します。

### 特徴

- `tools/langchain_rag.py#ChromaRetrievalQATool` が `examples/corpus` の Markdown を読み込み、OpenAI 埋め込みで Chroma ストアを構築します。
- ツールの返すドラフト回答とスニペットを LLM ノードで再構成し、最終回答を生成します。
- 実行には `OPENAI_API_KEY` と `pip install langchain-openai chromadb` が必要です。

### 実行

```bash
pip install langchain-openai chromadb
export OPENAI_API_KEY=sk-your-key
python examples/langchain_rag_example.py
```

Markdown ファイルの内容に基づいた回答と参照元ファイルのパスが出力されます。

## LangChain VectorStore Override (`examples/langchain_rag_vectorstore_agent.yaml`)

`tools/langchain_rag.py` を使わず、LangChain 標準の `VectorStoreQATool` を `tool_overrides` で差し込むサンプルです。

### 特徴

- YAML 側では `tools/langchain_stub.py#requires_override` を指定し、実行時に必ず上書きすることを促します。
- `examples/langchain_rag_vectorstore_example.py` がコーパスの読み込み・Chroma 構築・`VectorStoreQATool` の生成・`tool_overrides` での注入までを Python 側で行います。
- 既存の LangChain 連携コードをそのまま活かしつつ、Agent Ethan のグラフ制御だけ利用したい場合に有効です。

### 実行

```bash
pip install langchain-openai chromadb
export OPENAI_API_KEY=sk-your-key
python examples/langchain_rag_vectorstore_example.py
```

`VectorStoreQATool` が返す回答と、ベクターストアから取得した類似ドキュメントのスニペットが表示されます。

## arXiv 研究支援エージェント (`examples/arxiv_agent.yaml`)

自然文のリクエストからキーワードを抽出し、arXiv で論文を検索して PDF をダウンロードします。

### 処理段階

1. **キーワード生成** – LLM 出力を利用し、失敗時はヒューリスティックなキーワードにフォールバック。
2. **arXiv 検索** – `tools/arxiv_local.py#search` が複数パターンのクエリを試行し、重複排除した結果を返します。
3. **絞り込み** – LLM がユーザの入力と関連性の高い論文のみを抽出し、その出力を `tools/arxiv_filter.py#parse_selection` が解析します。JSON でない場合もキーワード一致で候補を選べます。
4. **ダウンロード** – PDF を取得し、検索結果のメタデータ (タイトル・著者・カテゴリなど) を付与して保存。
5. **要約** – LLM が応答を生成し、失敗時は `tools/arxiv_summary.py#fallback_summary` が事実ベースの一覧を出力します。

### 実行コマンド

```bash
export OPENAI_COMPATIBLE_BASE_URL=http://host.docker.internal:1234/v1
python examples/arxiv_example.py "lightgbm 時系列 特徴量エンジニアリング"
```

`downloads/` ディレクトリに PDF が保存され、標準出力には取得済み論文と保存パスが表示されます。

## 応用アイデア

- ルーターノードで状態に応じた分岐を追加し、マルチターン対話へ拡張する。
- サブグラフを使って共通プロンプト処理をモジュール化する。
- `tools/http_call.py` と独自の Python ツールを組み合わせてハイブリッドな検索体験を構築する。

詳細な YAML 設計は [設定リファレンス](configuration.md) を参照してください。
