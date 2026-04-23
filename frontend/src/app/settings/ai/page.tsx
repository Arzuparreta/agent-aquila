"use client";

import { useProviderConfigs } from "@/components/features/ai-settings/use-provider-configs";
import { ProtectedPage } from "@/components/features/protected-page";
import { AIModelsPanel } from "@/components/features/settings/ai-models-panel";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { useProviderRegistry } from "@/lib/ai-providers";
import { useTranslation } from "@/lib/i18n";

export default function AISettingsPage() {
  const { t } = useTranslation();
  const { providers, loading: providersLoading } = useProviderRegistry();
  const api = useProviderConfigs({ providers, providersLoading });

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.ai.title")}
        intro={t("settings.hub.section.ai.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("settings.technical.aiModelsTitle")} intro={t("settings.technical.aiModelsIntro")}>
          <AIModelsPanel api={api} />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
