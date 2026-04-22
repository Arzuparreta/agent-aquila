from __future__ import annotations

from typing import Self
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """DATABASE_URL, when non-empty, is used as-is. Otherwise the URL is built from POSTGRES_* with proper encoding
    (so passwords containing @, :, #, etc. work). Docker Compose clears DATABASE_URL and sets POSTGRES_HOST=db.
    """

    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    postgres_user: str = Field(default="aquila_user", validation_alias="POSTGRES_USER")
    postgres_password: str = Field(default="aquila_password", validation_alias="POSTGRES_PASSWORD")
    postgres_db: str = Field(default="aquila_db", validation_alias="POSTGRES_DB")
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    # POST /auth/register — disable after your account exists on a private instance.
    registration_open: bool = Field(default=True, validation_alias="REGISTRATION_OPEN")
    # Comma-separated lowercase domains (no @). Empty = any domain when registration_open is true.
    registration_email_domain_allowlist: str = Field(
        default="", validation_alias="REGISTRATION_EMAIL_DOMAIN_ALLOWLIST"
    )
    # 0 = unlimited. Set to 1 for single-tenant (only the first account may register).
    registration_max_users: int = Field(default=0, ge=0, le=1_000_000, validation_alias="REGISTRATION_MAX_USERS")
    cors_origins: str = "http://localhost:3000,http://localhost:3002,http://127.0.0.1:3002"
    # Fernet key (urlsafe base64, 32 bytes). If unset, a deterministic key is derived from jwt_secret (dev only).
    fernet_encryption_key: str | None = None
    embedding_dimensions: int = 1536
    # Comma-separated email domains allowed for agent-approved outbound mail (empty = allow all).
    agent_email_domain_allowlist: str = Field(default="", validation_alias="AGENT_EMAIL_DOMAIN_ALLOWLIST")
    agent_max_runs_per_hour: int = Field(default=60, ge=1, le=10_000, validation_alias="AGENT_MAX_RUNS_PER_HOUR")
    agent_max_tool_steps: int = Field(default=10, ge=1, le=100, validation_alias="AGENT_MAX_TOOL_STEPS")
    # When true and REDIS_URL is set, chat agent turns are enqueued to ARQ so the HTTP
    # request returns immediately. Do not run the agent in the request handler: it trips
    # Next.js / reverse-proxy limits and spurious 5xx. If the queue is unavailable, the
    # API returns a clear system message instead of blocking or hanging.
    agent_async_runs: bool = Field(default=True, validation_alias="AGENT_ASYNC_RUNS")
    # Hard cap on proactive agent heartbeat runs per user/hour. 0 disables the cap.
    agent_heartbeat_burst_per_hour: int = Field(
        default=20, ge=0, le=10_000, validation_alias="AGENT_HEARTBEAT_BURST_PER_HOUR"
    )

    # Redis (used for OAuth state and the ARQ heartbeat worker). If unset, a local in-memory
    # fallback is used for OAuth state only (single-process dev); the heartbeat worker will
    # refuse to start without it.
    redis_url: str = Field(default="", validation_alias="REDIS_URL")

    # Google OAuth (https://console.cloud.google.com → OAuth 2.0 Client IDs → "Web application").
    # Redirect URI registered in Google must be `${google_oauth_redirect_base}/api/v1/oauth/google/callback`.
    google_oauth_client_id: str = Field(default="", validation_alias="GOOGLE_OAUTH_CLIENT_ID")
    google_oauth_client_secret: str = Field(default="", validation_alias="GOOGLE_OAUTH_CLIENT_SECRET")
    google_oauth_redirect_base: str = Field(
        default="http://localhost:8000", validation_alias="GOOGLE_OAUTH_REDIRECT_BASE"
    )
    # Where to send the browser after a successful callback (usually the Next.js app).
    oauth_post_auth_redirect: str = Field(
        default="http://localhost:3002/settings", validation_alias="OAUTH_POST_AUTH_REDIRECT"
    )

    # Microsoft Graph OAuth (Azure AD app registration). Optional; enables Phase 5.
    microsoft_oauth_client_id: str = Field(default="", validation_alias="MICROSOFT_OAUTH_CLIENT_ID")
    microsoft_oauth_client_secret: str = Field(default="", validation_alias="MICROSOFT_OAUTH_CLIENT_SECRET")
    microsoft_oauth_tenant: str = Field(default="common", validation_alias="MICROSOFT_OAUTH_TENANT")

    # ------------------------------------------------------------------
    # OpenClaw-style agent infrastructure
    # ------------------------------------------------------------------
    # Optional override for the agent skills folder. Defaults to
    # ``backend/skills/`` shipped with the app; override it to mount
    # a custom skill set from a docker volume without rebuilding.
    skills_dir: str = Field(default="", validation_alias="AQUILA_SKILLS_DIR")
    # OpenClaw-style workspace (SOUL.md, AGENTS.md). Default: ``backend/agent_workspace``.
    workspace_dir: str = Field(default="", validation_alias="AQUILA_WORKSPACE_DIR")
    # Heartbeat: when true, the worker runs ``agent_heartbeat`` every
    # ``agent_heartbeat_minutes`` minutes (defaults to off so freshly
    # cloned dev setups never spawn surprise LLM calls).
    agent_heartbeat_enabled: bool = Field(
        default=False, validation_alias="AGENT_HEARTBEAT_ENABLED"
    )
    agent_heartbeat_minutes: int = Field(
        default=15, ge=1, le=1440, validation_alias="AGENT_HEARTBEAT_MINUTES"
    )
    # When false (default), heartbeat does not instruct the model to scan Gmail —
    # avoids surprise Gmail API volume. Set true only if you want proactive inbox checks.
    agent_heartbeat_check_gmail: bool = Field(
        default=False, validation_alias="AGENT_HEARTBEAT_CHECK_GMAIL"
    )
    # Mark runs as needs_attention when they stop emitting progress.
    agent_run_attention_enabled: bool = Field(
        default=True, validation_alias="AGENT_RUN_ATTENTION_ENABLED"
    )
    # For queued/pending runs before first stage starts.
    agent_run_attention_pending_seconds: int = Field(
        default=300, ge=30, le=86_400, validation_alias="AGENT_RUN_ATTENTION_PENDING_SECONDS"
    )
    # For llm/tool stages that stop progressing.
    agent_run_attention_stage_seconds: int = Field(
        default=600, ge=30, le=86_400, validation_alias="AGENT_RUN_ATTENTION_STAGE_SECONDS"
    )
    # Global fallback when stage is unknown but run is stale.
    agent_run_attention_silence_seconds: int = Field(
        default=240, ge=30, le=86_400, validation_alias="AGENT_RUN_ATTENTION_SILENCE_SECONDS"
    )
    # full = all connector tools; compact = smaller palette (see agent_tools.tools_for_palette_mode).
    agent_tool_palette: str = Field(default="full", validation_alias="AGENT_TOOL_PALETTE")
    # System prompt size: full (default) | minimal (shorter tool docs) | none (identity + rules + tools only).
    agent_prompt_tier: str = Field(default="full", validation_alias="AGENT_PROMPT_TIER")
    # When true, inject a short "harness facts" markdown block (limits, connector list).
    agent_include_harness_facts: bool = Field(default=True, validation_alias="AGENT_INCLUDE_HARNESS_FACTS")
    # Omit tool schemas for providers the user has not connected (reduces confusion + tokens).
    agent_connector_gated_tools: bool = Field(default=False, validation_alias="AGENT_CONNECTOR_GATED_TOOLS")
    # In prompted harness mode, use shorter JSON (tighter descriptions, no indent) for tool embed.
    agent_prompted_compact_json: bool = Field(default=True, validation_alias="AGENT_PROMPTED_COMPACT_JSON")
    # Prior chat turns sent to the agent (default 8). Lower = fewer tokens.
    agent_history_turns: int = Field(default=8, ge=1, le=64, validation_alias="AGENT_HISTORY_TURNS")
    # When > 0 and thread history exceeds this many user+assistant pairs, older turns are dropped from context.
    agent_thread_compact_after_pairs: int = Field(
        default=0, ge=0, le=500, validation_alias="AGENT_THREAD_COMPACT_AFTER_PAIRS"
    )
    # OpenClaw-style: run a memory-only agent turn with the dropped transcript before trimming history.
    agent_memory_flush_enabled: bool = Field(default=True, validation_alias="AGENT_MEMORY_FLUSH_ENABLED")
    agent_memory_flush_max_steps: int = Field(
        default=8, ge=1, le=50, validation_alias="AGENT_MEMORY_FLUSH_MAX_STEPS"
    )
    agent_memory_flush_max_transcript_chars: int = Field(
        default=16000, ge=1000, le=500_000, validation_alias="AGENT_MEMORY_FLUSH_MAX_TRANSCRIPT_CHARS"
    )
    # After a completed agent reply, optionally extract durable facts from the last exchange (JSON LLM call).
    agent_memory_post_turn_enabled: bool = Field(
        default=True, validation_alias="AGENT_MEMORY_POST_TURN_ENABLED"
    )
    # heuristic = only when name/remember/preference signals match; always = every completed turn (higher cost).
    agent_memory_post_turn_mode: str = Field(
        default="heuristic", validation_alias="AGENT_MEMORY_POST_TURN_MODE"
    )
    # Telegram bot (optional). Webhook path uses secret; leave empty to disable routes.
    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(default="", validation_alias="TELEGRAM_WEBHOOK_SECRET")
    # When true, HTTP channel stub and binding helpers are enabled (gateway integration).
    agent_channel_gateway_enabled: bool = Field(
        default=False, validation_alias="AGENT_CHANNEL_GATEWAY_ENABLED"
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def resolve_database_url(self) -> Self:
        raw = (self.database_url or "").strip()
        if raw:
            self.database_url = raw
            return self
        user = quote_plus(self.postgres_user)
        password = quote_plus(self.postgres_password)
        self.database_url = (
            f"postgresql+asyncpg://{user}:{password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )
        return self


settings = Settings()
