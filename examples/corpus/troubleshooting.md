# Troubleshooting Tips

When an agent run fails, inspect the state keys that tools populate. The runtime records the last tool outputs under `result`, so you can render them inside error handlers. For persistent conversation memory, ensure the `memory` block declares a `session_id` and that state includes `messages`.

To debug RAG behaviour:
- Verify that your documents are embedded with the same model that you query with.
- Recreate the vector store if you change the corpus contents.
- Log the retrieved snippets to confirm the vector search covers the desired context.

