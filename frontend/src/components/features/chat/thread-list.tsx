"use client";

import { useState } from "react";

import { apiFetch } from "@/lib/api";
import { intlLocaleTag, useTranslation } from "@/lib/i18n";
import type { ChatThread } from "@/types/api";

import { ThreadActionsMenu } from "./thread-actions-menu";

// Threads no longer mirror first-class CRM entities. Any entity-bound thread
// kind (gmail_message, calendar_event, drive_file, …) gets a generic chip.
const KIND_BADGES: Record<string, string> = {
  gmail_message: "📩",
  calendar_event: "📅",
  drive_file: "📎",
  outlook_message: "📩",
  teams_message: "💬",
};

function timeShort(iso: string | null, localeTag: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString(localeTag, { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(localeTag, { day: "2-digit", month: "2-digit" });
}

export function ChatThreadList({
  threads,
  activeId,
  loading,
  error,
  showArchived,
  bulkArchivePending,
  onPick,
  onThreadListChanged,
  onArchiveAllActive,
  onRenameThread,
  onTogglePinThread,
  onToggleArchiveThread,
  onDeleteThread
}: {
  threads: ChatThread[];
  activeId: number | null;
  loading: boolean;
  error: string | null;
  showArchived: boolean;
  bulkArchivePending: boolean;
  onPick: (id: number) => void;
  onThreadListChanged: () => Promise<void> | void;
  onArchiveAllActive: () => Promise<void> | void;
  onRenameThread: (id: number, title: string) => Promise<void> | void;
  onTogglePinThread: (id: number, next: boolean) => Promise<void> | void;
  onToggleArchiveThread: (id: number, next: boolean) => Promise<void> | void;
  onDeleteThread: (id: number) => Promise<void> | void;
}) {
  const { t, locale } = useTranslation();
  const localeTag = intlLocaleTag(locale);
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null);

  const startNewThread = async () => {
    const created = await apiFetch<ChatThread>("/threads", {
      method: "POST",
      body: JSON.stringify({ title: t("chat.threadList.newThreadTitle") })
    });
    await onThreadListChanged();
    onPick(created.id);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center gap-2 border-b border-border-subtle px-3 py-3">
        <div className="flex-1 text-sm font-semibold uppercase tracking-wide text-fg-subtle">
          {t("chat.threadList.title")}
        </div>
        {!showArchived ? (
          <button
            type="button"
            disabled={bulkArchivePending || threads.length === 0}
            onClick={() => {
              void onArchiveAllActive();
            }}
            className="rounded-md p-1 text-fg-muted hover:bg-interactive-hover disabled:cursor-not-allowed disabled:opacity-40"
            aria-label={t("chat.archive.archiveAllAria")}
            title={t("chat.archive.archiveAll")}
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M3 7h18" />
              <path d="M5 7l1.2 12a2 2 0 0 0 2 1.8h7.6a2 2 0 0 0 2-1.8L19 7" />
              <path d="M9.5 11.5v5M14.5 11.5v5" />
              <path d="M9 7V5.5A1.5 1.5 0 0 1 10.5 4h3A1.5 1.5 0 0 1 15 5.5V7" />
            </svg>
          </button>
        ) : null}
        <button
          onClick={startNewThread}
          className="rounded-md p-1 text-fg-muted hover:bg-interactive-hover"
          aria-label={t("chat.threadList.newAria")}
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      </div>
      <div className="scroll-stealth min-h-0 flex-1 overflow-y-auto">
        {loading ? <div className="px-4 py-3 text-sm text-fg-subtle">{t("common.loading")}</div> : null}
        {error ? <div className="px-4 py-3 text-sm text-rose-300">{error}</div> : null}
        <ul>
          {threads.map((t) => {
            const active = t.id === activeId;
            const badge = (t.entity_type && KIND_BADGES[t.entity_type]) || "💬";
            const menuOpen = menuOpenId === t.id;
            return (
              <li key={t.id}>
                <div
                  className={`group/row relative flex w-full items-center gap-3 border-l-[3px] py-3 pl-[9px] pr-3 transition ${
                    active
                      ? "border-l-primary bg-primary/15 text-fg ring-2 ring-inset ring-primary/35"
                      : "border-l-transparent text-fg hover:bg-interactive-hover"
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
                      <span className="block truncate text-xs text-fg-subtle">
                        {t.kind === "entity" ? `${t.entity_type} · ` : ""}
                        {timeShort(t.last_message_at, localeTag)}
                      </span>
                    </span>
                    {t.unread > 0 ? (
                      <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-xs text-primary-fg">
                        {t.unread}
                      </span>
                    ) : null}
                  </button>
                  {/* Fixed width so the title `truncate` ellipsis ends left of the ⋯ control.
                      Previously the menu wrapper was `display: none` until hover, so the row button
                      spanned the full width and CSS “…” looked like a three-dot menu — clicks
                      selected the thread instead of opening actions. */}
                  <div className="flex h-8 w-8 shrink-0 items-center justify-end">
                    <ThreadActionsMenu
                      thread={t}
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
    </div>
  );
}
