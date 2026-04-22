/**
 * Live Gmail message row as returned by the `/gmail/messages?detail=metadata`
 * proxy. There is no local mirror anymore — every field comes from the Gmail
 * REST API at request time. `internal_date` is Gmail's millisecond epoch as a
 * string; the inbox renders relative timestamps from it.
 */
export type GmailMessageRow = {
  id: string;
  thread_id: string;
  snippet: string;
  subject: string;
  sender_name: string | null;
  sender_email: string;
  to: string;
  internal_date: string | null;
  label_ids: string[];
  is_unread: boolean;
};

export type GmailMessagesPage = {
  messages: GmailMessageRow[];
  next_page_token: string | null;
  result_size_estimate?: number | null;
};

/**
 * Full Gmail message payload (`format=full`). Untyped beyond the ids because
 * the inbox detail simply renders headers + a best-effort plain-text body via
 * a shared decoder utility.
 */
export type GmailMessageFull = {
  id: string;
  threadId: string;
  labelIds?: string[];
  snippet?: string;
  internalDate?: string;
  payload?: GmailMessagePart;
};

export type GmailMessagePart = {
  partId?: string;
  mimeType?: string;
  filename?: string;
  headers?: { name: string; value: string }[];
  body?: { size?: number; data?: string; attachmentId?: string };
  parts?: GmailMessagePart[];
};

export type HarnessMode = "auto" | "native" | "prompted";

export type TimeFormatPreference = "auto" | "12" | "24";

export type AgentToolPalette = "full" | "compact";
export type AgentPromptTier = "full" | "minimal" | "none";
export type AgentMemoryPostTurnMode = "heuristic" | "always" | "committee" | "adaptive";

/** Effective agent tunables after merging server env defaults with per-user overrides. */
export type AgentRuntimeConfigResolved = {
  agent_max_runs_per_hour: number;
  agent_max_tool_steps: number;
  agent_async_runs: boolean;
  agent_heartbeat_burst_per_hour: number;
  agent_heartbeat_enabled: boolean;
  agent_heartbeat_minutes: number;
  agent_heartbeat_check_gmail: boolean;
  agent_tool_palette: AgentToolPalette;
  agent_prompt_tier: AgentPromptTier;
  agent_include_harness_facts: boolean;
  agent_connector_gated_tools: boolean;
  agent_prompted_compact_json: boolean;
  agent_history_turns: number;
  agent_thread_compact_after_pairs: number;
  agent_memory_flush_enabled: boolean;
  agent_memory_flush_max_steps: number;
  agent_memory_flush_max_transcript_chars: number;
  agent_memory_post_turn_enabled: boolean;
  agent_memory_post_turn_mode: AgentMemoryPostTurnMode;
  agent_channel_gateway_enabled: boolean;
  agent_email_domain_allowlist: string;
};

/** PATCH payload: set a field to `null` to clear an override and fall back to env default. */
export type AgentRuntimeConfigPartial = {
  agent_max_runs_per_hour?: number | null;
  agent_max_tool_steps?: number | null;
  agent_async_runs?: boolean | null;
  agent_heartbeat_burst_per_hour?: number | null;
  agent_heartbeat_enabled?: boolean | null;
  agent_heartbeat_minutes?: number | null;
  agent_heartbeat_check_gmail?: boolean | null;
  agent_tool_palette?: AgentToolPalette | null;
  agent_prompt_tier?: AgentPromptTier | null;
  agent_include_harness_facts?: boolean | null;
  agent_connector_gated_tools?: boolean | null;
  agent_prompted_compact_json?: boolean | null;
  agent_history_turns?: number | null;
  agent_thread_compact_after_pairs?: number | null;
  agent_memory_flush_enabled?: boolean | null;
  agent_memory_flush_max_steps?: number | null;
  agent_memory_flush_max_transcript_chars?: number | null;
  agent_memory_post_turn_enabled?: boolean | null;
  agent_memory_post_turn_mode?: AgentMemoryPostTurnMode | null;
  agent_channel_gateway_enabled?: boolean | null;
  agent_email_domain_allowlist?: string | null;
};

