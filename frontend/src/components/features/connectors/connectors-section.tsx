"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import type { ConnectorConnection } from "@/types/api";

const PROVIDER_EXAMPLES = [
  { id: "mock_email", label: "Mock email (dev)" },
  { id: "mock_calendar", label: "Mock calendar (dev)" },
  { id: "mock_files", label: "Mock files (dev)" },
  { id: "mock_teams", label: "Mock Teams (dev)" },
  { id: "smtp", label: "SMTP (host/port/user/password)" },
  { id: "graph_mail", label: "Microsoft Graph — mail" },
  { id: "google_gmail", label: "Google Gmail (manual token — prefer Connect Google)" },
  { id: "graph_calendar", label: "Microsoft Graph — calendar" },
  { id: "google_calendar", label: "Google Calendar (manual token — prefer Connect Google)" },
  { id: "graph_onedrive", label: "Microsoft OneDrive / SharePoint" },
  { id: "google_drive", label: "Google Drive (manual token — prefer Connect Google)" },
  { id: "graph_teams", label: "Microsoft Teams (Graph)" }
];

type GoogleAppCredentials = {
  client_id: string;
  redirect_base: string;
  redirect_uri: string;
  configured: boolean;
  has_saved_secret: boolean;
};

type MicrosoftAppCredentials = {
  client_id: string;
  tenant: string;
  redirect_base: string;
  redirect_uri: string;
  configured: boolean;
  has_saved_secret: boolean;
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

export function ConnectorsSection() {
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

  const load = useCallback(async () => {
    try {
      const list = await apiFetch<ConnectorConnection[]>("/connectors");
      setRows(list);
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
      setInfo(`${niceProv} connected${account ? ` as ${account}` : ""}. Initial sync scheduled.`);
      void load();
      void loadOAuthForms();
    } else if (status === "error") {
      const err = params.get("error") || "unknown";
      const detail = params.get("detail") || "";
      setError(`Sign-in failed: ${err}${detail ? ` — ${detail}` : ""}`);
    }
    const url = new URL(window.location.href);
    ["oauth", "provider", "account", "connection_ids", "scopes", "error", "detail"].forEach((k) =>
      url.searchParams.delete(k)
    );
    window.history.replaceState({}, "", url.toString());
  }, [load, loadOAuthForms]);

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
      setError(e instanceof Error ? e.message : `Failed to start ${vendor} OAuth`);
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
      setInfo(
        updated.configured
          ? "Google link saved. You can use Connect Google below, or update these fields any time."
          : "Saved. Add the Client secret if Google still asks for it, then try Connect Google."
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save Google settings");
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
      setInfo(
        updated.configured
          ? "Microsoft link saved. You can use Connect Microsoft below, or update these fields any time."
          : "Saved. Add the Client secret if Azure still asks for it, then try Connect Microsoft."
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save Microsoft settings");
    } finally {
      setMsSetupSaving(false);
    }
  };

  const triggerSync = async (connectionId: number, resource: string) => {
    setError(null);
    setInfo(null);
    try {
      await apiFetch(`/connectors/${connectionId}/sync/${resource}`, { method: "POST" });
      setInfo(`Queued ${resource} sync for connection #${connectionId}.`);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to queue sync");
    }
  };

  const addConnection = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    let credentials: Record<string, unknown>;
    try {
      credentials = JSON.parse(credentialsJson) as Record<string, unknown>;
    } catch {
      setError("Credentials must be valid JSON.");
      return;
    }
    if (!label.trim()) {
      setError("Label is required.");
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
      setError(e instanceof Error ? e.message : "Failed to save connection");
    } finally {
      setLoading(false);
    }
  };

  const remove = async (id: number) => {
    setError(null);
    setLoading(true);
    try {
      await apiFetch(`/connectors/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="mt-8 p-5">
      <h2 className="text-lg font-semibold text-slate-900">External connectors</h2>
      <p className="mt-1 text-sm text-slate-600">
        Connect your accounts with a single click. Google Workspace (Gmail, Calendar, Drive) uses OAuth 2.0 and
        tokens are refreshed automatically. Mirrored data lives in Postgres and is available to the agent for
        search and drafting. Writes (send, create event, upload) remain human-gated.
      </p>
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
        <h3 className="text-sm font-semibold text-slate-900">This app&apos;s web address</h3>
        <p className="mt-1 text-xs text-slate-600">
          Use the same address people type to open this site (example: <span className="font-mono">http://localhost:3002</span>{" "}
          at home, or your real domain in production). No trailing slash. Google and Microsoft both use it for secure
          return links after sign-in.
        </p>
        <label className="mt-2 block text-xs font-medium text-slate-800">
          Public URL
          <Input
            className="mt-1 font-mono text-xs"
            value={oauthPublicBase}
            onChange={(e) => setOauthPublicBase(e.target.value)}
            placeholder="https://your-site.example"
            autoComplete="off"
          />
        </label>
        <p className="mt-2 text-xs text-slate-500">
          This value is saved when you click &quot;Save Google link&quot; or &quot;Save Microsoft link&quot; below.
        </p>
      </div>

      <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-slate-900">Google Workspace</h3>
          <p className="text-xs text-slate-600">
            Link Google once here (any signed-in person can do it). Then use{" "}
            <span className="font-medium">Connect Google</span> to choose which mailbox and calendars to use.
          </p>
        </div>

        <form className="mt-3 grid gap-3 rounded-md border border-slate-200 bg-white p-3" onSubmit={(e) => void saveGoogleAppSetup(e)}>
          <p className="text-xs font-medium text-slate-800">Step 1 — Google Cloud (external site)</p>
          <ol className="list-decimal space-y-1 pl-4 text-xs text-slate-600">
            <li>
              Open{" "}
              <a
                className="font-medium text-slate-900 underline underline-offset-2"
                href="https://console.cloud.google.com/apis/credentials"
                target="_blank"
                rel="noopener noreferrer"
              >
                Google Cloud Console → Credentials
              </a>{" "}
              and create an <span className="font-medium">OAuth client ID</span> of type{" "}
              <span className="font-medium">Web application</span>.
            </li>
            <li>
              Under <span className="font-medium">Authorized redirect URIs</span>, add this exact line (copy–paste):{" "}
              <code className="mt-1 block break-all rounded bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-800">
                {`${oauthPublicBase.replace(/\/$/, "") || "(set Public URL above)"}/api/v1/oauth/google/callback`}
              </code>
            </li>
            <li>
              Turn on the <span className="font-medium">Gmail</span>, <span className="font-medium">Calendar</span>, and{" "}
              <span className="font-medium">Drive</span> APIs for that project.
            </li>
          </ol>

          <p className="text-xs font-medium text-slate-800">Step 2 — Paste into this page</p>
          <label className="text-xs font-medium text-slate-800">
            Client ID (from Google)
            <Input
              className="mt-1 font-mono text-xs"
              value={googleFormClientId}
              onChange={(e) => setGoogleFormClientId(e.target.value)}
              placeholder="….apps.googleusercontent.com"
              autoComplete="off"
            />
          </label>
          <label className="text-xs font-medium text-slate-800">
            Client secret (from Google)
            <Input
              className="mt-1 font-mono text-xs"
              type="password"
              value={googleFormSecret}
              onChange={(e) => setGoogleFormSecret(e.target.value)}
              placeholder={
                googleApp?.has_saved_secret
                  ? "Leave blank to keep the saved secret, or paste a new one to replace it"
                  : "Paste the secret from Google (stored encrypted on this server)"
              }
              autoComplete="off"
            />
          </label>
          <Button
            type="submit"
            className="w-fit bg-slate-900 text-white hover:bg-slate-800"
            disabled={googleSetupSaving}
          >
            {googleSetupSaving ? "Saving…" : "Save Google link"}
          </Button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            className="bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            disabled={!googleApp?.configured}
            title={
              googleApp?.configured
                ? undefined
                : "Save the Client ID and secret above first, then these buttons open Google sign-in."
            }
            onClick={() => void connectGoogle("all")}
          >
            Connect Google (Gmail + Calendar + Drive)
          </Button>
          <Button
            type="button"
            disabled={!googleApp?.configured}
            title={googleApp?.configured ? undefined : "Complete Step 2 and save, then try again."}
            onClick={() => void connectGoogle("gmail")}
          >
            Gmail only
          </Button>
          <Button
            type="button"
            disabled={!googleApp?.configured}
            title={googleApp?.configured ? undefined : "Complete Step 2 and save, then try again."}
            onClick={() => void connectGoogle("calendar")}
          >
            Calendar only
          </Button>
          <Button
            type="button"
            disabled={!googleApp?.configured}
            title={googleApp?.configured ? undefined : "Complete Step 2 and save, then try again."}
            onClick={() => void connectGoogle("drive")}
          >
            Drive only
          </Button>
        </div>
      </div>

      <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-4">
        <div className="flex flex-col gap-1">
          <h3 className="text-sm font-semibold text-slate-900">Microsoft 365 (Graph)</h3>
          <p className="text-xs text-slate-600">
            Link Microsoft Entra (Azure AD) once here. Then use <span className="font-medium">Connect Microsoft</span>{" "}
            to sign in with the account that should own mail, calendar, and OneDrive.
          </p>
        </div>

        <form className="mt-3 grid gap-3 rounded-md border border-slate-200 bg-white p-3" onSubmit={(e) => void saveMicrosoftAppSetup(e)}>
          <p className="text-xs font-medium text-slate-800">Step 1 — Azure / Entra (external site)</p>
          <ol className="list-decimal space-y-1 pl-4 text-xs text-slate-600">
            <li>
              Open{" "}
              <a
                className="font-medium text-slate-900 underline underline-offset-2"
                href="https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
                target="_blank"
                rel="noopener noreferrer"
              >
                Azure Portal → App registrations
              </a>
              , create a registration, then <span className="font-medium">Add a platform → Web</span>.
            </li>
            <li>
              Under <span className="font-medium">Redirect URIs</span>, add this exact line:{" "}
              <code className="mt-1 block break-all rounded bg-slate-100 px-2 py-1 font-mono text-[11px] text-slate-800">
                {`${oauthPublicBase.replace(/\/$/, "") || "(set Public URL above)"}/api/v1/oauth/microsoft/callback`}
              </code>
            </li>
            <li>
              Create a <span className="font-medium">Client secret</span> under Certificates &amp; secrets, and note the{" "}
              <span className="font-medium">Application (client) ID</span> from the Overview page.
            </li>
          </ol>

          <p className="text-xs font-medium text-slate-800">Step 2 — Paste into this page</p>
          <label className="text-xs font-medium text-slate-800">
            Application (client) ID
            <Input
              className="mt-1 font-mono text-xs"
              value={msFormClientId}
              onChange={(e) => setMsFormClientId(e.target.value)}
              placeholder="Azure Overview → Application (client) ID"
              autoComplete="off"
            />
          </label>
          <label className="text-xs font-medium text-slate-800">
            Directory (tenant) ID or <span className="font-mono">common</span>
            <Input
              className="mt-1 font-mono text-xs"
              value={msFormTenant}
              onChange={(e) => setMsFormTenant(e.target.value)}
              placeholder="common"
              autoComplete="off"
            />
            <span className="mt-1 block font-normal text-slate-500">
              Use <span className="font-mono">common</span> unless your IT team gave you a specific tenant ID.
            </span>
          </label>
          <label className="text-xs font-medium text-slate-800">
            Client secret (from Azure)
            <Input
              className="mt-1 font-mono text-xs"
              type="password"
              value={msFormSecret}
              onChange={(e) => setMsFormSecret(e.target.value)}
              placeholder={
                msApp?.has_saved_secret
                  ? "Leave blank to keep the saved secret, or paste a new one to replace it"
                  : "Paste the secret (stored encrypted on this server)"
              }
              autoComplete="off"
            />
          </label>
          <Button
            type="submit"
            className="w-fit bg-slate-900 text-white hover:bg-slate-800"
            disabled={msSetupSaving}
          >
            {msSetupSaving ? "Saving…" : "Save Microsoft link"}
          </Button>
        </form>

        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            className="bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            disabled={!msApp?.configured}
            title={
              msApp?.configured
                ? undefined
                : "Save the Application ID and secret above first, then these buttons open Microsoft sign-in."
            }
            onClick={() => void connectMicrosoft("all")}
          >
            Connect Microsoft (Mail + Calendar + OneDrive)
          </Button>
          <Button
            type="button"
            disabled={!msApp?.configured}
            title={msApp?.configured ? undefined : "Complete Step 2 and save, then try again."}
            onClick={() => void connectMicrosoft("mail")}
          >
            Mail only
          </Button>
          <Button
            type="button"
            disabled={!msApp?.configured}
            title={msApp?.configured ? undefined : "Complete Step 2 and save, then try again."}
            onClick={() => void connectMicrosoft("calendar")}
          >
            Calendar only
          </Button>
          <Button
            type="button"
            disabled={!msApp?.configured}
            title={msApp?.configured ? undefined : "Complete Step 2 and save, then try again."}
            onClick={() => void connectMicrosoft("drive")}
          >
            OneDrive only
          </Button>
        </div>
      </div>

      <div className="mt-6">
        <button
          type="button"
          className="text-xs font-medium text-slate-600 underline-offset-2 hover:underline"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? "Hide advanced" : "Advanced: add SMTP / mock / paste-a-token"}
        </button>
      </div>

      {showAdvanced ? (
        <form className="mt-4 grid gap-3" onSubmit={(e) => void addConnection(e)}>
          <label className="text-sm font-medium text-slate-800">
            Provider
            <select
              className="mt-1 w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
            >
              {PROVIDER_EXAMPLES.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-sm font-medium text-slate-800">
            Label
            <Input className="mt-1" value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Work Gmail" />
          </label>
          <label className="text-sm font-medium text-slate-800">
            Credentials (JSON)
            <textarea
              className="mt-1 min-h-[120px] w-full rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs"
              value={credentialsJson}
              onChange={(e) => setCredentialsJson(e.target.value)}
              spellCheck={false}
            />
          </label>
          <Button type="submit" className="w-fit bg-slate-900 text-white hover:bg-slate-800" disabled={loading}>
            Add connection
          </Button>
        </form>
      ) : null}

      <div className="mt-6 space-y-2">
        <h3 className="text-sm font-medium text-slate-800">Saved connections</h3>
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">None yet. Connect Google or Microsoft above to get started.</p>
        ) : (
          <ul className="space-y-2">
            {rows.map((r) => {
              const needsReauth =
                typeof r.meta === "object" && r.meta !== null && (r.meta as Record<string, unknown>).status === "needs_reauth";
              const syncList = syncRows[r.id] || [];
              return (
                <li
                  key={r.id}
                  className="flex flex-col gap-2 rounded border border-slate-100 px-3 py-2 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span>
                      <span className="font-medium">{r.label}</span>{" "}
                      <span className="text-slate-500">
                        ({r.provider}) · #{r.id}
                      </span>
                      {needsReauth ? (
                        <span className="ml-2 rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">
                          needs reconnect
                        </span>
                      ) : null}
                    </span>
                    <div className="flex gap-2">
                      {r.provider === "google_gmail" ? (
                        <Button type="button" className="text-xs" onClick={() => void triggerSync(r.id, "gmail")}>
                          Sync now
                        </Button>
                      ) : null}
                      {r.provider === "google_calendar" ? (
                        <Button type="button" className="text-xs" onClick={() => void triggerSync(r.id, "calendar")}>
                          Sync now
                        </Button>
                      ) : null}
                      {r.provider === "google_drive" ? (
                        <Button type="button" className="text-xs" onClick={() => void triggerSync(r.id, "drive")}>
                          Sync now
                        </Button>
                      ) : null}
                      {r.provider === "graph_mail" ? (
                        <Button
                          type="button"
                          className="text-xs"
                          onClick={() => void triggerSync(r.id, "graph_mail")}
                        >
                          Sync now
                        </Button>
                      ) : null}
                      {r.provider === "graph_calendar" ? (
                        <Button
                          type="button"
                          className="text-xs"
                          onClick={() => void triggerSync(r.id, "graph_calendar")}
                        >
                          Sync now
                        </Button>
                      ) : null}
                      {r.provider === "graph_onedrive" ? (
                        <Button
                          type="button"
                          className="text-xs"
                          onClick={() => void triggerSync(r.id, "graph_drive")}
                        >
                          Sync now
                        </Button>
                      ) : null}
                      <Button
                        type="button"
                        className="border-dashed text-xs"
                        disabled={loading}
                        onClick={() => void remove(r.id)}
                      >
                        Remove
                      </Button>
                    </div>
                  </div>
                  {syncList.length > 0 ? (
                    <div className="grid grid-cols-1 gap-1 text-xs text-slate-600 md:grid-cols-2">
                      {syncList.map((s) => (
                        <div key={`${s.connection_id}-${s.resource}`} className="rounded bg-slate-50 px-2 py-1">
                          <span className="font-mono">{s.resource}</span> · {s.status}
                          {s.last_delta_at ? ` · last ${new Date(s.last_delta_at).toLocaleString()}` : ""}
                          {s.error_count > 0 ? ` · errors ${s.error_count}` : ""}
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
