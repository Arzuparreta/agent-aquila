"use client";

import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { SkillsSection } from "@/components/features/skills/skills-section";
import { useTranslation } from "@/lib/i18n";

export default function SkillsSettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.skills.title")}
        intro={t("settings.hub.section.skills.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("settings.skillsSectionTitle")}>
          <SkillsSection />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