export type UserAISettings = {
  provider_kind: string;
  base_url: string | null;
  embedding_model: string;
  chat_model: string;
  classify_model: string | null;
  /** When set, agent-memory embeddings use this saved provider row instead of the active chat provider. */
  embedding_provider_kind?: string | null;
  /** When set, auxiliary LLM (classify / ranking) uses this saved row instead of the active provider. */
  ranking_provider_kind?: string | null;
  ai_disabled: boolean;
  has_api_key: boolean;
  extras: Record<string, unknown> | null;
  harness_mode: HarnessMode;
  user_timezone: string | null;
  time_format: TimeFormatPreference;
  agent_processing_paused?: boolean;
  agent_runtime?: AgentRuntimeConfigResolved;
};

export type ProviderFieldType = "text" | "password" | "url" | "select";
export type ProviderAuthKind = "bearer" | "x-api-key" | "api-key-header" | "none";

export type ProviderField = {
  key: string;
  label: string;
  type: ProviderFieldType;
  required: boolean;
  placeholder?: string;
  help?: string;
  secret?: boolean;
  default?: string | null;
  options?: string[] | null;
};

export type AIProvider = {
  id: string;
  label: string;
  description: string;
  auth_kind: ProviderAuthKind;
  fields: ProviderField[];
  default_base_url: string | null;
  default_chat_model: string | null;
  default_embedding_model: string | null;
  default_classify_model: string | null;
  docs_url?: string | null;
  model_list_is_deployments?: boolean;
  chat_openai_compatible?: boolean;
  supports_capability_filter?: boolean;
  suggested_chat_models?: string[] | null;
};

export type ProviderConfigRequest = {
  provider_id: string;
  api_key?: string | null;
  base_url?: string | null;
  extras?: Record<string, unknown> | null;
};

export type TestConnectionResult = {
  ok: boolean;
  message: string;
  code?: string | null;
  detail?: string | null;
};

export type ModelCapability = "chat" | "embedding" | "unknown";

export type ModelInfo = {
  id: string;
  label: string;
  capability: ModelCapability;
};

export type ListModelsResponse = {
  ok: boolean;
  models: ModelInfo[];
  error?: TestConnectionResult | null;
};

/**
 * Sentinel sent in the api_key field of provider test / list-models requests
 * to tell the backend "reuse the key that's already stored for this user".
 */
export const STORED_API_KEY_SENTINEL = "__stored__";

export type ProviderTestStatus = {
  ok: boolean | null;
  at: string | null;
  message: string | null;
};

export type ProviderConfig = {
  provider_kind: string;
  base_url: string | null;
  chat_model: string;
  embedding_model: string;
  classify_model: string | null;
  extras: Record<string, unknown> | null;
  has_api_key: boolean;
  is_active: boolean;
  last_test: ProviderTestStatus;
  created_at: string;
  updated_at: string;
};

export type ProviderConfigsResponse = {
  active_provider_kind: string | null;
  /** When set, agent-memory embeddings use this saved provider row instead of the active chat provider. */
  embedding_provider_kind: string | null;
  /** When set, auxiliary LLM (classify / ranking) uses this saved row instead of the active provider. */
  ranking_provider_kind: string | null;
  ai_disabled: boolean;
  harness_mode: HarnessMode;
  user_timezone: string | null;
  time_format: TimeFormatPreference;
  /** Effective agent behavior settings (env defaults merged with per-user overrides). */
  agent_runtime: AgentRuntimeConfigResolved;
  configs: ProviderConfig[];
};

export type ProviderConfigUpsertRequest = {
  base_url?: string | null;
  chat_model?: string | null;
  embedding_model?: string | null;
  classify_model?: string | null;
  extras?: Record<string, unknown> | null;
  /** Send "" to clear, omit/null to keep, anything else to replace. */
  api_key?: string | null;
};

export type AIHealth = {
  ai_disabled: boolean;
  active_provider_kind: string | null;
  has_api_key: boolean;
  chat_model: string | null;
  last_test: ProviderTestStatus;
  needs_setup: boolean;
  message: string | null;
};

export type SemanticSearchHit = {
  entity_type: string;
  entity_id: number;
  score: number;
  title: string;
  snippet: string;
  citation: string;
  chunk_id?: number | null;
  match_sources?: string[] | null;
  rrf_score?: number | null;
};

