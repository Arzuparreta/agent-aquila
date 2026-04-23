# Integrations roadmap (backlog)

**Status:** ideas and near-term work — **not** a release commitment. The live product story is
[VISION.md](./VISION.md). This file tracks how new connectors should be added: a broad **tool
catalogue** backed by **thin REST clients**, **OAuth** via `TokenManager`, optional **skills**
(markdown recipes), and **live provider proxies** under `/api/v1` so the UI and the agent share
one implementation.

## Principles

- One code path per provider family (e.g. all Gmail writes go through `[GmailClient](../backend/app/services/connectors/gmail_client.py)` and `[gmail` routes](../backend/app/routes/gmail.py)).
- Add integrations as **client + routes (if UI needs them) + `agent_tools` entries + `_DISPATCH` handlers**, with **mocked HTTP tests** so CI does not need real tokens.
- Prefer **documented public APIs**; avoid scraping or unofficial endpoints unless the tradeoff is explicit.

## Connector checklist (repeat for every new integration)

Use this before merging a new provider:

1. **Provider id** — Pick a stable `ConnectorConnection.provider` string (e.g. `google_youtube`, `whatsapp_business`, `icloud_caldav`). Alias legacy ids in `tool_required_connector_providers` if needed (`gcal` / `google_calendar`).
2. **Auth mode** — **OAuth2 (Google/Microsoft)** via `[TokenManager](../backend/app/services/oauth/token_manager.py)`: add the provider to `_GOOGLE_PROVIDERS` / `_MICROSOFT_PROVIDERS` when refresh applies. **Static secrets** (WhatsApp, CalDAV): store in encrypted `credentials_encrypted`; non-OAuth branches in `TokenManager.get_valid_creds` return the stored access token.
3. **OAuth scopes** — For Google: extend `[google_oauth.py](../backend/app/services/oauth/google_oauth.py)` `SCOPES_*`, `scopes_for_intent`, and `provider_ids_for_scopes` so the callback creates the right rows. Enable the matching API in Google Cloud Console.
4. **HTTP client** — Add a thin client under `[backend/app/services/connectors/](../backend/app/services/connectors/)` with a `*APIError` type carrying `status_code` + `detail` for the agent dispatcher.
5. **Agent tools** — Register OpenAI-format schemas in `[agent_tools.py](../backend/app/services/agent_tools.py)` (correct bucket: read-only, auto-apply, or proposal).
6. **Dispatch** — Map `name` → `AgentService._tool_*` in `[agent_dispatch_table.py](../backend/app/services/agent_dispatch_table.py)`; proposal tools use `takes_run_id=True`.
7. `**tool_required_connector_providers`** — So `[filter_tools_for_user_connectors](../backend/app/services/agent_tools.py)` hides tools when the account is not linked.
8. **Gating** — Outbound high-risk sends use `PendingProposal` + `[PendingExecutionService](../backend/app/services/pending_execution_service.py)`; extend `kind`, `preview_for_proposal_kind`, and `[capability_policy](../backend/app/services/capability_policy.py)` `KIND_RISK` if needed.
9. **Tests** — Mocked HTTP or unit tests (see Gmail/Drive tests); keep CI free of real tokens.

## Gmail constraints (reference)

- `**users.settings.filters`**: `action.addLabelIds` **must not** include the system label `**SPAM`** — Google returns `400 Invalid label SPAM in AddLabelIds`. Use `**users.threads.modify` / `users.messages.modify**` to move existing mail to Spam; filters can only use allowed actions (e.g. skip inbox via `removeLabelIds`).

## Near-term: Google


