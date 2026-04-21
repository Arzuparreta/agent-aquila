"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { StatusToast } from "@/components/ui/status-toast";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import {
  aggregateByVersion,
  aggregateIssueMap,
  countBySeverity,
} from "@/lib/telemetry/aggregate";
import { TELEMETRY_CHANGED_EVENT } from "@/lib/telemetry/constants";
import {
  getAppVersionLabel,
  getBuildIdLabel,
  isTelemetryEnabled,
} from "@/lib/telemetry/record";
import { clearAllTelemetryEvents, getAllTelemetryEvents } from "@/lib/telemetry/store";
import type { TelemetryEvent } from "@/lib/telemetry/types";

function formatTelemetryKind(
  kind: string,
  t: (key: TranslationKey, params?: Record<string, string | number>) => string,
): string {
  const keys: Record<string, TranslationKey> = {
    api_error: "telemetry.kind.api_error",
    slow_request: "telemetry.kind.slow_request",
    network_error: "telemetry.kind.network_error",
    client_error: "telemetry.kind.client_error",
    agent_run_failed: "telemetry.kind.agent_run_failed",
    assistant_poll_timeout: "telemetry.kind.assistant_poll_timeout",
  };
  const k = keys[kind];
  return k ? t(k) : kind;
}

export function TelemetryDashboard() {
  const { t } = useTranslation();
  const [events, setEvents] = useState<TelemetryEvent[]>([]);
  const [versionFilter, setVersionFilter] = useState<string>("");
  const [clearOpen, setClearOpen] = useState(false);
  const [clearPending, setClearPending] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const rows = await getAllTelemetryEvents();
    setEvents(rows);
  }, []);

  useEffect(() => {
    void reload();
    const onChange = () => void reload();
    window.addEventListener(TELEMETRY_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(TELEMETRY_CHANGED_EVENT, onChange);
  }, [reload]);

  const versions = useMemo(() => {
    const s = new Set<string>();
    for (const e of events) {
      s.add(e.appVersion || "unknown");
    }
    return [...s].sort();
  }, [events]);

  const currentVersion = getAppVersionLabel();
  const buildId = getBuildIdLabel();

  const byVersion = useMemo(() => aggregateByVersion(events), [events]);
  const issueRows = useMemo(
    () => aggregateIssueMap(events, versionFilter || null),
    [events, versionFilter],
  );
  const severity = useMemo(() => countBySeverity(events), [events]);

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(events, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `aquila-telemetry-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const onClear = async () => {
    setClearPending(true);
    try {
      await clearAllTelemetryEvents();
      await reload();
      setToast(t("telemetry.clearedToast"));
    } finally {
      setClearPending(false);
      setClearOpen(false);
    }
  };

  useEffect(() => {
    if (!toast) return;
    const id = window.setTimeout(() => setToast(null), 2400);
    return () => window.clearTimeout(id);
  }, [toast]);

  const active = isTelemetryEnabled();

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border border-border bg-surface-muted/40 px-4 py-3 text-sm text-fg">
        <div className="font-medium">{t("telemetry.currentBuild")}</div>
        <div className="mt-1 font-mono text-xs text-fg-muted">
          {t("telemetry.versionLine", {
            version: currentVersion,
            build: buildId || t("telemetry.buildUnknown"),
          })}
        </div>
        {!active ? (
          <p className="mt-2 text-amber-700 dark:text-amber-300">{t("telemetry.collectOffHint")}</p>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-4">
        <StatCard label={t("telemetry.statsTotal")} value={events.length} />
        <StatCard label={t("telemetry.statsErrors")} value={severity.errors} tone="err" />
        <StatCard label={t("telemetry.statsWarnings")} value={severity.warnings} tone="warn" />
        <StatCard label={t("telemetry.statsInfo")} value={severity.info} tone="info" />
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-sm text-fg">
          <span className="text-fg-muted">{t("telemetry.filterVersion")}</span>
          <select
            className="rounded-md border border-border bg-surface-base px-2 py-1.5 font-mono text-xs text-fg"
            value={versionFilter}
            onChange={(e) => setVersionFilter(e.target.value)}
          >
            <option value="">{t("telemetry.filterAllVersions")}</option>
            {versions.map((v) => (
              <option key={v} value={v}>
                {v}
                {v === currentVersion ? ` (${t("telemetry.thisVersion")})` : ""}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className="rounded-md border border-border bg-surface-base px-3 py-1.5 text-sm text-fg hover:bg-surface-muted"
          onClick={exportJson}
        >
          {t("telemetry.exportJson")}
        </button>
        <button
          type="button"
          className="rounded-md border border-rose-800/50 bg-rose-950/30 px-3 py-1.5 text-sm text-rose-100 hover:bg-rose-950/50"
          onClick={() => setClearOpen(true)}
        >
          {t("telemetry.clearAll")}
        </button>
      </div>

      <section>
        <h2 className="mb-2 text-base font-semibold">{t("telemetry.byVersionTitle")}</h2>
        <p className="mb-3 text-xs text-fg-subtle">{t("telemetry.byVersionHint")}</p>
        <div className="flex flex-col gap-2">
          {byVersion.length === 0 ? (
            <p className="text-sm text-fg-muted">{t("telemetry.empty")}</p>
          ) : (
            byVersion.map((b) => {
              const total = Math.max(b.errors + b.warnings + b.info, 1);
              const isCurrent = b.version === currentVersion;
              return (
                <div
                  key={b.version}
                  className={`rounded-md border px-3 py-2 text-sm ${
                    isCurrent
                      ? "border-emerald-700/50 bg-emerald-950/20"
                      : "border-border bg-surface-elevated"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="font-mono text-xs">
                      {b.version}
                      {isCurrent ? (
                        <span className="ml-2 text-emerald-600 dark:text-emerald-400">
                          {t("telemetry.thisVersion")}
                        </span>
                      ) : null}
                    </span>
                    <span className="text-xs text-fg-muted">
                      {t("telemetry.versionCounts", {
                        total: b.total,
                        errors: b.errors,
                        warnings: b.warnings,
                      })}
                    </span>
                  </div>
                  <div className="mt-2 flex h-2 w-full overflow-hidden rounded bg-surface-muted">
                    <div
                      className="h-full bg-rose-500"
                      style={{ width: `${(b.errors / total) * 100}%` }}
                      title={`errors ${b.errors}`}
                    />
                    <div
                      className="h-full bg-amber-500"
                      style={{ width: `${(b.warnings / total) * 100}%` }}
                      title={`warnings ${b.warnings}`}
                    />
                    <div
                      className="h-full bg-slate-500"
                      style={{ width: `${(b.info / total) * 100}%` }}
                      title={`info ${b.info}`}
                    />
                  </div>
                </div>
              );
            })
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-1 text-base font-semibold">{t("telemetry.issueMapTitle")}</h2>
        <p className="mb-3 text-xs text-fg-subtle">{t("telemetry.issueMapHint")}</p>
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full min-w-[36rem] border-collapse text-left text-sm">
            <thead className="bg-surface-muted text-xs text-fg-muted">
              <tr>
                <th className="px-2 py-2">{t("telemetry.tableKind")}</th>
                <th className="px-2 py-2">{t("telemetry.tableMessage")}</th>
                <th className="px-2 py-2">{t("telemetry.tableWhere")}</th>
                <th className="px-2 py-2">{t("telemetry.tableCount")}</th>
                <th className="px-2 py-2">{t("telemetry.tableVersions")}</th>
                <th className="px-2 py-2">{t("telemetry.tableLastSeen")}</th>
              </tr>
            </thead>
            <tbody>
              {issueRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-2 py-4 text-center text-fg-muted">
                    {t("telemetry.empty")}
                  </td>
                </tr>
              ) : (
                issueRows.slice(0, 40).map((row) => (
                  <tr key={row.groupKey} className="border-t border-border">
                    <td className="px-2 py-2 align-top text-xs">
                      {formatTelemetryKind(row.kind, t)}
                    </td>
                    <td className="max-w-[14rem] px-2 py-2 align-top text-xs text-fg">
                      {row.message}
                    </td>
                    <td className="px-2 py-2 align-top font-mono text-[10px] text-fg-muted">
                      {row.apiPathGroup ?? "—"}
                    </td>
                    <td className="px-2 py-2 align-top tabular-nums">{row.count}</td>
                    <td className="px-2 py-2 align-top font-mono text-[10px] text-fg-muted">
                      {row.versions.join(", ")}
                    </td>
                    <td className="px-2 py-2 align-top text-xs text-fg-muted">
                      {new Date(row.lastTs).toLocaleString()}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-base font-semibold">{t("telemetry.recentTitle")}</h2>
        <ul className="flex flex-col gap-2 text-xs">
          {events.length === 0 ? (
            <li className="text-fg-muted">{t("telemetry.empty")}</li>
          ) : (
            events.slice(0, 25).map((e) => (
              <li
                key={e.id}
                className="rounded border border-border bg-surface-elevated px-2 py-2 font-mono text-[11px] text-fg-muted"
              >
                <span className="text-fg">{formatTelemetryKind(e.kind, t)}</span>
                {" · "}
                <span>{e.appVersion}</span>
                {" · "}
                {new Date(e.ts).toLocaleString()}
                <div className="mt-1 text-fg">{e.message}</div>
              </li>
            ))
          )}
        </ul>
      </section>

      <ConfirmDialog
        open={clearOpen}
        title={t("telemetry.clearConfirmTitle")}
        description={t("telemetry.clearConfirmDescription")}
        confirmLabel={t("telemetry.clearConfirmButton")}
        onConfirm={() => void onClear()}
        onCancel={() => setClearOpen(false)}
        pending={clearPending}
      />

      {toast ? (
        <StatusToast
          kind="ok"
          text={toast}
          onDismiss={() => setToast(null)}
          dismissAriaLabel={t("chat.dismissToast")}
        />
      ) : null}
    </div>
  );
}

function StatCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "err" | "warn" | "info";
}) {
  const toneClass =
    tone === "err"
      ? "text-rose-400"
      : tone === "warn"
        ? "text-amber-400"
        : tone === "info"
          ? "text-slate-400"
          : "text-fg";
  return (
    <div className="rounded-lg border border-border bg-surface-elevated px-3 py-2">
      <div className="text-xs text-fg-muted">{label}</div>
      <div className={`text-2xl font-semibold tabular-nums ${toneClass}`}>{value}</div>
    </div>
  );
}
