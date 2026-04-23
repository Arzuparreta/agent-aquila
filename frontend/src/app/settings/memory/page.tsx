"use client";

import { MemorySection } from "@/components/features/memory/memory-section";
import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { useTranslation } from "@/lib/i18n";

export default function MemorySettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.memory.title")}
        intro={t("settings.hub.section.memory.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("settings.memorySectionTitle")}>
          <MemorySection />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
