"use client";

import { LanguageSection } from "@/components/features/language/language-section";
import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { useTranslation } from "@/lib/i18n";

export default function LanguageSettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.language.title")}
        intro={t("settings.hub.section.language.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("language.sectionTitle")}>
          <LanguageSection />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
