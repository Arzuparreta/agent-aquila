/**
 * Record local telemetry events (browser-only). All user-facing copy lives in i18n.
 */

import { TELEMETRY_CHANGED_EVENT, TELEMETRY_ENABLED_KEY } from "./constants";
import { putTelemetryEvent } from "./store";
import type { TelemetryEvent, TelemetryKind, TelemetrySeverity } from "./types";

const SLOW_MS = 4000;

export function getAppVersionLabel(): string {
  return process.env.NEXT_PUBLIC_APP_VERSION ?? "0.0.0-dev";
}

export function getBuildIdLabel(): string | null {
  const v = process.env.NEXT_PUBLIC_APP_BUILD_ID?.trim();
  return v || null;
}

export function isTelemetryEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return window.localStorage.getItem(TELEMETRY_ENABLED_KEY) === "1";
}

export function getTelemetryEnabled(): boolean {
  return isTelemetryEnabled();
}

export function setTelemetryEnabled(value: boolean): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TELEMETRY_ENABLED_KEY, value ? "1" : "0");
  window.dispatchEvent(new Event(TELEMETRY_CHANGED_EVENT));
}

export function normalizeApiPath(path: string): string {
  const p = path.split("?")[0];
  return p.replace(/\/\d+/g, "/:id");
}

export function summarizeDetail(detail: unknown): Record<string, unknown> | null {
  if (detail === undefined || detail === null) return null;
  if (typeof detail === "object" && !Array.isArray(detail)) {
    const o = detail as Record<string, unknown>;
    const out: Record<string, unknown> = {};
    for (const k of ["kind", "message", "connection_id", "retry_after_seconds"]) {
      if (k in o) out[k] = o[k];
    }
    return Object.keys(out).length ? out : null;
  }
  return null;
}

function severityForHttpStatus(status: number): TelemetrySeverity {
  if (status >= 500) return "error";
  if (status === 429) return "warning";
  if (status >= 400) return "warning";
  return "info";
}

function buildGroupKey(
  kind: TelemetryKind,
  apiPathGroup: string | null,
  status: number | null,
  message: string,
): string {
  return `${kind}|${apiPathGroup ?? ""}|${status ?? ""}|${message.slice(0, 160)}`;
}

function baseEvent(): Pick<
  TelemetryEvent,
  "id" | "ts" | "appVersion" | "buildId" | "route"
