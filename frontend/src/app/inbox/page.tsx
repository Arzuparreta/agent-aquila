"use client";

import { Suspense } from "react";

import { ProtectedPage } from "@/components/features/protected-page";
import { InboxPage } from "@/components/features/inbox/inbox-page";

export default function InboxRoute() {
  return (
    <ProtectedPage>
      <Suspense
        fallback={
          <div className="flex h-screen w-screen items-center justify-center bg-slate-950 text-sm text-slate-400">
            Cargando bandeja…
          </div>
        }
      >
        <InboxPage />
      </Suspense>
    </ProtectedPage>
  );
}
