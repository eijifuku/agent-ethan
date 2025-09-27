# ハンズオンチュートリアル

このチュートリアルでは、ゼロからシンプルなサポートエージェントを作成し、段階的に機能を追加していきます。

## ステップ 1: 雛形を作成

```bash
mkdir -p agents/tutorial
cd agents/tutorial
```

`support_agent.yaml` を作成し、基本情報とステートを定義します。

```yaml
meta:
  schema_version: 1
  name: support_agent
  defaults:
    llm: openai:gpt-4o-mini
  providers:
    openai:
      type: openai
      client_kwargs:
        api_key: "{{env.OPENAI_API_KEY}}"

state:
  shape:
    question: str
    answer: str | null
    history: list[str]
  reducer: deepmerge
  init:
    history: []
```

## ステップ 2: プロンプトを追加

```yaml
prompts:
  partials:
    system/base: |
      You are a helpful support specialist.
  templates:
    respond:
      system: "{{> system/base }}"
      user: |
        Question: {{ question }}
        History:
        {%- for entry in history %}
        - {{ entry }}
        {%- endfor %}
```

## ステップ 3: ツールを宣言

最初は noop (何もしない) ツールで履歴を操作します。

```yaml
tools:
  - id: record
    kind: noop
```

## ステップ 4: グラフを構築

```yaml
graph:
  inputs: [question]
  outputs: [answer, history]
  nodes:
    - id: recorder
      type: noop
      map:
        merge:
          history:
            - "{{ inputs.question }}"

    - id: responder
      type: llm
      prompt: respond
      map:
        set:
          answer: "{{ result.text }}"

  edges:
    - from: recorder
      to: responder
```

## ステップ 5: 実行

```python
from agent_ethan.builder import build_agent_from_path

runtime = build_agent_from_path("agents/tutorial/support_agent.yaml")
state = runtime.run({"question": "How do I reset my password?"})
print(state["answer"])
```

## ステップ 6: エラー時のフォールバック

LLM の呼び出しが失敗した場合に備えてフォールバックツールを追加します。

```yaml
tools:
  - id: fallback
    kind: python
    impl: "../agent_ethan/tools/arxiv_summary.py#fallback_summary"
  - id: record
    kind: noop

nodes:
  - id: responder
    type: llm
    prompt: respond
    on_error:
      resume: true
    map:
      set:
        answer: "{{ result.text }}"

  - id: ensure_answer
    type: tool
    uses: fallback
    inputs:
      downloads: []
      llm_summary: "{{ state.answer }}"
    map:
      set:
        answer: "{{ result.json['summary'] or 'We will contact you shortly.' }}"

edges:
  - from: responder
    to: ensure_answer
```

## ステップ 7: 応用

- ルーターノードで分岐を追加し、条件に応じて異なる回答プロンプトを使用。
- ループノードでスコアが十分高くなるまで回答を改善。
- サブグラフで共通処理をモジュール化し、複数のエージェントから呼び出す。

次は [設定リファレンス](configuration.md) や [ノード一覧](nodes.md) を参照しながら、自分のユースケースに合わせた YAML を設計してください。
