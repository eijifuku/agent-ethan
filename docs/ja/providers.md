# プロバイダ設定

エージェントは YAML の `providers` セクション、または `AgentRuntime.run` に直接渡した `LLMClient` で LLM を解決します。

## ビルトインファクトリ

### OpenAI 互換

```python
from agent_ethan.providers import create_openai_client

client = create_openai_client(
    model="gpt-4o-mini",
    temperature=0.1,
    client_kwargs={"api_key": os.environ["OPENAI_API_KEY"]},
)
```

```yaml
meta:
  defaults:
    llm: openai:gpt-4o-mini
  providers:
    openai:
      type: openai
      temperature: 0.1
      client_kwargs:
        api_key: "{{env.OPENAI_API_KEY}}"
```

### OpenAI互換 (LM Studio や vLLM など)

```python
from agent_ethan.providers import create_openai_compatible_client

client = create_openai_compatible_client(
    model="google/gemma-3-12b",
    base_url=os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:1234/v1"),
    temperature=0.2,
)
```

```yaml
meta:
  defaults:
    llm: local:google/gemma-3-12b
  providers:
    local:
      type: openai_compatible  # 互換性のため "lmstudio" も指定できます
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b
      request_timeout: 120
```

### Google Gemini

```python
from agent_ethan.providers import create_gemini_client

client = create_gemini_client(
    model="gemini-1.5-flash",
    api_key=os.environ["GEMINI_API_KEY"],
    temperature=0.2,
    top_p=0.9,
)
```

```yaml
meta:
  defaults:
    llm: gemini:gemini-1.5-flash
  providers:
    gemini:
      type: gemini
      model: gemini-1.5-flash
      temperature: 0.2
      api_key: "{{env.GEMINI_API_KEY}}"
      top_p: 0.9
```

### Anthropic Claude

```python
from agent_ethan.providers import create_claude_client

client = create_claude_client(
    model="claude-3-sonnet-20240229",
    api_key=os.environ["ANTHROPIC_API_KEY"],
    temperature=0.3,
    max_tokens=1024,
)
```

```yaml
meta:
  defaults:
    llm: claude:claude-3-sonnet-20240229
  providers:
    claude:
      type: claude
      model: claude-3-sonnet-20240229
      api_key: "{{env.ANTHROPIC_API_KEY}}"
      temperature: 0.3
      max_tokens: 1024
```

## 環境変数の埋め込み

`"{{env.VAR_NAME}}"` 形式で環境変数を参照できます。未定義の場合は `AgentRuntimeError` として即座に通知されます。

## カスタムプロバイダ

独自の API を利用する場合は `LLMClient` を自作します。

```python
from agent_ethan.llm import LLMClient

def call(*, node, prompt, timeout=None):
    response = my_api.chat(prompt, timeout=timeout)
    return {
        "status": response.status,
        "json": response.payload,
        "text": response.content,
        "error": response.error,
        "items": None,
        "result": response.content,
    }

client = LLMClient(call=call)
```

作成したクライアントは `runtime.run(inputs, llm_client=client)` で利用できます。YAML から利用したい場合は自前のファクトリモジュールを組み込み、`_instantiate_llm_provider` を拡張してください。
