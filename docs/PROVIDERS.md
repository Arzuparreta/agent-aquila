# AI provider setup

Three configuration tiers that are known to work end-to-end with the agent harness.
All use the same `LLMClient.chat_with_tools` + `EmbeddingClient.embed_texts` clients —
no provider-specific code paths in the agent loop.

| Tier              | Provider                       | Cost                       | Hardware            |
| ----------------- | ------------------------------ | -------------------------- | ------------------- |
| **Free cloud**    | Google AI Studio (Gemini 2.5)  | $0 (generous free tier)    | Anything            |
| **Free local**    | Ollama (watt-tool-8B / qwen3-coder) | $0                    | 8–24 GB VRAM tiered |
| **Paid frontier** | OpenAI (GPT-4o / gpt-4o-mini)  | Pay-as-you-go              | Anything            |

The registry also ships **OpenRouter**, **LiteLLM Proxy**, **Azure OpenAI**, and **Custom** (any
OpenAI-compatible `/v1` server).

After configuring any tier, run the smoke test below to confirm the agent
loop and embeddings (used by [agent persistent memory](MEMORY.md))
work against your configured provider.

> The harness no longer ships an inbox triage classifier or a RAG chunk index.
> Embeddings are now used solely by the agent's persistent memory; if you don't
> care about semantic memory recall you can leave the embedding model unset.

---

## 0. The smoke test (run after every config change)

A single command exercises **the same code paths the agent uses**:

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

If you have more than one user row, the script lists them and exits — pick one:

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider --list-users
docker compose exec backend python -m app.scripts.smoke_ai_provider --user-id 1
# or: --first  (uses lowest id; fine for quick local checks)
```

Output looks like this on success:

```
User           : me@example.com (id=1)
Provider       : Google AI Studio (Gemini)  (google)
Base URL       : https://generativelanguage.googleapis.com/v1beta/openai
Chat model     : gemini-2.5-flash
Classify model : gemini-2.5-flash
Embedding model: text-embedding-004
AI disabled    : False

[1/3] Tool calling
Tool calling (agent contract)
  OK   got 2 tool call(s): ['echo', 'final_answer']
  OK   all tool-call arguments parsed as dicts

[2/3] JSON mode
JSON mode (structured output contract)
  OK   parsed JSON

[3/3] Embeddings
Embeddings (agent memory recall contract)
  OK   got 2 vectors of dim 768; pad_embedding() will zero-pad to 1536. Compatible with pgvector(1536).

Smoke test PASSED — provider is fully wired for the agent harness.
```

Useful flags:

- `--email someone@example.com` — pick a specific user (default: the only user).
- `--user-id 1` — pick by id.
- `--skip embeddings` — skip a check if you haven't set an embedding model yet.
- `--all` — iterate **every** saved provider config for the user and print a per-provider results table.
  Useful after a KEK rotation.

---

## 1. Free cloud — Google AI Studio (Gemini 2.5 Flash)

This is the **fastest path to a fully working agent at zero cost**. Gemini
2.5 Flash honors `tools=` + `tool_choice="required"` reliably.

### Steps

1. Open <https://aistudio.google.com/apikey> → **Create API key**.
2. In the app, **Settings → AI Model** → Provider: **Google AI Studio (Gemini)**.
3. The form pre-fills the working defaults:
   - Base URL: `https://generativelanguage.googleapis.com/v1beta/openai`
   - Chat model: `gemini-2.5-flash`
   - Embedding model: `text-embedding-004`
4. Paste the API key → **Save**.

### Verify

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

All three checks should be `OK`. The embedding check reports dim 768 —
`pad_embedding()` will zero-pad to 1536. Expected and harmless.

### Try from chat

Open `/`, ask a question like *"Resume mis correos no leídos"*. The agent
should call `gmail_list_messages`, follow up with `gmail_get_message` as needed,
end with `final_answer`.

### Known limits

