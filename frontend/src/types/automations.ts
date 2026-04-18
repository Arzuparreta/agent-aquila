export type Automation = {
  id: number;
  name: string;
  trigger: string;
  conditions: Record<string, unknown>;
  prompt_template: string;
  instruction_natural_language: string | null;
  source: string | null;
  default_connection_id: number | null;
  auto_approve: boolean;
  enabled: boolean;
  last_run_at: string | null;
  run_count: number;
  created_at: string;
  updated_at: string;
};

export type AutomationPatch = {
  name?: string;
  enabled?: boolean;
  auto_approve?: boolean;
  instruction_natural_language?: string;
};
