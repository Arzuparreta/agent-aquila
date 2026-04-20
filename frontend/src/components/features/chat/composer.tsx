"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { EntityRef } from "@/types/api";
import { useTranslation } from "@/lib/i18n";

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
 *   - Bottom inset uses `pb-safe-plus` so the bar clears the home indicator and has
 *     breathing room from the viewport edge.
 */
export function ChatComposer({
  onSend,
  disabled
}: {
  onSend: (content: string, references: EntityRef[]) => Promise<void> | void;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  const refs = useChatReferences();
  const [value, setValue] = useState("");
  const taRef = useRef<HTMLTextAreaElement>(null);

  const autoSize = useCallback(() => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 28 * 6 + 20) + "px";
  }, []);

  useEffect(() => {
    autoSize();
  }, [value, autoSize]);

  const submit = useCallback(async () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    setValue("");
    try {
      await onSend(trimmed, refs.refs);
    } catch {
      setValue(trimmed);
    }
  }, [value, disabled, onSend, refs.refs]);

  return (
    <div className="pb-safe-plus shrink-0 px-3 pt-2">
      <div className="mx-auto max-w-3xl rounded-3xl border border-border-subtle bg-surface-elevated p-3 shadow-md">
        {refs.refs.length > 0 ? (
          <div className="mb-2 flex flex-wrap gap-1">
            {refs.refs.map((r, idx) => (
              <button
                key={`${r.type}-${r.id}-${idx}`}
                onClick={() => refs.remove(idx)}
                className="flex items-center gap-1 rounded-full bg-primary/15 px-2.5 py-1 text-sm text-fg hover:bg-primary/25"
                title={t("chat.composer.removeRef")}
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
            placeholder={t("chat.composer.placeholder")}
            className="min-h-[48px] flex-1 resize-none rounded-2xl border border-border bg-surface-muted px-4 py-3 text-base leading-snug text-fg placeholder:text-fg-subtle focus:outline-none focus:ring-2 focus:ring-ring/40"
          />
          <button
            onClick={submit}
            disabled={disabled || !value.trim()}
            className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-fg transition disabled:bg-surface-muted disabled:text-fg-subtle"
            aria-label={t("chat.composer.send")}
          >
            <svg viewBox="0 0 24 24" className="h-6 w-6" fill="none" stroke="currentColor" strokeWidth={2}>
              <path d="M5 12l14-7-7 14-2-5-5-2z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
