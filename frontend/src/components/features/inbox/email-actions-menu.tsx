"use client";

import {
  DropdownMenu,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import type { GmailMessageRow } from "@/types/api";

/**
 * Row / detail-bar overflow menu for a Gmail message.
 *
 * Every action talks straight to the Gmail proxy on the backend (no local
 * mirror), via the handlers passed in from the page component which owns
 * optimistic updates and inline status feedback.
 */
export function EmailActionsMenu({
  message,
  onMarkRead,
  onArchive,
  onTrash,
  onSilence,
  onStartChat,
  variant = "row",
  open,
  onOpenChange,
}: {
  message: GmailMessageRow;
  onMarkRead: (msg: GmailMessageRow, next: boolean) => void;
  onArchive: (msg: GmailMessageRow) => void;
  onTrash: (msg: GmailMessageRow) => void;
  onSilence: (msg: GmailMessageRow) => void;
  onStartChat: (msg: GmailMessageRow) => void;
  variant?: "row" | "bar";
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const triggerSize = variant === "bar" ? "p-2" : "p-1";
  const isUnread = message.is_unread;

  const trigger = (
    <button
      type="button"
      aria-label="Acciones del correo"
      className={`rounded-md ${triggerSize} text-fg-subtle hover:bg-interactive-hover-strong hover:text-fg`}
      onClick={(e) => e.stopPropagation()}
    >
      <svg
        viewBox="0 0 24 24"
        className="h-4 w-4"
        fill="none"
        stroke="currentColor"
        strokeWidth={2}
      >
        <circle cx="5" cy="12" r="1.5" />
        <circle cx="12" cy="12" r="1.5" />
        <circle cx="19" cy="12" r="1.5" />
      </svg>
    </button>
  );

  return (
    <DropdownMenu trigger={trigger} align="end" open={open} onOpenChange={onOpenChange}>
      <DropdownMenuItem onSelect={() => onMarkRead(message, isUnread)}>
        {isUnread ? "Marcar como leído" : "Marcar como no leído"}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => onStartChat(message)}>
        Iniciar chat sobre este correo
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem onSelect={() => onArchive(message)}>
        Archivar
      </DropdownMenuItem>
      <DropdownMenuItem destructive onSelect={() => onTrash(message)}>
        Mover a papelera
      </DropdownMenuItem>
      <DropdownMenuSeparator />
      <DropdownMenuItem destructive onSelect={() => onSilence(message)}>
        Silenciar remitente…
      </DropdownMenuItem>
    </DropdownMenu>
  );
}
