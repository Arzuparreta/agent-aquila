/**
 * WebSocket client for `GET /api/v1/realtime/ws?token=...` — JSON events from
 * :mod:`app.services.agent_event_bus` (Redis-fan-out).
 */
import { ApiError } from "@/lib/api";

export type AgentRunWsSnapshot = {
  id: number;
  status: string;
  error: string | null;
};

const DEFAULT_MAX_WAIT_MS = 3_700_000; // just over 1h server cap

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

/**
 * Resolves when the run emits a terminal ``run.status`` event for this ``runId``.
 */
export function waitForRunTerminalWebSocket(
  runId: number,
  options: { maxWaitMs?: number } = {}
): Promise<AgentRunWsSnapshot> {
  const maxWaitMs = options.maxWaitMs ?? DEFAULT_MAX_WAIT_MS;
  const token =
    typeof window !== "undefined" ? window.localStorage.getItem("token") : null;
  if (!token) {
    return Promise.reject(new ApiError("Not logged in", 401));
  }
  const url = buildRealtimeWsUrl(token);
  if (!url) {
    return Promise.reject(
      new ApiError("WebSocket URL is not available in this context.", 500, {
        kind: "ws_no_url",
      })
    );
  }
  return new Promise((resolve, reject) => {
    let settled = false;
    const ws = new WebSocket(url);
    const timer = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      try {
        ws.close();
      } catch {
        // ignore
      }
      reject(
        new ApiError(
          "The assistant is still running after a long wait. Check that the worker container is up and Redis is reachable.",
          408,
          { kind: "ws_timeout" }
        )
      );
    }, maxWaitMs);
    const done = (fn: () => void) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      fn();
    };
    ws.onmessage = (ev) => {
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
      done(() => {
        try {
          ws.close();
        } catch {
          // ignore
        }
        resolve({
          id: runId,
          status: String(st),
          error: data.error == null ? null : String(data.error),
        });
      });
    };
    ws.onerror = () => {
      done(() => {
        reject(
          new ApiError("WebSocket connection error", 502, { kind: "ws_error" })
        );
      });
    };
    ws.onclose = (ev) => {
      if (settled) return;
      if (ev.wasClean) {
        return;
      }
      done(() => {
        reject(
          new ApiError(`WebSocket closed (${ev.code})`, 502, { kind: "ws_close" })
        );
      });
    };
  });
}
