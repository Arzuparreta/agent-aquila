"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ProtectedPage } from "@/components/features/protected-page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";

type OnboardingStatus = {
  database_ok: boolean;
  redis_ok: boolean;
  has_ai_provider: boolean;
  connector_count: number;
  telegram_configured: boolean;
  agent_async_runs: boolean;
};

type DashboardStatus = {
  database_ok: boolean;
  redis_configured: boolean;
  redis_ping_ok: boolean;
  arq_pool_ok: boolean;
};

type DashboardMetrics = {
  agent_runs_last_24h: number;
  agent_runs_completed_last_24h: number;
  agent_runs_failed_last_24h: number;
};

type AgentRunSummary = {
  id: number;
  status: string;
  user_message_preview: string;
  created_at: string;
  root_trace_id: string | null;
  chat_thread_id: number | null;
};

type AISettings = {
  agent_processing_paused: boolean;
};

export default function DashboardPage() {
  const [onb, setOnb] = useState<OnboardingStatus | null>(null);
  const [st, setSt] = useState<DashboardStatus | null>(null);
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [runs, setRuns] = useState<AgentRunSummary[]>([]);
  const [ai, setAi] = useState<AISettings | null>(null);
  const [pair, setPair] = useState<{ code: string; expires_at: string } | null>(null);
  const [tgLinked, setTgLinked] = useState<boolean | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    setErr(null);
    try {
      const [o, s, m, r, settings] = await Promise.all([
        apiFetch<OnboardingStatus>("/onboarding/status"),
        apiFetch<DashboardStatus>("/dashboard/status"),
        apiFetch<DashboardMetrics>("/dashboard/metrics"),
        apiFetch<AgentRunSummary[]>("/agent/runs?limit=20"),
        apiFetch<AISettings>("/ai/settings"),
      ]);
      setOnb(o);
      setSt(s);
      setMetrics(m);
      setRuns(r);
      setAi(settings);
      if (o.telegram_configured) {
        const ls = await apiFetch<{ linked: boolean }>("/telegram/link-status");
        setTgLinked(ls.linked);
      } else {
        setTgLinked(null);
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load dashboard");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const togglePause = async () => {
    if (!ai) return;
    const next = !ai.agent_processing_paused;
    const updated = await apiFetch<AISettings>("/ai/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_processing_paused: next }),
    });
    setAi(updated);
  };

  const genTelegramCode = async () => {
    setPair(null);
    const p = await apiFetch<{ code: string; expires_at: string }>("/telegram/pairing-code", {
      method: "POST",
    });
    setPair(p);
    void load();
  };

  return (
    <ProtectedPage>
      <div className="mx-auto flex min-h-screen max-w-3xl flex-col gap-4 p-4">
        <div className="flex items-center justify-between gap-2">
          <h1 className="text-xl font-semibold">Dashboard</h1>
          <div className="flex gap-2">
            <Link href="/" className="text-sm text-fg-muted underline">
              Chat
            </Link>
            <Link href="/settings" className="text-sm text-fg-muted underline">
              Settings
            </Link>
          </div>
        </div>

        {err ? (
          <Card className="border-rose-700/50 bg-rose-950/20 p-3 text-sm text-rose-200">{err}</Card>
        ) : null}

        <Card className="space-y-2 p-4">
          <h2 className="font-medium">Agent control</h2>
          {ai ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className="text-sm text-fg-muted">
                Status: {ai.agent_processing_paused ? "Paused" : "Running"}
              </span>
              <Button className="text-xs" onClick={() => void togglePause()}>
                {ai.agent_processing_paused ? "Resume agent" : "Pause agent"}
              </Button>
            </div>
          ) : (
            <p className="text-sm text-fg-muted">Loading…</p>
          )}
        </Card>

        <Card className="space-y-2 p-4">
          <h2 className="font-medium">Setup checklist</h2>
          {onb ? (
            <ul className="list-inside list-disc text-sm text-fg-muted">
              <li>Database: {onb.database_ok ? "OK" : "unreachable"}</li>
              <li>Redis: {onb.redis_ok ? "OK" : "not reachable (async chat may fall back to sync)"}</li>
              <li>AI provider selected: {onb.has_ai_provider ? "yes" : "no — open Settings → AI"}</li>
              <li>Connectors linked: {onb.connector_count}</li>
              <li>Telegram bot configured: {onb.telegram_configured ? "yes" : "no (TELEGRAM_BOT_TOKEN)"}</li>
              <li>Async agent runs: {onb.agent_async_runs ? "enabled" : "disabled or missing Redis"}</li>
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">Loading…</p>
          )}
        </Card>

        <Card className="space-y-2 p-4">
          <h2 className="font-medium">Live status</h2>
          {st ? (
            <ul className="list-inside list-disc text-sm text-fg-muted">
              <li>DB ping: {st.database_ok ? "OK" : "failed"}</li>
              <li>Redis URL set: {st.redis_configured ? "yes" : "no"}</li>
              <li>Redis ping: {st.redis_ping_ok ? "OK" : "failed"}</li>
              <li>ARQ pool: {st.arq_pool_ok ? "OK" : "not available"}</li>
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">Loading…</p>
          )}
        </Card>

        <Card className="space-y-2 p-4">
          <h2 className="font-medium">Last 24h activity</h2>
          {metrics ? (
            <ul className="text-sm text-fg-muted">
              <li>Runs: {metrics.agent_runs_last_24h}</li>
              <li>Completed: {metrics.agent_runs_completed_last_24h}</li>
              <li>Failed: {metrics.agent_runs_failed_last_24h}</li>
            </ul>
          ) : (
            <p className="text-sm text-fg-muted">Loading…</p>
          )}
        </Card>

        <Card className="space-y-3 p-4">
          <h2 className="font-medium">Telegram</h2>
          {onb?.telegram_configured ? (
            <>
              <p className="text-sm text-fg-muted">
                Linked: {tgLinked === null ? "…" : tgLinked ? "yes" : "no"}
              </p>
              <Button className="text-xs" onClick={() => void genTelegramCode()}>
                Generate link code
              </Button>
              {pair ? (
                <p className="rounded-md bg-surface-muted p-2 font-mono text-sm">
                  Send to the bot:{" "}
                  <strong>
                    /start {pair.code}
                  </strong>
                  <br />
                  <span className="text-fg-muted">Expires: {pair.expires_at}</span>
                </p>
              ) : null}
            </>
          ) : (
            <p className="text-sm text-fg-muted">
              Set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET on the server, register the webhook, then
              refresh this page.
            </p>
          )}
        </Card>

        <Card className="space-y-2 p-4">
          <h2 className="font-medium">Recent agent runs</h2>
          <ul className="space-y-2 text-sm">
            {runs.map((r) => (
              <li key={r.id} className="rounded-md border border-border-subtle p-2">
                <div className="flex justify-between gap-2">
                  <span className="font-mono text-xs text-fg-muted">#{r.id}</span>
                  <span className="text-xs uppercase text-fg-muted">{r.status}</span>
                </div>
                <p className="mt-1 text-fg">{r.user_message_preview}</p>
                {r.root_trace_id ? (
                  <Link
                    className="mt-1 inline-block text-xs text-accent underline"
                    href={`/settings`}
                    title="Open run in API client or add trace viewer here"
                  >
                    trace {r.root_trace_id.slice(0, 8)}…
                  </Link>
                ) : null}
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </ProtectedPage>
  );
}
