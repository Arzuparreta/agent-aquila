import * as React from "react";

import { cn } from "@/lib/utils";

export function Button({
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "rounded border border-border bg-surface-elevated px-3 py-2 text-sm font-medium text-fg hover:bg-surface-muted",
        className
      )}
      {...props}
    />
  );
}
