"use client";

import { intlLocaleTag, useTranslation, type Locale, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { ProviderTestStatus } from "@/types/api";

type StatusPillProps = {
  status: ProviderTestStatus;
  hasApiKey: boolean;
  authNone?: boolean;
  size?: "sm" | "md";
  showLabel?: boolean;
};

type TFn = (key: TranslationKey, params?: Record<string, string | number>) => string;

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
  const { t, locale } = useTranslation();
  const tone = resolveTone(t, status, hasApiKey, authNone);
  const dotSize = size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5";
  const tooltip = describe(t, locale, status, hasApiKey, authNone);
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

function resolveTone(t: TFn, status: ProviderTestStatus, hasApiKey: boolean, authNone?: boolean) {
  if (status?.ok === true) {
    return {
      label: t("statusPill.connected"),
      dot: "bg-emerald-500",
      text: "text-emerald-700 dark:text-emerald-300"
    };
  }
  if (status?.ok === false) {
    return {
      label: t("statusPill.error"),
      dot: "bg-rose-500",
      text: "text-rose-700 dark:text-rose-300"
    };
  }
  if (!hasApiKey && !authNone) {
    return {
      label: t("statusPill.noKey"),
      dot: "bg-amber-400",
      text: "text-amber-700 dark:text-amber-300"
    };
  }
  return {
    label: t("statusPill.notTested"),
    dot: "bg-slate-400",
    text: "text-fg-subtle"
  };
}

function describe(
  t: TFn,
  locale: Locale,
  status: ProviderTestStatus,
  hasApiKey: boolean,
  authNone?: boolean
): string {
  const tag = intlLocaleTag(locale);
  if (status?.ok === true) {
    const when = status.at ? ` (${formatRelative(t, tag, status.at)})` : "";
    return t("statusPill.tooltip.connected", {
      when,
      message: status.message ?? ""
    });
  }
  if (status?.ok === false) {
    const when = status.at ? ` (${formatRelative(t, tag, status.at)})` : "";
    return t("statusPill.tooltip.error", {
      when,
      message: status.message ?? t("statusPill.lastTestFailed")
    });
  }
  if (!hasApiKey && !authNone) return t("statusPill.tooltip.noKey");
  return t("statusPill.tooltip.notTested");
}

function formatRelative(t: TFn, localeTag: string, iso: string): string {
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return iso;
  const diffSec = Math.round((Date.now() - then) / 1000);
  if (diffSec < 60) return t("time.relative.seconds", { seconds: diffSec });
  if (diffSec < 3600) return t("time.relative.minutes", { minutes: Math.round(diffSec / 60) });
  if (diffSec < 86_400) return t("time.relative.hours", { hours: Math.round(diffSec / 3600) });
  return new Date(iso).toLocaleString(localeTag);
}
