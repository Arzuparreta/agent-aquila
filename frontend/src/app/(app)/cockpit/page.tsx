"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import { useAsyncAction } from "@/lib/useAsyncAction";
import { PendingOperationCard } from "@/components/features/cockpit/pending-operation-card";
import { AgentRun, PendingProposal } from "@/types/api";

export default function CockpitPage() {
  const { t } = useTranslation();
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
      setMessages((m) => [...m, { role: "assistant", text: runAgent.error || t("cockpit.requestFailed") }]);
      return;
    }

    setLastRun(result);
    let reply = (result.assistant_reply || "").trim();
    if (!reply) {
      reply = result.error ? t("cockpit.errorPrefix", { message: result.error }) : t("cockpit.noReply");
    }
    if (result.status !== "completed") {
      reply = `${reply}\n\n${t("cockpit.statusSuffix", { status: result.status })}`;
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
      setBanner({ variant: "success", message: t("cockpit.proposalApproved") });
      await loadInbox();
    }
  };

  const reject = async (id: number) => {
    setBanner(null);
    const ok = await proposalAction.run(() =>
      apiFetch<PendingProposal>(`/agent/proposals/${id}/reject`, { method: "POST" })
    );
    if (ok) {
      setBanner({ variant: "info", message: t("cockpit.proposalRejected") });
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
      const summary = Object.entries(counts)
        .map(([k, v]) => `${k} ${v}`)
        .join(", ");
      setBanner({
        variant: "success",
        message: t("cockpit.reindexed", { summary })
      });
    }
  };

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 lg:flex-row">
      <div className="min-w-0 flex-1">
        <h1 className="mb-2 text-2xl font-semibold">{t("cockpit.title")}</h1>
        <p className="mb-4 text-sm text-slate-600">{t("cockpit.intro")}</p>

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
            {messages.length === 0 ? <p className="text-slate-500">{t("cockpit.example")}</p> : null}
            {messages.map((msg, i) => (
              <div
                key={`${i}-${msg.role}`}
                className={`rounded-lg px-3 py-2 ${
                  msg.role === "user" ? "ml-8 bg-slate-900 text-white" : "mr-8 border border-slate-200 bg-white"
                }`}
              >
                <div className="text-xs font-medium opacity-70">{msg.role === "user" ? t("cockpit.you") : t("cockpit.copilot")}</div>
                <div className="mt-1 whitespace-pre-wrap">{msg.text}</div>
              </div>
            ))}
          </div>
          <form className="flex gap-2 border-t border-slate-100 pt-3" onSubmit={(e) => void send(e)}>
            <Input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={t("cockpit.askPlaceholder")}
              disabled={runAgent.pending}
            />
            <Button type="submit" className="shrink-0 bg-slate-900 text-white hover:bg-slate-800" disabled={runAgent.pending}>
              {runAgent.pending ? t("common.ellipsis") : t("common.send")}
            </Button>
          </form>
          {runAgent.error ? <p className="mt-2 text-xs text-red-600">{runAgent.error}</p> : null}
        </Card>

        {lastRun && lastRun.steps.length > 0 ? (
          <details className="text-xs text-slate-600">
            <summary className="cursor-pointer font-medium text-slate-800">{t("cockpit.trace")}</summary>
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
        <h2 className="mb-2 text-lg font-semibold">{t("cockpit.approvals")}</h2>
        <p className="mb-3 text-xs text-slate-600">{t("cockpit.approvalsIntro")}</p>

        <div className="mb-4 flex flex-wrap gap-2">
          <Button
            type="button"
            className="border-dashed text-xs"
            disabled={backfillAction.pending}
            onClick={() => void backfill()}
          >
            {backfillAction.pending ? t("cockpit.reindexing") : t("cockpit.reindex")}
          </Button>
          <Link href="/settings" className="text-xs text-slate-600 underline">
            {t("cockpit.aiAndConnectors")}
          </Link>
        </div>
        {backfillAction.error ? <p className="mb-2 text-xs text-red-600">{backfillAction.error}</p> : null}

        <div className="space-y-3">
          {inbox.length === 0 ? (
            <Card className="p-3 text-sm text-slate-600">{t("cockpit.noProposals")}</Card>
          ) : (
            inbox.map((p) => (
              <PendingOperationCard
                key={p.id}
                proposal={p}
                busy={proposalAction.pending}
                onApprove={(id) => void approve(id)}
                onReject={(id) => void reject(id)}
              />
            ))
          )}
        </div>
      </aside>
    </div>
  );
}
