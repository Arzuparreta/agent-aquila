"use client";

import { ConnectorsSection } from "@/components/features/connectors/connectors-section";
import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsLayout } from "@/components/features/settings/settings-shell";
import { useTranslation } from "@/lib/i18n";

export default function ConnectorsSettingsPage() {
  const { t } = useTranslation();

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.connectors.title")}
        intro={t("settings.hub.section.connectors.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <ConnectorsSection />
      </SettingsLayout>
    </ProtectedPage>
  );
}
