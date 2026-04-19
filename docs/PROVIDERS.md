# AI provider setup — three options, each fully wired for the agent

This file is a step-by-step playbook for the three configurations that are
known to work end-to-end with the agent harness in this repo:

| Tier              | Provider                       | Cost                       | Hardware            |
| ----------------- | ------------------------------ | -------------------------- | ------------------- |
| **Free cloud**    | Google AI Studio (Gemini 2.5)  | $0 (generous free tier)    | Anything            |
| **Free local**    | Ollama (watt-tool-8B / qwen3-coder) | $0                    | 8–24 GB VRAM tiered |
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

## 2. Free local — Ollama (2026 tool-calling picks)

Nothing leaves your machine; no API keys. Aquila uses a **dual harness**:

- **Native** — OpenAI-style `tools=` + `tool_choice="required"` (works on cloud APIs and on Ollama with models that implement tool calling correctly).
- **Prompted** — full tool JSON is embedded in the system prompt and the model emits `<tool_call>{"name":...,"arguments":...}</tool_call>` blocks. Used automatically for `qwen3` (non-coder) and Hermes-style models on Ollama when **Harness** is **Auto** (see [ollama#8421](https://github.com/ollama/ollama/issues/8421), [ollama#14601](https://github.com/ollama/ollama/issues/14601)).

**Settings → Modo harness del agente**: `Auto` (recommended), `Native`, or `Prompted`.

### Model tiers (VRAM ≈ Q4_K_M; verify on your GPU)

| Tier | Model (`ollama pull …`) | Harness | Notes |
|------|-------------------------|---------|--------|
| 8 GB | `hengwen/watt-tool-8B` | native | BFCL-oriented 8B tool specialist; **registry default** chat/classify. |
| 12 GB | `qwen3-coder:14b` | native | Strong coding + tool stack; Ollama’s 2026 engine improvements. |
| 24 GB | `qwen3-coder:30b` | native | Heavier; best local quality/speed tradeoff if it fits. |
| 8 GB | `allenporter/xlam:7b` | native | Salesforce xLAM family; action/tool-oriented. |
| 8 GB | `qwen3:8b` | prompted | Base Qwen3 on Ollama: use **Auto** or **Prompted** — native `tools=` is unreliable until upstream fixes land. |
| 8 GB | `hermes3:8b` | prompted | Nous Hermes; tag-style tool output — **Auto** selects prompted. |
| 6 GB | `qwen2.5:7b-instruct` | native | Minimum “classic” instruct fallback; still solid for tool calling on many Ollama builds. |

Reference benchmarks: [BFCL V4 leaderboard](http://gorilla.cs.berkeley.edu/leaderboard.html) (tool calling). Community notes: [OpenClaw + Ollama models 2026](https://clawdbook.org/blog/openclaw-best-ollama-models-2026).

### One-time install

1. Install Ollama: <https://ollama.com/download>.
2. Daemon running: `curl -s http://localhost:11434/api/tags | jq .`
3. Pull chat + embeddings (defaults in registry: watt-tool + nomic):

   ```bash
   ollama pull hengwen/watt-tool-8B
   ollama pull nomic-embed-text
   ```

### Configure the app

1. **Settings → Modelo de IA** → **Ollama**.
2. Server URL: `http://localhost:11434` (host) or `http://host.docker.internal:11434` (backend in Docker).
3. Chat model: start with `hengwen/watt-tool-8B` (or another row from the table).
4. **Harness**: leave **Auto** unless you are debugging.
5. **Probar conexión** → **Guardar**.

### Verify

```bash
docker compose exec backend python -m app.scripts.smoke_ai_provider
```

- Prints **native** and, for Ollama, **prompted** tool checks. Either path may pass; **Auto** picks the right mode per model.
- If native fails but prompted passes, you’ll see a `WARN` — that’s expected for `qwen3:8b`.

### Try it from the chat UI

First turn can take 5–20 s on a local GPU — normal.

### Tuning notes

- `OLLAMA_KEEP_ALIVE` — keep the model loaded between turns.
- **Classify model** can be smaller than chat if you split models (e.g. classify on CPU-light model).

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
- Agent workspace prompts: `backend/agent_workspace/` (`SOUL.md`, `AGENTS.md`)
- Agent harness (native + prompted): `backend/app/services/agent_harness/` and
  the loop in `backend/app/services/agent_service.py`
- This smoke script:
  `backend/app/scripts/smoke_ai_provider.py`
