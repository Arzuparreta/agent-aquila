"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";
import type { ChatThread } from "@/types/api";

import { LibraryDrawer } from "./library-drawer";
import { ThreadActionsMenu } from "./thread-actions-menu";

const KIND_BADGES: Record<string, string> = {
  contact: "👤",
  deal: "💼",
  event: "📅",
  email: "📩",
  drive_file: "📎",
  attachment: "📎"
};

function timeShort(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString("es", { day: "2-digit", month: "2-digit" });
}

export function ChatThreadList({
  threads,
  activeId,
  loading,
  error,
  onPick,
  onCreateGeneral,
  onRenameThread,
  onTogglePinThread,
  onToggleArchiveThread,
  onDeleteThread
}: {
  threads: ChatThread[];
  activeId: number | null;
  loading: boolean;
  error: string | null;
  onPick: (id: number) => void;
  onCreateGeneral: () => Promise<void> | void;
  onRenameThread: (id: number, title: string) => Promise<void> | void;
  onTogglePinThread: (id: number, next: boolean) => Promise<void> | void;
  onToggleArchiveThread: (id: number, next: boolean) => Promise<void> | void;
  onDeleteThread: (id: number) => Promise<void> | void;
}) {
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null);

  const startNewThread = async () => {
    const created = await apiFetch<ChatThread>("/threads", {
      method: "POST",
      body: JSON.stringify({ title: "Nueva conversación" })
    });
    await onCreateGeneral();
    onPick(created.id);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-white/5 px-3 py-3">
        <div className="flex-1 text-sm font-semibold uppercase tracking-wide text-slate-400">
          Conversaciones
        </div>
        <button
          onClick={startNewThread}
          className="rounded-md p-1 text-slate-300 hover:bg-white/5"
          aria-label="Nueva conversación"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </div>
      <div className="scroll-stealth min-h-0 flex-1 overflow-y-auto">
        {loading ? <div className="px-4 py-3 text-sm text-slate-400">Cargando…</div> : null}
        {error ? <div className="px-4 py-3 text-sm text-rose-300">{error}</div> : null}
        <ul>
          {threads.map((t) => {
            const active = t.id === activeId;
            const badge = (t.entity_type && KIND_BADGES[t.entity_type]) || "💬";
            const menuOpen = menuOpenId === t.id;
            return (
              <li key={t.id}>
                <div
                  className={`group/row relative flex w-full items-center gap-3 px-3 py-3 transition ${
                    active ? "bg-indigo-600/20 text-white" : "text-slate-200 hover:bg-white/5"
                  }`}
                >
                  <button
                    type="button"
                    onClick={() => onPick(t.id)}
                    className="flex min-w-0 flex-1 items-center gap-3 text-left"
                  >
                    <span className="text-lg leading-none">{badge}</span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">{t.title}</span>
                        {t.pinned ? <span className="text-xs text-amber-300">★</span> : null}
                      </span>
                      <span className="block truncate text-xs text-slate-400">
                        {t.kind === "entity" ? `${t.entity_type} · ` : ""}
                        {timeShort(t.last_message_at)}
                      </span>
                    </span>
                    {t.unread > 0 ? (
                      <span className="shrink-0 rounded-full bg-indigo-500 px-2 py-0.5 text-xs">{t.unread}</span>
                    ) : null}
                  </button>
                  {/* Fixed width so the title `truncate` ellipsis ends left of the ⋯ control.
                      Previously the menu wrapper was `display: none` until hover, so the row button
                      spanned the full width and CSS “…” looked like a three-dot menu — clicks
                      selected the thread instead of opening actions. */}
                  <div className="flex h-8 w-8 shrink-0 items-center justify-end">
                    <ThreadActionsMenu
                      thread={t}
                      variant="row"
                      open={menuOpen}
                      onOpenChange={(next) => setMenuOpenId(next ? t.id : null)}
                      onRename={onRenameThread}
                      onTogglePin={onTogglePinThread}
                      onToggleArchive={onToggleArchiveThread}
                      onDelete={onDeleteThread}
                    />
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
      <button
        onClick={() => setLibraryOpen(true)}
        className="border-t border-white/5 px-3 py-3 text-left text-sm text-slate-300 hover:bg-white/5"
      >
        📚 Biblioteca · contactos, eventos, archivos…
      </button>
      {libraryOpen ? <LibraryDrawer onClose={() => setLibraryOpen(false)} /> : null}
    </div>
  );
}
