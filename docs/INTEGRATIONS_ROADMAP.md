# Integrations roadmap (backlog)

**Status:** ideas and near-term work — **not** a release commitment. The live product
story is [VISION.md](./VISION.md). This file tracks the current connector surface and
planned additions.

> **Note:** Per the [REFACTOR_PLAN.md](./REFACTOR_PLAN.md), several low-ROI connectors
> (YouTube, Discord, Teams, iCloud extras like photos/reminders/notes) are slated for removal
> to simplify the tool palette and reduce maintenance burden.

## Principles

- One code path per provider family (e.g. all Gmail writes go through `GmailClient` and
  the `gmail` routes).
- Add integrations as: **client + routes (if UI needs them) + agent_tools entries + `_DISPATCH` handlers**,
  with mocked HTTP tests so CI does not need real tokens.
- Prefer **documented public APIs**; avoid scraping or unofficial endpoints unless the tradeoff is explicit.

## Connector checklist template (for new integrations)

1. **Provider id** — Pick a stable `ConnectorConnection.provider` string, e.g.
   `google_youtube`, `whatsapp_business`, `icloud_caldav`. Alias legacy ids in
   `tool_required_connector_providers` if needed.
2. **Auth mode** — **OAuth2** (Google/Microsoft) via `TokenManager`, or
   **static secrets** stored in encrypted `credentials_encrypted`.
3. **OAuth scopes** — Extend the provider's scope registry so the callback creates
   the right `ConnectorConnection` rows.
4. **HTTP client** — Thin client under `backend/app/services/connectors/` with a
   `*APIError` type carrying `status_code` + `detail`.
5. **Agent tools** — Register OpenAI-format schemas in `agent_tools.py` (read-only,
   auto-apply, or proposal bucket).
6. **Dispatch** — Map `name → handler` in `agent_dispatch_table.py`;
   proposal tools use `takes_run_id=True`.
7. **Gating** — `tool_required_connector_providers()` must return the providers
   for `filter_tools_for_user_connectors()`.
8. **Gating** — High-risk sends use `PendingProposal` + `PendingExecutionService`.
9. **Tests** — Mocked HTTP or unit tests; keep CI free of real tokens.

## Connector surface (current)

### Google (OAuth, done)

| API | Status | Note |
| --- | ------ | ---- |
| **Gmail** | Done | Live read/write; spam/silence/label/modify; filters |
| **Calendar** | Done | Google Calendar, Microsoft Graph CalDAV, iCloud CalDAV unified via `calendar_*` tools |
| **Drive** | Done | List/upload files; share if needed |
| **Tasks** | Done | CRUD on tasklists |
| **Sheets** | Done (narrow) | `sheets_read_range`, `sheets_append_row` |
| **Docs** | Done (narrow) | `docs_get_document` |
| **People** | Done | `people_search_contacts` |
| **YouTube** | Done → **remove** | Low ROI for personal assistant; see refactor plan |

### Microsoft (Graph OAuth, done)

| Surface | Status | Note |
| ------- | ------ | ---- |
| **Outlook mail** | Done | `outlook_list_messages`, `outlook_get_message` |
| **Teams** | Done → **remove** | Limited to self-hosted; low value; see refactor plan |

### Apple/iCloud (app-specific passwords, done)

| Surface | Status | Note |
| ------- | ------ | ---- |
| **Calendar (CalDAV)** | Done | `calendar_*` tools; `icloud_caldav` provider |
| **Drive** | Done (best-effort) | PyiCloud web APIs; 2FA may be required |
| **Contacts (CardDAV)** | Done (read) | `icloud_contacts_list`, `icloud_contacts_search` |

> **Planned removal** per refactor plan: iCloud extras (photos, reminders, notes), iCloud Drive tools.

### Third-party (api key / bot token, done)

| Surface | Status | Note |
| ------- | ------ | ---- |
| **GitHub** | Done | PAT connector; `github_list_my_repos`, `github_list_repo_issues` |
| **Slack** | Done | Bot token; `slack_list_conversations`, `slack_get_conversation_history` |
| **Linear** | Done | API key; `linear_list_issues`, `linear_get_issue` |
| **Notion** | Done | Integration token; `notion_search`, `notion_get_page` |
| **Telegram** | Done | Bot token; `telegram_get_updates`, `telegram_send_message` |
| **Discord** | Done → **remove** | Very low personal-assistant value; see refactor plan |
| **WhatsApp** | Done | Meta Cloud API; `propose_whatsapp_send` (approval-gated) |

### Device bridge (done)

| Surface | Status | Note |
| ------- | ------ | ---- |
| **File ingest** | Done | `POST /api/v1/device-files/ingest`; agent tools: `device_list_ingested_files`, `device_get_ingested_file` |
| iOS Shortcuts action | Done | Can upload files via HTTP bearer token |

## Connector gating

When `agent_connector_gated_tools` is enabled, the agent's tool palette is filtered to
only include tools for the connectors the user has actually linked. This prevents the
model from trying to call tools it cannot use (e.g. `gmail_list_messages` with no Gmail
connection).

## Gmail constraints (reference)

- `users.settings.filters`: `action.addLabelIds` **must not** include `SPAM` —
  Gmail returns 400. Use `users.threads.modify` / `users.messages.modify` to
  move existing mail to Spam; filters can only do skip-inbox via `removeLabelIds`.

## Near-term priorities

1. **Stability** — Expand mock-first tests per connector (Gmail pattern in `test_gmail_*.py`).
2. **Tool palette cleanup** — Remove low-ROI connectors per refactor plan;
   shrink tool descriptions; eliminate duplicate tools (`memory_search` alias).
3. **New connectors** — Add one at a time; avoid duplicating full API surfaces.

## Related docs

- [SKILLS.md](SKILLS.md) — skill file format and authoring.
- [PROVIDERS.md](PROVIDERS.md) — AI provider setup guides.
- [REFACTOR_PLAN.md](REFACTOR_PLAN.md) — architectural simplification plan.
