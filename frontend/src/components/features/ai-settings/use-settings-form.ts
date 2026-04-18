"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "@/lib/api";
import { isExtraField } from "@/lib/ai-providers";
import { useTranslation } from "@/lib/i18n";
import {
  AIProvider,
  ListModelsResponse,
  ModelInfo,
  ProviderConfigRequest,
  STORED_API_KEY_SENTINEL,
  TestConnectionResult,
  UserAISettings
} from "@/types/api";

type FormState = {
  providerId: string;
  apiKey: string;
  baseUrl: string;
  extras: Record<string, string>;
  chatModel: string;
  embeddingModel: string;
  classifyModel: string;
  aiDisabled: boolean;
};

type LoadState = "idle" | "loading" | "loaded" | "error";

const EMPTY_FORM: FormState = {
  providerId: "",
  apiKey: "",
  baseUrl: "",
  extras: {},
  chatModel: "",
  embeddingModel: "",
  classifyModel: "",
  aiDisabled: false
};

// Field changes that actually reach the provider invalidate a prior
// successful test (api key, base url, extras). Model selections and the
// "disable AI" toggle don't affect the connection itself, so they shouldn't
// erase the green "Connected" badge.
const CONNECTION_FIELDS: ReadonlySet<keyof FormState> = new Set<keyof FormState>([
  "apiKey",
  "baseUrl",
  "extras"
]);

function extrasFromApi(extras: Record<string, unknown> | null): Record<string, string> {
  if (!extras) return {};
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(extras)) {
    if (value == null) continue;
    out[key] = String(value);
  }
  return out;
}

function applyDefaults(provider: AIProvider, current: FormState): FormState {
  const defaults: Partial<FormState> = {
    baseUrl: current.baseUrl || provider.default_base_url || "",
    chatModel: current.chatModel || provider.default_chat_model || "",
    embeddingModel: current.embeddingModel || provider.default_embedding_model || "",
    classifyModel: current.classifyModel || provider.default_classify_model || ""
  };
  const extras = { ...current.extras };
  for (const field of provider.fields) {
    if (!isExtraField(field.key)) continue;
    if (!extras[field.key] && field.default) {
      extras[field.key] = field.default;
    }
  }
  return { ...current, ...defaults, extras };
}

type UseSettingsFormApi = {
  form: FormState;
  settings: UserAISettings | null;
  loadState: LoadState;
  loadError: string | null;
  provider: AIProvider | null;
  providersLoading: boolean;
  providers: AIProvider[];
  tested: TestConnectionResult | null;
  testing: boolean;
  models: ModelInfo[];
  loadingModels: boolean;
  setProviderId: (id: string) => void;
  setField: <K extends keyof FormState>(key: K, value: FormState[K]) => void;
  setFieldsValue: (patch: Partial<FormState>) => void;
  test: () => Promise<void>;
  refreshModels: () => Promise<void>;
  save: () => Promise<{ ok: boolean; message: string } | null>;
  clearKey: () => Promise<void>;
  reload: () => Promise<void>;
};

type UseSettingsFormOptions = {
  providers: AIProvider[];
  providersLoading: boolean;
};

