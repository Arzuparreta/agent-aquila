"use client";

import { AgentRuntimeSection } from "@/components/features/ai-settings/agent-runtime-section";
import { useProviderConfigs } from "@/components/features/ai-settings/use-provider-configs";
import { ProtectedPage } from "@/components/features/protected-page";
import { SettingsContentCard, SettingsLayout } from "@/components/features/settings/settings-shell";
import { useProviderRegistry } from "@/lib/ai-providers";
import { useTranslation } from "@/lib/i18n";

export default function AgentRuntimeSettingsPage() {
  const { t } = useTranslation();
  const { providers, loading: providersLoading } = useProviderRegistry();
  const api = useProviderConfigs({ providers, providersLoading });

  return (
    <ProtectedPage>
      <SettingsLayout
        title={t("settings.hub.section.runtime.title")}
        intro={t("settings.hub.section.runtime.description")}
        backHref="/settings"
        backLabel={t("settings.hub.backToSettings")}
      >
        <SettingsContentCard title={t("settings.agentRuntime.title")} intro={t("settings.agentRuntime.intro")}>
          <AgentRuntimeSection
            agentRuntime={api.agentRuntime}
            formKey={api.agentRuntimeFormKey}
            saving={api.agentRuntimeSaving}
            error={api.agentRuntimeError}
            patchAgentRuntime={api.patchAgentRuntime}
            resetAllAgentRuntimeOverrides={api.resetAllAgentRuntimeOverrides}
          />
        </SettingsContentCard>
      </SettingsLayout>
    </ProtectedPage>
  );
}
