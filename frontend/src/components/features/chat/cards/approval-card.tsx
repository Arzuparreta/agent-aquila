"use client";

import { useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";

type Card = {
  card_kind: "approval";
  proposal_id: number;
  kind: string;
  summary: string | null;
  risk_tier: string;
  preview: Record<string, unknown>;
};

const RISK_LABEL: Record<string, string> = {
  low: "Bajo",
  medium: "Medio",
  high: "Alto",
  external: "Externo"
};

export function ApprovalCard({ card }: { card: Card }) {
  const [status, setStatus] = useState<"pending" | "approved" | "rejected">("pending");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const act = async (action: "approve" | "reject") => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/agent/proposals/${card.proposal_id}/${action}`, { method: "POST" });
      setStatus(action === "approve" ? "approved" : "rejected");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Acción fallida.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-2xl border border-amber-400/30 bg-amber-950/30 p-3 text-sm text-amber-50">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="rounded bg-amber-500/30 px-2 py-0.5 font-mono uppercase text-amber-100">
          {card.kind}
        </span>
        <span className="text-amber-200/80">
          Riesgo: {RISK_LABEL[card.risk_tier] ?? card.risk_tier}
        </span>
      </div>
      <div className="mb-2 font-medium">{card.summary || "Acción propuesta"}</div>
      {Object.keys(card.preview ?? {}).length > 0 ? (
        <details className="mb-2 text-xs text-amber-100/90">
          <summary className="cursor-pointer">Ver detalles</summary>
          <pre className="mt-1 whitespace-pre-wrap break-words font-mono text-[11px]">
            {JSON.stringify(card.preview, null, 2)}
          </pre>
        </details>
      ) : null}
      {status === "pending" ? (
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => act("approve")}
            disabled={busy}
            className="rounded-full bg-emerald-500 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-400 disabled:opacity-50"
          >
            ✓ Aprobar
          </button>
          <button
            onClick={() => act("reject")}
            disabled={busy}
            className="rounded-full bg-rose-600 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-500 disabled:opacity-50"
          >
            ✕ Rechazar
          </button>
        </div>
      ) : (
        <div className="text-xs font-semibold text-amber-100">
          {status === "approved" ? "✓ Aprobado." : "✕ Rechazado."}
        </div>
      )}
      {error ? <div className="mt-1 text-xs text-rose-300">{error}</div> : null}
    </div>
  );
}
