"use client";

import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import {
  DropdownMenu,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import type { ChatThread } from "@/types/api";

/**
 * Shared overflow-actions menu for a single chat thread.
 *
 * Used by both:
 * - the sidebar row (``thread-list.tsx``) — hover-revealed trigger.
 * - the chat top bar (``top-bar.tsx``) — always-visible trigger for the
 *   currently-open thread, so mobile users (no hover) can still reach
 *   these actions.
 *
 * Mutation handlers are passed in from ``chat-home.tsx`` so post-mutation
 * focus / refresh logic stays centralized.
 */
export function ThreadActionsMenu({
  thread,
  onRename,
  onTogglePin,
  onToggleArchive,
  onDelete,
  variant = "row",
  open,
  onOpenChange,
}: {
  thread: ChatThread;
  onRename: (id: number, title: string) => Promise<void> | void;
  onTogglePin: (id: number, next: boolean) => Promise<void> | void;
  onToggleArchive: (id: number, next: boolean) => Promise<void> | void;
  onDelete: (id: number) => Promise<void> | void;
  /** ``"row"`` = compact icon for the sidebar; ``"bar"`` = bigger icon for the top bar. */
  variant?: "row" | "bar";
  /** Controlled open state. Optional — when omitted the menu manages itself. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [renameOpen, setRenameOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pending, setPending] = useState(false);

  const triggerSize = variant === "bar" ? "p-2" : "p-1";

  const trigger = (
    <button
      type="button"
      aria-label="Acciones de la conversación"
      className={`rounded-md ${triggerSize} text-fg-subtle hover:bg-interactive-hover-strong hover:text-fg`}
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
    <>
      <DropdownMenu trigger={trigger} align="end" open={open} onOpenChange={onOpenChange}>
        <DropdownMenuItem onSelect={() => setRenameOpen(true)}>Renombrar</DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => {
            void onTogglePin(thread.id, !thread.pinned);
          }}
        >
          {thread.pinned ? "Quitar fijación" : "Fijar arriba"}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => {
            void onToggleArchive(thread.id, !thread.archived);
          }}
        >
          {thread.archived ? "Desarchivar" : "Archivar"}
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem destructive onSelect={() => setConfirmOpen(true)}>
          Eliminar conversación
        </DropdownMenuItem>
      </DropdownMenu>

      {renameOpen ? (
        <RenameDialog
          currentTitle={thread.title}
          pending={pending}
          onCancel={() => setRenameOpen(false)}
          onSubmit={async (title) => {
            setPending(true);
            try {
              await onRename(thread.id, title);
              setRenameOpen(false);
            } finally {
              setPending(false);
            }
          }}
        />
      ) : null}

      <ConfirmDialog
        open={confirmOpen}
        title={`¿Eliminar "${thread.title}"?`}
        description="Se eliminarán todos los mensajes de esta conversación. Esta acción no se puede deshacer."
        confirmLabel="Eliminar"
        cancelLabel="Cancelar"
        pending={pending}
        onConfirm={async () => {
          setPending(true);
          try {
            await onDelete(thread.id);
            setConfirmOpen(false);
          } finally {
            setPending(false);
          }
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </>
  );
}

function RenameDialog({
  currentTitle,
  pending,
  onCancel,
  onSubmit,
}: {
  currentTitle: string;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (title: string) => Promise<void> | void;
}) {
  const [value, setValue] = useState(currentTitle);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !pending) onCancel();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onCancel, pending]);

  const trimmed = value.trim();
  const canSave = trimmed.length > 0 && trimmed !== currentTitle.trim() && !pending;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-scrim"
        aria-label="Cerrar"
        onClick={onCancel}
        disabled={pending}
      />
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSave) void onSubmit(trimmed);
        }}
        className="relative z-10 w-full max-w-md rounded-lg border border-border bg-surface-elevated p-4 text-fg shadow-lg"
      >
        <h2 className="text-lg font-semibold">Renombrar conversación</h2>
        <p className="mt-1 text-sm text-fg-muted">
          Elige un nombre que te ayude a reconocerla más tarde.
        </p>
        <input
          ref={inputRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          maxLength={255}
          disabled={pending}
          className="mt-3 w-full rounded border border-border bg-surface-inset px-3 py-2 text-sm text-fg focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" className="border-dashed" onClick={onCancel} disabled={pending}>
            Cancelar
          </Button>
          <Button
            type="submit"
            className="border-primary bg-primary text-primary-fg hover:opacity-90 disabled:opacity-50"
            disabled={!canSave}
          >
            {pending ? "…" : "Guardar"}
          </Button>
        </div>
      </form>
    </div>
  );
}
