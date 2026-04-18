"use client";

import { useState } from "react";

import { useTranslation } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type AdvancedSectionProps = {
  children: React.ReactNode;
  defaultOpen?: boolean;
  summary?: string;
};

/**
 * Disclosure wrapper for rarely-touched AI settings (embedding/classify
 * models, "disable AI", clear-key). Intentionally low-chrome so it fits
 * inside the main Card without competing with the primary form.
 */
export function AdvancedSection({ children, defaultOpen = false, summary }: AdvancedSectionProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const label = summary ?? t("advanced.summary");
  return (
    <div className="rounded-md border border-slate-200 bg-slate-50/50">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "flex w-full items-center justify-between px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100",
          open && "border-b border-slate-200"
        )}
      >
        <span>{label}</span>
        <svg
          width="10"
          height="10"
          viewBox="0 0 10 10"
          aria-hidden="true"
          className={cn("transition-transform", open ? "rotate-180" : "rotate-0")}
        >
          <path d="M2 4L5 7L8 4" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open ? <div className="grid gap-3 p-3">{children}</div> : null}
    </div>
  );
}
