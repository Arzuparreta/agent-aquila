"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { EntityRef } from "@/types/api";

import { useChatReferences } from "./reference-context";

const ENTITY_LABEL: Record<string, string> = {
  contact: "👤",
  deal: "💼",
  event: "📅",
  email: "📩",
  drive_file: "📎",
  attachment: "📎"
};

/**
 * Composer with @reference chips and auto-grow textarea.
 *
 * The chips come from `useChatReferences` (a tiny context populated when the artist
 * taps an item in the library drawer). The composer renders them as removable pills
 * directly above the textarea.
 *
 * UX details:
 *   - Enter sends; Shift+Enter inserts a newline (matches every modern chat app).
 *   - The textarea grows up to 6 lines tall, then scrolls inside itself.
 *   - Bottom inset includes `pb-safe` so iPhones don't park the input under the home bar.
 */
export function ChatComposer({
  onSend,
  disabled
}: {
  onSend: (content: string, references: EntityRef[]) => Promise<void> | void;
  disabled?: boolean;
}) {
  const refs = useChatReferences();
  const [value, setValue] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  const autoSize = useCallback(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 24 * 6 + 16) + "px";
  }, []);

  useEffect(() => {
    autoSize();
  }, [value, autoSize]);

  const submit = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    setValue("");
    await onSend(trimmed, refs.refs);
  }, [value, disabled, onSend, refs.refs]);

  return (
    <div className="pb-safe border-t border-border-subtle bg-surface-elevated px-3 py-2">
      {refs.refs.length > 0 ? (
        <div className="mb-2 flex flex-wrap gap-1">
          {refs.refs.map((r, idx) => (
            <button
              key={`${r.type}-${r.id}-${idx}`}
              onClick={() => refs.remove(idx)}
              className="flex items-center gap-1 rounded-full bg-primary/15 px-2 py-1 text-xs text-fg hover:bg-primary/25"
              title="Quitar referencia"
            >
              <span>{ENTITY_LABEL[r.type] ?? "•"}</span>
              <span className="max-w-[10rem] truncate">{r.label || `${r.type} #${r.id}`}</span>
              <span className="text-fg-subtle">×</span>
            </button>
          ))}
        </div>
      ) : null}
      <div className="flex items-end gap-2">
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
          rows={1}
          disabled={disabled}
          placeholder="Escribe a tu mánager…"
          className="min-h-[42px] flex-1 resize-none rounded-2xl border border-border bg-surface-muted px-4 py-2 text-sm text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-2 focus:ring-ring/40"
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-primary-fg transition disabled:bg-surface-muted disabled:text-fg-subtle"
          aria-label="Enviar"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
            <path d="M5 12l14-7-7 14-2-5-5-2z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
