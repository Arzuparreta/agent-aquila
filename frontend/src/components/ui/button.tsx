import * as React from "react";

import { cn } from "@/lib/utils";

export function Button({
  className,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn("rounded border px-3 py-2 text-sm font-medium hover:bg-slate-100", className)}
      {...props}
    />
  );
}
