"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";
import type { ChatThread } from "@/types/api";

import { StatusToast } from "@/components/ui/status-toast";

import { DeleteAllArchivedDialog } from "./delete-all-archived-dialog";
import { ChatThreadList } from "./thread-list";
import { ChatThreadView } from "./thread-view";
import { ChatTopBar } from "./top-bar";

/** Dedupes concurrent bootstrap POSTs (e.g. React Strict Mode double mount). */
let bootstrapActiveChatInFlight: Promise<ChatThread> | null = null;

function requestBootstrapActiveChat(title: string): Promise<ChatThread> {
  if (!bootstrapActiveChatInFlight) {
    bootstrapActiveChatInFlight = apiFetch<ChatThread>("/threads", {
      method: "POST",
      body: JSON.stringify({ title })
    }).finally(() => {
      bootstrapActiveChatInFlight = null;
    });
  }
  return bootstrapActiveChatInFlight;
}

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
  const [deleteAllArchivedOpen, setDeleteAllArchivedOpen] = useState(false);
  const [deleteAllArchivedPending, setDeleteAllArchivedPending] = useState(false);
  const [bulkArchivePending, setBulkArchivePending] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ kind: "ok" | "error"; text: string; action?: { label: string; onClick: () => void } } | null>(null);

  const refreshThreads = useCallback(
    async (includeArchived = showArchived) => {
      try {
        const qs = includeArchived ? "?include_archived=true" : "";
        const rows = await apiFetch<ChatThread[]>(`/threads${qs}`);
        setThreads(rows);
        setActiveId((prev) => {
          const ids = new Set(rows.map((r) => r.id));
          if (prev != null && ids.has(prev)) return prev;
          if (!includeArchived) {
            return rows.find((r) => !r.archived)?.id ?? rows[0]?.id ?? null;
          }
          return (
            rows.find((r) => r.archived)?.id ??
            rows.find((r) => !r.archived)?.id ??
            rows[0]?.id ??
            null
          );
        });
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

  // Auto-dismiss the status toast after a few seconds.
  useEffect(() => {
    if (!statusMessage) return;
    const id = window.setTimeout(() => setStatusMessage(null), 6000);
    return () => window.clearTimeout(id);
  }, [statusMessage]);

  const visibleThreads = useMemo(
    () => threads.filter((th) => (showArchived ? th.archived : !th.archived)),
    [threads, showArchived]
  );

  // Active tab: always show a chat (like ChatGPT / Gemini). Create one if the list is empty.
  useEffect(() => {
    if (showArchived || loading || error || visibleThreads.length > 0) return;
    let cancelled = false;
    void requestBootstrapActiveChat(t("chat.threadList.newThreadTitle"))
      .then((created) => {
        if (cancelled) return;
        setThreads((prev) => {
          if (prev.some((x) => x.id === created.id)) return prev;
          return [...prev, created].sort(threadSortFn);
        });
        setActiveId(created.id);
        setError(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setStatusMessage({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("chat.errors.bootstrapChat")
        });
      });
    return () => {
      cancelled = true;
    };
  }, [showArchived, loading, error, visibleThreads.length, t]);

  // Honor `?thread=NN` deep-links from push notifications.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const target = Number(params.get("thread"));
    if (target > 0) setActiveId(target);
  }, [threads.length]);

  const activeThread = useMemo(
    () => threads.find((th) => th.id === activeId) ?? null,
    [threads, activeId]
  );

  const onPickThread = useCallback((id: number) => {
    setActiveId(id);
    setDrawerOpen(false);
  }, []);

  const onThreadUpdated = useCallback((updated: ChatThread) => {
    setThreads((prev) => {
      const next = prev.map((th) => (th.id === updated.id ? updated : th));
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
        (th) => th.id !== removedId && (archivedFlag ? th.archived : !th.archived)
      );
      const sorted = [...candidates].sort(threadSortFn);
      return sorted[0]?.id ?? allThreads.find((th) => th.id !== removedId)?.id ?? null;
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
        setThreads((prev) => prev.map((th) => (th.id === id ? updated : th)).sort(threadSortFn));
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
        setThreads((prev) => prev.map((th) => (th.id === id ? updated : th)).sort(threadSortFn));
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
          const merged = prev.map((th) => (th.id === id ? updated : th)).sort(threadSortFn);
          // If the active thread just left the visible list, pick another.
          if (id === activeId) {
            const inView = merged.some((th) => th.id === id && (showArchived ? th.archived : !th.archived));
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
          const remaining = prev.filter((th) => th.id !== id);
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

  const onThreadListChanged = useCallback(async () => {
    await refreshThreads();
  }, [refreshThreads]);

  const onDeleteAllArchived = useCallback(async () => {
    setDeleteAllArchivedPending(true);
    try {
      const { deleted } = await apiFetch<{ deleted: number }>("/threads/archived", {
        method: "DELETE"
      });
      setShowArchived(false);
      await refreshThreads(false);
      setStatusMessage({
        kind: "ok",
        text: t("chat.status.allArchivedDeleted", { count: deleted })
      });
      setDeleteAllArchivedOpen(false);
    } catch (err) {
      setStatusMessage({
        kind: "error",
        text: err instanceof ApiError ? err.message : t("chat.errors.deleteAllArchivedFailed")
      });
    } finally {
      setDeleteAllArchivedPending(false);
    }
  }, [refreshThreads, t]);

  const onArchiveAllActive = useCallback(async () => {
    const activeThreads = threads.filter((th) => !th.archived);
    if (activeThreads.length === 0) return;
    setBulkArchivePending(true);
    try {
      await Promise.all(
        activeThreads.map((th) =>
          apiFetch<ChatThread>(`/threads/${th.id}`, {
            method: "PATCH",
            body: JSON.stringify({ archived: true })
          })
        )
      );
      await refreshThreads(false);
      setStatusMessage({
        kind: "ok",
        text: t("chat.status.allActiveArchived", { count: activeThreads.length })
      });
    } catch (err) {
      setStatusMessage({
        kind: "error",
        text: err instanceof ApiError ? err.message : t("chat.errors.archiveAllFailed")
      });
    } finally {
      setBulkArchivePending(false);
    }
  }, [refreshThreads, t, threads]);

  return (
    <div className="app-shell bg-surface-base text-fg">
      <ChatTopBar
        title={activeThread?.title ?? t("chat.defaultTitle")}
        onOpenDrawer={() => setDrawerOpen(true)}
      />
      {statusMessage ? (
        <StatusToast
          kind={statusMessage.kind}
          text={statusMessage.text}
          action={statusMessage.action}
          onDismiss={() => setStatusMessage(null)}
          dismissAriaLabel={t("chat.dismissToast")}
        />
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
          <ArchivedBulkToolbar
            showArchived={showArchived}
            disabled={deleteAllArchivedPending || loading || visibleThreads.length === 0}
            onRequestDeleteAll={() => setDeleteAllArchivedOpen(true)}
          />
          <ChatThreadList
            threads={visibleThreads}
            activeId={activeId}
            loading={loading}
            error={error}
            showArchived={showArchived}
            bulkArchivePending={bulkArchivePending}
            onPick={onPickThread}
            onThreadListChanged={onThreadListChanged}
            onArchiveAllActive={onArchiveAllActive}
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
              <ArchivedBulkToolbar
                showArchived={showArchived}
                disabled={deleteAllArchivedPending || loading || visibleThreads.length === 0}
                onRequestDeleteAll={() => setDeleteAllArchivedOpen(true)}
              />
              <ChatThreadList
                threads={visibleThreads}
                activeId={activeId}
                loading={loading}
                error={error}
                showArchived={showArchived}
                bulkArchivePending={bulkArchivePending}
                onPick={onPickThread}
                onThreadListChanged={onThreadListChanged}
                onArchiveAllActive={onArchiveAllActive}
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
      <DeleteAllArchivedDialog
        open={deleteAllArchivedOpen}
        onOpenChange={setDeleteAllArchivedOpen}
        pending={deleteAllArchivedPending}
        onConfirm={onDeleteAllArchived}
      />
    </div>
  );
}

function threadSortFn(a: ChatThread, b: ChatThread): number {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
  const ta = a.last_message_at ?? a.created_at;
  const tb = b.last_message_at ?? b.created_at;
  return tb.localeCompare(ta);
}

function ArchivedBulkToolbar({
  showArchived,
  disabled,
  onRequestDeleteAll
}: {
  showArchived: boolean;
  disabled: boolean;
  onRequestDeleteAll: () => void;
}) {
  const { t } = useTranslation();
  if (!showArchived) return null;
  return (
    <div className="flex justify-end border-b border-border-subtle px-3 py-2">
      <button
        type="button"
        disabled={disabled}
        onClick={onRequestDeleteAll}
        aria-label={t("chat.archive.deleteAllAria")}
        title={t("chat.archive.deleteAll")}
        className="rounded-md p-1 text-rose-400 hover:bg-interactive-hover hover:text-rose-300 disabled:cursor-not-allowed disabled:opacity-40"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M3 7h18" />
          <path d="M5 7l1.2 12a2 2 0 0 0 2 1.8h7.6a2 2 0 0 0 2-1.8L19 7" />
          <path d="M9.5 11.5v5M14.5 11.5v5" />
          <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
        </svg>
      </button>
    </div>
  );
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
