/**
 * Local-only diagnostic events (IndexedDB). Never transmitted to a server.
 */

export type TelemetryKind =
  | "api_error"
  | "slow_request"
  | "network_error"
  | "client_error"
  | "agent_run_failed"
  | "assistant_poll_timeout"
  | "assistant_sse_timeout"
  | "assistant_sse_error"
  | "assistant_ws_timeout"
  | "assistant_ws_error";

export type TelemetrySeverity = "info" | "warning" | "error";

export type TelemetryEvent = {
  id: string;
  ts: string;
  appVersion: string;
  buildId: string | null;
  kind: TelemetryKind;
  severity: TelemetrySeverity;
  /** Browser route when the event was recorded (pathname). */
  route: string | null;
  /** Raw API path (e.g. /threads/5/messages). */
  apiPath: string | null;
  /** Normalised path for grouping (numeric ids → :id). */
  apiPathGroup: string | null;
  method: string | null;
  status: number | null;
  durationMs: number | null;
  message: string;
  /** Stable key for issue-map aggregation. */
  groupKey: string;
  /** Small structured hint (no secrets). */
  detail: Record<string, unknown> | null;
};
