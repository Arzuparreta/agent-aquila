"use client";

import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { UsersSettingsSection } from "@/components/features/users/users-settings-section";
import { useTranslation } from "@/lib/i18n";

export default function UsersSettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.users.title")}
        intro={t("settings.hub.section.users.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard
          title={t("settings.hub.section.users.title")}
          intro="Create, deactivate, and maintain user accounts for this instance."
        >
          <UsersSettingsSection />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
