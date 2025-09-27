# セットアップ手順

## 必要条件

- Python 3.10 以上
- LLMのAPI接続(OenAI/Gemini/Claude/OpenAI互換API)
- LangChain(langchain_core/langchain_community)のインストール（チャット履歴の保持やLangChain同梱のツールを使用する場合）
- その他、使用するツールによってはライブラリの追加インストールが必要となる場合があります。

## 環境変数

| 変数名 | 用途 |
| ------ | ---- |
| `OPENAI_COMPATIBLE_BASE_URL` | OpenAI 互換 API (LM Studio や vLLM など) のベース URL |
| `OPENAI_API_KEY` | OpenAI 互換 API を利用する際のキー |
| `GEMINI_API_KEY` | Google Gemini の API キー |
| `ANTHROPIC_API_KEY` | Anthropic Claude の API キー |

`.env` ファイルで管理する場合:

```bash
cat <<'ENV' > .env
OPENAI_COMPATIBLE_BASE_URL=http://127.0.0.1:1234/v1
OPENAI_API_KEY=your-openai-api-key
GEMINI_API_KEY=your-gemini-key
ANTHROPIC_API_KEY=your-claude-key
ENV
```

## サンプルの実行

1. **RAG ワークフロー**
   ```bash
   python examples/example.py
   ```
   ローカル検索結果を使って応答を生成します。

2. **arXiv ワークフロー**
   ```bash
   export OPENAI_COMPATIBLE_BASE_URL=http://host.docker.internal:1234/v1
   python examples/arxiv_example.py "lightgbm 時系列 特徴量エンジニアリング"
   ```
   自然文リクエストからキーワードを作成し、arXiv で検索した論文をダウンロードして要約します。

## Docker 環境

`Dockerfile` と `docker-compose.yml` を用意しています。

```bash
docker compose run --rm agent
```

コンテナ内でリポジトリをマウントし、`pip install -e .` を実行してユニットテストを起動します。OpenAI 互換エンドポイント (例: LM Studio) に接続する場合は `OPENAI_COMPATIBLE_BASE_URL` を適宜上書きしてください。

## テスト

```bash
python -m unittest
```

`tests/` ディレクトリに網羅的なテストが含まれています。新しい機能を追加した際は必ずテストを更新してください。
