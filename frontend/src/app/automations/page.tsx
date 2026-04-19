"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ProtectedPage } from "@/components/features/protected-page";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch, ApiError } from "@/lib/api";
import type { Automation } from "@/types/automations";

/**
 * Plain-language automations panel.
 *
 * The artist sees a flat list of "rules" the agent has learned (or that they
 * created themselves), each shown as one line of natural-language description.
 * No prompt templates, no JSON conditions, no triggers, no model knobs — just
 * Edit / Disable / Delete. The technical fields stay in the DB and are reused
 * by the backend automation runner unchanged.
 */
export default function AutomationsPage() {
  const [rows, setRows] = useState<Automation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<{ id: number; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<Automation[]>("/automations");
      setRows(data);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cargar.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const toggleEnabled = async (row: Automation) => {
    setBusy(true);
    try {
      const updated = await apiFetch<Automation>(`/automations/${row.id}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !row.enabled })
      });
      setRows((prev) => prev?.map((r) => (r.id === updated.id ? updated : r)) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cambiar.");
    } finally {
      setBusy(false);
    }
  };

  const remove = async (row: Automation) => {
    if (!confirm(`¿Borrar la regla "${row.name}"?`)) return;
    setBusy(true);
    try {
      await apiFetch(`/automations/${row.id}`, { method: "DELETE" });
      setRows((prev) => prev?.filter((r) => r.id !== row.id) ?? null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo borrar.");
    } finally {
      setBusy(false);
    }
  };

  const saveEdit = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      const updated = await apiFetch<Automation>(`/automations/${editing.id}`, {
        method: "PATCH",
        body: JSON.stringify({ instruction_natural_language: editing.text })
      });
      setRows((prev) => prev?.map((r) => (r.id === updated.id ? updated : r)) ?? null);
      setEditing(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo guardar.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ProtectedPage>
      <div className="min-h-screen bg-surface-base text-fg">
        <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-surface-elevated px-4 py-3 shadow-sm">
          <Link
            href="/"
            className="rounded-md px-2 py-1 text-sm text-fg-muted hover:bg-surface-muted"
          >
            ← Volver al chat
          </Link>
          <h1 className="text-base font-semibold">Reglas aprendidas</h1>
        </header>
        <main className="mx-auto flex max-w-2xl flex-col gap-3 px-4 py-4">
          <p className="text-sm text-fg-muted">
            Tu mánager crea estas reglas automáticamente cuando le pides cosas como{" "}
            <em>“nunca contestes a este correo”</em> o{" "}
            <em>“avísame siempre que mencionen Madrid”</em>. Aquí puedes verlas, ajustarlas
            o eliminarlas.
          </p>

          {error ? (
            <div className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
              {error}
            </div>
          ) : null}

          {rows === null ? (
            <Card>Cargando…</Card>
          ) : rows.length === 0 ? (
            <Card>
              <p className="text-sm text-fg-muted">
                Aún no hay reglas. Cuando hables con tu mánager y aparezca alguna pauta,
                la verás aquí.
              </p>
            </Card>
          ) : (
            rows.map((row) => (
              <Card key={row.id}>
                <div className="mb-2 flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-semibold">{row.name}</div>
                    <div className="text-[11px] uppercase tracking-wide text-fg-subtle">
                      {row.source === "agent" ? "Aprendida automáticamente" : "Creada por ti"}
                      {row.run_count > 0 ? ` · ejecutada ${row.run_count}×` : ""}
                    </div>
                  </div>
                  <label className="flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={row.enabled}
                      onChange={() => toggleEnabled(row)}
                      disabled={busy}
                    />
                    Activa
                  </label>
                </div>

                {editing?.id === row.id ? (
                  <div className="grid gap-2">
                    <textarea
                      value={editing.text}
                      onChange={(e) => setEditing({ id: row.id, text: e.target.value })}
                      rows={3}
                      className="w-full rounded border border-border bg-surface-inset px-2 py-1 text-sm text-fg"
                    />
                    <div className="flex gap-2">
                      <Button
                        onClick={saveEdit}
                        disabled={busy}
                        className="border-primary bg-primary text-primary-fg hover:opacity-90"
                      >
                        Guardar
                      </Button>
                      <Button onClick={() => setEditing(null)} disabled={busy}>
                        Cancelar
                      </Button>
                    </div>
                  </div>
                ) : (
                  <p className="whitespace-pre-wrap text-sm text-fg">
                    {row.instruction_natural_language ||
                      "(Sin descripción en lenguaje natural — borrar y recrear desde el chat para que tu mánager la explique)."}
                  </p>
                )}

                <div className="mt-3 flex flex-wrap gap-2">
                  {editing?.id !== row.id ? (
                    <Button
                      onClick={() =>
                        setEditing({ id: row.id, text: row.instruction_natural_language || "" })
                      }
                    >
                      Editar
                    </Button>
                  ) : null}
                  <Button onClick={() => remove(row)} className="border-rose-300 text-rose-700">
                    Borrar
                  </Button>
                </div>
              </Card>
            ))
          )}
        </main>
      </div>
    </ProtectedPage>
  );
}
