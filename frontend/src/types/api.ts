export type Contact = {
  id: number;
  name: string;
  email: string | null;
  phone: string | null;
  role: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type TriageCategory = "actionable" | "informational" | "noise" | "unknown";
export type TriageSource = "heuristic" | "llm" | "known_contact" | "manual";

export type Email = {
  id: number;
  contact_id: number | null;
  sender_email: string;
  sender_name: string | null;
  subject: string;
  body: string;
  received_at: string;
  created_at: string;
  triage_category?: TriageCategory | null;
  triage_reason?: string | null;
  triage_source?: TriageSource | null;
  triage_at?: string | null;
};

export type Deal = {
  id: number;
  contact_id: number;
  title: string;
  status: string;
  amount: string | null;
  currency: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
};

export type CalendarEvent = {
  id: number;
  deal_id: number | null;
  venue_name: string;
  event_date: string;
  city: string | null;
  status: string;
  notes: string | null;
  created_at: string;
  updated_at: string;
  triage_category?: TriageCategory | null;
  triage_reason?: string | null;
  triage_source?: TriageSource | null;
  triage_at?: string | null;
};

export type UserAISettings = {
  provider_kind: string;
  base_url: string | null;
  embedding_model: string;
  chat_model: string;
  classify_model: string | null;
  ai_disabled: boolean;
  has_api_key: boolean;
  extras: Record<string, unknown> | null;
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
  created_at: string;
  updated_at: string;
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
  steps: AgentStep[];
  pending_proposals: PendingProposal[];
};

export type EmailDraftResponse = {
  draft: string;
  model: string;
};

export type ChatThreadKind = "general" | "entity";
export type ChatEntityType =
  | "contact"
  | "deal"
  | "event"
  | "email"
  | "drive_file"
  | "attachment";
export type ChatMessageRole = "user" | "assistant" | "system" | "event";

export type EntityRef = {
  type: ChatEntityType;
  id: number;
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
 * Inline cards live inside `ChatMessage.attachments`. Each card is rendered specially
 * by the chat view (approval / undo / connector setup / oauth).
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
      card_kind: "undo";
      action_id: number;
      kind: string;
      summary: string | null;
      status: string;
      reversible_until: string | null;
      result: Record<string, unknown> | null;
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
      card_kind: "rule_learned";
      automation_id: number;
      title: string;
      instruction_natural_language: string;
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
  created_at: string;
};

export type ChatMessageCreate = {
  content: string;
  references?: EntityRef[];
  attachment_ids?: number[];
};

export type ChatSendResult = {
  thread: ChatThread;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  error: string | null;
};

export type AttachmentMeta = {
  id: number;
  filename: string;
  mime_type: string;
  size_bytes: number;
  thread_id: number | null;
  created_at: string;
  embedded: boolean;
  has_text: boolean;
};
