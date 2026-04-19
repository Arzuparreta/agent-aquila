"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";
import { isExtraField } from "@/lib/ai-providers";
import {
  AIProvider,
  ListModelsResponse,
  ModelInfo,
  ProviderConfig,
  ProviderConfigsResponse,
  ProviderConfigUpsertRequest,
  STORED_API_KEY_SENTINEL,
  TestConnectionResult
} from "@/types/api";

/**
 * Per-provider in-memory draft.
 *
 * Drafts survive switching the rail selection — typing into Ollama, then
 * clicking Google AI Studio, then back to Ollama, preserves the typed
 * values until the user explicitly saves or discards.
 */
export type ProviderDraft = {
  apiKey: string;
  baseUrl: string;
  chatModel: string;
  embeddingModel: string;
  classifyModel: string;
  extras: Record<string, string>;
};

const EMPTY_DRAFT: ProviderDraft = {
  apiKey: "",
  baseUrl: "",
  chatModel: "",
  embeddingModel: "",
  classifyModel: "",
  extras: {}
};

function extrasFromUnknown(extras: Record<string, unknown> | null): Record<string, string> {
  if (!extras) return {};
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(extras)) {
    if (v == null) continue;
    out[k] = String(v);
  }
  return out;
}

function draftFromConfig(cfg: ProviderConfig | null, provider: AIProvider | null): ProviderDraft {
  if (!cfg) {
    if (!provider) return { ...EMPTY_DRAFT };
    const extras: Record<string, string> = {};
    for (const f of provider.fields) {
      if (isExtraField(f.key) && f.default) extras[f.key] = f.default;
    }
    return {
      apiKey: "",
      baseUrl: provider.default_base_url ?? "",
      chatModel: provider.default_chat_model ?? "",
      embeddingModel: provider.default_embedding_model ?? "",
      classifyModel: provider.default_classify_model ?? "",
      extras
    };
  }
  return {
    apiKey: "",
    baseUrl: cfg.base_url ?? "",
    chatModel: cfg.chat_model ?? "",
    embeddingModel: cfg.embedding_model ?? "",
    classifyModel: cfg.classify_model ?? "",
    extras: extrasFromUnknown(cfg.extras)
  };
}

export type UseProviderConfigsApi = {
  loading: boolean;
  loadError: string | null;
  configs: ProviderConfig[];
  activeKind: string | null;
  aiDisabled: boolean;

  selectedKind: string | null;
  selectedConfig: ProviderConfig | null;
  selectedProvider: AIProvider | null;
  draft: ProviderDraft;
  isDirty: boolean;
  isNew: boolean;

  models: ModelInfo[];
  loadingModels: boolean;
  testing: boolean;
  testResult: TestConnectionResult | null;
  saving: boolean;
  saveError: string | null;
  toast: string | null;

  selectKind: (kind: string) => void;
  startNew: (kind: string) => void;
  updateDraft: (patch: Partial<ProviderDraft>) => void;
  discardDraft: () => void;
  save: () => Promise<ProviderConfig | null>;
  test: () => Promise<TestConnectionResult | null>;
  setActive: (kind?: string) => Promise<void>;
  remove: (kind: string) => Promise<void>;
  setAIDisabled: (disabled: boolean) => Promise<void>;
  refreshModels: () => Promise<void>;
  reload: () => Promise<void>;
};

type Options = {
  providers: AIProvider[];
  providersLoading: boolean;
};

/**
 * Owns the multi-provider state for the new settings UI.
 *
 * The previous single-form hook drove a single-row form keyed by
 * `provider_kind`, overwriting the same DB row whenever you switched
 * providers. This hook keeps every provider's draft in memory and only
 * touches the saved `(user_id, provider_kind)` row that the user
 * explicitly saved — so swapping providers no longer destroys keys.
 */
