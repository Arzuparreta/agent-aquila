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
  { id: "graph_teams", labelKey: "connectors.provider.graph_teams" },
  { id: "whatsapp_business", labelKey: "connectors.provider.whatsapp_business" },
  { id: "icloud_caldav", labelKey: "connectors.provider.icloud_caldav" },
  { id: "github", labelKey: "connectors.provider.github" }
];

/** Saved-connection list: human-readable provider names (raw id otherwise). */
const CONNECTOR_PROVIDER_LABEL_KEYS: Partial<Record<string, TranslationKey>> = {
  whatsapp_business: "connectors.provider.whatsapp_business",
  icloud_caldav: "connectors.provider.icloud_caldav",
  github: "connectors.provider.github"
};

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

  const [waAccessToken, setWaAccessToken] = useState("");
  const [waPhoneId, setWaPhoneId] = useState("");
  const [waGraphVer, setWaGraphVer] = useState("v21.0");
  const [waLabel, setWaLabel] = useState("");
  const [waSaving, setWaSaving] = useState(false);

  const [icloudAppleId, setIcloudAppleId] = useState("");
  const [icloudAppPassword, setIcloudAppPassword] = useState("");
  const [icloudLabel, setIcloudLabel] = useState("");
  const [icloudChinaMainland, setIcloudChinaMainland] = useState(false);
  const [icloudSaving, setIcloudSaving] = useState(false);

  const [ghPat, setGhPat] = useState("");
  const [ghLabel, setGhLabel] = useState("");
  const [ghSaving, setGhSaving] = useState(false);

  const load = useCallback(async () => {
    try {
      // After the OpenClaw refactor there is no local mirror, so there is no
      // background sync state to surface either — every connector talks to its
      // upstream API on demand.
      const list = await apiFetch<ConnectorConnection[]>("/connectors");
      setRows(list);
      setVerifyHint({});
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

  const normalizeGraphApiVersion = (raw: string) => {
    const s = (raw || "v21.0").trim() || "v21.0";
    return s.startsWith("v") ? s : `v${s}`;
  };

  const saveWhatsAppConnection = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setInfo(null);
    if (!waAccessToken.trim() || !waPhoneId.trim() || !waLabel.trim()) {
      setError(t("connectors.whatsapp.errors.missing"));
      return;
    }
    setWaSaving(true);
    try {
      await apiFetch<ConnectorConnection>("/connectors", {
        method: "POST",
        body: JSON.stringify({
          provider: "whatsapp_business",
          label: waLabel.trim(),
          credentials: {
            access_token: waAccessToken.trim(),
            phone_number_id: waPhoneId.trim(),
            graph_api_version: normalizeGraphApiVersion(waGraphVer)
          },
          meta: { source: "settings_ui" }
        })
      });
      setWaAccessToken("");
      setWaPhoneId("");
      setWaGraphVer("v21.0");
      setWaLabel("");
      setInfo(t("connectors.whatsapp.saved"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.errors.saveFailed"));
    } finally {
      setWaSaving(false);
    }
  };

  const saveIcloudConnection = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setInfo(null);
    if (!icloudAppleId.trim() || !icloudAppPassword.trim() || !icloudLabel.trim()) {
      setError(t("connectors.icloud.errors.missing"));
      return;
    }
    setIcloudSaving(true);
    try {
      await apiFetch<ConnectorConnection>("/connectors", {
        method: "POST",
        body: JSON.stringify({
          provider: "icloud_caldav",
          label: icloudLabel.trim(),
          credentials: {
            username: icloudAppleId.trim(),
            password: icloudAppPassword.trim(),
            ...(icloudChinaMainland ? { china_mainland: true } : {})
          },
          meta: { source: "settings_ui" }
        })
      });
      setIcloudAppleId("");
      setIcloudAppPassword("");
      setIcloudLabel("");
      setIcloudChinaMainland(false);
      setInfo(t("connectors.icloud.saved"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.errors.saveFailed"));
    } finally {
      setIcloudSaving(false);
    }
  };

  const saveGithubConnection = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setInfo(null);
    if (!ghPat.trim() || !ghLabel.trim()) {
      setError(t("connectors.github.errors.missing"));
      return;
    }
    setGhSaving(true);
    try {
      await apiFetch<ConnectorConnection>("/connectors", {
        method: "POST",
        body: JSON.stringify({
          provider: "github",
          label: ghLabel.trim(),
          credentials: { access_token: ghPat.trim() },
          meta: { source: "settings_ui" }
        })
      });
      setGhPat("");
      setGhLabel("");
      setInfo(t("connectors.github.saved"));
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("connectors.errors.saveFailed"));
    } finally {
      setGhSaving(false);
    }
  };

  const gmailNeedsReauth = rows.some(
    (r) => (r.provider === "google_gmail" || r.provider === "gmail") && r.needs_reauth,
  );

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

      {gmailNeedsReauth ? (
        <div className="mt-3 flex flex-col gap-2 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="font-semibold">Reconectar Gmail</p>
            <p className="text-xs text-amber-800">
              El agente necesita un permiso adicional de Gmail (filtros y configuración básica) para
              poder silenciar y mover remitentes a spam directamente. Reconecta tu cuenta para
              autorizarlo.
            </p>
          </div>
          <Button
            type="button"
            className="border-amber-400 bg-amber-100 text-amber-900 hover:bg-amber-200"
            onClick={() => void connectGoogle("gmail")}
          >
            Reconectar Gmail
          </Button>
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

      <div className="mt-4 rounded-md border border-border bg-surface-muted p-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-fg">{t("connectors.whatsapp.title")}</h3>
          <p className="text-xs text-fg-muted">
            <RichText text={t("connectors.whatsapp.intro")} />
          </p>
          <a
            className="text-xs font-medium text-fg underline underline-offset-2"
            href="https://developers.facebook.com/apps/"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("connectors.whatsapp.consoleLink")}
          </a>
        </div>
        <form
          className="mt-3 grid gap-3 rounded-md border border-border bg-surface-elevated p-3"
          onSubmit={(e) => void saveWhatsAppConnection(e)}
        >
          <label className="text-xs font-medium text-fg">
            {t("connectors.whatsapp.accessToken")}
            <Input
              className="mt-1 font-mono text-xs"
              type="password"
              value={waAccessToken}
              onChange={(e) => setWaAccessToken(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.whatsapp.phoneNumberId")}
            <Input
              className="mt-1 font-mono text-xs"
              value={waPhoneId}
              onChange={(e) => setWaPhoneId(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.whatsapp.graphVersion")}
            <Input
              className="mt-1 font-mono text-xs"
              value={waGraphVer}
              onChange={(e) => setWaGraphVer(e.target.value)}
              placeholder="v21.0"
              autoComplete="off"
            />
            <span className="mt-1 block font-normal text-fg-subtle">
              <RichText text={t("connectors.whatsapp.graphVersionHint")} />
            </span>
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.whatsapp.label")}
            <Input
              className="mt-1"
              value={waLabel}
              onChange={(e) => setWaLabel(e.target.value)}
              placeholder={t("connectors.whatsapp.labelPlaceholder")}
            />
          </label>
          <Button
            type="submit"
            className="w-fit border-primary bg-primary text-primary-fg hover:opacity-90"
            disabled={waSaving}
          >
            {waSaving ? t("connectors.whatsapp.saving") : t("connectors.whatsapp.save")}
          </Button>
        </form>
      </div>

      <div className="mt-4 rounded-md border border-border bg-surface-muted p-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-fg">{t("connectors.icloud.title")}</h3>
          <p className="text-xs text-fg-muted">
            <RichText text={t("connectors.icloud.intro")} />
          </p>
          <a
            className="text-xs font-medium text-fg underline underline-offset-2"
            href="https://appleid.apple.com/sign-in"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("connectors.icloud.consoleLink")}
          </a>
        </div>
        <form
          className="mt-3 grid gap-3 rounded-md border border-border bg-surface-elevated p-3"
          onSubmit={(e) => void saveIcloudConnection(e)}
        >
          <label className="text-xs font-medium text-fg">
            {t("connectors.icloud.appleId")}
            <Input
              className="mt-1 font-mono text-xs"
              type="email"
              value={icloudAppleId}
              onChange={(e) => setIcloudAppleId(e.target.value)}
              autoComplete="username"
            />
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.icloud.appPassword")}
            <Input
              className="mt-1 font-mono text-xs"
              type="password"
              value={icloudAppPassword}
              onChange={(e) => setIcloudAppPassword(e.target.value)}
              autoComplete="new-password"
            />
          </label>
          <label className="flex cursor-pointer items-start gap-2 text-xs font-medium text-fg">
            <input
              type="checkbox"
              className="mt-0.5 rounded border-border"
              checked={icloudChinaMainland}
              onChange={(e) => setIcloudChinaMainland(e.target.checked)}
            />
            <span>
              {t("connectors.icloud.chinaMainland")}
              <span className="mt-0.5 block font-normal text-fg-subtle">
                {t("connectors.icloud.chinaMainlandHint")}
              </span>
            </span>
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.icloud.label")}
            <Input
              className="mt-1"
              value={icloudLabel}
              onChange={(e) => setIcloudLabel(e.target.value)}
              placeholder={t("connectors.icloud.labelPlaceholder")}
            />
          </label>
          <Button
            type="submit"
            className="w-fit border-primary bg-primary text-primary-fg hover:opacity-90"
            disabled={icloudSaving}
          >
            {icloudSaving ? t("connectors.icloud.saving") : t("connectors.icloud.save")}
          </Button>
        </form>
      </div>

      <div className="mt-4 rounded-md border border-border bg-surface-muted p-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-fg">{t("connectors.github.title")}</h3>
          <p className="text-xs text-fg-muted">
            <RichText text={t("connectors.github.intro")} />
          </p>
          <a
            className="text-xs font-medium text-fg underline underline-offset-2"
            href="https://github.com/settings/tokens"
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("connectors.github.consoleLink")}
          </a>
        </div>
        <form
          className="mt-3 grid gap-3 rounded-md border border-border bg-surface-elevated p-3"
          onSubmit={(e) => void saveGithubConnection(e)}
        >
          <label className="text-xs font-medium text-fg">
            {t("connectors.github.pat")}
            <Input
              className="mt-1 font-mono text-xs"
              type="password"
              value={ghPat}
              onChange={(e) => setGhPat(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label className="text-xs font-medium text-fg">
            {t("connectors.github.label")}
            <Input
              className="mt-1"
              value={ghLabel}
              onChange={(e) => setGhLabel(e.target.value)}
              placeholder={t("connectors.github.labelPlaceholder")}
            />
          </label>
          <Button
            type="submit"
            className="w-fit border-primary bg-primary text-primary-fg hover:opacity-90"
            disabled={ghSaving}
          >
            {ghSaving ? t("connectors.github.saving") : t("connectors.github.save")}
          </Button>
        </form>
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
              const providerPretty =
                CONNECTOR_PROVIDER_LABEL_KEYS[r.provider] !== undefined
                  ? t(CONNECTOR_PROVIDER_LABEL_KEYS[r.provider]!)
                  : r.provider;
              const isGmailLike = r.provider === "google_gmail" || r.provider === "gmail";
              const reconnectTarget = (() => {
                if (r.provider.startsWith("google_") || r.provider === "gmail") return "google";
                if (r.provider.startsWith("graph_")) return "microsoft";
                return null;
              })();
              const reconnectIntent = (() => {
                if (r.provider === "google_gmail" || r.provider === "gmail") return "gmail";
                if (r.provider === "google_calendar") return "calendar";
                if (r.provider === "google_drive") return "drive";
                if (r.provider === "graph_mail") return "mail";
                if (r.provider === "graph_calendar") return "calendar";
                if (r.provider === "graph_onedrive") return "drive";
                if (r.provider === "graph_teams") return "teams";
                return "all";
              })();
              return (
                <li
                  key={r.id}
                  className="flex flex-col gap-2 rounded border border-border-subtle px-3 py-2 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="font-medium">{r.label}</span>{" "}
                      <span className="text-fg-subtle">
                        ({providerPretty}) · #{r.id}
                      </span>
                      {r.needs_reauth ? (
                        <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                          Necesita reconectarse
                        </span>
                      ) : null}
                    </span>
                    <div className="flex gap-2">
                      {r.needs_reauth && reconnectTarget ? (
                        <Button
                          type="button"
                          className="border-amber-400 bg-amber-100 text-xs text-amber-900 hover:bg-amber-200"
                          onClick={() =>
                            void startOAuth(reconnectTarget, reconnectIntent)
                          }
                        >
                          {isGmailLike ? "Reconectar Gmail" : "Reconectar"}
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        className="text-xs"
                        disabled={verifyLoadingId === r.id || loading}
                        onClick={() => void verifyAccess(r.id)}
                      >
                        {verifyLoadingId === r.id
                          ? t("connectors.saved.verifying")
                          : t("connectors.saved.verifyAccess")}
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
                  {r.needs_reauth && r.missing_scopes && r.missing_scopes.length > 0 ? (
                    <p className="text-xs text-amber-700 dark:text-amber-300">
                      Faltan permisos: <span className="font-mono">{r.missing_scopes.join(", ")}</span>
                    </p>
                  ) : null}
                  {r.token_expires_at ? (
                    <p className="text-xs text-fg-muted">
                      {t("connectors.saved.tokenExpires", {
                        when: new Date(r.token_expires_at).toLocaleString(),
                      })}
                    </p>
                  ) : null}
                  {verifyHint[r.id] ? (
                    <p
                      className={
                        verifyHint[r.id].variant === "ok"
                          ? "text-xs text-green-800"
                          : "text-xs text-red-800"
                      }
                    >
                      {verifyHint[r.id].text}
                    </p>
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
