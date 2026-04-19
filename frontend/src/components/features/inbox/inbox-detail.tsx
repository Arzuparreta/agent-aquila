"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useChatReferences } from "@/components/features/chat/reference-context";
import type { Email, TriageCategory } from "@/types/api";

import { EmailActionsMenu } from "./email-actions-menu";

const TRIAGE_BADGE: Record<TriageCategory, { label: string; className: string }> = {
  actionable: { label: "Accionable", className: "bg-emerald-600/30 text-emerald-200" },
  informational: { label: "Info", className: "bg-slate-600/40 text-slate-200" },
  noise: { label: "Silenciado", className: "bg-rose-700/30 text-rose-200" },
  unknown: { label: "Sin clasificar", className: "bg-slate-700/40 text-slate-300" }
};

/**
 * Email detail pane. Renders sender / subject / timestamp / body and the
 * primary actions:
 *   - Referenciar en chat: pushes an @email chip into the shared composer state and
 *     navigates to the main chat.
 *   - Iniciar chat sobre este correo: server creates an entity-bound thread (no agent
 *     run) and we navigate straight into it.
 *   - Promover / Silenciar: re-classify the email's triage category in place.
 *   - Overflow menu (kebab): same actions plus mark read/unread, mirrored on
 *     the row in the inbox list. The kebab is the only discoverable surface for
 *     these on touch devices once the detail is open.
 *
 * All mutating actions are owned by the page (``inbox-page.tsx``) so it can do
 * optimistic updates and surface a single inline status banner.
 */
export function InboxDetail({
  email,
  onClose,
  onMarkRead,
  onPromote,
  onSuppress,
  onStartChat
}: {
  email: Email;
  onClose: () => void;
  onMarkRead: (id: number, next: boolean) => Promise<void> | void;
  onPromote: (id: number) => Promise<void> | void;
  onSuppress: (id: number) => Promise<void> | void;
  onStartChat: (id: number) => Promise<void> | void;
}) {
  const router = useRouter();
  const refs = useChatReferences();
  const [busy, setBusy] = useState<string | null>(null);

  const cat: TriageCategory = (email.triage_category ?? "unknown") as TriageCategory;
  const badge = TRIAGE_BADGE[cat] ?? TRIAGE_BADGE.unknown;

  const onReference = () => {
    refs.add({
      type: "email",
      id: email.id,
      label: email.subject || email.sender_name || email.sender_email
    });
    router.push("/");
  };

  const wrap = async (key: string, fn: () => Promise<void> | void) => {
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-2 border-b border-white/5 bg-slate-900 px-3 py-2">
        <button
          onClick={onClose}
          className="rounded-md p-2 text-slate-300 hover:bg-white/5 md:hidden"
          aria-label="Volver"
        >
          ←
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-semibold">
            {email.subject || "(sin asunto)"}
          </div>
          <div className="truncate text-xs text-slate-400">
            {email.sender_name ? `${email.sender_name} · ` : ""}
            {email.sender_email}
          </div>
        </div>
        <span
          className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${badge.className}`}
          title={email.triage_reason ?? undefined}
        >
          {badge.label}
        </span>
        <EmailActionsMenu
          email={email}
          variant="bar"
          onMarkRead={onMarkRead}
          onPromote={onPromote}
          onSuppress={onSuppress}
          onStartChat={onStartChat}
        />
      </header>

      <div className="flex flex-wrap gap-2 border-b border-white/5 bg-slate-900/40 px-3 py-2 text-xs">
        <button
          onClick={onReference}
          disabled={busy !== null}
          className="rounded-full bg-indigo-600 px-3 py-1 font-medium text-white hover:bg-indigo-500 disabled:opacity-60"
        >
          Referenciar en chat
        </button>
        <button
          onClick={() => void wrap("chat", () => onStartChat(email.id))}
          disabled={busy !== null}
          className="rounded-full bg-indigo-700/40 px-3 py-1 font-medium text-indigo-100 hover:bg-indigo-700/60 disabled:opacity-60"
        >
          {busy === "chat" ? "Abriendo…" : "Iniciar chat sobre este correo"}
        </button>
        {cat !== "actionable" ? (
          <button
            onClick={() => void wrap("promote", () => onPromote(email.id))}
            disabled={busy !== null}
            className="rounded-full bg-emerald-700/40 px-3 py-1 text-emerald-200 hover:bg-emerald-700/60 disabled:opacity-60"
          >
            {busy === "promote" ? "…" : "Promover a accionable"}
          </button>
        ) : null}
        {cat !== "noise" ? (
          <button
            onClick={() => void wrap("suppress", () => onSuppress(email.id))}
            disabled={busy !== null}
            className="rounded-full bg-slate-700/40 px-3 py-1 text-slate-200 hover:bg-slate-700/60 disabled:opacity-60"
          >
            {busy === "suppress" ? "…" : "Silenciar"}
          </button>
        ) : null}
        <span className="ml-auto self-center text-[11px] text-slate-500">
          {new Date(email.received_at).toLocaleString("es-ES")}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-slate-200">
          {email.body || email.snippet || ""}
        </pre>
      </div>
    </div>
  );
}
