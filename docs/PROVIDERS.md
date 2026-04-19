# AI provider setup — three options, each fully wired for the agent

This file is a step-by-step playbook for the three configurations that are
known to work end-to-end with the agent harness in this repo:

| Tier              | Provider                       | Cost                       | Hardware            |
| ----------------- | ------------------------------ | -------------------------- | ------------------- |
| **Free cloud**    | Google AI Studio (Gemini 2.5)  | $0 (generous free tier)    | Anything            |
| **Free local**    | Ollama (Qwen 2.5 7B)           | $0                         | RTX 3060 12GB ✅     |
| **Paid frontier** | OpenAI (GPT-5 / 4.1 / 4o)      | Pay-as-you-go              | Anything            |

All three use the same `LLMClient.chat_with_tools` + `EmbeddingClient.embed_texts`
clients — no provider-specific code paths. The differences are entirely in the
**Settings → Modelo de IA** form (which is itself driven by
`backend/app/services/ai_providers/registry.py`).

After configuring any tier, run the smoke test below to confirm the agent
loop and embeddings (used by [agent persistent memory](MEMORY.md))
work against your configured provider.

> The harness no longer ships an inbox triage classifier or a RAG chunk
> index. Embeddings are now used solely by the agent's persistent memory;
> if you don't care about semantic memory recall you can leave the
> embedding model unset.

---

## 0. The smoke test (run after every config change)

A single command exercises **the same code paths the agent uses**:

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
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
- `--all` — iterate **every** saved provider config for the user and print a
  per-provider results table. Useful after a KEK rotation or when you want
  to confirm both an Ollama fallback **and** a cloud key still work.

If a check fails it prints the upstream error verbatim so you can tell apart
"wrong API key" from "tool_choice not supported" from "model emitted invalid
JSON".

---

## 1. Free cloud — Google AI Studio (Gemini 2.5 Flash)

This is the **fastest path to a fully working agent at zero cost**. Gemini
2.5 Flash honors `tools=` + `tool_choice="required"` reliably and has a
generous free tier on Google AI Studio (no credit card required for the free
key).

### Steps

1. Open <https://aistudio.google.com/apikey> and click **Create API key →
   Create API key in new project**. Copy the `AIza...` string.
2. In the running app, go to **Settings → Modelo de IA**.
3. Provider: select **Google AI Studio (Gemini)**.
4. The form pre-fills with the working defaults:
   - Base URL: `https://generativelanguage.googleapis.com/v1beta/openai`
   - Chat model: `gemini-2.5-flash`
   - Classify model: `gemini-2.5-flash`
   - Embedding model: `text-embedding-004`
5. Paste the API key into **API key**.
6. Click **Probar conexión** — should report ~50 models found.
7. Click **Guardar**.

### Verify

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

All three checks should be `OK`. The embedding check will report dim 768 and
note that `pad_embedding()` will pad to 1536 — that's expected and harmless.

### Try it from the chat UI

- Open `/`, ask: **"Resume mis correos no leídos"**. The agent should call
  `gmail_list_messages` (with `q="is:unread"`), follow up with
  `gmail_get_message` as needed, and end with `final_answer`.
- Open `/inbox`, click any email, then **Iniciar chat sobre este correo**.
  The agent should NOT auto-run; you type the first message yourself, then
  the agent answers using tool calls.

### Known limits

- Free tier is **generous but rate-limited** (currently ~10 RPM / 250 RPD on
  `gemini-2.5-flash`). For one user that is plenty; if you hit a 429 the run
  fails fast with a readable error.
- `text-embedding-004` is 768-dim; embeddings are only used by agent memory
  recall, so switching providers later just means recall quality changes —
  there is no RAG index to rebuild. To wipe the embeddings the agent stored
  for itself:

  ```bash
  docker compose exec db psql -U app -d app -c "UPDATE agent_memories SET embedding=NULL, embedding_model=NULL;"
  ```

---

## 2. Free local — Ollama + Qwen 2.5 7B (RTX 3060 12GB)

The full local plan: nothing leaves your machine, no API keys anywhere. The
combo below is the one the registry now defaults to and is sized for a
12 GB GPU.

### One-time install

1. Install Ollama: <https://ollama.com/download> (Linux: `curl -fsSL https://ollama.com/install.sh | sh`).
2. Make sure the daemon is running:

   ```bash
   ollama serve &           # if not already running as a systemd unit
   curl -s http://localhost:11434/api/tags | jq .
   ```

3. Pull the two models the registry defaults to:

   ```bash
   ollama pull qwen2.5:7b-instruct      # ~5 GB on disk, ~6 GB VRAM at Q4_K_M
   ollama pull nomic-embed-text         # ~270 MB, 768-dim embeddings
   ```

   **Why these specifically?** `qwen2.5:7b-instruct` is the smallest model
   in the Qwen 2.5 family that reliably honors the OpenAI-compat tool-calling
   contract this harness depends on. Anything smaller (Gemma 3B/4B, Phi 3,
   Llama 3.2 3B) will silently invent tool names and break the loop — the
   agent has zero compensating shims by design (see the docstring at the top
   of `app/services/agent_service.py`).

   Stretch option if you have headroom: `ollama pull qwen2.5:14b-instruct`
   (~9 GB VRAM at Q4 — tight on 12 GB, leave context short).

### Configure the app

