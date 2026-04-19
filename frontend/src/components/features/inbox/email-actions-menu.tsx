"use client";

import {
  DropdownMenu,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import type { Email, TriageCategory } from "@/types/api";

/**
 * Row-level overflow menu for an email.
 *
 * Mirrors the chat ``ThreadActionsMenu`` pattern:
 * - hover-revealed kebab on a list row (``variant="row"``).
 * - always-visible kebab in the detail header (``variant="bar"``) so mobile
 *   users without hover can still reach these actions.
 *
 * Mutation handlers are passed in so the page-level component can do
 * optimistic updates and show inline status feedback in one place.
 */
export function EmailActionsMenu({
  email,
  onMarkRead,
  onPromote,
  onSuppress,
  onStartChat,
  variant = "row",
  open,
  onOpenChange,
}: {
  email: Email;
  onMarkRead: (id: number, next: boolean) => Promise<void> | void;
  onPromote: (id: number) => Promise<void> | void;
  onSuppress: (id: number) => Promise<void> | void;
  onStartChat: (id: number) => Promise<void> | void;
  variant?: "row" | "bar";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const triggerSize = variant === "bar" ? "p-2" : "p-1";
  const cat: TriageCategory = (email.triage_category ?? "unknown") as TriageCategory;
  const isRead = !!email.is_read;

  const trigger = (
    <button
      type="button"
      aria-label="Acciones del correo"
      className={`rounded-md ${triggerSize} text-slate-400 hover:bg-white/10 hover:text-slate-100`}
      onClick={(e) => e.stopPropagation()}
    >
      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2}>
        <circle cx="5" cy="12" r="1.5" />
        <circle cx="12" cy="12" r="1.5" />
        <circle cx="19" cy="12" r="1.5" />
      </svg>
    </button>
  );

  return (
    <DropdownMenu trigger={trigger} align="end" open={open} onOpenChange={onOpenChange}>
      <DropdownMenuItem onSelect={() => void onMarkRead(email.id, !isRead)}>
        {isRead ? "Marcar como no leído" : "Marcar como leído"}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => void onStartChat(email.id)}>
        Iniciar chat sobre este correo
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      {cat !== "actionable" ? (
        <DropdownMenuItem onSelect={() => void onPromote(email.id)}>
          Promover a accionable
        </DropdownMenuItem>
      ) : null}
      {cat !== "noise" ? (
        <DropdownMenuItem destructive onSelect={() => void onSuppress(email.id)}>
          Silenciar remitente
        </DropdownMenuItem>
      ) : null}
    </DropdownMenu>
  );
}
