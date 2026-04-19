"use client";

import Link from "next/link";

type Card = {
  card_kind: "key_decrypt_error";
  scope: string;
  reason?: string | null;
  message?: string | null;
  settings_url?: string | null;
};

/**
 * Surfaces a `KeyDecryptError`: the encrypted blob exists but we can't
 * unwrap it (KEK rotated without re-wrap, ciphertext corrupted, etc.).
 * The fix is always "re-enter the API key", so we deep-link to settings.
 */
export function KeyDecryptErrorCard({ card }: { card: Card }) {
  const settingsHref = card.settings_url ?? "/settings";
  return (
    <div className="rounded-2xl border border-amber-400/40 bg-amber-950/40 p-3 text-sm text-amber-50">
      <div className="mb-1 text-xs uppercase tracking-wide text-amber-300">
        Clave cifrada no se pudo descifrar
      </div>
      <div className="mb-1 font-semibold">
        {card.message ?? "No pudimos leer tu clave guardada."}
      </div>
      <p className="mb-2 whitespace-pre-wrap text-amber-100/90">
        Vuelve a introducir tu API key en ajustes para reactivar este proveedor.
        Tus otros proveedores no se ven afectados.
      </p>
      {card.reason ? (
        <details className="mb-2 text-xs text-amber-200/70">
          <summary className="cursor-pointer">Detalles técnicos</summary>
          <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-amber-900/60 p-2 font-mono text-[11px]">
            {card.reason}
          </pre>
        </details>
      ) : null}
      <Link
        href={settingsHref}
        className="inline-block rounded-full bg-amber-600 px-3 py-1 text-xs font-semibold text-white hover:bg-amber-500"
      >
        Reintroducir clave
      </Link>
    </div>
  );
}
