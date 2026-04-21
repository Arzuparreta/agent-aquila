"""Locked roadmap answers for sections A–F (questionnaire).

These assumptions drive schema, seed data, and AI/RAG scope until you change them explicitly.

A — Domain (Agent Aquila)
    Connectors: Gmail, Calendar, Drive, Outlook, Teams (OAuth per user) plus chat and durable agent memory.
    Legacy CRM-shaped tables (contacts, deals, events) may remain for compatibility; `role` / pipeline fields are optional.
    Tenancy: single shared deployment dataset; multi-tenant isolation is per-user accounts and row ownership.

B — Volume & performance
    Target seed: ~20 contacts, ~10 deals, ~30 emails, ~5 upcoming events (order-of-magnitude for UX).
    Triage/embeddings may complete inline on request; sub-minute latency acceptable for MVP.
    No external IMAP/Gmail import in v1—only rows created via API/UI.

C — Auth
    Per-user accounts (existing `users` table). All authenticated users share the same CRM rows.

D — AI configuration
    Per-user provider settings (`user_ai_settings`): OpenAI-compatible APIs, Ollama, OpenRouter via `base_url`.
    One active embedding model per user; vectors stored as `vector(1536)` with zero-padding for shorter models.
    Users can disable AI entirely (`ai_disabled`).

E — RAG
    Chunked hybrid retrieval: entities are indexed as labeled text chunks in `rag_chunks` (dense embeddings + English FTS, RRF fusion).
    Row-level `embedding` columns remain as a mean-of-chunks summary and legacy fallback when chunk index is empty.
    Search API returns citation snippets (chunk text + entity id + type + optional chunk id).
    Retention: same as row storage (no separate purge).

F — Email
    v1: each `emails` row is a single ingested message; threading is a future concern.
    Compose/send to external SMTP is out of scope; draft generation is assistive text only.
"""
