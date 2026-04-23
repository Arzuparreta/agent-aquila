"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function SettingsLayout({
  title,
  intro,
  backHref,
  backLabel,
  children,
  contentClassName
}: {
  title: string;
  intro?: string;
  backHref: string;
  backLabel: string;
  children: ReactNode;
  contentClassName?: string;
}) {
  return (
    <div className="min-h-screen bg-surface-base text-fg">
      <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-surface-elevated px-4 py-3 shadow-sm">
        <Link href={backHref} className="rounded-md px-2 py-1 text-sm text-fg-muted hover:bg-surface-muted">
          {backLabel}
        </Link>
        <h1 className="text-base font-semibold">{title}</h1>
      </header>
      <main className={cn("mx-auto max-w-5xl px-4 py-4", contentClassName)}>
        {intro ? <p className="mb-4 text-sm text-fg-muted">{intro}</p> : null}
        {children}
      </main>
    </div>
  );
}

export function SettingsContentCard({
  title,
  intro,
  children,
  className
}: {
  title: string;
  intro?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={className}>
      <h2 className="mb-1 text-base font-semibold">{title}</h2>
      {intro ? <p className="mb-3 text-xs text-fg-subtle">{intro}</p> : null}
      {children}
    </Card>
  );
}
