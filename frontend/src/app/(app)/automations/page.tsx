"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";

type Automation = {
  id: number;
  name: string;
  trigger: string;
  conditions: Record<string, unknown>;
  prompt_template: string;
  default_connection_id: number | null;
  auto_approve: boolean;
  enabled: boolean;
  last_run_at: string | null;
  run_count: number;
  created_at: string;
  updated_at: string;
};

type Banner = { variant: "error" | "success" | "info"; message: string };

const PROMPT_EXAMPLE = `A new inbound email arrived:
From: {from}
Subject: {subject}

{body}

Search the CRM for context, then propose a reply (do not send).`;

export default function AutomationsPage() {
  const [rows, setRows] = useState<Automation[]>([]);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [loading, setLoading] = useState(false);

  const [name, setName] = useState("");
  const [fromContains, setFromContains] = useState("");
  const [subjectContains, setSubjectContains] = useState("");
  const [bodyContains, setBodyContains] = useState("");
  const [promptTemplate, setPromptTemplate] = useState(PROMPT_EXAMPLE);
  const [autoApprove, setAutoApprove] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await apiFetch<Automation[]>("/automations");
      setRows(list);
    } catch (e) {
      setBanner({ variant: "error", message: e instanceof Error ? e.message : "Failed to load automations" });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const add = async (ev: FormEvent) => {
    ev.preventDefault();
    if (!name.trim() || !promptTemplate.trim()) {
      setBanner({ variant: "error", message: "Name and prompt template are required." });
      return;
    }
    const conditions: Record<string, string> = {};
    if (fromContains.trim()) conditions.from_contains = fromContains.trim();
    if (subjectContains.trim()) conditions.subject_contains = subjectContains.trim();
    if (bodyContains.trim()) conditions.body_contains = bodyContains.trim();
    setLoading(true);
    try {
      await apiFetch<Automation>("/automations", {
        method: "POST",
        body: JSON.stringify({
          name: name.trim(),
          trigger: "email_received",
          conditions,
          prompt_template: promptTemplate,
          auto_approve: autoApprove,
          enabled: true
        })
      });
      setName("");
      setFromContains("");
      setSubjectContains("");
      setBodyContains("");
      setPromptTemplate(PROMPT_EXAMPLE);
      setAutoApprove(false);
      setBanner({ variant: "success", message: "Automation saved." });
      await load();
    } catch (e) {
      setBanner({ variant: "error", message: e instanceof Error ? e.message : "Failed to save" });
    } finally {
      setLoading(false);
    }
  };

  const toggle = async (row: Automation) => {
    try {
      await apiFetch(`/automations/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !row.enabled })
      });
      await load();
    } catch (e) {
      setBanner({ variant: "error", message: e instanceof Error ? e.message : "Failed" });
    }
  };

  const remove = async (id: number) => {
    try {
      await apiFetch(`/automations/${id}`, { method: "DELETE" });
      await load();
    } catch (e) {
      setBanner({ variant: "error", message: e instanceof Error ? e.message : "Failed" });
    }
  };

  const testRun = async (id: number) => {
    try {
      const result = await apiFetch<{ ok: boolean; agent_run_id?: number; status?: string; error?: string }>(
        `/automations/${id}/run`,
        { method: "POST", body: JSON.stringify({ subject: "Test subject", from: "test@example.com", body: "Manual test run." }) }
      );
      if (result.ok) {
        setBanner({
          variant: "success",
          message: `Test run started — agent run #${result.agent_run_id} · ${result.status}`
        });
      } else {
        setBanner({ variant: "error", message: result.error || "Test failed" });
      }
    } catch (e) {
      setBanner({ variant: "error", message: e instanceof Error ? e.message : "Failed" });
    }
  };

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold">Automations</h1>
        <p className="mt-1 text-sm text-slate-600">
          Trigger the agent whenever an inbound email matches a rule. The agent can propose replies, calendar
          events, and other actions — which remain human-gated in the Cockpit inbox.
        </p>
      </div>

      {banner ? (
        <div className="mb-4">
          <AlertBanner variant={banner.variant} message={banner.message} onDismiss={() => setBanner(null)} />
        </div>
      ) : null}

      <Card className="p-5">
        <h2 className="text-lg font-semibold">New rule</h2>
        <form className="mt-4 grid gap-3" onSubmit={(e) => void add(e)}>
          <label className="text-sm font-medium text-slate-800">
            Name
            <Input className="mt-1" value={name} onChange={(e) => setName(e.target.value)} placeholder="Auto-reply to venue inquiries" />
          </label>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="text-sm font-medium text-slate-800">
              From contains
              <Input
                className="mt-1"
                value={fromContains}
                onChange={(e) => setFromContains(e.target.value)}
                placeholder="@venue.com"
              />
            </label>
            <label className="text-sm font-medium text-slate-800">
              Subject contains
              <Input
                className="mt-1"
                value={subjectContains}
                onChange={(e) => setSubjectContains(e.target.value)}
                placeholder="booking"
              />
            </label>
            <label className="text-sm font-medium text-slate-800">
              Body contains
              <Input
                className="mt-1"
                value={bodyContains}
                onChange={(e) => setBodyContains(e.target.value)}
                placeholder="festival"
              />
            </label>
          </div>
          <label className="text-sm font-medium text-slate-800">
            Prompt template
            <textarea
              className="mt-1 min-h-[140px] w-full rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs"
              value={promptTemplate}
              onChange={(e) => setPromptTemplate(e.target.value)}
              spellCheck={false}
            />
            <span className="mt-1 block text-xs text-slate-500">
              Placeholders: <code>{"{subject}"}</code>, <code>{"{from}"}</code>, <code>{"{body}"}</code>,
              <code>{"{thread_id}"}</code>, <code>{"{email_id}"}</code>
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={autoApprove} onChange={(e) => setAutoApprove(e.target.checked)} />
            Auto-approve agent proposals (advanced — off by default)
          </label>
          <Button type="submit" className="w-fit bg-slate-900 text-white hover:bg-slate-800" disabled={loading}>
            Save rule
          </Button>
        </form>
      </Card>

      <Card className="mt-6 p-5">
        <h2 className="text-lg font-semibold">Rules</h2>
        {rows.length === 0 ? (
          <p className="mt-2 text-sm text-slate-500">No automations yet.</p>
        ) : (
          <ul className="mt-4 space-y-3">
            {rows.map((r) => (
              <li key={r.id} className="rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-semibold">{r.name}</span>
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{r.trigger}</span>
                      <span
                        className={`rounded px-2 py-0.5 text-xs ${
                          r.enabled ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"
                        }`}
                      >
                        {r.enabled ? "enabled" : "disabled"}
                      </span>
                      {r.auto_approve ? (
                        <span className="rounded bg-amber-100 px-2 py-0.5 text-xs text-amber-800">auto-approve</span>
                      ) : null}
                    </div>
                    <div className="mt-1 text-xs text-slate-500">
                      runs: {r.run_count} · last: {r.last_run_at ? new Date(r.last_run_at).toLocaleString() : "never"}
                    </div>
                    <div className="mt-1 text-xs text-slate-600">
                      conditions: <code className="font-mono">{JSON.stringify(r.conditions)}</code>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Button type="button" className="text-xs" onClick={() => void toggle(r)}>
                      {r.enabled ? "Disable" : "Enable"}
                    </Button>
                    <Button type="button" className="text-xs" onClick={() => void testRun(r.id)}>
                      Test run
                    </Button>
                    <Button type="button" className="border-dashed text-xs" onClick={() => void remove(r.id)}>
                      Delete
                    </Button>
                  </div>
                </div>
                <pre className="mt-3 whitespace-pre-wrap rounded bg-slate-50 p-2 text-xs text-slate-700">
                  {r.prompt_template}
                </pre>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
