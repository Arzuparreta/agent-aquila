"use client";

import { useEffect } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { AIProvider, ProviderConfig } from "@/types/api";

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
 * Renders provider-specific fields from the registry, two model selectors
 * (chat + embedding), an "advanced" disclosure with the optional classify
 * model + clear-key affordance, and a sticky footer with the three primary
 * actions: probar, guardar, usar como activo.
 */
export function ProviderForm({ api }: ProviderFormProps) {
  const {
    selectedKind,
    selectedConfig,
    selectedProvider,
    activeKind,
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

  if (!selectedKind || !selectedProvider) {
    return (
      <div className="flex min-h-[16rem] flex-col items-center justify-center rounded-md border border-dashed border-border bg-surface-muted/40 p-6 text-center text-sm text-fg-subtle">
        Selecciona un proveedor de la izquierda o pulsa &quot;+ Añadir proveedor&quot; para empezar.
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
          <span className="text-xs text-fg-subtle">Nuevo (sin guardar)</span>
        )}
        {selectedProvider.docs_url ? (
          <a
            href={selectedProvider.docs_url}
            target="_blank"
            rel="noreferrer"
            className="text-xs text-primary underline-offset-4 hover:underline"
          >
            Documentación ↗
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
        />

        <TestConnectionButton onTest={() => void test()} pending={testing} result={testResult} />

        <ModelSelector
          label="Modelo de chat"
          required
          value={draft.chatModel}
          onChange={(v) => updateDraft({ chatModel: v })}
          models={models}
          loading={loadingModels}
          capability="chat"
          helpText={modelHelpText(selectedProvider, models, loadingModels)}
        />
        <ModelSelector
          label="Modelo de embeddings"
          required
          value={draft.embeddingModel}
          onChange={(v) => updateDraft({ embeddingModel: v })}
          models={models}
          loading={loadingModels}
          capability="embedding"
        />

        <details className="rounded-md border border-border bg-surface-muted/40 p-3">
          <summary className="cursor-pointer text-sm font-medium text-fg-muted">Avanzado</summary>
          <div className="mt-3 grid gap-3">
            <ModelSelector
              label="Modelo de clasificación (opcional)"
              value={draft.classifyModel}
              onChange={(v) => updateDraft({ classifyModel: v })}
              models={models}
              loading={loadingModels}
              helpText="Si lo dejas vacío usamos el modelo de chat también para clasificar."
            />
            {selectedConfig?.has_api_key ? (
              <Button
                type="button"
                onClick={() => updateDraft({ apiKey: "" })}
                className="self-start text-rose-700 hover:bg-rose-50 dark:text-rose-300 dark:hover:bg-rose-950/40"
              >
                Borrar clave guardada al guardar
              </Button>
            ) : null}
            {selectedConfig ? (
              <Button
                type="button"
                onClick={() => {
                  if (
                    window.confirm(
                      `¿Eliminar la configuración de ${selectedProvider.label}? Esto borra la API key cifrada de este proveedor para tu usuario.`
                    )
                  ) {
                    void remove(selectedKind);
                  }
                }}
                className="self-start border-rose-300 text-rose-700 hover:bg-rose-50 dark:border-rose-900/40 dark:text-rose-300 dark:hover:bg-rose-950/40"
              >
                Eliminar este proveedor
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
            Descartar cambios
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
          {saving ? "Guardando…" : isNew ? "Crear" : "Guardar cambios"}
        </Button>
        {selectedConfig && !isActive ? (
          <Button
            type="button"
            onClick={() => void setActive(selectedKind)}
            className="border-emerald-500 text-emerald-700 hover:bg-emerald-50 dark:text-emerald-300 dark:hover:bg-emerald-950/40"
          >
            Usar este proveedor
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
  onChange
}: {
  provider: AIProvider;
  draft: ProviderDraft;
  storedApiKey: boolean;
  onChange: (patch: Partial<ProviderDraft>) => void;
}) {
  return (
    <div className="grid gap-3">
      {provider.fields.map((f) => {
        const id = `pf-${provider.id}-${f.key}`;
        if (f.key === "api_key") {
          const placeholder = storedApiKey
            ? "•••••• (clave guardada — escribe para reemplazar)"
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
                <p className="text-xs text-fg-subtle">
                  No incluyas <code>/v1</code> — lo añadimos automáticamente al llamar al endpoint compatible con OpenAI.
                </p>
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

function modelHelpText(provider: AIProvider, models: import("@/types/api").ModelInfo[], loading: boolean): string | undefined {
  if (loading) return undefined;
  const hints =
    provider.suggested_chat_models && provider.suggested_chat_models.length > 0
      ? `Modelos sugeridos: ${provider.suggested_chat_models.join(", ")}.`
      : null;
  if (models.length === 0) {
    if (provider.id === "ollama") {
      return [
        "No conseguimos listar tus modelos. Asegúrate de que Ollama está corriendo y prueba la conexión.",
        hints
      ]
        .filter(Boolean)
        .join(" ");
    }
    return [hints, "Pulsa Probar conexión para refrescar la lista de modelos disponibles."].filter(Boolean).join(" ");
  }
  return hints ?? undefined;
}
