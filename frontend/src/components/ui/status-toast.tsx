"use client";

/**
 * Floating status toast: fixed bottom-right, glass-style, does not reflow the layout.
 */
export function StatusToast({
  kind,
  text,
  action,
  onDismiss,
  dismissAriaLabel
}: {
  kind: "ok" | "error";
  text: string;
  action?: { label: string; onClick: () => void };
  onDismiss: () => void;
  dismissAriaLabel: string;
}) {
  const accent = kind === "ok" ? "bg-emerald-500" : "bg-rose-500";

  return (
    <div
      className="pointer-events-none fixed bottom-0 right-0 z-40 max-w-[min(22rem,calc(100vw-1.5rem))] p-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-0 sm:bottom-2 sm:right-2 sm:p-4 sm:pb-[max(1rem,env(safe-area-inset-bottom))]"
      aria-live="polite"
    >
      <div
        className="pointer-events-auto flex gap-2.5 rounded-2xl border border-border-subtle bg-surface-elevated/80 px-3 py-2.5 shadow-2xl backdrop-blur-xl animate-toast-in"
        role="status"
      >
        <div className={`w-1 shrink-0 self-stretch rounded-full ${accent}`} aria-hidden />
        <p className="min-w-0 flex-1 text-[13px] leading-snug text-fg">{text}</p>
        <div className="flex shrink-0 items-start gap-1">
          {action ? (
            <button
              type="button"
              onClick={() => {
                action.onClick();
                onDismiss();
              }}
              className="rounded-lg px-2.5 py-1 text-xs font-medium text-fg ring-1 ring-border-subtle/80 hover:bg-interactive-hover-strong"
            >
              {action.label}
            </button>
          ) : null}
          <button
            type="button"
            onClick={onDismiss}
            className="rounded-md p-1 text-fg-muted hover:bg-interactive-hover hover:text-fg"
            aria-label={dismissAriaLabel}
          >
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2.5}>
              <path d="M6 6l12 12M6 18 18 6" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  );
}
