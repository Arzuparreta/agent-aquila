/**
 * Pure helpers for the local telemetry dashboard (no network).
 */

import type { TelemetryEvent } from "./types";

export type VersionBucket = {
  version: string;
  total: number;
  errors: number;
  warnings: number;
  info: number;
};

export type GroupRow = {
  groupKey: string;
  kind: string;
  message: string;
  count: number;
  versions: string[];
  lastTs: string;
  apiPathGroup: string | null;
};

export function aggregateByVersion(events: TelemetryEvent[]): VersionBucket[] {
  const map = new Map<string, VersionBucket>();
  for (const e of events) {
    const v = e.appVersion || "unknown";
    if (!map.has(v)) {
      map.set(v, { version: v, total: 0, errors: 0, warnings: 0, info: 0 });
    }
    const b = map.get(v)!;
    b.total++;
    if (e.severity === "error") b.errors++;
    else if (e.severity === "warning") b.warnings++;
    else b.info++;
  }
  return [...map.values()].sort((a, b) => b.total - a.total);
}

export function aggregateIssueMap(events: TelemetryEvent[], versionFilter: string | null): GroupRow[] {
  const list = versionFilter ? events.filter((e) => e.appVersion === versionFilter) : events;
  const map = new Map<string, GroupRow>();
  for (const e of list) {
    const gk = e.groupKey;
    if (!map.has(gk)) {
      map.set(gk, {
        groupKey: gk,
        kind: e.kind,
        message: e.message,
        count: 0,
        versions: [],
        lastTs: e.ts,
        apiPathGroup: e.apiPathGroup,
      });
    }
    const row = map.get(gk)!;
    row.count++;
    if (e.ts > row.lastTs) row.lastTs = e.ts;
    if (!row.versions.includes(e.appVersion)) row.versions.push(e.appVersion);
  }
  return [...map.values()].sort((a, b) => b.count - a.count);
}

export function countBySeverity(events: TelemetryEvent[]): {
  errors: number;
  warnings: number;
  info: number;
} {
  let errors = 0;
  let warnings = 0;
  let info = 0;
  for (const e of events) {
    if (e.severity === "error") errors++;
    else if (e.severity === "warning") warnings++;
    else info++;
  }
  return { errors, warnings, info };
}
