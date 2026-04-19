import * as React from "react";

import { cn } from "@/lib/utils";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "w-full rounded border border-border bg-surface-inset px-3 py-2 text-sm text-fg",
        className
      )}
      {...props}
    />
  );
}
