"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiFetch, ApiError } from "@/lib/api";

/**
 * Settings card body that lets the artist hard-delete the legacy auto-spawned
 * chat threads (Mozilla / LinkedIn / Correo \u00b7 X / Evento \u00b7 Y / etc.) created by the
 * old proactive layer. Only deletes threads with zero user-typed messages, so it
 * never destroys real conversations.
 */
export function MaintenanceSection() {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onConfirm = async () => {
    setPending(true);
    setError(null);
    try {
      const res = await apiFetch<{ deleted: number }>("/maintenance/purge-proactive-threads", {
        method: "POST"
      });
      setResult(
        res.deleted === 0
          ? "No había conversaciones automáticas que limpiar."
          : `Eliminadas ${res.deleted} conversaciones automáticas.`
      );
      setConfirmOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo limpiar.");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-slate-500">
        Borra las conversaciones que se generaron automáticamente para correos
        entrantes (por ejemplo &ldquo;Mozilla&rdquo;, &ldquo;LinkedIn&rdquo;,
        &ldquo;Correo · X&rdquo;) en las que nunca llegaste a escribir nada.
        Las conversaciones reales en las que sí participaste no se tocan.
      </p>
      <div className="flex items-center gap-3">
        <Button
          onClick={() => setConfirmOpen(true)}
          className="bg-red-600 text-white hover:bg-red-700"
          disabled={pending}
        >
          Limpiar conversaciones automáticas
        </Button>
        {result ? <span className="text-sm text-emerald-700">{result}</span> : null}
        {error ? <span className="text-sm text-rose-600">{error}</span> : null}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        title="¿Borrar conversaciones automáticas?"
        description="Se eliminarán de forma permanente todas las conversaciones generadas automáticamente por correos / contactos / eventos en las que no escribiste nada."
        confirmLabel="Borrar"
        cancelLabel="Cancelar"
        pending={pending}
        onConfirm={onConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
