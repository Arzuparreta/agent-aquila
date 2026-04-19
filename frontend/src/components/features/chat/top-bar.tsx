"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { ChatThread } from "@/types/api";

import { AIStatusBadge } from "./ai-status-badge";
import { ThreadActionsMenu } from "./thread-actions-menu";

/**
 * Compact bar with: hamburger (mobile only), title, optional thread-actions
 * menu for the active conversation, inbox link with unread badge, and an
 * account/settings menu. The thread-actions surface is the only discoverable
 * way to delete / archive / rename on mobile (no hover on touch).
 */
export function ChatTopBar({
  title,
  activeThread,
  onOpenDrawer,
  onRenameThread,
  onTogglePinThread,
  onToggleArchiveThread,
  onDeleteThread
}: {
  title: string;
  activeThread: ChatThread | null;
  onOpenDrawer: () => void;
  onRenameThread: (id: number, title: string) => Promise<void> | void;
  onTogglePinThread: (id: number, next: boolean) => Promise<void> | void;
  onToggleArchiveThread: (id: number, next: boolean) => Promise<void> | void;
  onDeleteThread: (id: number) => Promise<void> | void;
}) {
  const { logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [unread, setUnread] = useState<number>(0);

  // Live unread count via the Gmail proxy. We deliberately use Gmail's own
  // ``q=is:unread`` so the badge always agrees with what the user sees in
  // gmail.com — no local mirror, no triage filter.
  useEffect(() => {
    let cancelled = false;
    const fetchUnread = async () => {
      try {
        const res = await apiFetch<{
          messages?: unknown[];
          result_size_estimate?: number | null;
        }>(
          "/gmail/messages?detail=ids&max_results=1&q=" +
            encodeURIComponent("is:unread in:inbox"),
        );
        if (cancelled) return;
        const estimate =
          typeof res.result_size_estimate === "number"
            ? res.result_size_estimate
            : (res.messages?.length ?? 0);
        setUnread(estimate);
      } catch {
        if (!cancelled) setUnread(0);
      }
    };
    void fetchUnread();
    const id = window.setInterval(fetchUnread, 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return (
    <header className="relative z-10 pt-safe flex items-center gap-2 border-b border-border-subtle bg-surface-elevated px-3 py-2">
      <button
        onClick={onOpenDrawer}
        className="rounded-md p-2 text-fg-muted hover:bg-interactive-hover md:hidden"
        aria-label="Abrir conversaciones"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M3 6h18M3 12h18M3 18h18" />
        </svg>
      </button>
      <div className="min-w-0 flex-1 truncate text-base font-semibold">{title}</div>
      {activeThread ? (
        <ThreadActionsMenu
          thread={activeThread}
          variant="bar"
          onRename={onRenameThread}
          onTogglePin={onTogglePinThread}
          onToggleArchive={onToggleArchiveThread}
          onDelete={onDeleteThread}
        />
      ) : null}
      <AIStatusBadge />
      <Link
        href="/inbox"
        className="relative rounded-md p-2 text-fg-muted hover:bg-interactive-hover"
        aria-label="Bandeja"
        title="Bandeja"
      >
        <svg
          viewBox="0 0 24 24"
          className="h-5 w-5"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
          <path d="m3 7 9 7 9-7" />
        </svg>
        {unread > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 flex min-w-[1.1rem] items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold leading-none text-white">
            {unread > 99 ? "99+" : unread}
          </span>
        ) : null}
      </Link>
      <div className="relative">
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="rounded-md p-2 text-fg-muted hover:bg-interactive-hover"
          aria-label="Menú"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="12" cy="5" r="1.5" />
            <circle cx="12" cy="12" r="1.5" />
            <circle cx="12" cy="19" r="1.5" />
          </svg>
        </button>
        {menuOpen ? (
          <div
            className="absolute right-0 top-full z-40 mt-2 w-56 overflow-hidden rounded-lg border border-border bg-surface-elevated py-1 text-sm text-fg shadow-xl"
            onMouseLeave={() => setMenuOpen(false)}
          >
            <Link
              href="/settings"
              className="block px-3 py-2 hover:bg-interactive-hover"
              onClick={() => setMenuOpen(false)}
            >
              Ajustes técnicos (avanzado)
            </Link>
            <button
              onClick={() => {
                setMenuOpen(false);
                logout();
              }}
              className="block w-full px-3 py-2 text-left text-rose-600 hover:bg-interactive-hover"
            >
              Cerrar sesión
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
}
