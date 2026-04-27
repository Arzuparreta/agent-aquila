# Troubleshooting

Use this page for startup failures, proxy errors, and long-running task stalls.

## Common Failures

| What you see | What to check |
|----------------|---------------|
| `backend` container **Exited (1)** right after `alembic upgrade head` | Run `docker logs <backend-container>` first. |
| Log includes **`StringDataRightTruncationError`**, **`character varying(32)`**, and SQL mentions **`alembic_version`** | PostgreSQL `alembic_version.version_num` was too short for a migration revision string. `backend/alembic/env.py` widens this column before upgrades. If this returns, verify that helper was not removed or bypassed. |
| UI shows **500** and mentions Next.js proxy / **`BACKEND_INTERNAL_URL`** | Usually the API never started. Check backend logs before frontend logs. |
| Dashboard/chat returns **500** while API appears up | Usually pending DB migrations after `git pull`. Run `cd backend && alembic upgrade head` (Compose: `docker compose up --build backend`). |
| API returns **503** with `schema_out_of_date` | Run Alembic migrations, then restart backend. |
| Startup fails because `user_ai_settings.agent_processing_paused` is missing | Apply latest migrations. Dev-only bypass: `AQUILA_SKIP_SCHEMA_PROBE=1`. |
| Chat stalls on `...`, or bulk Gmail jobs never finish | Confirm `worker` is running (`arq app.worker.WorkerSettings`), `REDIS_URL` is set, and `AGENT_ASYNC_RUNS` is enabled. |
| **Step budget exceeded** | Increase `AGENT_MAX_TOOL_STEPS` in `.env` or reduce tool rounds. For inbox wipes, prefer `gmail_trash_bulk_query` for one-shot runs. |
| OAuth redirect points to `localhost` when accessing from a different URL (e.g., Tailscale Funnel) | The OAuth redirect URI is now captured dynamically from the request URL. If you still see this, ensure all possible base URLs are registered in your Google Cloud Console OAuth app settings. See the note below. |

## OAuth Redirect URI Configuration

When setting up Google OAuth, you must register **all possible redirect URIs** in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials):

1. Go to APIs & Services → Credentials → Your OAuth 2.0 Client ID
2. Add **Authorized Redirect URIs** for each access method:
   - `http://localhost:8000/api/v1/oauth/google/callback` (local development)
   - `https://your-tailnet.tailscale.net/api/v1/oauth/google/callback` (Tailscale Funnel)
   - Any other URL you use to access the app

The application now dynamically captures the request's base URL when starting the OAuth flow, so the redirect after authentication will match the URL you used to access the app. However, Google's OAuth policy requires exact URI matching, so all possible URLs must be pre-registered.

**Note:** Microsoft OAuth has the same requirement—register all possible redirect URIs in your Azure AD app registration.

## Helpful Search Terms

- `StringDataRightTruncation`
- `alembic_version`
- `_widen_alembic_version_num`

Regression test reference: `backend/tests/test_alembic_version_column.py`.
