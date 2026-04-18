"use client";

import { useEffect, useState } from "react";

import { apiFetch } from "@/lib/api";
import { AIProvider } from "@/types/api";

/**
 * Runtime-loaded mirror of the backend provider registry (`GET /ai/providers`).
 * Shared across all hook callers within a session so the settings page
 * doesn't re-fetch it when navigating between tabs.
 */

let cachedPromise: Promise<AIProvider[]> | null = null;
let cachedValue: AIProvider[] | null = null;

async function loadProviders(): Promise<AIProvider[]> {
  if (cachedValue) return cachedValue;
  if (!cachedPromise) {
    cachedPromise = apiFetch<AIProvider[]>("/ai/providers").then((data) => {
      cachedValue = data;
      return data;
    });
  }
  try {
    return await cachedPromise;
  } catch (error) {
    cachedPromise = null;
    throw error;
  }
}

type RegistryState = {
  providers: AIProvider[];
  loading: boolean;
  error: string | null;
};

export function useProviderRegistry(): RegistryState {
  const [state, setState] = useState<RegistryState>({
    providers: cachedValue ?? [],
    loading: cachedValue === null,
    error: null
  });

  useEffect(() => {
    let cancelled = false;
    if (cachedValue) {
      setState({ providers: cachedValue, loading: false, error: null });
      return;
    }
    setState((prev) => ({ ...prev, loading: true, error: null }));
    loadProviders()
      .then((providers) => {
        if (!cancelled) setState({ providers, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const message = error instanceof Error ? error.message : "Failed to load providers";
        setState({ providers: [], loading: false, error: message });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return state;
}

export function findProvider(providers: AIProvider[], id: string | null | undefined): AIProvider | null {
  if (!id) return null;
  return providers.find((p) => p.id === id) ?? null;
}

/**
 * Provider keys consumed by the user go into either top-level config
 * (`api_key`, `base_url`) or the free-form `extras` JSON bag. This helper
 * keeps the split consistent across the UI.
 */
export function isExtraField(key: string): boolean {
  return key !== "api_key" && key !== "base_url";
}
