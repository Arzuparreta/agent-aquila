# Integrations roadmap (OpenClaw-style)

This project follows an **OpenClaw-like** shape: a broad **tool catalogue** backed by **thin REST clients**, **OAuth** via `TokenManager`, optional **skills** (markdown recipes), and **live provider proxies** under `/api/v1` so the UI and the agent share one implementation.

## Principles

- One code path per provider family (e.g. all Gmail writes go through [`GmailClient`](../backend/app/services/connectors/gmail_client.py) and [`gmail` routes](../backend/app/routes/gmail.py)).
- Add integrations as **client + routes (if UI needs them) + `agent_tools` entries + `_DISPATCH` handlers**, with **mocked HTTP tests** so CI does not need real tokens.
- Prefer **documented public APIs**; avoid scraping or unofficial endpoints unless the tradeoff is explicit.

## Gmail constraints (reference)

- **`users.settings.filters`**: `action.addLabelIds` **must not** include the system label **`SPAM`** — Google returns `400 Invalid label SPAM in AddLabelIds`. Use **`users.threads.modify` / `users.messages.modify`** to move existing mail to Spam; filters can only use allowed actions (e.g. skip inbox via `removeLabelIds`).

## Near-term: Google

| API | Feasibility | Notes |
|-----|-------------|--------|
| **Gmail** | Done | Live proxy + agent tools; spam/silence behavior matches API limits above. |
| **Calendar / Drive** | Done | Same pattern as Gmail. |
| **Tasks** (`tasks.googleapis.com`) | High | OAuth + REST; tasklists and tasks CRUD; good next connector. |
| **Google Keep** | Low | No supported consumer REST API for third-party apps comparable to Tasks/Drive. Defer unless Google publishes a stable surface. |
| **People / Contacts** | Medium | People API; scope and UX review for PII. |
| **Sheets / Docs** | Medium | Large surface; add narrow tools (e.g. append row, read range) first. |

## Apple and iCloud

| Surface | Feasibility | Notes |
|---------|-------------|--------|
| **iCloud Calendar / Contacts** | Medium | **CalDAV / CardDAV** with app-specific passwords; not OAuth2-in-the-browser like Google. |
| **iCloud Drive** | Low | No first-party “Google Drive–like” REST for arbitrary files for third parties. |
| **EventKit / File Provider (macOS/iOS)** | Medium | Requires a **local bridge** (companion app or MCP on device) — different trust and distribution model. |

## Suggested phases

1. **Stability**: Expand **mock-first tests** per connector for mutations and error shapes (Gmail pattern in `backend/tests/test_gmail_*.py`).
2. **Google Tasks**: New client, optional REST routes, tools, OAuth scopes, tests.
3. **Additional Google APIs**: One product at a time; avoid duplicating full API surfaces in tool schemas.
4. **Apple CalDAV**: Spike read-only calendar list/events; then opt-in writes with clear conflict policy.

## Related docs

- [`docs/testing.md`](testing.md) — how to run backend tests.
- [`docs/SKILLS.md`](SKILLS.md) — skill files for repeatable workflows.
- [`docs/PROVIDERS.md`](PROVIDERS.md) — connector / OAuth overview.
