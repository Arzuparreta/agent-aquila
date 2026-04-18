"use client";

import { useCallback, useState } from "react";

import { ApiError } from "@/lib/api";

type AsyncActionState = {
  pending: boolean;
  error: string | null;
};

export function useAsyncAction() {
  const [state, setState] = useState<AsyncActionState>({ pending: false, error: null });

  const reset = useCallback(() => {
    setState({ pending: false, error: null });
  }, []);

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setState({ pending: true, error: null });
    try {
      const result = await fn();
      setState({ pending: false, error: null });
      return result;
    } catch (e) {
      const message = e instanceof ApiError ? e.message : e instanceof Error ? e.message : "Something went wrong";
      setState({ pending: false, error: message });
      return undefined;
    }
  }, []);

  return { ...state, run, reset };
}
