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

type GoogleStatus = {
  configured: boolean;
  redirect_uri: string;
  providers: string[];
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
  const [googleStatus, setGoogleStatus] = useState<GoogleStatus | null>(null);
  const [msStatus, setMsStatus] = useState<GoogleStatus | null>(null);

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

  useEffect(() => {
    void load();
    void apiFetch<GoogleStatus>("/oauth/google/status")
      .then(setGoogleStatus)
      .catch(() => setGoogleStatus(null));
    void apiFetch<GoogleStatus>("/oauth/microsoft/status")
      .then(setMsStatus)
      .catch(() => setMsStatus(null));
  }, [load]);

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
    } else if (status === "error") {
      const err = params.get("error") || "unknown";
      const detail = params.get("detail") || "";
      setError(`Google OAuth failed: ${err}${detail ? ` — ${detail}` : ""}`);
    }
    const url = new URL(window.location.href);
    ["oauth", "provider", "account", "connection_ids", "scopes", "error", "detail"].forEach((k) =>
      url.searchParams.delete(k)
    );
    window.history.replaceState({}, "", url.toString());
  }, [load]);

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

      <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Google Workspace</h3>
            <p className="text-xs text-slate-600">
              {googleStatus?.configured
                ? `OAuth client configured. Redirect URI: ${googleStatus.redirect_uri}`
                : "OAuth is not set up on this server yet. The connect buttons stay disabled until an administrator adds credentials (see below)."}
            </p>
          </div>
        </div>
        {!googleStatus?.configured ? (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
            <p className="font-medium">For whoever runs this deployment</p>
            <ol className="mt-2 list-decimal space-y-1 pl-4 text-amber-900">
              <li>
                In{" "}
                <a
                  className="font-medium underline underline-offset-2 hover:text-amber-950"
                  href="https://console.cloud.google.com/apis/credentials"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Google Cloud Console → Credentials
                </a>
                , create an OAuth 2.0 Client ID (Web application).
              </li>
              <li>
                Under Authorized redirect URIs, add exactly:{" "}
                <code className="break-all rounded bg-white/80 px-1 py-0.5 text-[11px] text-slate-800">
                  {googleStatus?.redirect_uri ?? "…load status to see URI…"}
                </code>
              </li>
              <li>Enable Gmail API, Google Calendar API, and Google Drive API for the project.</li>
              <li>
                Set <code className="rounded bg-white/80 px-1">GOOGLE_OAUTH_CLIENT_ID</code> and{" "}
                <code className="rounded bg-white/80 px-1">GOOGLE_OAUTH_CLIENT_SECRET</code> in the API server
                environment, set <code className="rounded bg-white/80 px-1">GOOGLE_OAUTH_REDIRECT_BASE</code> to match
                your API origin, then restart the backend.
              </li>
            </ol>
            <p className="mt-2 text-amber-800">
              After that, end users only click Connect and sign in with Google — no API keys to paste.
            </p>
          </div>
        ) : null}
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            className="bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            disabled={!googleStatus?.configured}
            title={
              googleStatus?.configured
                ? undefined
                : "Disabled until GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET are set on the server."
            }
            onClick={() => void connectGoogle("all")}
          >
            Connect Google (Gmail + Calendar + Drive)
          </Button>
          <Button
            type="button"
            disabled={!googleStatus?.configured}
            title={
              googleStatus?.configured
                ? undefined
                : "Disabled until Google OAuth is configured on the server."
            }
            onClick={() => void connectGoogle("gmail")}
          >
            Gmail only
          </Button>
          <Button
            type="button"
            disabled={!googleStatus?.configured}
            title={
              googleStatus?.configured
                ? undefined
                : "Disabled until Google OAuth is configured on the server."
            }
            onClick={() => void connectGoogle("calendar")}
          >
            Calendar only
          </Button>
          <Button
            type="button"
            disabled={!googleStatus?.configured}
            title={
              googleStatus?.configured
                ? undefined
                : "Disabled until Google OAuth is configured on the server."
            }
            onClick={() => void connectGoogle("drive")}
          >
            Drive only
          </Button>
        </div>
      </div>

      <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-4">
        <div className="flex items-center justify-between gap-2">
          <div>
            <h3 className="text-sm font-semibold text-slate-900">Microsoft 365 (Graph)</h3>
            <p className="text-xs text-slate-600">
              {msStatus?.configured
                ? `Azure AD client configured. Redirect URI: ${msStatus.redirect_uri}`
                : "Microsoft OAuth not configured on server. Set MICROSOFT_OAUTH_CLIENT_ID / MICROSOFT_OAUTH_CLIENT_SECRET and restart."}
            </p>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <Button
            type="button"
            className="bg-slate-900 text-white hover:bg-slate-800 disabled:opacity-50"
            disabled={!msStatus?.configured}
            onClick={() => void connectMicrosoft("all")}
          >
            Connect Microsoft (Mail + Calendar + OneDrive)
          </Button>
          <Button
            type="button"
            disabled={!msStatus?.configured}
            onClick={() => void connectMicrosoft("mail")}
          >
            Mail only
          </Button>
          <Button
            type="button"
            disabled={!msStatus?.configured}
            onClick={() => void connectMicrosoft("calendar")}
          >
            Calendar only
          </Button>
          <Button
            type="button"
            disabled={!msStatus?.configured}
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
          <p className="text-sm text-slate-500">None yet. Connect Google above to get started.</p>
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
