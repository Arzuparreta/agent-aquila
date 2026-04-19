"use client";

import { useState } from "react";

import type { Email, TriageCategory } from "@/types/api";

import { EmailActionsMenu } from "./email-actions-menu";

export type EmailFilter = "all" | "actionable" | "informational" | "noise";

const TRIAGE_BADGE: Record<TriageCategory, { label: string; className: string }> = {
  actionable: { label: "Accionable", className: "bg-emerald-600/30 text-emerald-200" },
  informational: { label: "Info", className: "bg-slate-600/40 text-slate-200" },
  noise: { label: "Silenciado", className: "bg-rose-700/30 text-rose-200" },
  unknown: { label: "Sin clasificar", className: "bg-slate-700/40 text-slate-300" }
};

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const now = Date.now();
  const diff = Math.max(0, now - then);
  const min = 60_000;
  const hour = 60 * min;
  const day = 24 * hour;
  if (diff < hour) return `${Math.max(1, Math.round(diff / min))} min`;
  if (diff < day) return `${Math.round(diff / hour)} h`;
  if (diff < 7 * day) return `${Math.round(diff / day)} d`;
  return new Date(iso).toLocaleDateString("es-ES", { day: "2-digit", month: "short" });
}

export function InboxList({
  emails,
  activeId,
  loading,
  error,
  onPick,
  onMarkRead,
  onPromote,
  onSuppress,
  onStartChat
}: {
  emails: Email[];
  activeId: number | null;
  loading: boolean;
  error: string | null;
  onPick: (email: Email) => void;
  onMarkRead: (id: number, next: boolean) => Promise<void> | void;
  onPromote: (id: number) => Promise<void> | void;
  onSuppress: (id: number) => Promise<void> | void;
  onStartChat: (id: number) => Promise<void> | void;
}) {
  const [menuOpenId, setMenuOpenId] = useState<number | null>(null);

  if (loading && emails.length === 0) {
    return <div className="p-4 text-sm text-slate-400">Cargando…</div>;
  }
  if (error) {
    return <div className="p-4 text-sm text-rose-300">{error}</div>;
  }
  if (emails.length === 0) {
    return (
      <div className="p-6 text-center text-sm text-slate-500">
        No hay correos en este filtro.
      </div>
    );
  }
  return (
    <ul className="min-h-0 flex-1 overflow-y-auto">
      {emails.map((email) => {
        const cat: TriageCategory = (email.triage_category ?? "unknown") as TriageCategory;
        const badge = TRIAGE_BADGE[cat] ?? TRIAGE_BADGE.unknown;
        const sender = email.sender_name || email.sender_email;
        const isActive = email.id === activeId;
        const unread = !email.is_read;
        const menuOpen = menuOpenId === email.id;
        return (
          <li key={email.id}>
            <div
              className={`group/row relative flex items-stretch border-b border-white/5 transition ${
                isActive ? "bg-indigo-600/10" : "hover:bg-white/5"
              }`}
            >
              <button
                type="button"
                onClick={() => onPick(email)}
                className="flex min-w-0 flex-1 flex-col gap-1 px-3 py-3 text-left"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 shrink-0 rounded-full ${
                      unread ? "bg-indigo-400" : "bg-transparent"
                    }`}
                    aria-label={unread ? "No leído" : "Leído"}
                  />
                  <span
                    className={`min-w-0 flex-1 truncate text-sm ${
                      unread ? "font-semibold text-white" : "font-normal text-slate-300"
                    }`}
                  >
                    {sender}
                  </span>
                  <span className="shrink-0 text-[11px] text-slate-500">
                    {relativeTime(email.received_at)}
                  </span>
                </div>
                <div
                  className={`truncate text-sm ${
                    unread ? "text-slate-100" : "text-slate-400"
                  }`}
                >
                  {email.subject || "(sin asunto)"}
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${badge.className}`}
                    title={email.triage_reason ?? undefined}
                  >
                    {badge.label}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-xs text-slate-500">
                    {email.snippet || ""}
                  </span>
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
                  email={email}
                  variant="row"
                  open={menuOpen}
                  onOpenChange={(next) => setMenuOpenId(next ? email.id : null)}
                  onMarkRead={onMarkRead}
                  onPromote={onPromote}
                  onSuppress={onSuppress}
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
