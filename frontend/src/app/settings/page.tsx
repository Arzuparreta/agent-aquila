"use client";

import Link from "next/link";
import { useState } from "react";

import { ProtectedPage } from "@/components/features/protected-page";
import { AdvancedSection } from "@/components/features/ai-settings/advanced-section";
import { ModelSelector } from "@/components/features/ai-settings/model-selector";
import { ProviderFields } from "@/components/features/ai-settings/provider-fields";
import { ProviderPicker } from "@/components/features/ai-settings/provider-picker";
import { TestConnectionButton } from "@/components/features/ai-settings/test-connection-button";
import { useSettingsForm } from "@/components/features/ai-settings/use-settings-form";
import { ConnectorsSection } from "@/components/features/connectors/connectors-section";
import { LanguageSection } from "@/components/features/language/language-section";
import { MaintenanceSection } from "@/components/features/maintenance/maintenance-section";
import { ThemeSection } from "@/components/features/theme/theme-section";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useProviderRegistry } from "@/lib/ai-providers";
import { useTranslation } from "@/lib/i18n";

/**
 * Technical / advanced settings.
 *
 * Hidden behind the top-bar dropdown menu intentionally — the artist should never
 * need to come here in normal use; the agent does the heavy lifting. Layout is
 * minimal and uses the existing AI / connector / language components verbatim,
 * just rearranged to be much less visually busy than the previous tabs page.
 */
export default function SettingsPage() {
  const { t } = useTranslation();
  const { providers, loading: providersLoading } = useProviderRegistry();
  const form = useSettingsForm({ providers, providersLoading });
  const [savedToast, setSavedToast] = useState<string | null>(null);

  const onSave = async () => {
    const result = await form.save();
    if (result) setSavedToast(result.message);
    setTimeout(() => setSavedToast(null), 3000);
  };

  return (
    <ProtectedPage>
      <div className="min-h-screen bg-surface-base text-fg">
        <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-surface-elevated px-4 py-3 shadow-sm">
          <Link
            href="/"
            className="rounded-md px-2 py-1 text-sm text-fg-muted hover:bg-surface-muted"
          >
            ← Volver al chat
          </Link>
          <h1 className="text-base font-semibold">Ajustes técnicos</h1>
        </header>
        <main className="mx-auto flex max-w-2xl flex-col gap-4 px-4 py-4">
          <Card>
            <h2 className="mb-1 text-base font-semibold">Modelo de IA</h2>
            <p className="mb-3 text-xs text-fg-subtle">
              Trae tu propia clave (BYOK). Puedes elegir un modelo distinto para cada tarea.
            </p>
            <div className="grid gap-3">
              <ProviderPicker
                providers={providers}
                value={form.form.providerId}
                onChange={form.setProviderId}
                disabled={providersLoading}
              />
              {form.provider ? (
                <>
                  <ProviderFields
                    provider={form.provider}
                    storedApiKey={Boolean(form.settings?.has_api_key)}
                    value={{
                      apiKey: form.form.apiKey,
                      baseUrl: form.form.baseUrl,
                      extras: form.form.extras
                    }}
                    onChange={(next) =>
                      form.setFieldsValue({
                        apiKey: next.apiKey,
                        baseUrl: next.baseUrl,
                        extras: next.extras
                      })
                    }
                  />
                  <TestConnectionButton
                    onTest={form.test}
                    pending={form.testing}
                    result={form.tested}
                  />
                  <ModelSelector
                    label="Modelo de chat"
                    value={form.form.chatModel}
                    onChange={(v) => form.setField("chatModel", v)}
                    models={form.models}
                    loading={form.loadingModels}
                    capability="chat"
                  />
                  <ModelSelector
                    label="Modelo de embeddings (búsqueda semántica)"
                    value={form.form.embeddingModel}
                    onChange={(v) => form.setField("embeddingModel", v)}
                    models={form.models}
                    loading={form.loadingModels}
                    capability="embedding"
                  />
                  <AdvancedSection summary="Avanzado">
                    <ModelSelector
                      label="Modelo de clasificación (opcional)"
                      value={form.form.classifyModel}
                      onChange={(v) => form.setField("classifyModel", v)}
                      models={form.models}
                      loading={form.loadingModels}
                    />
                    <label className="mt-2 flex items-center gap-2 text-sm text-fg">
                      <input
                        type="checkbox"
                        checked={form.form.aiDisabled}
                        onChange={(e) => form.setField("aiDisabled", e.target.checked)}
                      />
                      Desactivar IA temporalmente
                    </label>
                    {form.settings?.has_api_key ? (
                      <Button className="mt-3" onClick={form.clearKey}>
                        Borrar clave guardada
                      </Button>
                    ) : null}
                  </AdvancedSection>
                </>
              ) : null}
              <div className="mt-2 flex items-center gap-3">
                <Button
                  onClick={onSave}
                  className="border-primary bg-primary text-primary-fg hover:opacity-90"
                >
                  Guardar
                </Button>
                {savedToast ? (
                  <span className="text-sm text-emerald-600">{savedToast}</span>
                ) : null}
              </div>
            </div>
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">{t("theme.sectionTitle")}</h2>
            <ThemeSection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">{t("language.sectionTitle")}</h2>
            <LanguageSection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">Conectores</h2>
            <p className="mb-3 text-xs text-fg-subtle">
              Casi siempre tu mánager te guiará para conectar Gmail, Outlook o Google Drive
              desde el chat. Esta zona es para inspeccionar o quitar manualmente conexiones.
            </p>
            <ConnectorsSection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">Mantenimiento</h2>
            <MaintenanceSection />
          </Card>
        </main>
      </div>
    </ProtectedPage>
  );
}
