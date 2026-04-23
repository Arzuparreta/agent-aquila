"use client";

import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { ThemeSection } from "@/components/features/theme/theme-section";
import { useTranslation } from "@/lib/i18n";

export default function AppearanceSettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.appearance.title")}
        intro={t("settings.hub.section.appearance.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("theme.sectionTitle")}>
          <ThemeSection />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
