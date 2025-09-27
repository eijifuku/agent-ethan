# Hands-on Tutorial

This walkthrough builds a working agent from scratch. Follow the steps to understand how each YAML section fits together.

## Step 1: Create the Project Skeleton

```bash
mkdir -p agents/tutorial
cd agents/tutorial
```

Create `support_agent.yaml` with the following scaffold:

```yaml
meta:
  schema_version: 1
  name: support_agent
  defaults:
    llm: local:google/gemma-3-12b
  providers:
    local:
      type: openai_compatible
      base_url: "{{env.OPENAI_COMPATIBLE_BASE_URL}}"
      model: google/gemma-3-12b

state:
  shape:
    question: str
    answer: str | null
    history: list[str]
  reducer: deepmerge
  init:
    history: []
```

This declares metadata, default provider, and the state schema.

## Step 2: Add Prompts

Append a prompt section:

```yaml
prompts:
  partials:
    system/base: |
      You are a helpful technical support specialist.
  templates:
    respond:
      system: "{{> system/base }}"
      user: |
        Question: {{ question }}
        Known History:
        {%- for entry in history %}
        - {{ entry }}
        {%- endfor %}
```

## Step 3: Declare Tools

For this tutorial, we only need a noop tool to append history entries:

```yaml
tools:
  - id: record
    kind: noop
```

No external files needed—`noop` is a valid node type.

## Step 4: Build the Graph

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

- The noop node stores the incoming question in `history`.
- The LLM node generates the answer.

## Step 5: Run the Agent

```python
from agent_ethan.builder import build_agent_from_path

runtime = build_agent_from_path("agents/tutorial/support_agent.yaml")
state = runtime.run({"question": "How do I reset my password?"})
print(state["answer"])
```

## Step 6: Add Error Handling

If the LLM might fail, add a fallback tool:

```yaml
tools:
  - id: fallback
    kind: python
    impl: "../tools/arxiv_summary.py#fallback_summary"

  - id: record
    kind: noop

nodes:
  ...
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
  - from: recorder
    to: responder
  - from: responder
    to: ensure_answer
```

Now the agent falls back to a canned response if the LLM output is empty.

## Step 7: Wire Additional Nodes

Add routers, loops, or subgraphs as needed. Refer to:
- [Configuration Reference](configuration.md) for YAML fields
- [Node Catalogue](nodes.md) for node behaviors
- [Providers](providers.md) to swap between LM Studio and OpenAI

This iterative approach—define state, declare prompts, add tools, then wire nodes—is the recommended pattern for every Agent Ethan project.
