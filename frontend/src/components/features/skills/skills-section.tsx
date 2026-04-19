"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";

type SkillSummary = {
  slug: string;
  title: string;
  summary: string;
};

type SkillFull = SkillSummary & { body: string };

/**
 * Read-only viewer over the agent's skills folder
 * (``backend/skills/*.md``). Lists every recipe the agent can load via the
 * ``load_skill`` tool. Skills are bundled with the deployment, not stored
 * per-user — editing happens in the repo.
 */
export function SkillsSection() {
  const [list, setList] = useState<SkillSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<SkillFull | null>(null);
  const [opening, setOpening] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<SkillSummary[]>("/skills");
      setList(data);
      setError(null);
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "No se pudieron cargar las habilidades.",
      );
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onOpen = useCallback(async (slug: string) => {
    setOpening(slug);
    try {
      const full = await apiFetch<SkillFull>(`/skills/${encodeURIComponent(slug)}`);
      setOpen(full);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo abrir.");
    } finally {
      setOpening(null);
    }
  }, []);

  return (
    <div className="grid gap-2">
      <p className="text-xs text-fg-subtle">
        Recetas en Markdown que el agente puede cargar bajo demanda. Vienen con
        el despliegue (carpeta <code>backend/skills/</code>); para añadir o
        editar habilidades, modifica los archivos del repositorio.
      </p>
      {error ? (
        <div
          role="alert"
          className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-200"
        >
          {error}
        </div>
      ) : null}
      {list === null ? (
        <p className="text-xs text-fg-subtle">Cargando…</p>
      ) : list.length === 0 ? (
        <p className="text-xs text-fg-subtle">No hay habilidades disponibles.</p>
      ) : (
        <ul className="divide-y divide-border-subtle rounded-md border border-border-subtle bg-surface-elevated">
          {list.map((s) => (
            <li
              key={s.slug}
              className="flex items-start justify-between gap-3 px-3 py-2"
            >
              <div className="min-w-0 flex-1">
                <div className="text-sm font-medium text-fg">{s.title}</div>
                <div className="text-[11px] font-mono text-fg-subtle">{s.slug}</div>
                <p className="mt-1 text-xs text-fg-muted">{s.summary}</p>
              </div>
              <button
                onClick={() => void onOpen(s.slug)}
                disabled={opening === s.slug}
                className="shrink-0 rounded-md bg-surface-muted px-2 py-1 text-xs text-fg hover:bg-surface-inset disabled:opacity-60"
              >
                {opening === s.slug ? "…" : "Ver"}
              </button>
            </li>
          ))}
        </ul>
      )}
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4"
          role="dialog"
          aria-modal="true"
        >
          <div className="flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-border-subtle bg-surface-elevated shadow-xl">
            <header className="flex items-start justify-between gap-3 border-b border-border-subtle px-4 py-3">
              <div className="min-w-0">
                <div className="text-base font-semibold text-fg">
                  {open.title}
                </div>
                <div className="text-[11px] font-mono text-fg-subtle">
                  {open.slug}
                </div>
              </div>
              <button
                onClick={() => setOpen(null)}
                className="rounded-md p-1 text-fg-muted hover:bg-interactive-hover"
                aria-label="Cerrar"
              >
                ✕
              </button>
            </header>
            <pre className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap break-words bg-surface-base px-4 py-3 font-mono text-xs leading-relaxed text-fg">
              {open.body}
            </pre>
          </div>
        </div>
      ) : null}
    </div>
  );
}
