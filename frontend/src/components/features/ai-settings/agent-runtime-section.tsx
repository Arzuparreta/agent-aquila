"use client";

import { useTranslation } from "@/lib/i18n";
import type {
  AgentMemoryPostTurnMode,
  AgentPromptTier,
  AgentRuntimeConfigPartial,
  AgentRuntimeConfigResolved,
  AgentToolPalette
} from "@/types/api";

type Props = {
  agentRuntime: AgentRuntimeConfigResolved | null;
  formKey: number;
  saving: boolean;
  error: string | null;
  patchAgentRuntime: (patch: AgentRuntimeConfigPartial) => Promise<void>;
  resetAllAgentRuntimeOverrides: () => Promise<void>;
};

function NumField(props: {
  fieldKey: string;
  formKey: number;
  label: string;
  min: number;
  max: number;
  value: number;
  disabled: boolean;
  onCommit: (n: number) => void;
}) {
  const { fieldKey, formKey, label, min, max, value, disabled, onCommit } = props;
  return (
    <label className="flex min-w-[10rem] flex-col gap-1 text-sm text-fg">
      <span className="text-fg-muted">{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg disabled:opacity-50"
        defaultValue={value}
        disabled={disabled}
        key={`${fieldKey}-${formKey}-${value}`}
        onBlur={(e) => {
          const n = parseInt(e.target.value, 10);
          if (!Number.isFinite(n)) return;
          const clamped = Math.min(max, Math.max(min, n));
          if (clamped !== value) void onCommit(clamped);
        }}
      />
    </label>
  );
}

export function AgentRuntimeSection({
  agentRuntime,
  formKey,
  saving,
  error,
  patchAgentRuntime,
  resetAllAgentRuntimeOverrides
}: Props) {
  const { t } = useTranslation();

  if (!agentRuntime) {
    return <p className="text-xs text-fg-subtle">{t("common.loading")}</p>;
  }

  const onResetAll = () => {
    if (typeof window !== "undefined" && !window.confirm(t("settings.agentRuntime.resetConfirm"))) {
      return;
    }
    void resetAllAgentRuntimeOverrides();
  };

  return (
    <div className="grid gap-6" key={formKey}>
      {error ? (
        <div
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-200"
        >
          {error}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className="rounded-md border border-border bg-surface-muted px-3 py-1.5 text-sm text-fg hover:bg-surface-base disabled:opacity-50"
          disabled={saving}
          onClick={onResetAll}
        >
          {t("settings.agentRuntime.resetAll")}
        </button>
        {saving ? <span className="text-xs text-fg-subtle">{t("common.saving")}</span> : null}
      </div>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionRateLimits")}</h3>
        <div className="flex flex-wrap gap-4">
          <NumField
            fieldKey="max_runs"
            formKey={formKey}
            label={t("settings.agentRuntime.maxRunsPerHour")}
            min={1}
            max={10000}
            value={agentRuntime.agent_max_runs_per_hour}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_max_runs_per_hour: n })}
          />
          <NumField
            fieldKey="max_steps"
            formKey={formKey}
            label={t("settings.agentRuntime.maxToolSteps")}
            min={1}
            max={100}
            value={agentRuntime.agent_max_tool_steps}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_max_tool_steps: n })}
          />
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_async_runs}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_async_runs: e.target.checked })}
            />
            {t("settings.agentRuntime.asyncRuns")}
          </label>
        </div>
      </section>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionHeartbeat")}</h3>
        <p className="text-xs text-fg-subtle">{t("settings.agentRuntime.heartbeatScheduleHint")}</p>
        <div className="flex flex-wrap gap-4">
          <NumField
            fieldKey="hb_burst"
            formKey={formKey}
            label={t("settings.agentRuntime.heartbeatBurstPerHour")}
            min={0}
            max={10000}
            value={agentRuntime.agent_heartbeat_burst_per_hour}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_heartbeat_burst_per_hour: n })}
          />
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_heartbeat_enabled}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_heartbeat_enabled: e.target.checked })}
            />
            {t("settings.agentRuntime.heartbeatEnabled")}
          </label>
          <NumField
            fieldKey="hb_minutes"
            formKey={formKey}
            label={t("settings.agentRuntime.heartbeatMinutes")}
            min={1}
            max={1440}
            value={agentRuntime.agent_heartbeat_minutes}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_heartbeat_minutes: n })}
          />
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_heartbeat_check_gmail}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_heartbeat_check_gmail: e.target.checked })}
            />
            {t("settings.agentRuntime.heartbeatCheckGmail")}
          </label>
        </div>
      </section>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionPromptTools")}</h3>
        <div className="flex flex-wrap gap-4">
          <label className="flex min-w-[12rem] flex-col gap-1 text-sm text-fg">
            <span className="text-fg-muted">{t("settings.agentRuntime.toolPalette")}</span>
            <select
              className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
              value={agentRuntime.agent_tool_palette}
              disabled={saving}
              onChange={(e) =>
                void patchAgentRuntime({ agent_tool_palette: e.target.value as AgentToolPalette })
              }
            >
              <option value="full">{t("settings.agentRuntime.paletteFull")}</option>
              <option value="compact">{t("settings.agentRuntime.paletteCompact")}</option>
            </select>
          </label>
          <label className="flex min-w-[12rem] flex-col gap-1 text-sm text-fg">
            <span className="text-fg-muted">{t("settings.agentRuntime.promptTier")}</span>
            <select
              className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
              value={agentRuntime.agent_prompt_tier}
              disabled={saving}
              onChange={(e) =>
                void patchAgentRuntime({ agent_prompt_tier: e.target.value as AgentPromptTier })
              }
            >
              <option value="full">{t("settings.agentRuntime.tierFull")}</option>
              <option value="minimal">{t("settings.agentRuntime.tierMinimal")}</option>
              <option value="none">{t("settings.agentRuntime.tierNone")}</option>
            </select>
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_include_harness_facts}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_include_harness_facts: e.target.checked })}
            />
            {t("settings.agentRuntime.includeHarnessFacts")}
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_connector_gated_tools}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_connector_gated_tools: e.target.checked })}
            />
            {t("settings.agentRuntime.connectorGatedTools")}
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_prompted_compact_json}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_prompted_compact_json: e.target.checked })}
            />
            {t("settings.agentRuntime.promptedCompactJson")}
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_tool_choice_required}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_tool_choice_required: e.target.checked })}
            />
            {t("settings.agentRuntime.toolChoiceRequired")}
          </label>
        </div>
      </section>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionHarness")}</h3>
        <p className="text-xs text-fg-subtle">{t("settings.agentRuntime.harnessHint")}</p>
        <div className="flex flex-wrap gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_non_chat_uses_compact_palette}
              disabled={saving}
              onChange={(e) =>
                void patchAgentRuntime({ agent_non_chat_uses_compact_palette: e.target.checked })
              }
            />
            {t("settings.agentRuntime.nonChatCompactPalette")}
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_inject_user_context_in_chat}
              disabled={saving}
              onChange={(e) =>
                void patchAgentRuntime({ agent_inject_user_context_in_chat: e.target.checked })
              }
            />
            {t("settings.agentRuntime.injectContextInChat")}
          </label>
        </div>
      </section>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionHistory")}</h3>
        <div className="flex flex-wrap gap-4">
          <NumField
            fieldKey="hist_turns"
            formKey={formKey}
            label={t("settings.agentRuntime.historyTurns")}
            min={1}
            max={64}
            value={agentRuntime.agent_history_turns}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_history_turns: n })}
          />
          <NumField
            fieldKey="compact_pairs"
            formKey={formKey}
            label={t("settings.agentRuntime.threadCompactAfterPairs")}
            min={0}
            max={500}
            value={agentRuntime.agent_thread_compact_after_pairs}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_thread_compact_after_pairs: n })}
          />
        </div>
      </section>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionMemoryFlush")}</h3>
        <div className="flex flex-wrap gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_memory_flush_enabled}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_memory_flush_enabled: e.target.checked })}
            />
            {t("settings.agentRuntime.memoryFlushEnabled")}
          </label>
          <NumField
            fieldKey="flush_steps"
            formKey={formKey}
            label={t("settings.agentRuntime.memoryFlushMaxSteps")}
            min={1}
            max={50}
            value={agentRuntime.agent_memory_flush_max_steps}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_memory_flush_max_steps: n })}
          />
          <NumField
            fieldKey="flush_chars"
            formKey={formKey}
            label={t("settings.agentRuntime.memoryFlushMaxTranscriptChars")}
            min={1000}
            max={500000}
            value={agentRuntime.agent_memory_flush_max_transcript_chars}
            disabled={saving}
            onCommit={(n) => void patchAgentRuntime({ agent_memory_flush_max_transcript_chars: n })}
          />
        </div>
      </section>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionPostTurn")}</h3>
        <div className="flex flex-wrap gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_memory_post_turn_enabled}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_memory_post_turn_enabled: e.target.checked })}
            />
            {t("settings.agentRuntime.postTurnEnabled")}
          </label>
          <label className="flex min-w-[12rem] flex-col gap-1 text-sm text-fg">
            <span className="text-fg-muted">{t("settings.agentRuntime.postTurnMode")}</span>
            <select
              className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
              value={agentRuntime.agent_memory_post_turn_mode}
              disabled={saving}
              onChange={(e) =>
                void patchAgentRuntime({
                  agent_memory_post_turn_mode: e.target.value as AgentMemoryPostTurnMode
                })
              }
            >
              <option value="heuristic">{t("settings.agentRuntime.postTurnHeuristic")}</option>
              <option value="always">{t("settings.agentRuntime.postTurnAlways")}</option>
              <option value="committee">{t("settings.agentRuntime.postTurnCommittee")}</option>
              <option value="adaptive">{t("settings.agentRuntime.postTurnAdaptive")}</option>
            </select>
          </label>
        </div>
      </section>

      <section className="grid gap-3 border-t border-border-subtle pt-4">
        <h3 className="text-sm font-medium text-fg">{t("settings.agentRuntime.sectionChannelsEmail")}</h3>
        <div className="flex flex-wrap gap-4">
          <label className="inline-flex items-center gap-2 text-sm text-fg">
            <input
              type="checkbox"
              checked={agentRuntime.agent_channel_gateway_enabled}
              disabled={saving}
              onChange={(e) => void patchAgentRuntime({ agent_channel_gateway_enabled: e.target.checked })}
            />
            {t("settings.agentRuntime.channelGatewayEnabled")}
          </label>
          <label className="flex min-w-[18rem] max-w-full flex-1 flex-col gap-1 text-sm text-fg">
            <span className="text-fg-muted">{t("settings.agentRuntime.emailDomainAllowlist")}</span>
            <textarea
              className="min-h-[4rem] rounded-md border border-border bg-surface-base px-2 py-1.5 font-mono text-base text-fg md:text-xs"
              defaultValue={agentRuntime.agent_email_domain_allowlist}
              disabled={saving}
              key={`allow-${formKey}`}
              onBlur={(e) => {
                const next = e.target.value.trim();
                if (next !== (agentRuntime.agent_email_domain_allowlist || "").trim()) {
                  void patchAgentRuntime({ agent_email_domain_allowlist: next });
                }
              }}
              placeholder={t("settings.agentRuntime.emailAllowlistPlaceholder")}
            />
            <span className="text-xs text-fg-subtle">{t("settings.agentRuntime.emailAllowlistHint")}</span>
          </label>
        </div>
      </section>
    </div>
  );
}