export function useSettingsForm({ providers, providersLoading }: UseSettingsFormOptions): UseSettingsFormApi {
  const { t } = useTranslation();
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [settings, setSettings] = useState<UserAISettings | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("idle");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [tested, setTested] = useState<TestConnectionResult | null>(null);
  const [testing, setTesting] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loadingModels, setLoadingModels] = useState(false);

  const providersByIdRef = useRef(new Map<string, AIProvider>());
  useEffect(() => {
    providersByIdRef.current = new Map(providers.map((p) => [p.id, p]));
  }, [providers]);

  const provider = useMemo(
    () => providersByIdRef.current.get(form.providerId) ?? providers.find((p) => p.id === form.providerId) ?? null,
    [form.providerId, providers]
  );

  const reload = useCallback(async () => {
    setLoadState("loading");
    setLoadError(null);
    try {
      const data = await apiFetch<UserAISettings>("/ai/settings");
      setSettings(data);
      setForm((current) => {
        const next: FormState = {
          providerId: data.provider_kind || current.providerId,
          apiKey: "",
          baseUrl: data.base_url || "",
          extras: extrasFromApi(data.extras),
          chatModel: data.chat_model || "",
          embeddingModel: data.embedding_model || "",
          classifyModel: data.classify_model || "",
          aiDisabled: data.ai_disabled
        };
        return next;
      });
      setLoadState("loaded");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : t("settings.couldNotLoad"));
      setLoadState("error");
    }
  }, [t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  // Seed defaults when a provider is picked and the form still has empty
  // fields. Runs after both providers and settings are ready.
  useEffect(() => {
    if (!provider) return;
    setForm((current) => applyDefaults(provider, current));
  }, [provider]);

  const setProviderId = useCallback((id: string) => {
    setForm((current) => {
      if (current.providerId === id) return current;
      // Reset fields that are provider-specific but keep the api key entry
      // the user may have just typed.
      return {
        ...current,
        providerId: id,
        baseUrl: "",
        chatModel: "",
        embeddingModel: "",
        classifyModel: "",
        extras: {}
      };
    });
    setTested(null);
    setModels([]);
  }, []);

  const setField = useCallback(<K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
    if (CONNECTION_FIELDS.has(key)) {
      setTested((current) => (current?.ok ? null : current));
    }
  }, []);

  const setFieldsValue = useCallback((patch: Partial<FormState>) => {
    setForm((current) => ({ ...current, ...patch }));
    const touchesConnection = (Object.keys(patch) as (keyof FormState)[]).some((k) => CONNECTION_FIELDS.has(k));
    if (touchesConnection) {
      setTested((current) => (current?.ok ? null : current));
    }
  }, []);

  const buildRequestConfig = useCallback((): ProviderConfigRequest | null => {
    if (!provider) return null;
    const apiKey = form.apiKey.trim();
    // If the user didn't type a new key and we have one on file, reuse it
    // server-side via the stored-sentinel.
    const resolvedKey = apiKey || (settings?.has_api_key ? STORED_API_KEY_SENTINEL : null);
    const extrasPayload: Record<string, string> = {};
    for (const [key, value] of Object.entries(form.extras)) {
      if (value.trim()) extrasPayload[key] = value.trim();
    }
    return {
      provider_id: provider.id,
      api_key: resolvedKey,
      base_url: form.baseUrl.trim() || null,
      extras: extrasPayload
    };
  }, [form, provider, settings?.has_api_key]);

  const refreshModels = useCallback(async () => {
    const payload = buildRequestConfig();
    if (!payload) return;
    setLoadingModels(true);
    try {
      const response = await apiFetch<ListModelsResponse>("/ai/providers/models?capability=chat", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      if (response.ok) {
        setModels(response.models);
      } else {
        setModels([]);
      }
    } catch (error) {
      setModels([]);
      // Fall through - the test-connection flow is the primary error surface.
      // Keep models empty so the UI falls back to free-text entry.
      void error;
    } finally {
      setLoadingModels(false);
    }
  }, [buildRequestConfig]);

  const test = useCallback(async () => {
    const payload = buildRequestConfig();
    if (!payload) return;
    setTesting(true);
    setTested(null);
    try {
      const result = await apiFetch<TestConnectionResult>("/ai/providers/test", {
        method: "POST",
        body: JSON.stringify(payload)
      });
      setTested(result);
      if (result.ok) {
        await refreshModels();
      } else {
        setModels([]);
      }
    } catch (error) {
      setTested({
        ok: false,
        message: error instanceof Error ? error.message : t("settings.test.unexpected"),
        code: "unknown"
      });
      setModels([]);
    } finally {
      setTesting(false);
    }
  }, [buildRequestConfig, refreshModels, t]);

  const save = useCallback(async () => {
    if (!provider) return null;
    const extrasPayload: Record<string, string> = {};
    for (const [key, value] of Object.entries(form.extras)) {
      if (value.trim()) extrasPayload[key] = value.trim();
    }
    const body: Record<string, unknown> = {
      provider_kind: provider.id,
      base_url: form.baseUrl.trim() || null,
      chat_model: form.chatModel.trim(),
      embedding_model: form.embeddingModel.trim(),
      classify_model: form.classifyModel.trim() || null,
      ai_disabled: form.aiDisabled,
      extras: extrasPayload
    };
    const apiKey = form.apiKey.trim();
    if (apiKey) body.api_key = apiKey;
    try {
      const data = await apiFetch<UserAISettings>("/ai/settings", { method: "PATCH", body: JSON.stringify(body) });
      setSettings(data);
      setForm((current) => ({ ...current, apiKey: "" }));
      return { ok: true, message: t("settings.savedToast") };
    } catch (error) {
      return { ok: false, message: error instanceof Error ? error.message : t("settings.couldNotSave") };
    }
  }, [form, provider, t]);

  const clearKey = useCallback(async () => {
    try {
      const data = await apiFetch<UserAISettings>("/ai/settings", {
        method: "PATCH",
        body: JSON.stringify({ api_key: "" })
      });
      setSettings(data);
      setForm((current) => ({ ...current, apiKey: "" }));
      setTested(null);
      setModels([]);
    } catch {
      // Surfacing the error is the caller's concern.
    }
  }, []);

  return {
    form,
    settings,
    loadState,
    loadError,
    provider,
    providersLoading,
    providers,
    tested,
    testing,
    models,
    loadingModels,
    setProviderId,
    setField,
    setFieldsValue,
    test,
    refreshModels,
    save,
    clearKey,
    reload
  };
}
