"use client";

import { useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";

type Card = {
  card_kind: "undo";
  action_id: number;
  kind: string;
  summary: string | null;
  status: string;
  reversible_until: string | null;
  result: Record<string, unknown> | null;
};

/**
 * "Done — UNDO?" card for auto-applied actions.
 *
 * The reversible window comes from the backend (`reversible_until`); we tick a 1s
 * timer locally to render the countdown, and disable the undo button when the
 * window expires. Hitting undo posts to `/agent/actions/{id}/undo` and flips the
 * card to "Reverted".
 */
export function UndoCard({ card }: { card: Card }) {
  const [status, setStatus] = useState(card.status || "executed");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const expiry = useMemo(
    () => (card.reversible_until ? new Date(card.reversible_until).getTime() : 0),
    [card.reversible_until]
  );
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    if (status !== "executed") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [status]);

  const remainingMs = Math.max(0, expiry - now);
  const expired = expiry > 0 && remainingMs === 0;
  const showUndo = status === "executed" && !expired;

  const undo = async () => {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/agent/actions/${card.action_id}/undo`, { method: "POST" });
      setStatus("reverted");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo deshacer.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center gap-3 rounded-2xl border border-emerald-400/30 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-50">
      <div className="text-lg">✓</div>
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{card.summary || card.kind}</div>
        <div className="text-xs text-emerald-200/80">
          {status === "reverted"
            ? "Revertido."
            : showUndo
            ? `Hecho. Puedes deshacer ${Math.ceil(remainingMs / 1000)}s.`
            : "Hecho."}
        </div>
      </div>
      {showUndo ? (
        <button
          onClick={undo}
          disabled={busy}
          className="rounded-full bg-emerald-700/70 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
        >
          Deshacer
        </button>
      ) : null}
      {error ? <div className="text-xs text-rose-200">{error}</div> : null}
    </div>
  );
}
