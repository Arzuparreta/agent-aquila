import * as React from "react";

import { cn } from "@/lib/utils";

export function Select({ className, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn("w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm", className)}
      {...props}
    />
  );
}
