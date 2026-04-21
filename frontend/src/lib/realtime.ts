/**
 * WebSocket + HTTP polling for agent run terminal state. Events originate from
 * :mod:`app.services.agent_event_bus` (Redis fan-out) and ``GET /agent/runs/{id}``.
 */
import { apiFetch, ApiError } from "@/lib/api";
import type { AgentRun } from "@/types/api";

export type AgentRunWsSnapshot = {
  id: number;
  status: string;
  error: string | null;
};

const DEFAULT_MAX_WAIT_MS = 3_700_000; // just over 1h server cap
const POLL_INTERVAL_MS = 1800;

function buildRealtimeWsUrl(token: string): string {
  const fromEnv = (process.env.NEXT_PUBLIC_WS_URL || "").trim().replace(/\/$/, "");
  if (fromEnv) {
    return `${fromEnv}/api/v1/realtime/ws?token=${encodeURIComponent(token)}`;
  }
  if (typeof window === "undefined") {
    return "";
  }
  const { protocol, host } = window.location;
  const wsProto = protocol === "https:" ? "wss:" : "ws:";
  return `${wsProto}//${host}/api/v1/realtime/ws?token=${encodeURIComponent(token)}`;
}

function isTerminalStatus(status: string): boolean {
  return status === "completed" || status === "failed";
}

/**
 * Resolves when the run reaches a terminal state, using ``GET /agent/runs/{id}``
 * (reliable) plus the realtime WebSocket (low latency). WebSocket errors do not
 * fail the wait while polling can still succeed.
 */
export function waitForRunTerminal(
  runId: number,
  options: { maxWaitMs?: number } = {}
): Promise<AgentRunWsSnapshot> {
  const maxWaitMs = options.maxWaitMs ?? DEFAULT_MAX_WAIT_MS;
  const token =
    typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
  if (!token) {
    return Promise.reject(new ApiError("Not logged in", 401));
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    let ws: WebSocket | null = null;
    let pollInterval: number | null = null;
    let deadlineTimer: number | null = null;

    const cleanup = () => {
      if (pollInterval != null) {
        window.clearInterval(pollInterval);
        pollInterval = null;
      }
      if (deadlineTimer != null) {
        window.clearTimeout(deadlineTimer);
        deadlineTimer = null;
      }
      if (ws) {
        try {
          ws.close();
        } catch {
          // ignore
        }
        ws = null;
      }
    };

    const settle = (snapshot: AgentRunWsSnapshot) => {
      if (settled) return;
      settled = true;
      cleanup();
      resolve(snapshot);
    };

    const fail = (err: ApiError) => {
      if (settled) return;
      settled = true;
      cleanup();
      reject(err);
    };

    deadlineTimer = window.setTimeout(() => {
      fail(
        new ApiError(
          "The assistant is still running after a long wait. Check that the worker container is up and Redis is reachable.",
          408,
          { kind: "ws_timeout" }
        )
      );
    }, maxWaitMs);

    const pollOnce = async () => {
      if (settled) return;
      try {
        const run = await apiFetch<AgentRun>(`/agent/runs/${runId}`);
        if (isTerminalStatus(run.status)) {
          settle({
            id: runId,
            status: run.status,
            error: run.error ?? null,
          });
        }
      } catch (err) {
        if (settled) return;
        if (err instanceof ApiError && err.status === 404) {
          fail(err);
        }
      }
    };

    void pollOnce();
    pollInterval = window.setInterval(() => {
      void pollOnce();
    }, POLL_INTERVAL_MS);

    const url = buildRealtimeWsUrl(token);
    if (!url) {
      return;
    }

    ws = new WebSocket(url);
    ws.onopen = () => {
      void pollOnce();
    };
    ws.onmessage = (ev) => {
      if (settled) return;
      let data: Record<string, unknown>;
      try {
        data = JSON.parse(ev.data as string) as Record<string, unknown>;
      } catch {
        return;
      }
      if (data.run_id == null || Number(data.run_id) !== runId) {
        return;
      }
      if (data.t !== "run.status" || !data.terminal) {
        return;
      }
      const st = data.status;
      if (st !== "completed" && st !== "failed") {
        return;
      }
      settle({
        id: runId,
        status: String(st),
        error: data.error == null ? null : String(data.error),
      });
    };
    ws.onerror = () => {
      // HTTP polling continues as the reliable path.
    };
    ws.onclose = () => {
      // Unclean closes are common behind proxies; polling continues until terminal or deadline.
    };
  });
}
