"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import type { ConnectorConnection, ConnectorHealthResponse } from "@/types/api";

type ProviderExample = { id: string; labelKey: TranslationKey };

const PROVIDER_EXAMPLES: ProviderExample[] = [
  { id: "mock_email", labelKey: "connectors.provider.mock_email" },
  { id: "mock_calendar", labelKey: "connectors.provider.mock_calendar" },
  { id: "mock_files", labelKey: "connectors.provider.mock_files" },
  { id: "mock_teams", labelKey: "connectors.provider.mock_teams" },
  { id: "smtp", labelKey: "connectors.provider.smtp" },
  { id: "graph_mail", labelKey: "connectors.provider.graph_mail" },
  { id: "google_gmail", labelKey: "connectors.provider.google_gmail" },
  { id: "graph_calendar", labelKey: "connectors.provider.graph_calendar" },
  { id: "google_calendar", labelKey: "connectors.provider.google_calendar" },
  { id: "graph_onedrive", labelKey: "connectors.provider.graph_onedrive" },
  { id: "google_drive", labelKey: "connectors.provider.google_drive" },
  { id: "graph_teams", labelKey: "connectors.provider.graph_teams" }
];

type OAuthCredentialSource = "database" | "environment" | "none";

type GoogleAppCredentials = {
  client_id: string;
  redirect_base: string;
  redirect_uri: string;
  configured: boolean;
  has_saved_secret: boolean;
  client_id_source: OAuthCredentialSource;
  client_secret_source: OAuthCredentialSource;
};

type MicrosoftAppCredentials = {
  client_id: string;
  tenant: string;
  redirect_base: string;
  redirect_uri: string;
  configured: boolean;
  has_saved_secret: boolean;
  client_id_source: OAuthCredentialSource;
  client_secret_source: OAuthCredentialSource;
  tenant_source: OAuthCredentialSource;
};

type OAuthStart = {
  authorize_url: string;
  state: string;
  scopes: string[];
  configured: boolean;
};

type SyncStatus = {
  connection_id: number;
  resource: string;
  status: string;
  last_full_sync_at: string | null;
  last_delta_at: string | null;
  error_count: number;
  last_error: string | null;
  cursor: string | null;
};

function credentialSourceKey(s: OAuthCredentialSource): TranslationKey {
  if (s === "database") return "connectors.credentialSource.database";
  if (s === "environment") return "connectors.credentialSource.environment";
  return "connectors.credentialSource.none";
}

function normalizedOriginFromPublicUrl(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  try {
    const u = new URL(trimmed.includes("://") ? trimmed : `https://${trimmed}`);
    return u.origin;
  } catch {
    return null;
  }
}

/**
 * Render a translation that contains lightweight inline markup. We support a
 * small allow-list (<strong>, <code>, <mono>) so translators can keep the
 * surrounding sentence intact in their language without juggling JSX.
 */
function RichText({ text }: { text: string }) {
  const parts = text.split(/(<strong>.*?<\/strong>|<code>.*?<\/code>|<mono>.*?<\/mono>)/g);
  return (
    <>
      {parts.map((part, idx) => {
        if (part.startsWith("<strong>")) {
          return (
            <span key={idx} className="font-medium">
              {part.replace(/<\/?strong>/g, "")}
            </span>
          );
        }
        if (part.startsWith("<code>") || part.startsWith("<mono>")) {
          return (
            <span key={idx} className="font-mono">
              {part.replace(/<\/?(code|mono)>/g, "")}
            </span>
          );
        }
        return <span key={idx}>{part}</span>;
      })}
    </>
  );
}

