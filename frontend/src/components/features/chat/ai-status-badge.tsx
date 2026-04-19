"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { AIHealth } from "@/types/api";

type Tone = {
  label: string;
  dot: string;
  textCls: string;
  borderCls: string;
};

const REFRESH_MS = 60_000;

/**
 * Compact pill in the chat top bar that shows whether the active AI
 * provider is healthy. Polls /ai/health once a minute (cheap), and on
 * focus, so artists notice immediately when their key was rejected /
 * disabled / never set.
 *
 *   verde   = active provider, last test ok
 *   ámbar   = needs setup (no key) or never tested
 *   rojo    = last test failed
 *   gris    = AI disabled by user
 */
export function AIStatusBadge() {
  const [health, setHealth] = useState<AIHealth | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function poll() {
      try {
        const data = await apiFetch<AIHealth>("/ai/health");
        if (!cancelled) {
          setHealth(data);
          setLoading(false);
        }
      } catch {
        if (!cancelled) setLoading(false);
      }
    }
    void poll();
    const id = window.setInterval(poll, REFRESH_MS);
    const onFocus = () => void poll();
    window.addEventListener("focus", onFocus);
    return () => {
      cancelled = true;
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, []);

  if (loading || !health) return null;

  const tone = resolveTone(health);
  const title = health.message ?? tone.label;

  return (
    <Link
      href="/settings"
      title={title}
      aria-label={`Estado de IA: ${title}`}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tone.borderCls,
        tone.textCls,
        "hover:bg-interactive-hover"
      )}
    >
      <span className={cn("inline-block h-2 w-2 rounded-full", tone.dot)} aria-hidden="true" />
      <span className="hidden sm:inline">{tone.label}</span>
    </Link>
  );
}

function resolveTone(health: AIHealth): Tone {
  if (health.ai_disabled) {
    return {
      label: "IA desactivada",
      dot: "bg-slate-400",
      textCls: "text-fg-subtle",
      borderCls: "border-border"
    };
  }
  if (health.needs_setup || !health.active_provider_kind) {
    return {
      label: "Configura IA",
      dot: "bg-amber-400",
      textCls: "text-amber-700 dark:text-amber-300",
      borderCls: "border-amber-300 dark:border-amber-900/40"
    };
  }
  if (health.last_test?.ok === false) {
    return {
      label: providerName(health.active_provider_kind) + " · error",
      dot: "bg-rose-500",
      textCls: "text-rose-700 dark:text-rose-300",
      borderCls: "border-rose-300 dark:border-rose-900/40"
    };
  }
  if (health.last_test?.ok === true) {
    return {
      label: providerName(health.active_provider_kind),
      dot: "bg-emerald-500",
      textCls: "text-emerald-700 dark:text-emerald-300",
      borderCls: "border-emerald-300 dark:border-emerald-900/40"
    };
  }
  return {
    label: providerName(health.active_provider_kind),
    dot: "bg-slate-400",
    textCls: "text-fg-subtle",
    borderCls: "border-border"
  };
}

function providerName(kind: string | null): string {
  if (!kind) return "IA";
  switch (kind) {
    case "openai":
    case "openai_compatible":
      return "OpenAI";
    case "ollama":
      return "Ollama";
    case "google_ai_studio":
    case "google_genai":
      return "Google AI";
    case "anthropic":
      return "Anthropic";
    case "azure_openai":
      return "Azure OpenAI";
    case "openrouter":
      return "OpenRouter";
    default:
      return kind;
  }
}
