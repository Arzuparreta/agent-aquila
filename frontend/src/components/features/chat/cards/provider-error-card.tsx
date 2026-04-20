"use client";

import Link from "next/link";

import { useTranslation } from "@/lib/i18n";

type Card = {
  card_kind: "provider_error";
  provider: string;
  provider_label?: string | null;
  status_code?: number | null;
  message: string;
  hint?: string | null;
  detail?: string | null;
  model?: string | null;
  settings_url?: string | null;
  transient?: boolean | null;
};

/**
 * Inline card shown when an upstream LLM call fails (404 model missing,
 * 401 invalid key, network unreachable, …). Rendered instead of (or in
 * addition to) the assistant's normal reply so the artist can act on it
 * without diving into the agent_run JSON.
 */
export function ProviderErrorCard({
  card,
  onRetry,
  retryDisabled
}: {
  card: Card;
  onRetry?: () => void;
  retryDisabled?: boolean;
}) {
  const { t } = useTranslation();
  const settingsHref = card.settings_url ?? "/settings";
  const label = card.provider_label || card.provider;
  const code = card.status_code ? ` · HTTP ${card.status_code}` : "";
  return (
    <div className="rounded-2xl border border-rose-400/40 bg-rose-950/40 p-3 text-sm text-rose-50">
      <div className="mb-1 flex items-center justify-between gap-2 text-xs uppercase tracking-wide text-rose-300">
        <span>
          {t("cards.providerError.title", {
            label,
            code
          })}
        </span>
        {card.transient ? (
          <span className="rounded-full bg-rose-900/60 px-2 py-0.5 text-[10px] font-semibold normal-case tracking-normal text-rose-200">
            {t("cards.providerError.transient")}
          </span>
        ) : null}
      </div>
      <div className="mb-1 font-semibold">{card.message}</div>
      {card.hint ? (
        <p className="mb-2 whitespace-pre-wrap text-rose-100/90">{card.hint}</p>
      ) : null}
      {card.transient ? (
        <p className="mb-2 text-xs text-rose-200/80">{t("cards.providerError.transientHint")}</p>
      ) : null}
      {card.model ? (
        <p className="mb-2 text-xs text-rose-200/80">
          {t("cards.providerError.requestedModel")}{" "}
          <code className="rounded bg-rose-900/60 px-1 py-0.5">{card.model}</code>
        </p>
      ) : null}
      {card.detail ? (
        <details className="mb-2 text-xs text-rose-200/70">
          <summary className="cursor-pointer">{t("cards.providerError.viewDetail")}</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-rose-900/60 p-2 font-mono text-[11px]">
            {card.detail}
          </pre>
        </details>
      ) : null}
      <div className="flex flex-wrap gap-2">
        {onRetry ? (
          <button
            type="button"
            disabled={retryDisabled}
            onClick={onRetry}
            className="rounded-full bg-rose-500 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-400 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("chat.message.retry")}
          </button>
        ) : null}
        <Link
          href={settingsHref}
          className="inline-block rounded-full bg-rose-600 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-500"
        >
          {t("cards.providerError.openAiSettings")}
        </Link>
      </div>
    </div>
  );
}
