"use client";

import { MaintenanceSection } from "@/components/features/maintenance/maintenance-section";
import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { useTranslation } from "@/lib/i18n";

export default function MaintenanceSettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.maintenance.title")}
        intro={t("settings.hub.section.maintenance.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("settings.maintenanceSectionTitle")}>
          <MaintenanceSection />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
