"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { usePushNotifications } from "@/lib/usePushNotifications";
import type { ChatThread } from "@/types/api";

import { ChatReferenceProvider } from "./reference-context";
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
  const [threads, setThreads] = useState<ChatThread[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const push = usePushNotifications();

  const refreshThreads = useCallback(async () => {
    try {
      const rows = await apiFetch<ChatThread[]>("/threads");
      setThreads(rows);
      setActiveId((prev) => prev ?? rows[0]?.id ?? null);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cargar la lista.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshThreads();
  }, [refreshThreads]);

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

  const showPushBanner =
    push.status === "idle" &&
    typeof window !== "undefined" &&
    "Notification" in window &&
    Notification.permission === "default";

  return (
    <ChatReferenceProvider>
    <div className="flex h-screen w-screen flex-col bg-slate-950 text-slate-100">
      <ChatTopBar
        title={activeThread?.title ?? "Mánager"}
        onOpenDrawer={() => setDrawerOpen(true)}
      />
      {showPushBanner ? (
        <button
          onClick={push.enable}
          className="bg-indigo-600/90 px-4 py-2 text-center text-sm font-medium text-white"
        >
          Activar notificaciones para enterarte al instante
        </button>
      ) : null}
      {push.status === "error" && push.error ? (
        <div className="bg-rose-900/60 px-4 py-2 text-center text-xs text-rose-100">
          Push: {push.error}
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1">
        {/* Permanent rail on desktop */}
        <aside className="hidden w-72 shrink-0 border-r border-white/5 bg-slate-900 md:block">
          <ChatThreadList
            threads={threads}
            activeId={activeId}
            loading={loading}
            error={error}
            onPick={onPickThread}
            onCreateGeneral={async () => {
              await refreshThreads();
            }}
          />
        </aside>
        {/* Mobile drawer */}
        {drawerOpen ? (
          <div className="absolute inset-0 z-30 flex md:hidden">
            <div className="w-72 max-w-[80vw] bg-slate-900 shadow-xl">
              <ChatThreadList
                threads={threads}
                activeId={activeId}
                loading={loading}
                error={error}
                onPick={onPickThread}
                onCreateGeneral={async () => {
                  await refreshThreads();
                }}
              />
            </div>
            <button
              onClick={() => setDrawerOpen(false)}
              className="flex-1 bg-black/60"
              aria-label="Cerrar menú"
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
            <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-slate-400">
              {loading
                ? "Cargando…"
                : "No hay conversaciones todavía. Empieza escribiendo cualquier cosa."}
            </div>
          )}
        </main>
      </div>
    </div>
    </ChatReferenceProvider>
  );
}

function threadSortFn(a: ChatThread, b: ChatThread): number {
  if (a.pinned !== b.pinned) return a.pinned ? -1 : 1;
  const ta = a.last_message_at ?? a.created_at;
  const tb = b.last_message_at ?? b.created_at;
  return tb.localeCompare(ta);
}
