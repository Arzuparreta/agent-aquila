"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { AIProvider, ProviderConfig } from "@/types/api";

import { StatusPill } from "./status-pill";

type ProviderListProps = {
  providers: AIProvider[];
  configs: ProviderConfig[];
  activeKind: string | null;
  selectedKind: string | null;
  onSelect: (kind: string) => void;
  onStartNew: (kind: string) => void;
};

/**
 * Left rail of the AI settings page.
 *
 * Shows one card per **configured** provider (with its connection status
 * and an "Activo" chip when applicable). At the bottom there's an
 * "Añadir proveedor" disclosure listing every registry provider that
 * isn't configured yet — clicking one creates an empty draft so the user
 * can fill it in on the right pane.
 */
export function ProviderList({
  providers,
  configs,
  activeKind,
  selectedKind,
  onSelect,
  onStartNew
}: ProviderListProps) {
  const [adding, setAdding] = useState(false);

  const configuredKinds = new Set(configs.map((c) => c.provider_kind));
  const providersByIdAvailable = providers.filter((p) => !configuredKinds.has(p.id));

  return (
    <aside className="flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-fg-subtle">
          Proveedores
        </h3>
        <span className="text-xs text-fg-subtle">{configs.length} guardados</span>
      </div>
      <ul className="flex flex-col gap-1.5">
        {configs.length === 0 ? (
          <li className="rounded-md border border-dashed border-border px-3 py-3 text-xs text-fg-subtle">
            Aún no has guardado ningún proveedor. Añade uno abajo para empezar.
          </li>
        ) : null}
        {configs.map((cfg) => {
          const provider = providers.find((p) => p.id === cfg.provider_kind);
          const label = provider?.label ?? cfg.provider_kind;
          const selected = selectedKind === cfg.provider_kind;
          const isActive = activeKind === cfg.provider_kind;
          return (
            <li key={cfg.provider_kind}>
              <button
                type="button"
                onClick={() => onSelect(cfg.provider_kind)}
                aria-current={selected ? "true" : undefined}
                className={cn(
                  "group flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left transition-colors",
                  selected
                    ? "border-primary bg-surface-muted"
                    : "border-border bg-surface-elevated hover:bg-surface-muted"
                )}
              >
                <span className="min-w-0 flex-1">
                  <span className="flex items-center gap-2">
                    <span className="truncate text-sm font-medium text-fg">{label}</span>
                    {isActive ? (
                      <span className="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300">
                        Activo
                      </span>
                    ) : null}
                  </span>
                  <span className="mt-0.5 flex items-center gap-2 text-xs text-fg-subtle">
                    <span className="truncate">{cfg.chat_model || "(sin modelo)"}</span>
                  </span>
                </span>
                <StatusPill
                  status={cfg.last_test}
                  hasApiKey={cfg.has_api_key}
                  authNone={provider?.auth_kind === "none"}
                />
              </button>
            </li>
          );
        })}
      </ul>

      {providersByIdAvailable.length > 0 ? (
        <div className="mt-2">
          {!adding ? (
            <Button
              type="button"
              onClick={() => setAdding(true)}
              className="w-full justify-center text-sm"
            >
              + Añadir proveedor
            </Button>
          ) : (
            <div className="rounded-md border border-border bg-surface-muted p-2">
              <div className="mb-1 px-1 text-xs font-medium text-fg-subtle">Elige un proveedor:</div>
              <ul className="flex flex-col gap-0.5">
                {providersByIdAvailable.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => {
                        onStartNew(p.id);
                        setAdding(false);
                      }}
                      className="block w-full truncate rounded px-2 py-1.5 text-left text-sm text-fg hover:bg-interactive-hover"
                    >
                      {p.label}
                      <span className="ml-2 text-xs text-fg-subtle">{p.description}</span>
                    </button>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                onClick={() => setAdding(false)}
                className="mt-1 block w-full rounded px-2 py-1 text-xs text-fg-subtle hover:bg-interactive-hover"
              >
                Cancelar
              </button>
            </div>
          )}
        </div>
      ) : null}
    </aside>
  );
}
