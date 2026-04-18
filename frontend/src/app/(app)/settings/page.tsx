"use client";

import { FormEvent, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { useAsyncAction } from "@/lib/useAsyncAction";
import { isNonEmpty } from "@/lib/validation";
import { UserAISettings } from "@/types/api";

type Banner = { variant: "error" | "success" | "info"; message: string };

export default function SettingsPage() {
  const [settings, setSettings] = useState<UserAISettings | null>(null);
  const [providerKind, setProviderKind] = useState("openai_compatible");
  const [baseUrl, setBaseUrl] = useState("");
  const [embeddingModel, setEmbeddingModel] = useState("text-embedding-3-small");
  const [chatModel, setChatModel] = useState("gpt-4o-mini");
  const [classifyModel, setClassifyModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [aiDisabled, setAiDisabled] = useState(false);
  const [banner, setBanner] = useState<Banner | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ providerKind?: string; embeddingModel?: string; chatModel?: string }>({});

  const asyncAction = useAsyncAction();

  const load = async () => {
    try {
      const data = await apiFetch<UserAISettings>("/ai/settings");
      setSettings(data);
      setProviderKind(data.provider_kind);
      setBaseUrl(data.base_url || "");
      setEmbeddingModel(data.embedding_model);
      setChatModel(data.chat_model);
      setClassifyModel(data.classify_model || "");
      setAiDisabled(data.ai_disabled);
    } catch (e) {
      setBanner({
        variant: "error",
        message: e instanceof Error ? e.message : "Could not load settings"
      });
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const validate = () => {
    const errs: { providerKind?: string; embeddingModel?: string; chatModel?: string } = {};
    if (!isNonEmpty(providerKind)) errs.providerKind = "Provider kind is required";
    if (!isNonEmpty(embeddingModel)) errs.embeddingModel = "Embedding model is required";
    if (!isNonEmpty(chatModel)) errs.chatModel = "Chat model is required";
    return errs;
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBanner(null);
    const errs = validate();
    setFieldErrors(errs);
    if (Object.keys(errs).length) return;

    const payload: Record<string, unknown> = {
      provider_kind: providerKind.trim(),
      base_url: baseUrl.trim() || null,
      embedding_model: embeddingModel.trim(),
      chat_model: chatModel.trim(),
      classify_model: classifyModel.trim() || null,
      ai_disabled: aiDisabled
    };
    if (apiKey.trim()) {
      payload.api_key = apiKey.trim();
    }

    const result = await asyncAction.run(() => apiFetch<UserAISettings>("/ai/settings", { method: "PATCH", body: JSON.stringify(payload) }));
    if (result) {
      setApiKey("");
      setBanner({ variant: "success", message: "Saved" });
      await load();
    }
  };

  const clearKey = async () => {
    setBanner(null);
    setFieldErrors({});
    const result = await asyncAction.run(() =>
      apiFetch<UserAISettings>("/ai/settings", {
        method: "PATCH",
        body: JSON.stringify({ api_key: "" })
      })
    );
    if (result) {
      setBanner({ variant: "success", message: "API key cleared" });
      await load();
    }
  };

  return (
    <div className="mx-auto max-w-3xl">
      <h1 className="mb-4 text-2xl font-semibold">AI settings</h1>
      <p className="mb-4 text-sm text-slate-600">
        Configure OpenAI-compatible endpoints, OpenRouter, or Ollama (<code className="rounded bg-slate-100 px-1">http://host:11434/v1</code>
        ). Keys are encrypted at rest when <code className="rounded bg-slate-100 px-1">FERNET_ENCRYPTION_KEY</code> is set; otherwise a dev key is
        derived from <code className="rounded bg-slate-100 px-1">JWT_SECRET</code>.
      </p>
      {settings ? (
        <p className="mb-4 text-sm">
          API key on file: <strong>{settings.has_api_key ? "yes" : "no"}</strong>
        </p>
      ) : null}

      {banner ? (
        <div className="mb-4">
          <AlertBanner variant={banner.variant} message={banner.message} onDismiss={() => setBanner(null)} />
        </div>
      ) : null}
      {asyncAction.error ? (
        <div className="mb-4">
          <AlertBanner variant="error" message={asyncAction.error} onDismiss={asyncAction.reset} />
        </div>
      ) : null}

      <Card>
        <form className="grid gap-3" onSubmit={save}>
          <label className="text-sm font-medium">
            Provider kind
            <Input
              value={providerKind}
              onChange={(e) => setProviderKind(e.target.value)}
              placeholder="openai_compatible"
              aria-invalid={Boolean(fieldErrors.providerKind)}
            />
            {fieldErrors.providerKind ? <p className="mt-1 text-xs text-red-600">{fieldErrors.providerKind}</p> : null}
          </label>
          <label className="text-sm font-medium">
            Base URL (optional)
            <Input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              placeholder="https://api.openai.com/v1 or http://localhost:11434/v1"
            />
          </label>
          <label className="text-sm font-medium">
            Embedding model
            <Input value={embeddingModel} onChange={(e) => setEmbeddingModel(e.target.value)} aria-invalid={Boolean(fieldErrors.embeddingModel)} />
            {fieldErrors.embeddingModel ? <p className="mt-1 text-xs text-red-600">{fieldErrors.embeddingModel}</p> : null}
          </label>
          <label className="text-sm font-medium">
            Chat model
            <Input value={chatModel} onChange={(e) => setChatModel(e.target.value)} aria-invalid={Boolean(fieldErrors.chatModel)} />
            {fieldErrors.chatModel ? <p className="mt-1 text-xs text-red-600">{fieldErrors.chatModel}</p> : null}
          </label>
          <label className="text-sm font-medium">
            Classify model (optional)
            <Input
              value={classifyModel}
              onChange={(e) => setClassifyModel(e.target.value)}
              placeholder="defaults to chat model"
            />
          </label>
          <label className="text-sm font-medium">
            API key (leave blank to keep existing)
            <Input type="password" value={apiKey} onChange={(e) => setApiKey(e.target.value)} autoComplete="off" />
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={aiDisabled} onChange={(e) => setAiDisabled(e.target.checked)} />
            Disable AI (skips embeddings, triage LLM, search, drafts)
          </label>
          <div className="flex gap-2">
            <Button type="submit" disabled={asyncAction.pending}>
              Save
            </Button>
            <Button type="button" className="border-dashed" onClick={() => void clearKey()} disabled={asyncAction.pending}>
              Clear API key
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