- Free tier is generous but rate-limited (~10 RPM / 250 RPD on Gemini).
  If you hit a 429, the run fails with a readable error.
- `text-embedding-004` is 768-dim. To wipe stored embeddings:

  ```bash
  docker compose exec db psql -U app -d app \
    -c "UPDATE agent_memories SET embedding=NULL, embedding_model=NULL;"
  ```

---

## 2. Free local — Ollama

Nothing leaves your machine; no API keys.

### Model tiers (VRAM ≈ Q4_K_M)

| VRAM | Model | Harness (native only — prompted mode removed) |
|------|-------|-----------------------------------------------|
| 8 GB | `hengwen/watt-tool-8B` | native (registry default) |
| 12 GB | `qwen3-coder:14b` | native |
| 24 GB | `qwen3-coder:30b` | native |
| 8 GB | `allenporter/xlam:7b` | native |
| 6 GB | `nomic-embed-text` | embedding only |

> **Harness note:** Aquila uses **native tool calling only** (`tools=` parameter).
> The old "prompted" mode (embedding tool JSON as text in the system prompt) has been
> removed as per the refactoring plan. Local models that don't support native `tools=`
> should be used behind a LiteLLM proxy or OpenRouter.

### One-time install

```bash
# Install Ollama: https://ollama.com/download
ollama pull hengwen/watt-tool-8B
ollama pull nomic-embed-text
```

### Configure

1. **Settings → AI Model** → **Ollama**.
2. Server URL: `http://localhost:11434` (host) or `http://host.docker.internal:11434` (Docker).
3. Chat model: `hengwen/watt-tool-8B`.
4. **Save**.

### Verify

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

### Tuning notes

- Set `OLLAMA_KEEP_ALIVE` to keep the model loaded between turns.

---

## 3. Paid frontier — OpenAI (GPT-4o / GPT-4o-mini)

For the highest tool-call accuracy.

### Steps

1. Get a key at <https://platform.openai.com/api-keys>.
2. **Settings → AI Model** → Provider: **OpenAI**.
3. Suggested values:
   - Base URL: `https://api.openai.com/v1` (default)
   - Chat model: `gpt-4o` (any GPT-4 family model with tool calling works; avoid `o1` reasoning models)
   - Classify model: `gpt-4o-mini` (for structured output helpers)
   - Embedding model: `text-embedding-3-small` (1536-dim recommended; no truncation needed)
4. Paste the API key → **Save**.

### Verify

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

### Cost guardrails

- Agent runs cost the chat-model price × turns. `gpt-4o` is ~$2.50/M in, ~$10/M out.
  Each turn carries the tool palette plus conversation history (~5–15K tokens), so a
  3-turn answer is ~25K input tokens ≈ $0.07. Budget accordingly.

---

## Other providers (OpenRouter, LiteLLM, Azure, Custom)

All share the same `LLMClient` / `EmbeddingClient` plumbing.

**Caveat — Anthropic:**
Anthropic's native Chat API doesn't expose `/chat/completions`. Use **OpenRouter →
anthropic/claude-…** which proxies via the OpenAI-compatible format, or wait for the
dedicated Anthropic provider.

**Caveat — Custom (OpenAI-compatible):**
Works for any server exposing `/chat/completions` and `/embeddings` in OpenAI's shape
(LM Studio, vLLM, Together, Fireworks, etc.). Set the base URL to that server's `/v1`.

---

## Where this stuff lives in code

- Provider definitions (UI form, defaults, capabilities):
  `backend/app/services/ai_providers/registry.py`
- Per-provider list-models / test-connection:
  `backend/app/services/ai_providers/adapters.py`
- Chat client: `backend/app/services/llm_client.py` (`chat_with_tools`, `chat_completion`)
- Embedding client: `backend/app/services/embedding_client.py`
- Embedding padding to pgvector 1536 dims:
  `backend/app/services/embedding_vector.py`
- Smoke script: `backend/app/scripts/smoke_ai_provider.py`
