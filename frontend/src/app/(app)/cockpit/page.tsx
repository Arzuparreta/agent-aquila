"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { useAsyncAction } from "@/lib/useAsyncAction";
import { AgentRun, PendingProposal } from "@/types/api";

function entityHref(entityType: string, id: number): string {
  switch (entityType) {
    case "contact":
      return `/contacts#${id}`;
    case "deal":
      return `/deals#${id}`;
    case "email":
      return `/emails#${id}`;
    case "event":
      return `/events#${id}`;
    default:
      return "#";
  }
}

export default function CockpitPage() {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<{ role: "user" | "assistant"; text: string }[]>([]);
  const [lastRun, setLastRun] = useState<AgentRun | null>(null);
  const [inbox, setInbox] = useState<PendingProposal[]>([]);
  const [banner, setBanner] = useState<{ variant: "error" | "success" | "info"; message: string } | null>(null);

  const runAgent = useAsyncAction();
  const proposalAction = useAsyncAction();
  const backfillAction = useAsyncAction();

  const loadInbox = useCallback(async () => {
    try {
      const rows = await apiFetch<PendingProposal[]>("/agent/proposals");
      setInbox(rows);
    } catch {
      setInbox([]);
    }
  }, []);

  useEffect(() => {
    void loadInbox();
  }, [loadInbox]);

  const send = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = input.trim();
    if (!text) return;
    setBanner(null);
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);

    const result = await runAgent.run(() =>
      apiFetch<AgentRun>("/agent/runs", {
        method: "POST",
        body: JSON.stringify({ message: text })
      })
    );

    if (!result) {
      setMessages((m) => [...m, { role: "assistant", text: runAgent.error || "Request failed." }]);
      return;
    }

    setLastRun(result);
    let reply = (result.assistant_reply || "").trim();
    if (!reply) {
      reply = result.error ? `Error: ${result.error}` : "No reply.";
    }
    if (result.status !== "completed") {
      reply = `${reply}\n\n(status: ${result.status})`;
    }
    setMessages((m) => [...m, { role: "assistant", text: reply }]);
    await loadInbox();
  };

  const approve = async (id: number) => {
    setBanner(null);
    const ok = await proposalAction.run(() =>
      apiFetch<PendingProposal>(`/agent/proposals/${id}/approve`, { method: "POST" })
    );
    if (ok) {
      setBanner({ variant: "success", message: "Proposal approved — deal created." });
      await loadInbox();
    }
  };

  const reject = async (id: number) => {
    setBanner(null);
    const ok = await proposalAction.run(() =>
      apiFetch<PendingProposal>(`/agent/proposals/${id}/reject`, { method: "POST" })
    );
    if (ok) {
      setBanner({ variant: "info", message: "Proposal rejected." });
      await loadInbox();
    }
  };

  const backfill = async () => {
    setBanner(null);
    const counts = await backfillAction.run(() =>
      apiFetch<Record<string, number>>("/ai/rag/backfill", {
        method: "POST",
        body: JSON.stringify({ limit_per_table: 60 })
      })
    );
    if (counts) {
      setBanner({
        variant: "success",
        message: `Reindexed rows: ${Object.entries(counts)
          .map(([k, v]) => `${k} ${v}`)
          .join(", ")}`
      });
    }
  };

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 lg:flex-row">
      <div className="min-w-0 flex-1">
        <h1 className="mb-2 text-2xl font-semibold">Operations cockpit</h1>
        <p className="mb-4 text-sm text-slate-600">
          Ask about festivals, bookings, and contacts. Answers use hybrid RAG (dense + keyword) over chunked CRM text.
          Deals are never created until a human approves a proposal.
        </p>

        {banner ? (
          <div className="mb-3">
            <AlertBanner variant={banner.variant} message={banner.message} onDismiss={() => setBanner(null)} />
          </div>
        ) : null}
        {proposalAction.error ? (
          <div className="mb-3">
            <AlertBanner variant="error" message={proposalAction.error} onDismiss={proposalAction.reset} />
          </div>
        ) : null}

        <Card className="mb-4 flex max-h-[min(70vh,720px)] flex-col p-4">
          <div className="mb-3 flex-1 space-y-3 overflow-y-auto text-sm">
            {messages.length === 0 ? (
              <p className="text-slate-500">
                Example: &quot;What open deals mention festivals this summer?&quot; or &quot;Summarize the last email from the
                Blue Note promoter.&quot;
              </p>
            ) : null}
            {messages.map((msg, i) => (
              <div
                key={`${i}-${msg.role}`}
                className={`rounded-lg px-3 py-2 ${
                  msg.role === "user" ? "ml-8 bg-slate-900 text-white" : "mr-8 border border-slate-200 bg-white"
                }`}
              >
                <div className="text-xs font-medium opacity-70">{msg.role === "user" ? "You" : "Copilot"}</div>
                <div className="mt-1 whitespace-pre-wrap">{msg.text}</div>
              </div>
            ))}
          </div>
          <form className="flex gap-2 border-t border-slate-100 pt-3" onSubmit={(e) => void send(e)}>
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about your CRM…"
              disabled={runAgent.pending}
            />
            <Button type="submit" className="shrink-0 bg-slate-900 text-white hover:bg-slate-800" disabled={runAgent.pending}>
              {runAgent.pending ? "…" : "Send"}
            </Button>
          </form>
          {runAgent.error ? (
            <p className="mt-2 text-xs text-red-600">{runAgent.error}</p>
          ) : null}
        </Card>

        {lastRun && lastRun.steps.length > 0 ? (
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer font-medium text-slate-800">Trace (agent steps)</summary>
            <ul className="mt-2 space-y-1 font-mono">
              {lastRun.steps.map((s) => (
                <li key={s.step_index}>
                  {s.step_index}. {s.kind} {s.name ? `— ${s.name}` : ""}
                </li>
              ))}
            </ul>
          </details>
        ) : null}
      </div>

      <aside className="w-full shrink-0 lg:w-96">
        <h2 className="mb-2 text-lg font-semibold">Human approvals</h2>
        <p className="mb-3 text-xs text-slate-600">
          Proposed deals from the copilot appear here until approved. Nothing is written to the pipeline without confirmation.
        </p>

        <div className="mb-4 flex flex-wrap gap-2">
          <Button
            type="button"
            className="border-dashed text-xs"
            disabled={backfillAction.pending}
            onClick={() => void backfill()}
          >
            {backfillAction.pending ? "Reindexing…" : "Reindex RAG (sample)"}
          </Button>
          <Link href="/settings" className="text-xs text-slate-600 underline">
            AI settings
          </Link>
        </div>
        {backfillAction.error ? (
          <p className="mb-2 text-xs text-red-600">{backfillAction.error}</p>
        ) : null}

        <div className="space-y-3">
          {inbox.length === 0 ? (
            <Card className="p-3 text-sm text-slate-600">No pending proposals.</Card>
          ) : (
            inbox.map((p) => (
              <Card key={p.id} className="p-3 text-sm">
                <div className="text-xs uppercase text-slate-500">
                  {p.kind} · #{p.id}
                </div>
                {p.kind === "create_deal" ? (
                  <div className="mt-2 space-y-1">
                    <div>
                      <span className="font-medium">Title:</span> {String(p.payload.title ?? "")}
                    </div>
                    <div>
                      <span className="font-medium">Contact:</span>{" "}
                      <Link href={entityHref("contact", Number(p.payload.contact_id))} className="text-blue-700 underline">
                        #{String(p.payload.contact_id)}
                      </Link>
                    </div>
                    <div>
                      <span className="font-medium">Status:</span> {String(p.payload.status ?? "new")}
                    </div>
                  </div>
                ) : (
                  <pre className="mt-2 max-h-32 overflow-auto text-xs">{JSON.stringify(p.payload, null, 2)}</pre>
                )}
                <div className="mt-3 flex gap-2">
                  <Button
                    type="button"
                    className="bg-emerald-700 text-white hover:bg-emerald-800"
                    disabled={proposalAction.pending}
                    onClick={() => void approve(p.id)}
                  >
                    Approve
                  </Button>
                  <Button type="button" className="border-dashed" disabled={proposalAction.pending} onClick={() => void reject(p.id)}>
                    Reject
                  </Button>
                </div>
              </Card>
            ))
          )}
        </div>
      </aside>
    </div>
  );
}
