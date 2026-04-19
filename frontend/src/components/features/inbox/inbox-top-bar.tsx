"use client";

import Link from "next/link";

/**
 * Compact top-bar for the inbox surface. Mirrors the shape of the chat top-bar so
 * the user feels at home navigating between the two.
 */
export function InboxTopBar() {
  return (
    <header className="pt-safe flex items-center gap-2 border-b border-border-subtle bg-surface-elevated px-3 py-2">
      <Link
        href="/"
        className="rounded-md px-2 py-1 text-sm text-fg-muted hover:bg-interactive-hover"
        aria-label="Volver al chat"
      >
        ← Chat
      </Link>
      <div className="min-w-0 flex-1 truncate text-base font-semibold">Bandeja</div>
    </header>
  );
}
