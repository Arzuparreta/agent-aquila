"use client";

import { Suspense } from "react";

import { InboxRouteFallback } from "@/components/features/inbox/inbox-route-fallback";
import { ProtectedPage } from "@/components/features/protected-page";
import { InboxPage } from "@/components/features/inbox/inbox-page";

export default function InboxRoute() {
  return (
    <ProtectedPage>
      <Suspense fallback={<InboxRouteFallback />}>
        <InboxPage />
      </Suspense>
    </ProtectedPage>
  );
}
