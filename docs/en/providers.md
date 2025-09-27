# Providers

Agent Ethan resolves LLM clients via the `providers` section in YAML or by passing an `LLMClient` directly to `AgentRuntime.run`.

## Built-in Factories

### OpenAI-compatible

```python
from agent_ethan.providers import create_openai_client

client = create_openai_client(
    model="gpt-4o-mini",
    temperature=0.1,
    client_kwargs={"api_key": os.environ["OPENAI_API_KEY"]},
)
```

YAML equivalent:

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

### OpenAI-compatible (LM Studio, vLLM, etc.)

```python
from agent_ethan.providers import create_openai_compatible_client

client = create_openai_compatible_client(
    model="google/gemma-3-12b",
    base_url=os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "http://127.0.0.1:1234/v1"),
    temperature=0.2,
    default_kwargs={"max_tokens": 512},
)
```

YAML configuration:

```yaml
meta:
  defaults:
    llm: local:google/gemma-3-12b
  providers:
    local:
      type: openai_compatible  # "lmstudio" is still accepted for backward compatibility
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b
      request_timeout: 120
      kwargs:
        max_tokens: 512
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

## Environment Placeholders

Provider settings, tool configuration, and even prompt templates can leverage environment variables via `{{env.VAR_NAME}}`. During runtime, unresolved variables raise `AgentRuntimeError` to prevent silent failures.

## Custom Providers

To integrate another backend, construct an `LLMClient` with a custom `call` implementation:

```python
from agent_ethan.llm import LLMClient

async def call(*, node, prompt, timeout=None):
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

Then execute:

```python
runtime.run(inputs, llm_client=client)
```

If you want to expose it via YAML, add a recognizer in your own factory module and modify `_instantiate_llm_provider` (or wrap `build_agent_from_yaml` with custom logic).