> {
  return {
    id:
      typeof crypto !== "undefined" && "randomUUID" in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`,
    ts: new Date().toISOString(),
    appVersion: getAppVersionLabel(),
    buildId: getBuildIdLabel(),
    route: typeof window !== "undefined" ? window.location.pathname : null,
  };
}

export function recordTelemetryApiError(payload: {
  path: string;
  method: string;
  status: number;
  durationMs: number;
  message: string;
  detail: unknown;
}): void {
  if (!isTelemetryEnabled()) return;
  const apiPathGroup = normalizeApiPath(payload.path);
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "api_error",
    severity: severityForHttpStatus(payload.status),
    apiPath: payload.path.split("?")[0],
    apiPathGroup,
    method: payload.method,
    status: payload.status,
    durationMs: Math.round(payload.durationMs),
    message: payload.message.slice(0, 500),
    groupKey: buildGroupKey("api_error", apiPathGroup, payload.status, payload.message),
    detail: summarizeDetail(payload.detail),
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetrySlowRequest(payload: {
  path: string;
  method: string;
  durationMs: number;
  status: number;
}): void {
  if (!isTelemetryEnabled()) return;
  if (payload.durationMs < SLOW_MS) return;
  const apiPathGroup = normalizeApiPath(payload.path);
  const msg = `Slow request ${Math.round(payload.durationMs)} ms`;
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "slow_request",
    severity: "warning",
    apiPath: payload.path.split("?")[0],
    apiPathGroup,
    method: payload.method,
    status: payload.status,
    durationMs: Math.round(payload.durationMs),
    message: msg,
    groupKey: buildGroupKey("slow_request", apiPathGroup, payload.status, msg),
    detail: null,
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryNetworkError(payload: {
  path: string;
  method: string;
  error: unknown;
}): void {
  if (!isTelemetryEnabled()) return;
  const apiPathGroup = normalizeApiPath(payload.path);
  const msg =
    payload.error instanceof Error
      ? payload.error.message.slice(0, 400)
      : String(payload.error).slice(0, 400);
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "network_error",
    severity: "error",
    apiPath: payload.path.split("?")[0],
    apiPathGroup,
    method: payload.method,
    status: null,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("network_error", apiPathGroup, null, msg),
    detail: null,
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryClientError(payload: {
  message: string;
  source?: string | null;
}): void {
  if (!isTelemetryEnabled()) return;
  const msg = payload.message.slice(0, 500);
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "client_error",
    severity: "error",
    apiPath: null,
    apiPathGroup: null,
    method: null,
    status: null,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("client_error", payload.source ?? null, null, msg),
    detail: payload.source ? { source: payload.source } : null,
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryAgentRunFailed(payload: {
  runId: number;
  error: string | null;
}): void {
  if (!isTelemetryEnabled()) return;
  const msg = (payload.error || "agent run failed").slice(0, 500);
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "agent_run_failed",
    severity: "error",
    apiPath: `/agent/runs/${payload.runId}`,
    apiPathGroup: "/agent/runs/:id",
    method: "GET",
    status: null,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("agent_run_failed", "/agent/runs/:id", null, msg),
    detail: { run_id: payload.runId },
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryAssistantPollTimeout(): void {
  if (!isTelemetryEnabled()) return;
  const msg = "Assistant run polling timed out (worker or Redis?)";
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "assistant_poll_timeout",
    severity: "warning",
    apiPath: null,
    apiPathGroup: null,
    method: null,
    status: 408,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("assistant_poll_timeout", null, 408, msg),
    detail: null,
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryAssistantSseTimeout(): void {
  if (!isTelemetryEnabled()) return;
  const msg = "Assistant run SSE hit max wait (worker or Redis?)";
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "assistant_sse_timeout",
    severity: "warning",
    apiPath: null,
    apiPathGroup: "/agent/runs/:id/stream",
    method: "GET",
    status: 408,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("assistant_sse_timeout", "/agent/runs/:id/stream", 408, msg),
    detail: null,
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryAssistantSseError(payload: {
  runId: number;
  status: number;
  message: string;
}): void {
  if (!isTelemetryEnabled()) return;
  const msg = payload.message.slice(0, 500);
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "assistant_sse_error",
    severity: payload.status >= 500 ? "error" : "warning",
    apiPath: `/agent/runs/${payload.runId}/stream`,
    apiPathGroup: "/agent/runs/:id/stream",
    method: "GET",
    status: payload.status,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("assistant_sse_error", "/agent/runs/:id/stream", payload.status, msg),
    detail: { run_id: payload.runId },
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryAssistantWsTimeout(): void {
  if (!isTelemetryEnabled()) return;
  const msg = "Assistant run WebSocket wait timed out (worker or Redis?)";
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "assistant_ws_timeout",
    severity: "warning",
    apiPath: "/api/v1/realtime/ws",
    apiPathGroup: "/api/v1/realtime/ws",
    method: "WS",
    status: 408,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("assistant_ws_timeout", "/api/v1/realtime/ws", 408, msg),
    detail: null,
  };
  void putTelemetryEvent(ev);
}

export function recordTelemetryAssistantWsError(payload: {
  runId: number;
  status: number;
  message: string;
}): void {
  if (!isTelemetryEnabled()) return;
  const msg = payload.message.slice(0, 500);
  const ev: TelemetryEvent = {
    ...baseEvent(),
    kind: "assistant_ws_error",
    severity: payload.status >= 500 ? "error" : "warning",
    apiPath: "/api/v1/realtime/ws",
    apiPathGroup: "/api/v1/realtime/ws",
    method: "WS",
    status: payload.status,
    durationMs: null,
    message: msg,
    groupKey: buildGroupKey("assistant_ws_error", "/api/v1/realtime/ws", payload.status, msg),
    detail: { run_id: payload.runId },
  };
  void putTelemetryEvent(ev);
}
