"use client";

import { useTranslation } from "@/lib/i18n";

export function InboxRouteFallback() {
  const { t } = useTranslation();
  return (
    <div className="app-shell items-center justify-center bg-surface-base text-sm text-fg-subtle">
      {t("inbox.loadingRoute")}
    </div>
  );
}