export type PendingProposal = {
  id: number;
  kind: string;
  summary: string | null;
  risk_tier?: string | null;
  idempotency_key?: string | null;
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
};

export type PendingOperationPreview = {
  kind: string;
  risk_tier: string;
  summary: string | null;
  preview: Record<string, unknown>;
};

export type ConnectorConnection = {
  id: number;
  provider: string;
  label: string;
  meta: Record<string, unknown> | null;
  token_expires_at?: string | null;
  oauth_scopes?: string[] | null;
  /**
   * Set by the backend whenever the stored OAuth grant is missing scopes the
   * agent now requires (e.g. ``gmail.settings.basic`` after the OpenClaw
   * refactor). The Settings UI shows a "Reconnect Gmail" banner when true.
   */
  needs_reauth?: boolean;
  missing_scopes?: string[] | null;
  created_at: string;
  updated_at: string;
};

export type ConnectorHealthResponse = {
  ok: boolean;
  provider: string;
  account?: string | null;
  error?: string | null;
};

export type AgentStep = {
  step_index: number;
  kind: string;
  name: string | null;
  payload: Record<string, unknown> | null;
};

export type AgentRun = {
  id: number;
  status: string;
  user_message: string;
  assistant_reply: string | null;
  error: string | null;
  /** W3C-style trace id for observability / eval correlation */
  root_trace_id?: string | null;
  chat_thread_id?: number | null;
  attention?: {
    stage: string;
    last_event_at: string | null;
    hint: string | null;
  } | null;
  steps: AgentStep[];
  pending_proposals: PendingProposal[];
};

export type ChatThreadKind = "general" | "entity";
/**
 * After the OpenClaw refactor the backend no longer mirrors CRM/email
 * entities; threads can pin to any opaque external resource (Gmail message id,
 * Calendar event id, Drive file id, etc.) so the type is a free-form string.
 */
export type ChatEntityType = string;
export type ChatMessageRole = "user" | "assistant" | "system" | "event";

export type EntityRef = {
  type: ChatEntityType;
  /** Numeric for legacy DB rows; Gmail/Calendar/Drive use string provider ids. */
  id: number | string;
  label?: string | null;
};

export type ChatThread = {
  id: number;
  kind: ChatThreadKind;
  entity_type: ChatEntityType | null;
  entity_id: number | null;
  title: string;
  pinned: boolean;
  archived: boolean;
  last_message_at: string | null;
  created_at: string;
  updated_at: string;
  unread: number;
};

/**
 * Inline cards live inside `ChatMessage.attachments`. After the OpenClaw
 * refactor only the approval card (for email send/reply gating), connector
 * setup / oauth, and provider/key error cards remain — every other agent
 * write auto-applies and never produces a card.
 */
export type ChatCard =
  | {
      card_kind: "approval";
      proposal_id: number;
      kind: string;
      summary: string | null;
      risk_tier: string;
      preview: Record<string, unknown>;
    }
  | {
      card_kind: "connector_setup";
      provider: string;
      step: string;
      title: string;
      body: string;
      cta?: { label: string; url?: string } | null;
      setup_token?: string | null;
    }
  | {
      card_kind: "oauth_authorize";
      provider: string;
      authorize_url: string;
      label?: string | null;
    }
  | {
      card_kind: "provider_error";
      provider: string;
      provider_label?: string | null;
      status_code?: number | null;
      message: string;
      hint?: string | null;
      detail?: string | null;
      model?: string | null;
      settings_url?: string | null;
      transient?: boolean | null;
    }
  | {
      card_kind: "key_decrypt_error";
      scope: string;
      reason?: string | null;
      message?: string | null;
      settings_url?: string | null;
    }
  | {
      card_kind: string;
      [key: string]: unknown;
    };

export type ChatMessage = {
  id: number;
  thread_id: number;
  role: ChatMessageRole;
  content: string;
  attachments: ChatCard[] | null;
  agent_run_id: number | null;
  client_token?: string | null;
  created_at: string;
};

export type ChatMessageCreate = {
  content: string;
  references?: EntityRef[];
  idempotency_key?: string;
};

export type ChatSendResult = {
  thread: ChatThread;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  error: string | null;
  /** When true, the client waits for the run (HTTP poll + WebSocket) then reloads messages. */
  agent_run_pending?: boolean;
};
