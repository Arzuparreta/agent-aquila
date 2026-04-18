"use client";

import { FormEvent, useMemo, useState } from "react";

import { ConnectorsSection } from "@/components/features/connectors/connectors-section";
import { AdvancedSection } from "@/components/features/ai-settings/advanced-section";
import { ModelSelector } from "@/components/features/ai-settings/model-selector";
import { ProviderFields } from "@/components/features/ai-settings/provider-fields";
import { ProviderPicker } from "@/components/features/ai-settings/provider-picker";
import { TestConnectionButton } from "@/components/features/ai-settings/test-connection-button";
import { useSettingsForm } from "@/components/features/ai-settings/use-settings-form";
import { LanguageSection } from "@/components/features/language/language-section";
import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useProviderRegistry } from "@/lib/ai-providers";
import { useTranslation } from "@/lib/i18n";

type Banner = { variant: "error" | "success" | "info"; message: string };

export default function SettingsPage() {
  const { t } = useTranslation();
  const registry = useProviderRegistry();
  const ctrl = useSettingsForm({ providers: registry.providers, providersLoading: registry.loading });
  const [banner, setBanner] = useState<Banner | null>(null);
  const [saving, setSaving] = useState(false);

  const canTest = useMemo(() => {
    if (!ctrl.provider) return false;
    for (const field of ctrl.provider.fields) {
      if (!field.required) continue;
      if (field.key === "api_key") {
        const hasKey = ctrl.form.apiKey.trim() || ctrl.settings?.has_api_key;
        if (!hasKey) return false;
      } else if (field.key === "base_url") {
        if (!ctrl.form.baseUrl.trim()) return false;
      } else if (!(ctrl.form.extras[field.key] ?? "").trim()) {
        return false;
      }
    }
    return true;
  }, [ctrl.form, ctrl.provider, ctrl.settings?.has_api_key]);

  const canSave = useMemo(() => {
    if (!ctrl.provider) return false;
    if (!ctrl.form.chatModel.trim()) return false;
    return true;
  }, [ctrl.form.chatModel, ctrl.provider]);

  const handleSave = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBanner(null);
    setSaving(true);
    try {
      const result = await ctrl.save();
      if (!result) return;
      setBanner({ variant: result.ok ? "success" : "error", message: result.message });
    } finally {
      setSaving(false);
    }
  };

  const handleClearKey = async () => {
    setBanner(null);
    await ctrl.clearKey();
    setBanner({ variant: "success", message: t("settings.keyCleared") });
  };

  const modelPickerHint = ctrl.provider?.model_list_is_deployments
    ? t("settings.deploymentHint")
    : ctrl.tested?.ok
      ? undefined
      : t("settings.testToLoad");

  const testedOk = ctrl.tested?.ok === true;
  const disabledReason = !ctrl.provider
    ? t("settings.disabledPickProvider")
    : !testedOk && ctrl.models.length === 0
      ? t("settings.disabledTestFirst")
      : null;

  const encryptedNoteParts = t("settings.encryptedNote", { var: "FERNET_ENCRYPTION_KEY" }).split(/<code>|<\/code>/);

  return (
    <div className="mx-auto max-w-3xl">
      <LanguageSection />

      <div className="mb-6">
        <h1 className="text-2xl font-semibold">{t("settings.title")}</h1>
        <p className="mt-1 text-sm text-slate-600">{t("settings.intro")}</p>
      </div>

      {banner ? (
        <div className="mb-4">
          <AlertBanner variant={banner.variant} message={banner.message} onDismiss={() => setBanner(null)} />
        </div>
      ) : null}

      {registry.error ? (
        <div className="mb-4">
          <AlertBanner variant="error" message={registry.error} />
        </div>
      ) : null}
      {ctrl.loadError ? (
        <div className="mb-4">
          <AlertBanner variant="error" message={ctrl.loadError} />
        </div>
      ) : null}

      <form onSubmit={handleSave}>
        <Card className="grid gap-6 p-5">
          {/* Step 1: provider picker */}
          <section className="grid gap-2">
            <div className="flex items-center justify-between gap-2">
              <label htmlFor="ai-provider-combobox" className="text-sm font-medium text-slate-800">
                {t("settings.providerLabel")}
                <span className="ml-1 text-red-600">*</span>
              </label>
              {ctrl.provider?.docs_url ? (
                <a
                  href={ctrl.provider.docs_url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-slate-500 underline hover:text-slate-700"
                >
                  {t("settings.docsLink", { label: ctrl.provider.label })}
                </a>
              ) : null}
            </div>
            <ProviderPicker
              providers={ctrl.providers}
              value={ctrl.form.providerId}
              onChange={ctrl.setProviderId}
              disabled={ctrl.providersLoading}
            />
            {ctrl.provider?.description ? (
              <p className="text-xs text-slate-500">{ctrl.provider.description}</p>
            ) : null}
          </section>

          {ctrl.provider ? (
            <>
              <div className="h-px w-full bg-slate-200" />

              {/* Step 2: dynamic fields */}
              <section className="grid gap-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                  {t("settings.credentials")}
                </h2>
                <ProviderFields
                  provider={ctrl.provider}
                  value={{ apiKey: ctrl.form.apiKey, baseUrl: ctrl.form.baseUrl, extras: ctrl.form.extras }}
                  storedApiKey={Boolean(ctrl.settings?.has_api_key)}
                  onChange={({ apiKey, baseUrl, extras }) =>
                    ctrl.setFieldsValue({ apiKey, baseUrl, extras })
                  }
                />
              </section>

              <div className="h-px w-full bg-slate-200" />

              {/* Step 3: test connection */}
              <section className="grid gap-2">
                <TestConnectionButton
                  onTest={() => void ctrl.test()}
                  pending={ctrl.testing}
                  result={ctrl.tested}
                  disabled={!canTest}
                />
                {!canTest ? (
                  <p className="text-xs text-slate-500">{t("settings.fillRequired")}</p>
                ) : null}
              </section>

              <div className="h-px w-full bg-slate-200" />

              {/* Step 4: model selection */}
              <section className="grid gap-3">
                <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-600">
                  {t("settings.modelSection")}
                </h2>
                <ModelSelector
                  id="chat-model"
                  label={ctrl.provider.model_list_is_deployments ? t("settings.chatDeployment") : t("settings.chatModel")}
                  required
                  value={ctrl.form.chatModel}
                  onChange={(value) => ctrl.setField("chatModel", value)}
                  models={ctrl.models}
                  loading={ctrl.loadingModels}
                  capability="chat"
                  disabledReason={disabledReason}
                  helpText={modelPickerHint}
                />
              </section>

              {/* Advanced */}
              <AdvancedSection>
                <ModelSelector
                  id="embedding-model"
                  label={t("settings.embeddingModel")}
                  value={ctrl.form.embeddingModel}
                  onChange={(value) => ctrl.setField("embeddingModel", value)}
                  models={ctrl.models}
                  loading={ctrl.loadingModels}
                  capability="embedding"
                  disabledReason={disabledReason}
                  helpText={t("settings.embeddingHelp")}
                />
                <ModelSelector
                  id="classify-model"
                  label={t("settings.classifyModel")}
                  value={ctrl.form.classifyModel}
                  onChange={(value) => ctrl.setField("classifyModel", value)}
                  models={ctrl.models}
                  loading={ctrl.loadingModels}
                  capability="chat"
                  disabledReason={disabledReason}
                  helpText={t("settings.classifyHelp")}
                />
                <label className="flex items-center gap-2 text-sm text-slate-700">
                  <input
                    type="checkbox"
                    checked={ctrl.form.aiDisabled}
                    onChange={(event) => ctrl.setField("aiDisabled", event.target.checked)}
                  />
                  {t("settings.disableAi")}
                </label>
                {ctrl.settings?.has_api_key ? (
                  <div className="flex items-center justify-between gap-2 border-t border-slate-200 pt-3">
                    <span className="text-xs text-slate-500">{t("settings.keyOnFile")}</span>
                    <Button type="button" className="border-dashed" onClick={() => void handleClearKey()}>
                      {t("settings.clearKey")}
                    </Button>
                  </div>
                ) : null}
              </AdvancedSection>

              <div className="flex items-center justify-between border-t border-slate-200 pt-4">
                <span className="text-xs text-slate-500">
                  {encryptedNoteParts[0]}
                  <code className="rounded bg-slate-100 px-1">{encryptedNoteParts[1] ?? "FERNET_ENCRYPTION_KEY"}</code>
                  {encryptedNoteParts[2] ?? ""}
                </span>
                <Button
                  type="submit"
                  className="bg-slate-900 text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:bg-slate-900"
                  disabled={!canSave || saving}
                >
                  {saving ? t("settings.savingButton") : t("settings.saveButton")}
                </Button>
              </div>
            </>
          ) : registry.loading ? (
            <p className="text-sm text-slate-500">{t("settings.providersLoading")}</p>
          ) : null}
        </Card>
      </form>

      <ConnectorsSection />
    </div>
  );
}
