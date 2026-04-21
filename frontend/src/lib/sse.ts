/**
 * Server-Sent Events client for `GET /api/v1/agent/runs/{id}/stream` (see backend agent routes).
 * Uses `fetch` + `ReadableStream` so `Authorization: Bearer` works (unlike `EventSource`).
 */
import { ApiError } from "@/lib/api";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/$/, "");

/** Last JSON payload for a run snapshot from the SSE stream. */
export type AgentRunSseSnapshot = {
  id: number;
  status: string;
  error: string | null;
  step_count: number;
};

function parseSseDataBlocks(buffer: string): { events: string[]; rest: string } {
  const events: string[] = [];
  let rest = buffer;
  let idx: number;
  while ((idx = rest.indexOf("\n\n")) >= 0) {
    const block = rest.slice(0, idx);
    rest = rest.slice(idx + 2);
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith("data: ")) {
        dataLines.push(line.slice(6));
      }
    }
    if (dataLines.length) {
      events.push(dataLines.join("\n"));
    }
  }
  return { events, rest };
}

/**
 * Subscribe until the run reaches ``completed`` or ``failed`` (or the server ends the stream).
 * Throws ``ApiError`` for HTTP errors, 404, stream timeout, or an empty/incomplete body.
 */
export async function streamAgentRunUntilTerminal(
  runId: number,
  init?: { signal?: AbortSignal }
): Promise<AgentRunSseSnapshot> {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
  const url = `${API_URL}/agent/runs/${runId}/stream`;
  const response = await fetch(url, {
    method: "GET",
    headers: {
      Accept: "text/event-stream",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    signal: init?.signal,
    cache: "no-store",
  });

  if (!response.ok) {
    const text = (await response.text()).trim();
    throw new ApiError(
      text.slice(0, 300) || `HTTP ${response.status}`,
      response.status
    );
  }
  if (!response.body) {
    throw new ApiError("The server sent an empty body for the run stream.", 502, {
      kind: "sse_no_body",
    });
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let last: AgentRunSseSnapshot | null = null;

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      buffer += decoder.decode(value, { stream: true });
      const { events, rest } = parseSseDataBlocks(buffer);
      buffer = rest;
      for (const raw of events) {
        let data: Record<string, unknown>;
        try {
          data = JSON.parse(raw) as Record<string, unknown>;
        } catch {
          throw new ApiError("The run stream sent invalid data.", 502, { kind: "sse_bad_json" });
        }
        if (typeof data.error === "string" && typeof data.status !== "string") {
          if (data.error === "not_found") {
            throw new ApiError("Run not found", 404);
          }
          if (data.error === "sse_timeout") {
            throw new ApiError(
              "The assistant is still running after a long wait. Check that the worker container is up and Redis is reachable.",
              408,
              { kind: "sse_timeout" }
            );
          }
        }
        if (typeof data.status === "string" && typeof data.id === "number") {
          const snap: AgentRunSseSnapshot = {
            id: data.id,
            status: data.status,
            error: data.error == null ? null : String(data.error),
            step_count: typeof data.step_count === "number" ? data.step_count : 0,
          };
          last = snap;
          if (snap.status === "completed" || snap.status === "failed") {
            return snap;
          }
        }
      }
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }

  if (!last) {
    throw new ApiError("The run stream closed before any status was received.", 502, {
      kind: "sse_incomplete",
    });
  }
  if (last.status === "completed" || last.status === "failed") {
    return last;
  }
  throw new ApiError("The run stream closed before the assistant finished.", 502, {
    kind: "sse_closed_early",
  });
}