| API                                | Feasibility      | Notes                                                                                                                                                     |
| ---------------------------------- | ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Gmail**                          | Done             | Live proxy + agent tools; spam/silence behavior matches API limits above.                                                                                 |
| **Calendar / Drive**               | Done             | Same pattern as Gmail.                                                                                                                                    |
| **Tasks** (`tasks.googleapis.com`) | Done             | OAuth + REST; tasklists and tasks CRUD via agent tools.                                                                                                   |
| **Google Keep**                    | Low              | No supported consumer REST API for third-party apps comparable to Tasks/Drive. Defer unless Google publishes a stable surface.                            |
| **People / Contacts**              | Medium           | People API; scope and UX review for PII.                                                                                                                  |
| **Sheets / Docs**                  | Done (narrow)    | OAuth scopes `google_sheets` / `google_docs`; tools: `sheets_read_range`, `sheets_append_row`, `docs_get_document`.                                       |
| **YouTube Data API**               | Done (iterating) | Channel search, videos, **playlists + playlist items** tools, metadata update, **gated upload** via `propose_youtube_upload` + `PendingExecutionService`. |
| **GitHub REST**                    | Done (narrow)    | PAT connector + `github_list_my_repos` / `github_list_repo_issues` (read issues/PRs mixed; filter in model if needed).                                    |


## WhatsApp Business (Meta Cloud API)


| Surface           | Notes                                                                                                                                                                                           |
| ----------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Outbound send** | `propose_whatsapp_send` → `whatsapp_send` on approval. Session text vs **template** messages follow [Meta policy](https://developers.facebook.com/docs/whatsapp/overview) (24h window, opt-in). |


## Apple and iCloud


| Surface                                          | Feasibility        | Notes                                                                                                                                                                                                                                                                               |
| ------------------------------------------------ | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **iCloud Calendar**                              | Done               | **CalDAV** with app-specific passwords on provider `icloud_caldav`.                                                                                                                                                                                                                 |
| **iCloud Drive**                                 | Done (best-effort) | Same connector: **PyiCloud** (Apple web APIs), not a published first-party Drive REST. Tools: `icloud_drive_list_folder`, `icloud_drive_get_file`. May require 2FA / device approval; can break if Apple changes endpoints.                                                         |
| **iCloud Contacts (CardDAV)**                    | Done (read)        | **CardDAV** at `contacts.icloud.com` (or `.com.cn`). Tools: `icloud_contacts_list`, `icloud_contacts_search`. Parsing is best-effort vCard.                                                                                                                                         |
| **iCloud Reminders / Notes / Photos (PyiCloud)** | Best-effort        | Same `icloud_caldav` + PyiCloud web session as Drive. Tools: `icloud_reminders_list`, `icloud_notes_list`, `icloud_photos_list` — **metadata only** for photos (ids, names, sizes); no full binary download in-tool. **Brittle** if Apple or PyiCloud change CloudKit/web behavior. |
| **EventKit / File Provider (macOS/iOS)**         | Medium             | Optional **device bridge** (`POST /device-files/ingest`) for files pushed from Shortcuts — complements Drive when web login is blocked.                                                                                                                                             |


## Suggested phases

1. **Stability**: Expand **mock-first tests** per connector for mutations and error shapes (Gmail pattern in `backend/tests/test_gmail_*.py`).
2. **Google Tasks**: New client, optional REST routes, tools, OAuth scopes, tests.
3. **Additional Google APIs**: One product at a time; avoid duplicating full API surfaces in tool schemas.
4. **Apple CalDAV**: Spike read-only calendar list/events; then opt-in writes with clear conflict policy.

## iOS files vs server-side connectors (Track A / B)

- **Track A — Device bridge (implemented, minimal):** Authenticated `POST /api/v1/device-files/ingest` (JSON: `filename`, `path_hint`, `mime_type`, `content_base64`, max 4 MiB decoded). The agent can list and read small ingests with `**device_list_ingested_files`** / `**device_get_ingested_file**`. A **Shortcuts** action can `Get Contents of URL` with the user’s bearer token to upload from iOS.
- **Track B — iCloud Drive (implemented via PyiCloud):** There is still no Google Drive–style *official* REST for consumer iCloud Drive. This harness uses **PyiCloud** against Apple’s web APIs, sharing credentials with CalDAV on `icloud_caldav`. Prefer **Google Drive** when you need OAuth-stable, long-term server automation; use **iCloud Drive tools** when the user’s files live in iCloud and accept Apple/web-login constraints. **Health** for `icloud_caldav` verifies both CalDAV and Drive root listing.

## Related docs

- `[docs/testing.md](testing.md)` — how to run backend tests.
- `[docs/SKILLS.md](SKILLS.md)` — skill files for repeatable workflows.
- `[docs/PROVIDERS.md](PROVIDERS.md)` — connector / OAuth overview.