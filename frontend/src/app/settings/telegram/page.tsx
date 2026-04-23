"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { Button } from "@/components/ui/button";
import { apiFetch, ApiError } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";

type TelegramIntegration = {
  configured: boolean;
  polling_enabled: boolean;
  poll_timeout: number;
  webhook_secret_configured: boolean;
  webhook_secret: string | null;
};

export default function TelegramSettingsPage() {
  const { t } = useTranslation();
  const [data, setData] = useState<TelegramIntegration | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [tokenInput, setTokenInput] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const row = await apiFetch<TelegramIntegration>("/telegram/integration");
      setData(row);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("settings.telegram.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const patch: Record<string, unknown> = {
        polling_enabled: data?.polling_enabled ?? true,
        poll_timeout: data?.poll_timeout ?? 45
      };
      const trimmed = tokenInput.trim();
      if (trimmed) {
        patch.bot_token = trimmed;
      }
      const row = await apiFetch<TelegramIntegration>("/telegram/integration", {
        method: "PATCH",
        body: JSON.stringify(patch)
      });
      setData(row);
      setTokenInput("");
      if (row.webhook_secret) {
        setInfo(t("settings.telegram.webhookSecretReveal"));
      } else {
        setInfo(t("settings.telegram.saved"));
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("settings.telegram.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const patchFlags = async (partial: Partial<TelegramIntegration>) => {
    if (!data) return;
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const row = await apiFetch<TelegramIntegration>("/telegram/integration", {
        method: "PATCH",
        body: JSON.stringify(partial)
      });
      setData(row);
      setInfo(t("settings.telegram.saved"));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("settings.telegram.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const regenerateSecret = async () => {
    setSaving(true);
    setError(null);
    setInfo(null);
    try {
      const row = await apiFetch<TelegramIntegration>("/telegram/integration", {
        method: "PATCH",
        body: JSON.stringify({ regenerate_webhook_secret: true })
      });
      setData(row);
      if (row.webhook_secret) {
        setInfo(t("settings.telegram.webhookSecretReveal"));
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : t("settings.telegram.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.telegram.title")}
        intro={t("settings.telegram.intro")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("settings.telegram.cardTitle")} intro={t("settings.telegram.cardIntro")}>
          {loading ? <p className="text-sm text-fg-muted">{t("common.loading")}</p> : null}
          {error ? <p className="text-sm text-rose-300">{error}</p> : null}
          {info ? <p className="text-sm text-emerald-200/90">{info}</p> : null}

          {data ? (
            <div className="space-y-6">
              <form onSubmit={(e) => void save(e)} className="space-y-3">
                <label className="block text-sm font-medium text-fg">{t("settings.telegram.botToken")}</label>
                <input
                  type="password"
                  autoComplete="off"
                  value={tokenInput}
                  onChange={(e) => setTokenInput(e.target.value)}
                  placeholder={data.configured ? "••••••••" : t("settings.telegram.botTokenPlaceholder")}
                  className="w-full rounded-md border border-border bg-surface-muted px-3 py-2 text-sm text-fg"
                />
                <p className="text-xs text-fg-muted">{t("settings.telegram.botTokenHint")}</p>
                <Button type="submit" disabled={saving || !tokenInput.trim()}>
                  {saving ? t("settings.telegram.saving") : t("settings.telegram.saveToken")}
                </Button>
              </form>

              <div className="space-y-2 border-t border-border-subtle pt-4">
                <label className="flex cursor-pointer items-center gap-2 text-sm text-fg">
                  <input
                    type="checkbox"
                    checked={data.polling_enabled}
                    disabled={saving}
                    onChange={(e) => {
                      const next = e.target.checked;
                      setData({ ...data, polling_enabled: next });
                      void patchFlags({ polling_enabled: next });
                    }}
                  />
                  {t("settings.telegram.pollingEnabled")}
                </label>
                <p className="text-xs text-fg-muted">{t("settings.telegram.pollingHint")}</p>
              </div>

              <div className="space-y-2">
                <label className="block text-sm font-medium text-fg">{t("settings.telegram.pollTimeout")}</label>
                <input
                  type="number"
                  min={0}
                  max={50}
                  value={data.poll_timeout}
                  disabled={saving}
                  onChange={(e) => {
                    const v = Math.max(0, Math.min(50, parseInt(e.target.value, 10) || 0));
                    setData({ ...data, poll_timeout: v });
                  }}
                  onBlur={() => {
                    void patchFlags({ poll_timeout: data.poll_timeout });
                  }}
                  className="w-28 rounded-md border border-border bg-surface-muted px-3 py-2 text-sm text-fg"
                />
                <p className="text-xs text-fg-muted">{t("settings.telegram.pollTimeoutHint")}</p>
              </div>

              <div className="space-y-2 border-t border-border-subtle pt-4">
                <p className="text-sm font-medium text-fg">{t("settings.telegram.webhookTitle")}</p>
                <p className="text-xs text-fg-muted">{t("settings.telegram.webhookHint")}</p>
                <p className="rounded-md bg-surface-muted px-3 py-2 font-mono text-xs text-fg-muted">
                  {t("settings.telegram.webhookPathPrefix")}
                  <span className="text-fg">{data.webhook_secret ? data.webhook_secret : "…"}</span>
                </p>
                {data.webhook_secret ? (
                  <p className="text-xs text-amber-200/90">{t("settings.telegram.webhookCopyOnce")}</p>
                ) : null}
                <Button type="button" disabled={saving} onClick={() => void regenerateSecret()}>
                  {t("settings.telegram.regenerateWebhookSecret")}
                </Button>
              </div>

              <p className="text-xs text-fg-muted">{t("settings.telegram.workerHint")}</p>
            </div>
          ) : null}
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
