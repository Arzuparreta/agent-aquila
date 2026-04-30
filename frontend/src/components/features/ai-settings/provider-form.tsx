"use client";

import { useEffect, useMemo } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { AIProvider } from "@/types/api";

import { ModelSelector } from "./model-selector";
import { StatusPill } from "./status-pill";
import { TestConnectionButton } from "./test-connection-button";
import type { ProviderDraft, UseProviderConfigsApi } from "./use-provider-configs";

type ProviderFormProps = {
  api: UseProviderConfigsApi;
};

/**
 * Right pane editing one provider's saved config.
 *
 * Renders provider-specific fields, chat model, then (when saved) agent-memory
 * embeddings and auxiliary ranking/classify LLM (same-as-active vs other provider),
 * advanced key/delete, and footer actions.
 */
export function ProviderForm({ api }: ProviderFormProps) {
  const { t } = useTranslation();
  const {
    providers,
    configs,
    selectedKind,
    selectedConfig,
    selectedProvider,
    activeKind,
    embeddingProviderKind,
    setEmbeddingProviderKind,
    refreshEmbeddingModels,
    updateEmbeddingModelForKind,
    embeddingModels,
    loadingEmbeddingModels,
    rankingProviderKind,
    setRankingProviderKind,
    refreshRankingModels,
    updateClassifyModelForKind,
    rankingModels,
    loadingRankingModels,
    draft,
    isDirty,
    isNew,
    models,
    loadingModels,
    testing,
    testResult,
    saving,
    saveError,
    updateDraft,
    discardDraft,
    save,
    test,
    setActive,
    remove,
    refreshModels
  } = api;

  const providersById = useMemo(() => new Map(providers.map((p) => [p.id, p])), [providers]);

  const useSeparateEmbeddingProvider = Boolean(
    embeddingProviderKind && activeKind && embeddingProviderKind !== activeKind
  );
  const memorySourceKind = useSeparateEmbeddingProvider
    ? (embeddingProviderKind as string)
    : activeKind;

  const useSeparateRankingProvider = Boolean(
    rankingProviderKind && activeKind && rankingProviderKind !== activeKind
  );
  const rankingSourceKind = useSeparateRankingProvider
    ? (rankingProviderKind as string)
    : activeKind;

  const canPickOtherProvider = Boolean(
    activeKind && configs.some((c) => c.provider_kind !== activeKind)
  );

  // Auto-load models the first time we land on a saved config that has
  // never been listed before (or after the user explicitly tests).
  useEffect(() => {
    if (!selectedKind || isDirty) return;
    if (selectedConfig?.has_api_key || selectedProvider?.auth_kind === "none") {
      void refreshModels();
    }
    // We intentionally only re-run when the selection changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKind]);

  useEffect(() => {
    if (!memorySourceKind) return;
    void refreshEmbeddingModels(memorySourceKind);
  }, [selectedConfig?.provider_kind, memorySourceKind, refreshEmbeddingModels]);

  useEffect(() => {
    if (!rankingSourceKind) return;
    void refreshRankingModels(rankingSourceKind);
  }, [selectedConfig?.provider_kind, rankingSourceKind, refreshRankingModels]);

  const editingMemoryRow = Boolean(
    selectedKind && memorySourceKind && selectedKind === memorySourceKind
  );

  const embeddingFieldValue = editingMemoryRow
    ? draft.embeddingModel
    : (configs.find((c) => c.provider_kind === memorySourceKind)?.embedding_model ?? "");

  const embeddingHelpRemote =
    selectedConfig && !editingMemoryRow && memorySourceKind
      ? t("settings.embeddings.editOnProviderHint", {
          label: providersById.get(memorySourceKind)?.label ?? memorySourceKind
        })
      : undefined;

  const editingRankingRow = Boolean(
    selectedKind && rankingSourceKind && selectedKind === rankingSourceKind
  );

  const classifyFieldValue = editingRankingRow
    ? draft.classifyModel
    : (configs.find((c) => c.provider_kind === rankingSourceKind)?.classify_model ?? "");

  const classifyHelpRemote =
    selectedConfig && !editingRankingRow && rankingSourceKind
      ? t("settings.ranking.editOnProviderHint", {
          label: providersById.get(rankingSourceKind)?.label ?? rankingSourceKind
        })
      : undefined;

  if (!selectedKind || !selectedProvider) {
    return (
      <div className="flex min-h-[16rem] flex-col items-center justify-center rounded-md border border-dashed border-border bg-surface-muted/40 p-6 text-center text-sm text-fg-subtle">
        {t("providerForm.selectPrompt")}
      </div>
    );
  }

  const isActive = activeKind === selectedKind;

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline gap-3">
        <h2 className="text-base font-semibold">{selectedProvider.label}</h2>
        {selectedConfig ? (
          <StatusPill
            status={selectedConfig.last_test}
            hasApiKey={selectedConfig.has_api_key}
            authNone={selectedProvider.auth_kind === "none"}
            showLabel
            size="md"
          />
        ) : (
          <span className="text-xs text-fg-subtle">{t("providerForm.newUnsaved")}</span>
        )}
        {selectedProvider.docs_url ? (
          <a
            href={selectedProvider.docs_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-primary underline-offset-4 hover:underline"
          >
            {t("providerForm.docs")}
          </a>
        ) : null}
      </header>
      <p className="text-xs text-fg-subtle">{selectedProvider.description}</p>

      <div className="grid gap-3">
        <ProviderInputs
          provider={selectedProvider}
          draft={draft}
          storedApiKey={Boolean(selectedConfig?.has_api_key)}
          onChange={(patch) => updateDraft(patch)}
          t={t}
        />

        <TestConnectionButton
          onTest={async () => {
            const result = await test();
            if (result?.ok) {
              await refreshModels();
            }
          }}
          pending={testing}
          result={testResult}
        />

        <ModelSelector
          label={t("settings.chatModel")}
          required
          value={draft.chatModel}
          onChange={(v) => updateDraft({ chatModel: v })}
          models={models}
          loading={loadingModels}
          capability="chat"
          helpText={modelHelpText(t, selectedProvider, models, loadingModels)}
        />
        {!selectedConfig ? (
          <ModelSelector
            label={t("settings.classifyModel")}
            value={draft.classifyModel}
            onChange={(v) => updateDraft({ classifyModel: v })}
            models={models}
            loading={loadingModels}
            capability="chat"
            helpText={t("settings.classifyHelp")}
          />
        ) : null}
        {selectedConfig ? (
          <div className="rounded-lg border border-border bg-surface-muted/35 p-3">
            <div className="text-sm font-semibold text-fg">{t("settings.embeddings.memoryBlockTitle")}</div>
            <p className="mt-1 text-xs text-fg-subtle">{t("settings.embeddings.memoryBlockIntro")}</p>
            <fieldset className="mt-3 flex flex-col gap-2">
              <label className="flex cursor-pointer items-start gap-2 text-sm text-fg">
                <input
                  type="radio"
                  name="memory-embed-source"
                  className="mt-0.5"
                  checked={!useSeparateEmbeddingProvider}
                  onChange={() => void setEmbeddingProviderKind(null)}
                />
                <span>{t("settings.embeddings.sameAsActive")}</span>
              </label>
              <label
                className={cn(
                  "flex items-start gap-2 text-sm",
                  canPickOtherProvider ? "cursor-pointer text-fg" : "cursor-not-allowed text-fg-muted"
                )}
              >
                <input
                  type="radio"
                  name="memory-embed-source"
                  className="mt-0.5"
                  checked={useSeparateEmbeddingProvider}
                  disabled={!canPickOtherProvider}
                  onChange={() => {
                    const first = configs.find((c) => c.provider_kind !== activeKind)?.provider_kind;
                    if (first) void setEmbeddingProviderKind(first);
                  }}
                />
                <span>{t("settings.embeddings.useOther")}</span>
              </label>
            </fieldset>
            {!canPickOtherProvider ? (
              <p className="mt-2 text-xs text-fg-muted">{t("settings.embeddings.needTwoProviders")}</p>
            ) : null}

            {useSeparateEmbeddingProvider ? (
              <div className="mt-3 grid gap-1">
                <label htmlFor="memory-embed-provider" className="text-sm font-medium text-fg-muted">
                  {t("settings.embeddings.selectProvider")}
                </label>
                <select
                  id="memory-embed-provider"
                  className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
                  value={embeddingProviderKind ?? ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v) void setEmbeddingProviderKind(v);
                  }}
                >
                  {configs
                    .filter((c) => c.provider_kind !== activeKind)
                    .map((c) => (
                      <option key={c.provider_kind} value={c.provider_kind}>
                        {providersById.get(c.provider_kind)?.label ?? c.provider_kind}
                      </option>
                    ))}
                </select>
              </div>
            ) : null}

            <div className="mt-3">
              <ModelSelector
                label={t("settings.embeddingModel")}
                required
                value={embeddingFieldValue}
                onChange={(v) => {
                  if (editingMemoryRow) {
                    updateDraft({ embeddingModel: v });
                  } else if (memorySourceKind) {
                    void updateEmbeddingModelForKind(memorySourceKind, v);
                  }
                }}
                models={embeddingModels}
                loading={loadingEmbeddingModels}
                capability="embedding"
                helpText={embeddingHelpRemote}
                emptyHint={t("settings.embeddings.pressTestEmbedding")}
              />
            </div>
          </div>
        ) : (
          <ModelSelector
            label={t("settings.embeddingModel")}
            required
            value={draft.embeddingModel}
            onChange={(v) => updateDraft({ embeddingModel: v })}
            models={models}
            loading={loadingModels}
            capability="embedding"
            helpText={t("settings.embeddings.hintNewProvider")}
          />
        )}

        {selectedConfig ? (
          <div className="rounded-lg border border-border bg-surface-muted/35 p-3">
            <div className="text-sm font-semibold text-fg">{t("settings.ranking.blockTitle")}</div>
            <p className="mt-1 text-xs text-fg-subtle">{t("settings.ranking.blockIntro")}</p>
            <fieldset className="mt-3 flex flex-col gap-2">
              <label className="flex cursor-pointer items-start gap-2 text-sm text-fg">
                <input
                  type="radio"
                  name="ranking-llm-source"
                  className="mt-0.5"
                  checked={!useSeparateRankingProvider}
                  onChange={() => void setRankingProviderKind(null)}
                />
                <span>{t("settings.ranking.sameAsActive")}</span>
              </label>
              <label
                className={cn(
                  "flex items-start gap-2 text-sm",
                  canPickOtherProvider ? "cursor-pointer text-fg" : "cursor-not-allowed text-fg-muted"
                )}
              >
                <input
                  type="radio"
                  name="ranking-llm-source"
                  className="mt-0.5"
                  checked={useSeparateRankingProvider}
                  disabled={!canPickOtherProvider}
                  onChange={() => {
                    const first = configs.find((c) => c.provider_kind !== activeKind)?.provider_kind;
                    if (first) void setRankingProviderKind(first);
                  }}
                />
                <span>{t("settings.ranking.useOther")}</span>
              </label>
            </fieldset>
            {!canPickOtherProvider ? (
              <p className="mt-2 text-xs text-fg-muted">{t("settings.ranking.needTwoProviders")}</p>
            ) : null}

            {useSeparateRankingProvider ? (
              <div className="mt-3 grid gap-1">
                <label htmlFor="ranking-llm-provider" className="text-sm font-medium text-fg-muted">
                  {t("settings.ranking.selectProvider")}
                </label>
                <select
                  id="ranking-llm-provider"
                  className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
                  value={rankingProviderKind ?? ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v) void setRankingProviderKind(v);
                  }}
                >
                  {configs
                    .filter((c) => c.provider_kind !== activeKind)
                    .map((c) => (
                      <option key={c.provider_kind} value={c.provider_kind}>
                        {providersById.get(c.provider_kind)?.label ?? c.provider_kind}
                      </option>
                    ))}
                </select>
              </div>
            ) : null}

            <div className="mt-3">
              <ModelSelector
                label={t("settings.classifyModel")}
                value={classifyFieldValue}
                onChange={(v) => {
                  if (editingRankingRow) {
                    updateDraft({ classifyModel: v });
                  } else if (rankingSourceKind) {
                    void updateClassifyModelForKind(rankingSourceKind, v);
                  }
                }}
                models={rankingModels}
                loading={loadingRankingModels}
                capability="chat"
                helpText={classifyHelpRemote ?? t("settings.classifyHelp")}
                emptyHint={t("settings.ranking.pressTestChat")}
              />
            </div>
          </div>
        ) : null}

        <details className="rounded-md border border-border bg-surface-muted/40 p-3">
          <summary className="cursor-pointer text-sm font-medium text-fg-muted">{t("advanced.summary")}</summary>
          <div className="mt-3 grid gap-3">
            {selectedConfig?.has_api_key ? (
              <Button
                type="button"
                onClick={() => updateDraft({ apiKey: "" })}
                className="self-start text-rose-700 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-950/40"
              >
                {t("providerForm.clearKeyOnSave")}
              </Button>
            ) : null}
            {selectedConfig ? (
              <Button
                type="button"
                onClick={() => {
                  if (
                    window.confirm(
                      t("providerForm.deleteConfirm", { label: selectedProvider.label })
                    )
                  ) {
                    void remove(selectedKind);
                  }
                }}
                className="self-start border-rose-300 text-rose-700 hover:bg-rose-50 dark:border-rose-900/40 dark:text-rose-300 dark:hover:bg-rose-950/40"
              >
                {t("providerForm.deleteProvider")}
              </Button>
            ) : null}
          </div>
        </details>

        {saveError ? (
          <p
            role="alert"
            className="rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-200"
          >
            {saveError}
          </p>
        ) : null}
      </div>

      <footer className="sticky bottom-0 -mx-4 -mb-4 flex flex-wrap items-center justify-end gap-2 border-t border-border bg-surface-elevated px-4 py-3">
        {isDirty ? (
          <Button type="button" onClick={discardDraft} className="text-fg-muted">
            {t("providerForm.discardChanges")}
          </Button>
        ) : null}
        <Button
          type="button"
          onClick={() => void save()}
          disabled={!isDirty || saving}
          className={cn(
            "border-primary bg-primary text-primary-fg hover:opacity-90",
            (!isDirty || saving) && "cursor-not-allowed opacity-60 hover:opacity-60"
          )}
        >
          {saving ? t("common.saving") : isNew ? t("providerForm.create") : t("providerForm.saveChanges")}
        </Button>
        {selectedConfig && !isActive ? (
          <Button
            type="button"
            onClick={() => void setActive(selectedKind)}
            className="border-emerald-500 text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-950/40"
          >
            {t("providerForm.useAsActive")}
          </Button>
        ) : null}
      </footer>
    </section>
  );
}

