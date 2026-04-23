# Gmail push notifications (automation / Phase B)

This document sketches **Gmail API `users.watch` + Google Pub/Sub** (compare upstream docs such as
[OpenClaw’s Gmail Pub/Sub](https://docs.openclaw.ai/automation/gmail-pubsub)). It is **not** wired
in Aquila yet. When implemented, **enqueue one agent run** with a tight user message and
`turn_profile=automation` so the core applies the [context-first harness](./VISION.md) (History API
+ `gmail_get_*`) instead of inbox-wide ReAct.

## Goals

- Replace “wake the agent and scan the whole inbox” with **event-driven** work when mail actually changes.
- Optionally feed a **small incremental sync** (History API) instead of repeated full list/get loops.

## GCP prerequisites

1. Enable **Gmail API** and **Pub/Sub API** on the Google Cloud project that owns your OAuth client.
2. Create a Pub/Sub **topic** (e.g. `aquila-gmail-watch`).
3. Grant Gmail push permission to publish:

   ```bash
   gcloud pubsub topics add-iam-policy-binding aquila-gmail-watch \
     --member="serviceAccount:gmail-api-push@system.gserviceaccount.com" \
     --role="roles/pubsub.publisher"
   ```

4. Create a **push subscription** targeting an **HTTPS** endpoint Aquila exposes (public URL, TLS). Google will POST Pub/Sub envelopes to that URL.

## Application components (future)

1. **Start / renew `users.watch`** after OAuth connects (and periodically before `expiration` — typically daily). Store `historyId` from the watch response on the connection or a small side table.
2. **Webhook route** — e.g. `POST /api/v1/webhooks/gmail-pubsub` (or a dedicated service):
   - Verify the request (Google-signed JWT on the push subscription, or a configured secret for development).
   - Decode the Pub/Sub message; extract enough to know the affected user/connection (map `emailAddress` / token identity to `connector_connection`).
3. **Incremental fetch** — call `users.history.list` with `startHistoryId` from the last stored value; apply label/message changes to a cache or enqueue a **single** agent wake with a **tight prompt** (“new message in thread X”) instead of a full inbox triage.
4. **Quota** — History list + occasional get is far cheaper than unbounded agent `gmail_list_messages` + per-message `gmail_get_message` loops.

## Operational notes

- Watch expires; renewal must run on a scheduler (same ARQ worker or API cron).
- **Multi-instance** Aquila: only one process should renew watch per mailbox; use a Redis lock or leader election.
- For self-hosted dev without a public URL, use a tunnel (Tailscale Funnel, ngrok, etc.) or skip push until deployed.

## Implementation checklist (when you build this)

1. Store `last_history_id` (and watch expiry) per Gmail connection; renew `users.watch` on a schedule.
2. `POST` webhook: verify Pub/Sub payload; resolve `user_id` + connection.
3. `users.history.list` from last id → at most one agent run with a **short** user message and
   `AgentRun.turn_profile = "automation"` (enables compact tools + `resolve_max_tool_steps_for_turn` via
   `agent_automation_max_tool_steps` in `agent_runtime_config`).
4. Truncate observability: trace events already include `turn_profile` and `max_tool_steps_effective`.

## References

- [Gmail API: Push notifications](https://developers.google.com/gmail/api/guides/push)
- [Gmail API: History](https://developers.google.com/gmail/api/reference/rest/v1/users.history/list)
