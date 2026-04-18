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
