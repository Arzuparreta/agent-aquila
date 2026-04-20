"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import type { ChatThread } from "@/types/api";

import { ChatThreadList } from "./thread-list";
import { ChatThreadView } from "./thread-view";
import { ChatTopBar } from "./top-bar";

/**
 * Root mobile-first chat surface. Layout:
 *   - On phones: thread view fills the screen; the thread list slides in as an
 *     overlay drawer triggered from the top bar's hamburger.
 *   - On wider screens (md+): a permanent left rail shows the thread list and the
 *     chat view sits to the right (a stretched mobile layout, per the spec).
 *
 * State is intentionally local — there's no global store yet because this is a
 * single-user-per-instance app and the chat surface owns most of the live data.
 */
export function ChatHome() {
  const { t } = useTranslation();
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showArchived, setShowArchived] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ kind: "ok" | "error"; text: string; action?: { label: string; onClick: () => void } } | null>(null);

  const refreshThreads = useCallback(
    async (includeArchived = showArchived) => {
      try {
        const qs = includeArchived ? "?include_archived=true" : "";
        const rows = await apiFetch<ChatThread[]>(`/threads${qs}`);
        setThreads(rows);
        setActiveId((prev) => prev ?? rows.find((r) => !r.archived)?.id ?? rows[0]?.id ?? null);
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : t("chat.errors.loadThreadList"));
      } finally {
        setLoading(false);
      }
    },
    [showArchived, t]
  );

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

  // Auto-dismiss the inline status message after a few seconds.
  useEffect(() => {
    if (!statusMessage) return;
    const id = window.setTimeout(() => setStatusMessage(null), 6000);
    return () => window.clearTimeout(id);
  }, [statusMessage]);

  const visibleThreads = useMemo(
    () => threads.filter((t) => (showArchived ? t.archived : !t.archived)),
    [threads, showArchived]
  );

  // Honor `?thread=NN` deep-links from push notifications.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const target = Number(params.get("thread"));
    if (target > 0) setActiveId(target);
  }, [threads.length]);

  const activeThread = useMemo(
    () => threads.find((t) => t.id === activeId) ?? null,
    [threads, activeId]
  );

  const onPickThread = useCallback((id: number) => {
    setActiveId(id);
    setDrawerOpen(false);
  }, []);

  const onThreadUpdated = useCallback((updated: ChatThread) => {
    setThreads((prev) => {
      const next = prev.map((t) => (t.id === updated.id ? updated : t));
      return next.sort(threadSortFn);
    });
  }, []);

  /**
   * After a destructive / state-changing mutation on the active thread,
   * pick a sensible new active thread from the currently-visible list (or
   * fall back to any non-archived row if nothing remains in view).
   */
  const pickNextActiveAfter = useCallback(
    (allThreads: ChatThread[], removedId: number, archivedFlag: boolean) => {
      const candidates = allThreads.filter(
        (t) => t.id !== removedId && (archivedFlag ? t.archived : !t.archived)
      );
      const sorted = [...candidates].sort(threadSortFn);
      return sorted[0]?.id ?? allThreads.find((t) => t.id !== removedId)?.id ?? null;
    },
    []
  );

  const onRenameThread = useCallback(
    async (id: number, title: string) => {
      try {
        const updated = await apiFetch<ChatThread>(`/threads/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ title })
        });
        setThreads((prev) => prev.map((t) => (t.id === id ? updated : t)).sort(threadSortFn));
        setStatusMessage({ kind: "ok", text: t("chat.status.renamed") });
      } catch (err) {
        setStatusMessage({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("chat.errors.renameFailed")
        });
        throw err;
      }
    },
    [t]
  );

  const onTogglePinThread = useCallback(
    async (id: number, next: boolean) => {
      try {
        const updated = await apiFetch<ChatThread>(`/threads/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ pinned: next })
        });
        setThreads((prev) => prev.map((t) => (t.id === id ? updated : t)).sort(threadSortFn));
        setStatusMessage({
          kind: "ok",
          text: next ? t("chat.status.pinned") : t("chat.status.unpinned")
        });
      } catch (err) {
        setStatusMessage({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("chat.errors.updateFailed")
        });
      }
    },
    [t]
  );

  const onToggleArchiveThread = useCallback(
    async (id: number, next: boolean) => {
      try {
        const updated = await apiFetch<ChatThread>(`/threads/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ archived: next })
        });
        setThreads((prev) => {
          const merged = prev.map((t) => (t.id === id ? updated : t)).sort(threadSortFn);
          // If the active thread just left the visible list, pick another.
          if (id === activeId) {
            const inView = merged.some((t) => t.id === id && (showArchived ? t.archived : !t.archived));
            if (!inView) {
              setActiveId(pickNextActiveAfter(merged, id, showArchived));
            }
          }
          return merged;
        });
        setStatusMessage({
          kind: "ok",
          text: next ? t("chat.status.archived") : t("chat.status.restored"),
          action: next && !showArchived
            ? {
                label: t("chat.status.viewArchived"),
                onClick: () => {
                  setShowArchived(true);
                  setActiveId(id);
                  void refreshThreads(true);
                }
              }
            : undefined
        });
      } catch (err) {
        setStatusMessage({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("chat.errors.archiveFailed")
        });
      }
    },
    [activeId, pickNextActiveAfter, refreshThreads, showArchived, t]
  );

  const onDeleteThread = useCallback(
    async (id: number) => {
      try {
        await apiFetch<Record<string, never>>(`/threads/${id}`, { method: "DELETE" });
        setThreads((prev) => {
          const remaining = prev.filter((t) => t.id !== id);
          if (id === activeId) {
            setActiveId(pickNextActiveAfter(remaining, id, showArchived));
          }
          return remaining;
        });
        setStatusMessage({ kind: "ok", text: t("chat.status.deleted") });
      } catch (err) {
        setStatusMessage({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("chat.errors.deleteFailed")
        });
        throw err;
      }
    },
    [activeId, pickNextActiveAfter, showArchived, t]
  );

  return (
    <div className="app-shell bg-surface-base text-fg">
      <ChatTopBar
        title={activeThread?.title ?? t("chat.defaultTitle")}
        activeThread={activeThread}
        onOpenDrawer={() => setDrawerOpen(true)}
        onRenameThread={onRenameThread}
        onTogglePinThread={onTogglePinThread}
        onToggleArchiveThread={onToggleArchiveThread}
        onDeleteThread={onDeleteThread}
      />
      {statusMessage ? (
        <div
          className={`flex items-center justify-center gap-3 px-4 py-2 text-center text-xs ${
            statusMessage.kind === "ok"
              ? "bg-emerald-900/60 text-emerald-100"
              : "bg-rose-900/60 text-rose-100"
          }`}
        >
          <span>{statusMessage.text}</span>
          {statusMessage.action ? (
            <button
              type="button"
              onClick={() => {
                statusMessage.action?.onClick();
                setStatusMessage(null);
              }}
              className="rounded border border-border px-2 py-0.5 text-[11px] font-medium hover:bg-interactive-hover-strong"
            >
              {statusMessage.action.label}
            </button>
          ) : null}
          <button
            type="button"
            onClick={() => setStatusMessage(null)}
            className="rounded p-0.5 text-fg-muted hover:bg-interactive-hover-strong hover:text-fg"
            aria-label={t("chat.dismissToast")}
          >
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path d="M6 6l12 12M6 18 18 6" />
            </svg>
          </button>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1">
        {/* Permanent rail on desktop */}
        <aside className="hidden w-72 shrink-0 border-r border-border-subtle bg-surface-elevated md:flex md:flex-col">
          <ArchiveTabs
            showArchived={showArchived}
            onChange={(next) => {
              setShowArchived(next);
              setActiveId(null);
              void refreshThreads(next);
            }}
          />
          <ChatThreadList
            threads={visibleThreads}
            activeId={activeId}
            loading={loading}
            error={error}
            onPick={onPickThread}
            onCreateGeneral={async () => {
              await refreshThreads();
            }}
            onRenameThread={onRenameThread}
            onTogglePinThread={onTogglePinThread}
            onToggleArchiveThread={onToggleArchiveThread}
            onDeleteThread={onDeleteThread}
          />
        </aside>
        {/* Mobile drawer */}
        {drawerOpen ? (
          <div className="absolute inset-0 z-30 flex md:hidden">
            <div className="flex w-72 max-w-[80vw] flex-col bg-surface-elevated shadow-xl">
              <ArchiveTabs
                showArchived={showArchived}
                onChange={(next) => {
                  setShowArchived(next);
                  setActiveId(null);
                  void refreshThreads(next);
                }}
              />
              <ChatThreadList
                threads={visibleThreads}
                activeId={activeId}
                loading={loading}
                error={error}
                onPick={onPickThread}
                onCreateGeneral={async () => {
                  await refreshThreads();
                }}
                onRenameThread={onRenameThread}
                onTogglePinThread={onTogglePinThread}
                onToggleArchiveThread={onToggleArchiveThread}
                onDeleteThread={onDeleteThread}
              />
            </div>
            <button
              onClick={() => setDrawerOpen(false)}
              className="flex-1 bg-scrim"
              aria-label={t("chat.closeDrawer")}
            />
          </div>
        ) : null}
        <main className="flex min-w-0 flex-1 flex-col">
          {activeThread ? (
            <ChatThreadView
              key={activeThread.id}
              thread={activeThread}
              onThreadUpdated={onThreadUpdated}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-fg-subtle">
              {loading ? t("chat.empty.loading") : t("chat.empty.noThreadsYet")}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}

function threadSortFn(a: ChatThread, b: ChatThread): number {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
  const ta = a.last_message_at ?? a.created_at;
  const tb = b.last_message_at ?? b.created_at;
  return tb.localeCompare(ta);
}

function ArchiveTabs({
  showArchived,
  onChange,
}: {
  showArchived: boolean;
  onChange: (next: boolean) => void;
}) {
  const { t } = useTranslation();
  const tabClass = (active: boolean) =>
    `flex-1 px-3 py-2 text-xs font-semibold uppercase tracking-wide transition ${
      active ? "border-b-2 border-primary text-fg" : "text-fg-subtle hover:text-fg-muted"
    }`;
  return (
    <div className="flex border-b border-border-subtle">
      <button type="button" onClick={() => onChange(false)} className={tabClass(!showArchived)}>
        {t("chat.archive.active")}
      </button>
      <button type="button" onClick={() => onChange(true)} className={tabClass(showArchived)}>
        {t("chat.archive.archived")}
      </button>
    </div>
  );
}