1. **Settings → Modelo de IA**.
2. Provider: **Ollama**.
3. Server URL:
   - Backend running natively: `http://localhost:11434`
   - Backend running in Docker (this repo's `docker-compose.yml`):
     `http://host.docker.internal:11434` *(the compose file already maps
     `host.docker.internal` to the host gateway via `extra_hosts`).*
4. The form pre-fills with:
   - Chat model: `qwen2.5:7b-instruct`
   - Classify model: `qwen2.5:7b-instruct`
   - Embedding model: `nomic-embed-text`
5. **Probar conexión** should list every model you've pulled.
6. **Guardar**.

### Verify

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

Expected nuance:

- **Tool calling**: `OK` for `qwen2.5:7b-instruct`. If you swapped in a
  smaller model and see `model returned text instead of a tool call`, that
  is the failure mode the harness was written to refuse to paper over —
  switch back to a 7B+ tool-calling-capable model.
- **JSON mode**: `OK`. Some Ollama builds reject `response_format=json_object`;
  the smoke script auto-retries without it (the triage parser tolerates
  loose JSON), so you may see a `WARN` line before the `OK`.
- **Embeddings**: `OK`, dim 768, padded to 1536.

### Try it from the chat UI

Same as the Gemini section. The first response will be slower than cloud
models (5–15 s on a 3060 for `qwen2.5:7b-instruct` Q4) — that's the model
inferring on your GPU, not a bug.

### Tuning notes

- Ollama keeps a model loaded in VRAM for `OLLAMA_KEEP_ALIVE` minutes after
  the last request (default 5). For a single-user CRM that's perfect; bump
  it (`OLLAMA_KEEP_ALIVE=60m`) if you find every prompt is paying re-load
  cost.
- If you want a smaller / faster classify model than the chat model, set
  **Classify model** to e.g. `qwen2.5:3b-instruct` while keeping the chat
  model on 7B. The harness will use it for inbox triage only.

---

## 3. Paid frontier — OpenAI (GPT-5 / GPT-4.1 / GPT-4o)

For when you want the highest tool-call accuracy and don't mind paying.
This is also the **canonical reference path** — every other provider is
emulating OpenAI's `/chat/completions` shape.

### Steps

1. Get a key at <https://platform.openai.com/api-keys>.
2. **Settings → Modelo de IA**.
3. Provider: **OpenAI**.
4. Suggested values:
   - Base URL: `https://api.openai.com/v1` (the default)
   - Chat model: `gpt-5` if you have access, otherwise `gpt-4.1` or
     `gpt-4o` *(any GPT-4 family model with tool calling works; avoid the
     `o1` reasoning models for the agent loop — they don't return tool calls
     in the OpenAI tool-calling format)*.
   - Classify model: `gpt-4o-mini` (used for any structured-output helper
     calls; can stay equal to the chat model if you don't want a second
     row).
   - Embedding model: `text-embedding-3-large` (3072-dim, truncated to
     1536 by `pad_embedding`) **or** `text-embedding-3-small` (1536-dim
     exactly — recommended; no truncation, half the cost). Used only for
     [agent memory recall](MEMORY.md) — leave unset if you don't need
     semantic recall.
5. Paste the API key.
6. **Probar conexión** → **Guardar**.

### Verify

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

All three checks should be `OK` in well under a second total.

### Cost guardrails

- There is no inbox triage classifier any more — the agent only spends
  tokens when *you* talk to it (or when the optional `agent_heartbeat`
  cron is enabled).
- Agent runs cost the chat-model price × turns. `gpt-4o` is ~$2.50/M in,
  ~$10/M out. Each turn carries the full tool palette (~8k tokens after
  adding the live Gmail / Calendar / Drive / Outlook / Teams tools), so
  a 3-turn answer is ~25k input tokens ≈ $0.07. Budget accordingly.

---

## Other providers in the registry (work the same way)

The registry also ships **OpenRouter**, **LiteLLM Proxy**, **Anthropic**,
**Azure OpenAI**, and **Custom (OpenAI-compatible)**. They all share the
same `LLMClient` / `EmbeddingClient` plumbing.

Caveats:

- **Anthropic native**: marked `chat_openai_compatible: False` in the
  registry. The current `LLMClient` posts to `/chat/completions`, which
  Anthropic's native API doesn't expose. Use **OpenRouter → anthropic/claude-…**
  or wait for the dedicated Anthropic chat path. The smoke script will
  fail loudly if you point it at native Anthropic — that's the harness
  telling you the truth.
- **Custom (OpenAI-compatible)**: works for any server that exposes
  `/chat/completions`, `/embeddings`, and `/models` in OpenAI's shape
  (LM Studio, vLLM, Together, Fireworks, DeepInfra, etc.). Set the base
  URL to that server's `/v1` root.

---

## Where this stuff lives in the code

- Provider definitions (UI form, defaults, capabilities, test strategy):
  `backend/app/services/ai_providers/registry.py`
- Per-provider list-models / test-connection HTTP shapes:
  `backend/app/services/ai_providers/adapters.py`
- The chat client the agent uses:
  `backend/app/services/llm_client.py` (`chat_with_tools`, `chat_completion`)
- The embedding client agent memory uses:
  `backend/app/services/embedding_client.py`
- Auto-padding to pgvector's 1536 dims:
  `backend/app/services/embedding_vector.py`
- Agent harness contract (no compensating shims):
  see the long docstring at the top of `backend/app/services/agent_service.py`
- This smoke script:
  `backend/app/scripts/smoke_ai_provider.py`
