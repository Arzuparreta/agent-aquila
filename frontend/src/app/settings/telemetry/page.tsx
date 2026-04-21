"use client";

import Link from "next/link";

import { TelemetryDashboard } from "@/components/features/telemetry/telemetry-dashboard";
import { ProtectedPage } from "@/components/features/protected-page";
import { useTranslation } from "@/lib/i18n";

export default function TelemetrySettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <div className="min-h-screen bg-surface-base text-fg">
        <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-surface-elevated px-4 py-3 shadow-sm">
          <Link
            href="/settings"
            className="rounded-md px-2 py-1 text-sm text-fg-muted hover:bg-surface-muted"
          >
            {t("telemetry.dashboardBack")}
          </Link>
          <h1 className="text-base font-semibold">{t("telemetry.dashboardTitle")}</h1>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-4">
          <p className="mb-6 text-sm text-fg-muted">{t("telemetry.dashboardIntro")}</p>
          <TelemetryDashboard />
        </main>
      </div>
    </ProtectedPage>
  );
}
