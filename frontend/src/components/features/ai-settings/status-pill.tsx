"use client";

import { cn } from "@/lib/utils";
import type { ProviderTestStatus } from "@/types/api";

type StatusPillProps = {
  status: ProviderTestStatus;
  hasApiKey: boolean;
  authNone?: boolean;
  size?: "sm" | "md";
  showLabel?: boolean;
};

/**
 * Coloured dot + optional label that summarises a provider's last test
 * result. Used in the rail (one per provider card) and in the chat top bar
 * for the active provider.
 *
 *   verde  = last test ok
 *   rojo   = last test failed
 *   gris   = never tested OR no API key (for providers that need one)
 */
export function StatusPill({ status, hasApiKey, authNone, size = "sm", showLabel = false }: StatusPillProps) {
  const tone = resolveTone(status, hasApiKey, authNone);
  const dotSize = size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5";
  const tooltip = describe(status, hasApiKey, authNone);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 text-xs",
        size === "sm" ? "leading-none" : "leading-tight",
        tone.text
      )}
      title={tooltip}
      aria-label={tooltip}
    >
      <span className={cn("inline-block rounded-full", dotSize, tone.dot)} aria-hidden="true" />
      {showLabel ? <span>{tone.label}</span> : null}
    </span>
  );
}

function resolveTone(status: ProviderTestStatus, hasApiKey: boolean, authNone?: boolean) {
  if (status?.ok === true) {
    return {
      label: "Conectado",
      dot: "bg-emerald-500",
      text: "text-emerald-700 dark:text-emerald-300"
    };
  }
  if (status?.ok === false) {
    return {
      label: "Error",
      dot: "bg-rose-500",
      text: "text-rose-700 dark:text-rose-300"
    };
  }
  if (!hasApiKey && !authNone) {
    return {
      label: "Sin clave",
      dot: "bg-amber-400",
      text: "text-amber-700 dark:text-amber-300"
    };
  }
  return {
    label: "Sin probar",
    dot: "bg-slate-400",
    text: "text-fg-subtle"
  };
}

function describe(status: ProviderTestStatus, hasApiKey: boolean, authNone?: boolean): string {
  if (status?.ok === true) {
    const when = status.at ? ` (${formatRelative(status.at)})` : "";
    return `Conectado${when}: ${status.message ?? ""}`;
  }
  if (status?.ok === false) {
    const when = status.at ? ` (${formatRelative(status.at)})` : "";
    return `Error${when}: ${status.message ?? "fallo en la última prueba"}`;
  }
  if (!hasApiKey && !authNone) return "Falta la API key";
  return "Aún sin probar — pulsa Probar conexión";
}

function formatRelative(iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return iso;
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 60) return `hace ${diffSec}s`;
  if (diffSec < 3600) return `hace ${Math.round(diffSec / 60)} min`;
  if (diffSec < 86_400) return `hace ${Math.round(diffSec / 3600)} h`;
  return new Date(iso).toLocaleString();
}