function ProviderInputs({
  provider,
  draft,
  storedApiKey,
  onChange,
  t
}: {
  provider: AIProvider;
  draft: ProviderDraft;
  storedApiKey: boolean;
  onChange: (patch: Partial<ProviderDraft>) => void;
  t: (key: TranslationKey, params?: Record<string, string | number>) => string;
}) {
  return (
    <div className="grid gap-3">
      {provider.fields.map((f) => {
        const id = `pf-${provider.id}-${f.key}`;
        if (f.key === "api_key") {
          const placeholder = storedApiKey
            ? t("providerForm.apiKeyPlaceholderStored")
            : f.placeholder || "sk-...";
          return (
            <div key={f.key} className="grid gap-1">
              <label htmlFor={id} className="text-sm font-medium text-fg">
                {f.label}
                {f.required && !storedApiKey ? <span className="ml-1 text-red-600">*</span> : null}
              </label>
              <Input
                id={id}
                type="password"
                autoComplete="new-password"
                placeholder={placeholder}
                value={draft.apiKey}
                onChange={(e) => onChange({ apiKey: e.target.value })}
              />
              {f.help ? <p className="text-xs text-fg-subtle">{f.help}</p> : null}
            </div>
          );
        }
        if (f.key === "base_url") {
          return (
            <div key={f.key} className="grid gap-1">
              <label htmlFor={id} className="text-sm font-medium text-fg">
                {f.label}
                {f.required ? <span className="ml-1 text-red-600">*</span> : null}
              </label>
              <Input
                id={id}
                type="url"
                inputMode="url"
                placeholder={f.placeholder || provider.default_base_url || ""}
                value={draft.baseUrl}
                onChange={(e) => onChange({ baseUrl: e.target.value })}
              />
              {f.help ? <p className="text-xs text-fg-subtle">{f.help}</p> : null}
              {provider.id === "ollama" ? (
                <p
                  className="text-xs text-fg-subtle"
                  dangerouslySetInnerHTML={{ __html: t("providerForm.ollamaBaseUrlHint") }}
                />
              ) : null}
            </div>
          );
        }
        const value = draft.extras[f.key] ?? "";
        return (
          <div key={f.key} className="grid gap-1">
            <label htmlFor={id} className="text-sm font-medium text-fg">
              {f.label}
              {f.required ? <span className="ml-1 text-red-600">*</span> : null}
            </label>
            <Input
              id={id}
              type={f.type === "url" ? "url" : "text"}
              placeholder={f.placeholder}
              value={value}
              onChange={(e) =>
                onChange({ extras: { ...draft.extras, [f.key]: e.target.value } })
              }
            />
            {f.help ? <p className="text-xs text-fg-subtle">{f.help}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

function modelHelpText(
  t: (key: TranslationKey, params?: Record<string, string | number>) => string,
  provider: AIProvider,
  models: import("@/types/api").ModelInfo[],
  loading: boolean
): string | undefined {
  if (loading) return undefined;
  const hints =
    provider.suggested_chat_models && provider.suggested_chat_models.length > 0
      ? t("providerForm.modelSuggested", { list: provider.suggested_chat_models.join(", ") })
      : null;
  if (models.length === 0) {
    if (provider.id === "ollama") {
      return [t("providerForm.ollamaListFailed"), hints].filter(Boolean).join(" ");
    }
    return [hints, t("providerForm.pressTestToRefresh")].filter(Boolean).join(" ");
  }
  return hints ?? undefined;
}