export function useProviderConfigs({ providers, providersLoading }: Options): UseProviderConfigsApi {
  const [loading, setLoading] = useState<boolean>(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [configs, setConfigs] = useState<ProviderConfig[]>([]);
  const [activeKind, setActiveKind] = useState<string | null>(null);
  const [aiDisabled, setAIDisabledState] = useState<boolean>(false);

  const [selectedKind, setSelectedKind] = useState<string | null>(null);
  const [draftByKind, setDraftByKind] = useState<Record<string, ProviderDraft>>({});
  // Tracks which kinds the user has touched. We use this to decide when to
  // reseed a draft from the saved config (after a fresh save) vs. preserve
  // an unsaved in-memory draft.
  const touchedRef = useRef<Set<string>>(new Set());

  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResult | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const providersByIdRef = useRef(new Map<string, AIProvider>());
  useEffect(() => {
    providersByIdRef.current = new Map(providers.map((p) => [p.id, p]));
  }, [providers]);

  const selectedProvider = useMemo<AIProvider | null>(() => {
    if (!selectedKind) return null;
    return providersByIdRef.current.get(selectedKind) ?? providers.find((p) => p.id === selectedKind) ?? null;
  }, [selectedKind, providers]);

  const selectedConfig = useMemo<ProviderConfig | null>(() => {
    if (!selectedKind) return null;
    return configs.find((c) => c.provider_kind === selectedKind) ?? null;
  }, [selectedKind, configs]);

  const isNew = Boolean(selectedKind && !selectedConfig);

  const draft = useMemo<ProviderDraft>(() => {
    if (!selectedKind) return { ...EMPTY_DRAFT };
    const explicit = draftByKind[selectedKind];
    if (explicit) return explicit;
    return draftFromConfig(selectedConfig, selectedProvider);
  }, [selectedKind, draftByKind, selectedConfig, selectedProvider]);

  const isDirty = useMemo<boolean>(() => {
    if (!selectedKind) return false;
    if (isNew) {
      // A brand-new provider is "dirty" the moment the user touched it.
      return touchedRef.current.has(selectedKind);
    }
    if (!selectedConfig) return false;
    const baseline = draftFromConfig(selectedConfig, selectedProvider);
    return (
      draft.apiKey !== "" ||
      draft.baseUrl !== baseline.baseUrl ||
      draft.chatModel !== baseline.chatModel ||
      draft.embeddingModel !== baseline.embeddingModel ||
      draft.classifyModel !== baseline.classifyModel ||
      JSON.stringify(draft.extras || {}) !== JSON.stringify(baseline.extras || {})
    );
  }, [selectedKind, selectedConfig, selectedProvider, draft, isNew]);

  const reload = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const data = await apiFetch<ProviderConfigsResponse>("/ai/providers/configs");
      setConfigs(data.configs);
      setActiveKind(data.active_provider_kind);
      setAIDisabledState(data.ai_disabled);
      // After reload, drop drafts for kinds whose saved row matches what we
      // just got back (the save probably succeeded). Keep drafts for kinds
      // that diverge so an in-flight edit isn't silently wiped.
      setDraftByKind((current) => {
        const next: Record<string, ProviderDraft> = {};
        for (const [kind, draftValue] of Object.entries(current)) {
          const cfg = data.configs.find((c) => c.provider_kind === kind);
          if (!cfg) {
            // It might be a kind the user is configuring for the first time.
            next[kind] = draftValue;
          } else {
            // Drop touched flag and let the UI rehydrate from the saved row.
            touchedRef.current.delete(kind);
          }
        }
        return next;
      });
      // Auto-select the active provider if nothing is selected yet.
      setSelectedKind((current) => current ?? data.active_provider_kind ?? data.configs[0]?.provider_kind ?? null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "Could not load AI configs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const selectKind = useCallback((kind: string) => {
    setSelectedKind(kind);
    setTestResult(null);
    setSaveError(null);
    setModels([]);
  }, []);

  const startNew = useCallback(
    (kind: string) => {
      setSelectedKind(kind);
      setTestResult(null);
      setSaveError(null);
      setModels([]);
      const provider = providersByIdRef.current.get(kind) ?? null;
      setDraftByKind((current) => ({
        ...current,
        [kind]: draftFromConfig(null, provider)
      }));
      touchedRef.current.add(kind);
    },
    []
  );

  const updateDraft = useCallback(
    (patch: Partial<ProviderDraft>) => {
      if (!selectedKind) return;
      touchedRef.current.add(selectedKind);
      setDraftByKind((current) => {
        const baseline = current[selectedKind] ?? draftFromConfig(selectedConfig, selectedProvider);
        return {
          ...current,
          [selectedKind]: { ...baseline, ...patch }
        };
      });
      // Editing api_key / base_url / extras invalidates a prior connection test.
      if (patch.apiKey !== undefined || patch.baseUrl !== undefined || patch.extras !== undefined) {
        setTestResult((current) => (current?.ok ? null : current));
      }
    },
    [selectedKind, selectedConfig, selectedProvider]
  );

  const discardDraft = useCallback(() => {
    if (!selectedKind) return;
    touchedRef.current.delete(selectedKind);
    setDraftByKind((current) => {
      const next = { ...current };
      delete next[selectedKind];
      return next;
    });
    setTestResult(null);
    setSaveError(null);
  }, [selectedKind]);

  const buildUpsert = useCallback((): ProviderConfigUpsertRequest => {
    const extras: Record<string, string> = {};
    for (const [k, v] of Object.entries(draft.extras || {})) {
      if (v.trim()) extras[k] = v.trim();
    }
    const body: ProviderConfigUpsertRequest = {
      base_url: draft.baseUrl.trim() || null,
      chat_model: draft.chatModel.trim(),
      embedding_model: draft.embeddingModel.trim(),
      classify_model: draft.classifyModel.trim() || "",
      extras
    };
    if (draft.apiKey.trim() !== "") body.api_key = draft.apiKey;
    return body;
  }, [draft]);

  const save = useCallback(async () => {
    if (!selectedKind) return null;
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await apiFetch<ProviderConfig>(`/ai/providers/configs/${selectedKind}`, {
        method: "PUT",
        body: JSON.stringify(buildUpsert())
      });
      // Refresh the full list so is_active flags stay correct.
      await reload();
      // Drop the draft for this kind so the form rehydrates from the saved row.
      setDraftByKind((current) => {
        const next = { ...current };
        delete next[selectedKind];
        return next;
      });
      touchedRef.current.delete(selectedKind);
      setToast("Guardado");
      window.setTimeout(() => setToast(null), 2500);
      return saved;
    } catch (error) {
      const msg = error instanceof Error ? error.message : "No se pudo guardar";
      setSaveError(msg);
      return null;
    } finally {
      setSaving(false);
    }
  }, [selectedKind, buildUpsert, reload]);

  const test = useCallback(async () => {
    if (!selectedKind) return null;
    setTesting(true);
    setTestResult(null);
    try {
      // If the user has a dirty draft, test the in-form values against the
      // transient `/ai/providers/test` endpoint (so they can verify before
      // saving). Otherwise test the saved row by id (which also persists
      // last_test_*).
      const result = isDirty
        ? await apiFetch<TestConnectionResult>("/ai/providers/test", {
            method: "POST",
            body: JSON.stringify({
              provider_id: selectedKind,
              api_key:
                draft.apiKey.trim() !== ""
                  ? draft.apiKey
                  : selectedConfig?.has_api_key
                    ? STORED_API_KEY_SENTINEL
                    : null,
              base_url: draft.baseUrl.trim() || null,
              extras: Object.fromEntries(
                Object.entries(draft.extras || {}).filter(([, v]) => v.trim())
              )
            })
          })
        : await apiFetch<TestConnectionResult>(`/ai/providers/configs/${selectedKind}/test`, {
            method: "POST"
          });
      setTestResult(result);
      if (result.ok && !isDirty) {
        // Pull the refreshed last_test_* into the list.
        await reload();
      }
      return result;
    } catch (error) {
      const fallback: TestConnectionResult = {
        ok: false,
        message: error instanceof Error ? error.message : "Error inesperado",
        code: "unknown",
        detail: null
      };
      setTestResult(fallback);
      return fallback;
    } finally {
      setTesting(false);
    }
  }, [selectedKind, isDirty, draft, selectedConfig?.has_api_key, reload]);

  const setActive = useCallback(
    async (kind?: string) => {
      const target = kind ?? selectedKind;
      if (!target) return;
      try {
        await apiFetch<ProviderConfig>("/ai/providers/active", {
          method: "POST",
          body: JSON.stringify({ provider_kind: target })
        });
        await reload();
        setToast("Proveedor activo cambiado");
        window.setTimeout(() => setToast(null), 2500);
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : "No se pudo activar");
      }
    },
    [selectedKind, reload]
  );

  const remove = useCallback(
    async (kind: string) => {
      try {
        await apiFetch<unknown>(`/ai/providers/configs/${kind}`, { method: "DELETE" });
        await reload();
        // If we just deleted the row we were editing, reset the selection.
        if (selectedKind === kind) {
          setSelectedKind(null);
          setDraftByKind((current) => {
            const next = { ...current };
            delete next[kind];
            return next;
          });
        }
      } catch (error) {
        setSaveError(error instanceof Error ? error.message : "No se pudo eliminar");
      }
    },
    [selectedKind, reload]
  );

  const setAIDisabled = useCallback(
    async (disabled: boolean) => {
      await apiFetch<unknown>("/ai/settings", {
        method: "PATCH",
        body: JSON.stringify({ ai_disabled: disabled })
      });
      setAIDisabledState(disabled);
    },
    []
  );

  const refreshModels = useCallback(async () => {
    if (!selectedKind) return;
    setLoadingModels(true);
    try {
      const payload = isDirty
        ? {
            provider_id: selectedKind,
            api_key:
              draft.apiKey.trim() !== ""
                ? draft.apiKey
                : selectedConfig?.has_api_key
                  ? STORED_API_KEY_SENTINEL
                  : null,
            base_url: draft.baseUrl.trim() || null,
            extras: Object.fromEntries(
              Object.entries(draft.extras || {}).filter(([, v]) => v.trim())
            )
          }
        : {
            provider_id: selectedKind,
            api_key: selectedConfig?.has_api_key ? STORED_API_KEY_SENTINEL : null,
            base_url: selectedConfig?.base_url || null,
            extras: (selectedConfig?.extras as Record<string, unknown>) ?? {}
          };
      const response = await apiFetch<ListModelsResponse>("/ai/providers/models?capability=chat", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setModels(response.ok ? response.models : []);
    } catch {
      setModels([]);
    } finally {
      setLoadingModels(false);
    }
  }, [selectedKind, isDirty, draft, selectedConfig]);

  return {
    loading: loading || providersLoading,
    loadError,
    configs,
    activeKind,
    aiDisabled,
    selectedKind,
    selectedConfig,
    selectedProvider,
    draft,
    isDirty,
    isNew,
    models,
    loadingModels,
    testing,
    testResult,
    saving,
    saveError,
    toast,
    selectKind,
    startNew,
    updateDraft,
    discardDraft,
    save,
    test,
    setActive,
    remove,
    setAIDisabled,
    refreshModels,
    reload
  };
}
