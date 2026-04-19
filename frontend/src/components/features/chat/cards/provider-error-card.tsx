"use client";

import Link from "next/link";

type Card = {
  card_kind: "provider_error";
  provider: string;
  status_code?: number | null;
  message: string;
  hint?: string | null;
  detail?: string | null;
  model?: string | null;
  settings_url?: string | null;
};

/**
 * Inline card shown when an upstream LLM call fails (404 model missing,
 * 401 invalid key, network unreachable, …). Rendered instead of (or in
 * addition to) the assistant's normal reply so the artist can act on it
 * without diving into the agent_run JSON.
 */
export function ProviderErrorCard({ card }: { card: Card }) {
  const settingsHref = card.settings_url ?? "/settings";
  return (
    <div className="rounded-2xl border border-rose-400/40 bg-rose-950/40 p-3 text-sm text-rose-50">
      <div className="mb-1 flex items-center justify-between gap-2 text-xs uppercase tracking-wide text-rose-300">
        <span>
          Error de proveedor · {card.provider}
          {card.status_code ? ` · HTTP ${card.status_code}` : ""}
        </span>
      </div>
      <div className="mb-1 font-semibold">{card.message}</div>
      {card.hint ? (
        <p className="mb-2 whitespace-pre-wrap text-rose-100/90">{card.hint}</p>
      ) : null}
      {card.model ? (
        <p className="mb-2 text-xs text-rose-200/80">
          Modelo solicitado: <code className="rounded bg-rose-900/60 px-1 py-0.5">{card.model}</code>
        </p>
      ) : null}
      {card.detail ? (
        <details className="mb-2 text-xs text-rose-200/70">
          <summary className="cursor-pointer">Ver detalle técnico</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-rose-900/60 p-2 font-mono text-[11px]">
            {card.detail}
          </pre>
        </details>
      ) : null}
      <Link
        href={settingsHref}
        className="inline-block rounded-full bg-rose-600 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-500"
      >
        Abrir ajustes de IA
      </Link>
    </div>
  );
}
