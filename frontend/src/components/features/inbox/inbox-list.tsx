"use client";

import { useState } from "react";

import { intlLocaleTag, useTranslation, type TranslationKey } from "@/lib/i18n";
import type { GmailMessageRow } from "@/types/api";

import { EmailActionsMenu } from "./email-actions-menu";

function relativeTime(
  internalDateMs: string | null,
  t: (key: TranslationKey, params?: Record<string, string | number>) => string,
  localeTag: string
): string {
  if (!internalDateMs) return "";
  const then = Number(internalDateMs);
  if (!Number.isFinite(then)) return "";
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const min = 60_000;
  const hour = 60 * min;
  const day = 24 * hour;
  if (diff < hour) return t("inbox.time.minutes", { n: Math.max(1, Math.round(diff / min)) });
  if (diff < day) return t("inbox.time.hours", { n: Math.round(diff / hour) });
  if (diff < 7 * day) return t("inbox.time.days", { n: Math.round(diff / day) });
  return new Date(then).toLocaleDateString(localeTag, {
    day: "2-digit",
    month: "short"
  });
}

/**
 * Single, undecorated Gmail row list. There is no triage chip, no per-row
 * category — Gmail's labels are the source of truth and we surface only the
 * ones the user can act on (UNREAD via bold, the rest stay in Gmail).
 */
export function InboxList({
  messages,
  activeId,
  loading,
  error,
  onPick,
  onMarkRead,
  onArchive,
  onTrash,
  onSilence,
  onStartChat,
}: {
  messages: GmailMessageRow[];
  activeId: string | null;
  loading: boolean;
  error: string | null;
  onPick: (msg: GmailMessageRow) => void;
  onMarkRead: (msg: GmailMessageRow, next: boolean) => void;
  onArchive: (msg: GmailMessageRow) => void;
  onTrash: (msg: GmailMessageRow) => void;
  onSilence: (msg: GmailMessageRow) => void;
  onStartChat: (msg: GmailMessageRow) => void;
}) {
  const { t, locale } = useTranslation();
  const localeTag = intlLocaleTag(locale);
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null);

  if (loading && messages.length === 0) {
    return <div className="p-4 text-sm text-fg-subtle">{t("common.loading")}</div>;
  }
  if (error) {
    return <div className="p-4 text-sm text-rose-300">{error}</div>;
  }
  if (messages.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-fg-subtle">
        {t("inbox.list.empty")}
      </div>
    );
  }
  return (
    <ul className="min-h-0 flex-1 overflow-y-auto">
      {messages.map((msg) => {
        const sender = msg.sender_name || msg.sender_email;
        const isActive = msg.id === activeId;
        const unread = msg.is_unread;
        const menuOpen = menuOpenId === msg.id;
        return (
          <li key={msg.id}>
            <div
              className={`group/row relative flex items-stretch border-b border-border-subtle transition ${
                isActive ? "bg-primary/10" : "hover:bg-interactive-hover"
              }`}
            >
              <button
                type="button"
                onClick={() => onPick(msg)}
                className="flex min-w-0 flex-1 flex-col gap-1 px-3 py-3 text-left"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${
                      unread ? "bg-primary" : "bg-transparent"
                    }`}
                    aria-label={unread ? t("inbox.unread") : t("inbox.read")}
                  />
                  <span
                    className={`min-w-0 flex-1 truncate text-sm ${
                      unread ? "font-semibold text-fg" : "font-normal text-fg-muted"
                    }`}
                  >
                    {sender}
                  </span>
                  <span className="shrink-0 text-[11px] text-fg-subtle">
                    {relativeTime(msg.internal_date, t, localeTag)}
                  </span>
                </div>
                <div
                  className={`truncate text-sm ${
                    unread ? "text-fg" : "text-fg-subtle"
                  }`}
                >
                  {msg.subject || t("inbox.noSubject")}
                </div>
                <div className="truncate text-xs text-fg-subtle">
                  {msg.snippet || ""}
                </div>
              </button>
              <span
                className={`flex items-start py-3 pr-2 ${
                  menuOpen
                    ? "inline-flex"
                    : "hidden group-hover/row:inline-flex group-focus-within/row:inline-flex"
                }`}
              >
                <EmailActionsMenu
                  message={msg}
                  variant="row"
                  open={menuOpen}
                  onOpenChange={(next) => setMenuOpenId(next ? msg.id : null)}
                  onMarkRead={onMarkRead}
                  onArchive={onArchive}
                  onTrash={onTrash}
                  onSilence={onSilence}
                  onStartChat={onStartChat}
                />
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
