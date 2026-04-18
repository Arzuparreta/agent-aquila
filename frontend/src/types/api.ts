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

export type Email = {
  id: number;
  contact_id: number | null;
  sender_email: string;
  sender_name: string | null;
  subject: string;
  body: string;
  received_at: string;
  created_at: string;
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
  status: string;
  payload: Record<string, unknown>;
  created_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
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
