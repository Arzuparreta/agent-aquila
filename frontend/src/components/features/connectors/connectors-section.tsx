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
  { id: "google_gmail", label: "Google Gmail" },
  { id: "graph_calendar", label: "Microsoft Graph — calendar" },
  { id: "google_calendar", label: "Google Calendar" },
  { id: "graph_onedrive", label: "Microsoft OneDrive / SharePoint" },
  { id: "google_drive", label: "Google Drive" },
  { id: "graph_teams", label: "Microsoft Teams (Graph)" }
];

export function ConnectorsSection() {
  const [rows, setRows] = useState<ConnectorConnection[]>([]);
  const [provider, setProvider] = useState("mock_email");
  const [label, setLabel] = useState("");
  const [credentialsJson, setCredentialsJson] = useState('{\n  "access_token": ""\n}');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await apiFetch<ConnectorConnection[]>("/connectors");
      setRows(list);
    } catch {
      setRows([]);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

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
        Store encrypted credentials per user (OAuth access tokens or SMTP). Use{" "}
        <span className="font-mono text-xs">PATCH /connectors/&#123;id&#125;</span> or the API to rotate tokens and set{" "}
        <span className="font-mono text-xs">token_expires_at</span> / <span className="font-mono text-xs">oauth_scopes</span>.
        Dry-run a payload with <span className="font-mono text-xs">POST /connectors/dry-run</span>. The copilot only proposes
        actions; you approve them in the cockpit. For development, use mock_* providers.
      </p>
      {error ? (
        <div className="mt-3">
          <AlertBanner variant="error" message={error} onDismiss={() => setError(null)} />
        </div>
      ) : null}

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

      <div className="mt-6 space-y-2">
        <h3 className="text-sm font-medium text-slate-800">Saved connections</h3>
        {rows.length === 0 ? (
          <p className="text-sm text-slate-500">None yet.</p>
        ) : (
          <ul className="space-y-2">
            {rows.map((r) => (
              <li
                key={r.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded border border-slate-100 px-3 py-2 text-sm"
              >
                <span>
                  <span className="font-medium">{r.label}</span>{" "}
                  <span className="text-slate-500">
                    ({r.provider}) · #{r.id}
                  </span>
                </span>
                <Button type="button" className="border-dashed text-xs" disabled={loading} onClick={() => void remove(r.id)}>
                  Remove
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </Card>
  );
}
