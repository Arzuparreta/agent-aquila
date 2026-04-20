"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { intlLocaleTag, useTranslation } from "@/lib/i18n";

type MemoryRow = {
  id: number;
  key: string;
  content: string;
  importance: number;
  tags?: string[] | null;
  updated_at?: string | null;
};

/**
 * Read-only viewer over the agent's persistent memory scratchpad
 * (``GET /memory``). Lets the user browse what the agent has remembered
 * and prune entries that no longer make sense; agent-driven writes happen
 * elsewhere via the ``upsert_memory`` tool.
 */
export function MemorySection() {
  const { t, locale } = useTranslation();
  const [rows, setRows] = useState<MemoryRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<MemoryRow[]>("/memory?limit=200");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("memory.loadError"));
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const onDelete = useCallback(
    async (key: string) => {
      if (!confirm(t("memory.deleteConfirm", { key }))) return;
      setBusy(key);
      try {
        await apiFetch(`/memory/${encodeURIComponent(key)}`, { method: "DELETE" });
        setRows((prev) => prev?.filter((r) => r.key !== key) ?? null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : t("memory.deleteError"));
      } finally {
        setBusy(null);
      }
    },
    [t],
  );

  return (
    <div className="grid gap-2">
      <p className="text-xs text-fg-subtle">{t("memory.intro")}</p>
      {error ? (
        <div
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-200"
        >
          {error}
        </div>
      ) : null}
      {rows === null ? (
        <p className="text-xs text-fg-subtle">{t("common.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-xs text-fg-subtle">{t("memory.empty")}</p>
      ) : (
        <ul className="divide-y divide-border-subtle rounded-md border border-border-subtle bg-surface-elevated">
          {rows.map((row) => (
            <li key={row.id} className="grid gap-1 px-3 py-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-mono text-fg">
                    {row.key}
                  </div>
                  {row.tags && row.tags.length > 0 ? (
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {row.tags.map((t) => (
                        <span
                          key={t}
                          className="rounded-full bg-surface-muted px-1.5 py-0.5 text-[10px] text-fg-subtle"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
                <button
                  onClick={() => void onDelete(row.key)}
                  disabled={busy === row.key}
                  className="shrink-0 rounded-md px-2 py-0.5 text-xs text-rose-300 hover:bg-rose-700/30 disabled:opacity-60"
                >
                  {t("memory.delete")}
                </button>
              </div>
              <p className="whitespace-pre-wrap text-xs text-fg-muted">
                {row.content}
              </p>
              {row.updated_at ? (
                <div className="text-[11px] text-fg-subtle">
                  {t("memory.updated", {
                    when: new Date(row.updated_at).toLocaleString(intlLocaleTag(locale))
                  })}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
