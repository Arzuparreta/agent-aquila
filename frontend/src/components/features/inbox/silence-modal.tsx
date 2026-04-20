"use client";

import { useEffect, useState } from "react";

import { useTranslation } from "@/lib/i18n";

export type SilenceMode = "mute" | "spam";

/**
 * Tiny confirmation modal for the "Silenciar" action.
 *
 * Two clearly labelled buttons, bilingual per the product copy:
 *   - "Silenciar / Mute"  — creates a Gmail filter that skips the inbox and
 *     marks future messages from this sender as read, then hides the current
 *     thread from the inbox view.
 *   - "Spam"               — creates a Gmail filter that hard-routes the
 *     sender to SPAM and applies SPAM to the current thread.
 *
 * Cancel restores the inbox without touching Gmail.
 */
export function SilenceModal({
  senderEmail,
  senderName,
  onCancel,
  onConfirm,
}: {
  senderEmail: string;
  senderName?: string | null;
  onCancel: () => void;
  onConfirm: (mode: SilenceMode) => void;
}) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<SilenceMode | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onCancel]);

  const click = (mode: SilenceMode) => {
    setBusy(mode);
    onConfirm(mode);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
      role="dialog"
      aria-modal="true"
    >
      <div className="w-full max-w-md rounded-xl border border-border-subtle bg-surface-elevated p-5 shadow-xl">
        <h2 className="text-base font-semibold text-fg">{t("silence.title")}</h2>
        <p className="mt-1 text-sm text-fg-muted">{t("silence.intro")}</p>
        <div className="mt-3 rounded-md bg-surface-muted px-3 py-2 text-sm">
          <div className="font-medium text-fg">
            {senderName || senderEmail}
          </div>
          {senderName ? (
            <div className="text-xs text-fg-subtle">{senderEmail}</div>
          ) : null}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={() => click("mute")}
            disabled={busy !== null}
            className="rounded-md bg-surface-muted px-3 py-2 text-sm font-medium text-fg hover:bg-surface-inset disabled:opacity-60"
          >
            <div className="flex flex-col items-start text-left">
              <span>{t("silence.muteLabel")}</span>
              <span className="text-[11px] font-normal text-fg-subtle">{t("silence.muteHint")}</span>
            </div>
          </button>
          <button
            type="button"
            onClick={() => click("spam")}
            disabled={busy !== null}
            className="rounded-md bg-rose-700/40 px-3 py-2 text-sm font-medium text-rose-100 hover:bg-rose-700/60 disabled:opacity-60"
          >
            <div className="flex flex-col items-start text-left">
              <span>{t("silence.spamLabel")}</span>
              <span className="text-[11px] font-normal text-rose-200/80">{t("silence.spamHint")}</span>
            </div>
          </button>
        </div>

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy !== null}
            className="rounded-md px-3 py-1.5 text-sm text-fg-muted hover:bg-interactive-hover disabled:opacity-60"
          >
            {t("common.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}
