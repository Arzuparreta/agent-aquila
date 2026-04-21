"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Card } from "@/components/ui/card";
import { useTranslation } from "@/lib/i18n";
import { TELEMETRY_CHANGED_EVENT } from "@/lib/telemetry/constants";
import { getTelemetryEnabled, setTelemetryEnabled } from "@/lib/telemetry/record";

export function TelemetrySection() {
  const { t } = useTranslation();
  const [enabled, setEnabled] = useState(false);

  useEffect(() => {
    setEnabled(getTelemetryEnabled());
    const onChange = () => setEnabled(getTelemetryEnabled());
    window.addEventListener(TELEMETRY_CHANGED_EVENT, onChange);
    return () => window.removeEventListener(TELEMETRY_CHANGED_EVENT, onChange);
  }, []);

  return (
    <Card>
      <h2 className="mb-1 text-base font-semibold">{t("telemetry.sectionTitle")}</h2>
      <p className="mb-3 text-xs text-fg-subtle">{t("telemetry.intro")}</p>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <label className="inline-flex cursor-pointer items-center gap-2 text-sm text-fg">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setTelemetryEnabled(e.target.checked)}
          />
          {t("telemetry.enableLabel")}
        </label>
        <Link
          href="/settings/telemetry"
          className="text-sm font-medium text-fg underline decoration-dotted underline-offset-2 hover:text-fg-muted"
        >
          {t("telemetry.openDashboard")}
        </Link>
      </div>
    </Card>
  );
}
