"use client";

import { useEffect, useMemo, useState } from "react";

import { ProviderForm } from "@/components/features/ai-settings/provider-form";
import { ProviderList } from "@/components/features/ai-settings/provider-list";
import type { UseProviderConfigsApi } from "@/components/features/ai-settings/use-provider-configs";
import { StatusToast } from "@/components/ui/status-toast";
import { listIanaTimeZones } from "@/lib/timezones";
import { useTranslation } from "@/lib/i18n";
import type { TimeFormatPreference } from "@/types/api";

export function AIModelsPanel({ api }: { api: UseProviderConfigsApi }) {
  const { t } = useTranslation();
  const [aiToggleSaving, setAiToggleSaving] = useState(false);
  const [tzDraft, setTzDraft] = useState("");
  const tzOptions = useMemo(() => listIanaTimeZones(), []);

  useEffect(() => {
    setTzDraft(api.userTimezone);
  }, [api.userTimezone]);

  return (
    <>
      <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
        <label className="inline-flex items-center gap-2 text-sm text-fg">
          <input
            type="checkbox"
            checked={api.aiDisabled}
            disabled={aiToggleSaving}
            onChange={async (e) => {
              setAiToggleSaving(true);
              try {
                await api.setAIDisabled(e.target.checked);
              } finally {
                setAiToggleSaving(false);
              }
            }}
          />
          {t("settings.technical.disableAiTemp")}
        </label>
        <label className="flex flex-col gap-1 text-sm text-fg">
          <span className="text-fg-muted">{t("settings.technical.harnessLabel")}</span>
          <select
            className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
            value={api.harnessMode}
            onChange={async (e) => {
              const v = e.target.value as "auto" | "native" | "prompted";
              await api.setHarnessMode(v);
            }}
          >
            <option value="auto">{t("settings.technical.harness.auto")}</option>
            <option value="native">{t("settings.technical.harness.native")}</option>
            <option value="prompted">{t("settings.technical.harness.prompted")}</option>
          </select>
          <span className="text-xs text-fg-subtle">{t("settings.technical.harnessHint")}</span>
        </label>
        <div className="flex min-w-[16rem] flex-col gap-1 text-sm text-fg">
          <span className="text-fg-muted">{t("settings.technical.timezoneLabel")}</span>
          <input
            className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
            list="iana-timezones"
            value={tzDraft}
            onChange={(e) => setTzDraft(e.target.value)}
            onBlur={() => {
              const value = tzDraft.trim();
              if (value !== (api.userTimezone || "").trim()) {
                void api.setUserTimezone(value || null);
              }
            }}
            placeholder="Europe/Madrid"
            autoComplete="off"
          />
          <datalist id="iana-timezones">
            {tzOptions.map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="rounded-md border border-border bg-surface-muted px-2 py-1 text-xs text-fg hover:bg-surface-base"
              onClick={() => void api.applyBrowserTimeZone()}
            >
              {t("settings.technical.useBrowserTz")}
            </button>
          </div>
          <span className="text-xs text-fg-subtle">{t("settings.technical.timezoneHint")}</span>
        </div>
        <label className="flex min-w-[12rem] flex-col gap-1 text-sm text-fg">
          <span className="text-fg-muted">{t("settings.technical.timeFormatLabel")}</span>
          <select
            className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
            value={api.timeFormat}
            onChange={(e) => {
              const value = e.target.value as TimeFormatPreference;
              void api.setTimeFormat(value);
            }}
          >
            <option value="auto">{t("settings.technical.timeFormat.auto")}</option>
            <option value="24">{t("settings.technical.timeFormat.24")}</option>
            <option value="12">{t("settings.technical.timeFormat.12")}</option>
          </select>
        </label>
      </div>

      {api.loadError ? (
        <p
          role="alert"
          className="mb-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-200"
        >
          {api.loadError}
        </p>
      ) : null}

      {api.loading && api.providers.length === 0 ? (
        <p className="text-sm text-fg-subtle">{t("settings.providersLoading")}</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
          <ProviderList
            providers={api.providers}
            configs={api.configs}
            activeKind={api.activeKind}
            selectedKind={api.selectedKind}
            onSelect={api.selectKind}
            onStartNew={api.startNew}
          />
          <ProviderForm api={api} />
        </div>
      )}

      {api.toast ? (
        <StatusToast
          kind="ok"
          text={api.toast}
          onDismiss={api.dismissToast}
          dismissAriaLabel={t("chat.dismissToast")}
        />
      ) : null}
    </>
  );
}