export function ConnectorsSection() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ConnectorConnection[]>([]);
  const [syncRows, setSyncRows] = useState<Record<number, SyncStatus[]>>({});
  const [provider, setProvider] = useState("mock_email");
  const [label, setLabel] = useState("");
  const [credentialsJson, setCredentialsJson] = useState('{\n  "access_token": ""\n}');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [oauthPublicBase, setOauthPublicBase] = useState("");
  const [googleApp, setGoogleApp] = useState<GoogleAppCredentials | null>(null);
  const [googleFormClientId, setGoogleFormClientId] = useState("");
  const [googleFormSecret, setGoogleFormSecret] = useState("");
  const [googleSetupSaving, setGoogleSetupSaving] = useState(false);
  const [msApp, setMsApp] = useState<MicrosoftAppCredentials | null>(null);
  const [msFormClientId, setMsFormClientId] = useState("");
  const [msFormTenant, setMsFormTenant] = useState("common");
  const [msFormSecret, setMsFormSecret] = useState("");
  const [msSetupSaving, setMsSetupSaving] = useState(false);
  const [verifyHint, setVerifyHint] = useState<
    Record<number, { variant: "ok" | "err"; text: string }>
  >({});
  const [verifyLoadingId, setVerifyLoadingId] = useState<number | null>(null);

  const load = useCallback(async () => {
    try {
      const list = await apiFetch<ConnectorConnection[]>("/connectors");
      setRows(list);
      setVerifyHint({});
      // Fetch sync state per connection (non-blocking).
      const next: Record<number, SyncStatus[]> = {};
      await Promise.all(
        list.map(async (r) => {
          try {
            const s = await apiFetch<SyncStatus[]>(`/connectors/${r.id}/sync-status`);
            next[r.id] = s;
          } catch {
            next[r.id] = [];
          }
        })
      );
      setSyncRows(next);
    } catch {
      setRows([]);
    }
  }, []);

  const loadOAuthForms = useCallback(async () => {
    const origin = typeof window !== "undefined" ? window.location.origin : "";
    try {
      const [g, m] = await Promise.all([
        apiFetch<GoogleAppCredentials>("/oauth/google/app-credentials"),
        apiFetch<MicrosoftAppCredentials>("/oauth/microsoft/app-credentials")
      ]);
      setGoogleApp(g);
      setGoogleFormClientId(g.client_id);
      setMsApp(m);
      setMsFormClientId(m.client_id);
      setMsFormTenant(m.tenant.trim() ? m.tenant : "common");
      const rb = g.redirect_base.trim() || m.redirect_base.trim() || origin;
      setOauthPublicBase(rb);
    } catch {
      setGoogleApp(null);
      setMsApp(null);
    }
  }, []);

  useEffect(() => {
    void load();
    void loadOAuthForms();
  }, [load, loadOAuthForms]);

  // Absorb OAuth callback query params (`?oauth=success|error&...`) so the user sees feedback.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const status = params.get("oauth");
    if (!status) return;
    if (status === "success") {
      const account = params.get("account") || "";
      const prov = params.get("provider") || "Provider";
      const niceProv = prov === "microsoft" ? "Microsoft" : prov === "google" ? "Google" : prov;
      setInfo(
        account
          ? t("connectors.oauth.successWithAccount", { provider: niceProv, account })
          : t("connectors.oauth.success", { provider: niceProv })
      );
      void load();
      void loadOAuthForms();
    } else if (status === "error") {
      const err = params.get("error") || "unknown";
      const detail = params.get("detail") || "";
      setError(
        detail
          ? t("connectors.oauth.errorWithDetail", { error: err, detail })
          : t("connectors.oauth.error", { error: err })
      );
    }
    const url = new URL(window.location.href);
    ["oauth", "provider", "account", "connection_ids", "scopes", "error", "detail"].forEach((k) =>
      url.searchParams.delete(k)
    );
    window.history.replaceState({}, "", url.toString());
  }, [load, loadOAuthForms, t]);

  const startOAuth = async (vendor: "google" | "microsoft", intent: string) => {
    setError(null);
    setInfo(null);
    try {
      const currentUrl =
        typeof window !== "undefined" ? `${window.location.origin}${window.location.pathname}` : undefined;
      const resp = await apiFetch<OAuthStart>(`/oauth/${vendor}/start`, {
        method: "POST",
        body: JSON.stringify({ intent, redirect_after: currentUrl })
      });
      if (typeof window !== "undefined") {
        window.location.href = resp.authorize_url;
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.errors.startOAuth", { vendor }));
    }
  };
  const connectGoogle = (intent: string) => startOAuth("google", intent);
  const connectMicrosoft = (intent: string) => startOAuth("microsoft", intent);

  const saveGoogleAppSetup = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setInfo(null);
    setGoogleSetupSaving(true);
    try {
      const updated = await apiFetch<GoogleAppCredentials>("/oauth/google/app-credentials", {
        method: "PUT",
        body: JSON.stringify({
          client_id: googleFormClientId.trim(),
          redirect_base: oauthPublicBase.trim(),
          client_secret: googleFormSecret.trim() ? googleFormSecret.trim() : null
        })
      });
      setGoogleApp(updated);
      setGoogleFormSecret("");
      void loadOAuthForms();
      setInfo(updated.configured ? t("connectors.google.savedConfigured") : t("connectors.google.savedNotConfigured"));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.google.savedError"));
    } finally {
      setGoogleSetupSaving(false);
    }
  };

  const saveMicrosoftAppSetup = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setInfo(null);
    setMsSetupSaving(true);
    try {
      const updated = await apiFetch<MicrosoftAppCredentials>("/oauth/microsoft/app-credentials", {
        method: "PUT",
        body: JSON.stringify({
          client_id: msFormClientId.trim(),
          tenant: msFormTenant.trim() || "common",
          redirect_base: oauthPublicBase.trim(),
          client_secret: msFormSecret.trim() ? msFormSecret.trim() : null
        })
      });
      setMsApp(updated);
      setMsFormSecret("");
      void loadOAuthForms();
      setInfo(updated.configured ? t("connectors.ms.savedConfigured") : t("connectors.ms.savedNotConfigured"));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.ms.savedError"));
    } finally {
      setMsSetupSaving(false);
    }
  };

  const triggerSync = async (connectionId: number, resource: string) => {
    setError(null);
    setInfo(null);
    try {
      await apiFetch(`/connectors/${connectionId}/sync/${resource}`, { method: "POST" });
      setInfo(t("connectors.saved.queuedSync", { resource, id: connectionId }));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.errors.queueFailed"));
    }
  };

  const addConnection = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    let credentials: Record<string, unknown>;
    try {
      credentials = JSON.parse(credentialsJson) as Record<string, unknown>;
    } catch {
      setError(t("connectors.errors.invalidJson"));
      return;
    }
    if (!label.trim()) {
      setError(t("connectors.errors.labelRequired"));
      return;
    }
    setLoading(true);
    try {
      await apiFetch<ConnectorConnection>("/connectors", {
        method: "POST",
        body: JSON.stringify({
          provider,
          label: label.trim(),
          credentials
        })
      });
      setLabel("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.errors.saveFailed"));
    } finally {
      setLoading(false);
    }
  };

  const verifyAccess = async (connectionId: number) => {
    setVerifyLoadingId(connectionId);
    setVerifyHint((prev) => {
      const next = { ...prev };
      delete next[connectionId];
      return next;
    });
    try {
      const h = await apiFetch<ConnectorHealthResponse>(`/connectors/${connectionId}/health`);
      if (h.ok) {
        const msg = h.account
          ? t("connectors.saved.verifyOk", { account: h.account })
          : t("connectors.saved.verifyOkNoAccount");
        setVerifyHint((prev) => ({ ...prev, [connectionId]: { variant: "ok", text: msg } }));
      } else {
        setVerifyHint((prev) => ({
          ...prev,
          [connectionId]: {
            variant: "err",
            text: t("connectors.saved.verifyFailed", { error: h.error || "—" })
          }
        }));
      }
    } catch (e) {
      setVerifyHint((prev) => ({
        ...prev,
        [connectionId]: {
          variant: "err",
          text: t("connectors.saved.verifyFailed", {
            error: e instanceof Error ? e.message : String(e)
          })
        }
      }));
    } finally {
      setVerifyLoadingId(null);
    }
  };

  const remove = async (id: number) => {
    setError(null);
    setLoading(true);
    try {
      await apiFetch(`/connectors/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.errors.deleteFailed"));
    } finally {
      setLoading(false);
    }
  };

  const publicBaseTrimmed = oauthPublicBase.replace(/\/$/, "") || t("connectors.oauth.publicUrlFallback");
  const googleRedirect = `${publicBaseTrimmed}/api/v1/oauth/google/callback`;
  const msRedirect = `${publicBaseTrimmed}/api/v1/oauth/microsoft/callback`;
  const browserOrigin = typeof window !== "undefined" ? window.location.origin : "";
  const oauthOriginGuess = normalizedOriginFromPublicUrl(oauthPublicBase);
  const redirectMismatch =
    Boolean(oauthOriginGuess) && Boolean(browserOrigin) && oauthOriginGuess !== browserOrigin;

  return (
    <Card className="mt-8 p-5">
      <h2 className="text-lg font-semibold text-fg">{t("connectors.title")}</h2>
      <p className="mt-1 text-sm text-fg-muted">{t("connectors.intro")}</p>
      {error ? (
        <div className="mt-3">
          <AlertBanner variant="error" message={error} onDismiss={() => setError(null)} />
        </div>
      ) : null}
      {info ? (
        <div className="mt-3">
          <AlertBanner variant="success" message={info} onDismiss={() => setInfo(null)} />
        </div>
      ) : null}

      <div className="mt-4 rounded-md border border-sky-200 bg-sky-50/60 p-4">
        <h3 className="text-sm font-semibold text-fg">{t("connectors.publicUrlTitle")}</h3>
        <p className="mt-1 text-xs text-fg-muted">
          <RichText text={t("connectors.publicUrlIntro")} />
        </p>
        <label className="mt-2 block text-xs font-medium text-fg">
          {t("connectors.publicUrlLabel")}
          <Input
            className="mt-1 font-mono text-xs"
            value={oauthPublicBase}
            onChange={(e) => setOauthPublicBase(e.target.value)}
            placeholder={t("connectors.publicUrlPlaceholder")}
            autoComplete="off"
          />
        </label>
        <p className="mt-2 text-xs text-fg-subtle">{t("connectors.publicUrlHelp")}</p>
        {redirectMismatch ? (
          <div className="mt-3">
            <AlertBanner
              variant="info"
              message={t("connectors.redirectMismatch", {
                publicBase: oauthOriginGuess || oauthPublicBase.trim() || publicBaseTrimmed,
                origin: browserOrigin
              })}
            />
          </div>
        ) : null}
      </div>

      <div className="mt-4 rounded-md border border-border bg-surface-muted p-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-fg">{t("connectors.google.title")}</h3>
          <p className="text-xs text-fg-muted">
            <RichText text={t("connectors.google.intro")} />
          </p>
        </div>

        {googleApp ? (
          <div className="mt-3 rounded-md border border-border-subtle bg-surface-elevated p-3 text-xs">
            <p className="font-medium text-fg">{t("connectors.google.appStatusTitle")}</p>
            <p className="mt-1 text-fg-muted">
              {t("connectors.google.appStatusLine", {
                idSrc: t(credentialSourceKey(googleApp.client_id_source)),
                secretSrc: t(credentialSourceKey(googleApp.client_secret_source))
              })}
            </p>
            <p className="mt-1 text-fg">
              {googleApp.configured
                ? t("connectors.google.configuredReady")
                : t("connectors.google.configuredIncomplete")}
            </p>
          </div>
        ) : null}

        <form
          className="mt-3 grid gap-3 rounded-md border border-border bg-surface-elevated p-3"
          onSubmit={(e) => void saveGoogleAppSetup(e)}
        >
          <p className="text-xs font-medium text-fg">{t("connectors.google.step1")}</p>
          <ol className="list-decimal space-y-1 pl-4 text-xs text-fg-muted">
            <li>
              {t("connectors.google.step1.line1Pre")}
              <a
                className="font-medium text-fg underline underline-offset-2"
                href="https://console.cloud.google.com/apis/credentials"
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("connectors.google.step1.linkLabel")}
              </a>
              <RichText text={t("connectors.google.step1.line1Post")} />
            </li>
            <li>
              <RichText text={t("connectors.google.step1.line2")} />
              <code className="mt-1 block break-all rounded bg-surface-muted px-2 py-1 font-mono text-[11px] text-fg">
                {googleRedirect}
              </code>
            </li>
            <li>
              <RichText text={t("connectors.google.step1.line3")} />
            </li>
          </ol>

          <p className="text-xs font-medium text-fg">{t("connectors.google.step2")}</p>
          <label className="text-xs font-medium text-fg">
            {t("connectors.google.clientId")}
            <Input
              className="mt-1 font-mono text-xs"
              value={googleFormClientId}
              onChange={(e) => setGoogleFormClientId(e.target.value)}
              placeholder={t("connectors.google.clientIdPlaceholder")}
              autoComplete="off"
            />
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.google.clientSecret")}
            <Input
              className="mt-1 font-mono text-xs"
              type="password"
              value={googleFormSecret}
              onChange={(e) => setGoogleFormSecret(e.target.value)}
              placeholder={
                googleApp?.has_saved_secret
                  ? t("connectors.google.secretSavedPlaceholder")
                  : t("connectors.google.secretEmptyPlaceholder")
              }
              autoComplete="off"
            />
          </label>
          <Button
            type="submit"
            className="w-fit border-primary bg-primary text-primary-fg hover:opacity-90"
            disabled={googleSetupSaving}
          >
            {googleSetupSaving ? t("connectors.google.saving") : t("connectors.google.saveLink")}
          </Button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            className="border-primary bg-primary text-primary-fg hover:opacity-90 disabled:opacity-50"
            disabled={!googleApp?.configured}
            title={googleApp?.configured ? undefined : t("connectors.google.tooltipSaveFirst")}
            onClick={() => void connectGoogle("all")}
          >
            {t("connectors.google.connectAll")}
          </Button>
          <Button
            type="button"
            disabled={!googleApp?.configured}
            title={googleApp?.configured ? undefined : t("connectors.google.tooltipCompleteStep2")}
            onClick={() => void connectGoogle("gmail")}
          >
            {t("connectors.google.gmailOnly")}
          </Button>
          <Button
            type="button"
            disabled={!googleApp?.configured}
            title={googleApp?.configured ? undefined : t("connectors.google.tooltipCompleteStep2")}
            onClick={() => void connectGoogle("calendar")}
          >
            {t("connectors.google.calendarOnly")}
          </Button>
          <Button
            type="button"
            disabled={!googleApp?.configured}
            title={googleApp?.configured ? undefined : t("connectors.google.tooltipCompleteStep2")}
            onClick={() => void connectGoogle("drive")}
          >
            {t("connectors.google.driveOnly")}
          </Button>
        </div>
      </div>

      <div className="mt-4 rounded-md border border-border bg-surface-muted p-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-fg">{t("connectors.ms.title")}</h3>
          <p className="text-xs text-fg-muted">
            <RichText text={t("connectors.ms.intro")} />
          </p>
        </div>

        {msApp ? (
          <div className="mt-3 rounded-md border border-border-subtle bg-surface-elevated p-3 text-xs">
            <p className="font-medium text-fg">{t("connectors.ms.appStatusTitle")}</p>
            <p className="mt-1 text-fg-muted">
              {t("connectors.ms.appStatusLine", {
                idSrc: t(credentialSourceKey(msApp.client_id_source)),
                secretSrc: t(credentialSourceKey(msApp.client_secret_source)),
                tenantSrc: t(credentialSourceKey(msApp.tenant_source))
              })}
            </p>
            <p className="mt-1 text-fg">
              {msApp.configured ? t("connectors.ms.configuredReady") : t("connectors.ms.configuredIncomplete")}
            </p>
          </div>
        ) : null}

        <form
          className="mt-3 grid gap-3 rounded-md border border-border bg-surface-elevated p-3"
          onSubmit={(e) => void saveMicrosoftAppSetup(e)}
        >
          <p className="text-xs font-medium text-fg">{t("connectors.ms.step1")}</p>
          <ol className="list-decimal space-y-1 pl-4 text-xs text-fg-muted">
            <li>
              {t("connectors.ms.step1.line1Pre")}
              <a
                className="font-medium text-fg underline underline-offset-2"
                href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
                target="_blank"
                rel="noopener noreferrer"
              >
                {t("connectors.ms.step1.linkLabel")}
              </a>
              <RichText text={t("connectors.ms.step1.line1Post")} />
            </li>
            <li>
              <RichText text={t("connectors.ms.step1.line2")} />
              <code className="mt-1 block break-all rounded bg-surface-muted px-2 py-1 font-mono text-[11px] text-fg">
                {msRedirect}
              </code>
            </li>
            <li>
              <RichText text={t("connectors.ms.step1.line3")} />
            </li>
          </ol>

          <p className="text-xs font-medium text-fg">{t("connectors.ms.step2")}</p>
          <label className="text-xs font-medium text-fg">
            {t("connectors.ms.clientId")}
            <Input
              className="mt-1 font-mono text-xs"
              value={msFormClientId}
              onChange={(e) => setMsFormClientId(e.target.value)}
              placeholder={t("connectors.ms.clientIdPlaceholder")}
              autoComplete="off"
            />
          </label>
          <label className="text-xs font-medium text-fg">
            <RichText text={t("connectors.ms.tenant")} />
            <Input
              className="mt-1 font-mono text-xs"
              value={msFormTenant}
              onChange={(e) => setMsFormTenant(e.target.value)}
              placeholder={t("connectors.ms.tenantPlaceholder")}
              autoComplete="off"
            />
            <span className="mt-1 block font-normal text-fg-subtle">
              <RichText text={t("connectors.ms.tenantHelp")} />
            </span>
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.ms.clientSecret")}
            <Input
              className="mt-1 font-mono text-xs"
              type="password"
              value={msFormSecret}
              onChange={(e) => setMsFormSecret(e.target.value)}
              placeholder={
                msApp?.has_saved_secret
                  ? t("connectors.ms.secretSavedPlaceholder")
                  : t("connectors.ms.secretEmptyPlaceholder")
              }
              autoComplete="off"
            />
          </label>
          <Button
            type="submit"
            className="w-fit border-primary bg-primary text-primary-fg hover:opacity-90"
            disabled={msSetupSaving}
          >
            {msSetupSaving ? t("connectors.google.saving") : t("connectors.ms.saveLink")}
          </Button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            className="border-primary bg-primary text-primary-fg hover:opacity-90 disabled:opacity-50"
            disabled={!msApp?.configured}
            title={msApp?.configured ? undefined : t("connectors.ms.tooltipSaveFirst")}
            onClick={() => void connectMicrosoft("all")}
          >
            {t("connectors.ms.connectAll")}
          </Button>
          <Button
            type="button"
            disabled={!msApp?.configured}
            title={msApp?.configured ? undefined : t("connectors.ms.tooltipCompleteStep2")}
            onClick={() => void connectMicrosoft("mail")}
          >
            {t("connectors.ms.mailOnly")}
          </Button>
          <Button
            type="button"
            disabled={!msApp?.configured}
            title={msApp?.configured ? undefined : t("connectors.ms.tooltipCompleteStep2")}
            onClick={() => void connectMicrosoft("calendar")}
          >
            {t("connectors.ms.calendarOnly")}
          </Button>
          <Button
            type="button"
            disabled={!msApp?.configured}
            title={msApp?.configured ? undefined : t("connectors.ms.tooltipCompleteStep2")}
            onClick={() => void connectMicrosoft("drive")}
          >
            {t("connectors.ms.driveOnly")}
          </Button>
        </div>
      </div>

      <div className="mt-6">
        <button
          type="button"
          className="text-xs font-medium text-fg-muted underline-offset-2 hover:underline"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? t("connectors.advanced.hide") : t("connectors.advanced.show")}
        </button>
      </div>

      {showAdvanced ? (
        <form className="mt-4 grid gap-3" onSubmit={(e) => void addConnection(e)}>
          <label className="text-sm font-medium text-fg">
            {t("connectors.advanced.provider")}
            <select
              className="mt-1 w-full rounded-md border border-border bg-surface-elevated px-3 py-2 text-sm"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {PROVIDER_EXAMPLES.map((p) => (
                <option key={p.id} value={p.id}>
                  {t(p.labelKey)}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm font-medium text-fg">
            {t("connectors.advanced.label")}
            <Input
              className="mt-1"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={t("connectors.advanced.labelPlaceholder")}
            />
          </label>
          <label className="text-sm font-medium text-fg">
            {t("connectors.advanced.credentials")}
            <textarea
              className="mt-1 min-h-[120px] w-full rounded-md border border-border bg-surface-elevated px-3 py-2 font-mono text-xs"
              value={credentialsJson}
              onChange={(e) => setCredentialsJson(e.target.value)}
              spellCheck={false}
            />
          </label>
          <Button type="submit" className="w-fit border-primary bg-primary text-primary-fg hover:opacity-90" disabled={loading}>
            {t("connectors.advanced.add")}
          </Button>
        </form>
      ) : null}

      <div className="mt-6 space-y-2">
        <h3 className="text-sm font-medium text-fg">{t("connectors.saved.title")}</h3>
        {rows.length === 0 ? (
          <p className="text-sm text-fg-subtle">{t("connectors.saved.empty")}</p>
        ) : (
          <ul className="space-y-2">
            {rows.map((r) => {
              const needsReauth =
                typeof r.meta === "object" && r.meta !== null && (r.meta as Record<string, unknown>).status === "needs_reauth";
              const syncList = syncRows[r.id] || [];
              return (
                <li key={r.id} className="flex flex-col gap-2 rounded border border-border-subtle px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="font-medium">{r.label}</span>{" "}
                      <span className="text-fg-subtle">
                        ({r.provider}) · #{r.id}
                      </span>
                      {needsReauth ? (
                        <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                          {t("connectors.saved.needsReauth")}
                        </span>
                      ) : null}
                    </span>
                    <div className="flex gap-2">
                      {r.provider === "google_gmail" ? (
                        <Button type="button" className="text-xs" onClick={() => void triggerSync(r.id, "gmail")}>
                          {t("connectors.saved.syncNow")}
                        </Button>
                      ) : null}
                      {r.provider === "google_calendar" ? (
                        <Button type="button" className="text-xs" onClick={() => void triggerSync(r.id, "calendar")}>
                          {t("connectors.saved.syncNow")}
                        </Button>
                      ) : null}
                      {r.provider === "google_drive" ? (
                        <Button type="button" className="text-xs" onClick={() => void triggerSync(r.id, "drive")}>
                          {t("connectors.saved.syncNow")}
                        </Button>
                      ) : null}
                      {r.provider === "graph_mail" ? (
                        <Button
                          type="button"
                          className="text-xs"
                          onClick={() => void triggerSync(r.id, "graph_mail")}
                        >
                          {t("connectors.saved.syncNow")}
                        </Button>
                      ) : null}
                      {r.provider === "graph_calendar" ? (
                        <Button
                          type="button"
                          className="text-xs"
                          onClick={() => void triggerSync(r.id, "graph_calendar")}
                        >
                          {t("connectors.saved.syncNow")}
                        </Button>
                      ) : null}
                      {r.provider === "graph_onedrive" ? (
                        <Button
                          type="button"
                          className="text-xs"
                          onClick={() => void triggerSync(r.id, "graph_drive")}
                        >
                          {t("connectors.saved.syncNow")}
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        className="text-xs"
                        disabled={verifyLoadingId === r.id || loading}
                        onClick={() => void verifyAccess(r.id)}
                      >
                        {verifyLoadingId === r.id ? t("connectors.saved.verifying") : t("connectors.saved.verifyAccess")}
                      </Button>
                      <Button
                        type="button"
                        className="border-dashed text-xs"
                        disabled={loading}
                        onClick={() => void remove(r.id)}
                      >
                        {t("connectors.saved.remove")}
                      </Button>
                    </div>
                  </div>
                  {r.token_expires_at ? (
                    <p className="text-xs text-fg-muted">
                      {t("connectors.saved.tokenExpires", {
                        when: new Date(r.token_expires_at).toLocaleString()
                      })}
                    </p>
                  ) : null}
                  {verifyHint[r.id] ? (
                    <p
                      className={
                        verifyHint[r.id].variant === "ok" ? "text-xs text-green-800" : "text-xs text-red-800"
                      }
                    >
                      {verifyHint[r.id].text}
                    </p>
                  ) : null}
                  {syncList.length > 0 ? (
                    <div className="grid grid-cols-1 gap-1 text-xs text-fg-muted md:grid-cols-2">
                      {syncList.map((s) => (
                        <div key={`${s.connection_id}-${s.resource}`} className="rounded bg-surface-muted px-2 py-1">
                          <div>
                            <span className="font-mono">{s.resource}</span> · {s.status}
                            {s.last_delta_at
                              ? ` · ${t("connectors.saved.lastSync", { when: new Date(s.last_delta_at).toLocaleString() })}`
                              : ""}
                            {s.error_count > 0
                              ? ` · ${t("connectors.saved.errorsCount", { count: s.error_count })}`
                              : ""}
                          </div>
                          {s.last_error && s.last_error.trim() ? (
                            <div className="mt-0.5 break-words text-amber-900 dark:text-amber-200/90">
                              {t("connectors.saved.lastError", { message: s.last_error })}
                            </div>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </Card>
  );
}
