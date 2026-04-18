"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode
} from "react";

import type { EntityRef } from "@/types/api";

/**
 * Holds the @reference chips that the artist has staged for the next message.
 *
 * The library drawer calls `add(ref)` when a row is tapped; the composer reads `refs`
 * to render the chips, calls `remove(idx)` when a chip is dismissed, and `clear()`
 * after a successful send. State is intentionally per-mount of `<ChatReferenceProvider>`
 * — the chat home wraps the whole shell with it.
 */

type Ctx = {
  refs: EntityRef[];
  add: (ref: EntityRef) => void;
  remove: (idx: number) => void;
  clear: () => void;
};

const ReferenceContext = createContext<Ctx | null>(null);

export function ChatReferenceProvider({ children }: { children: ReactNode }) {
  const [refs, setRefs] = useState<EntityRef[]>([]);
  const add = useCallback((ref: EntityRef) => {
    setRefs((prev) => {
      if (prev.some((r) => r.type === ref.type && r.id === ref.id)) return prev;
      return [...prev, ref];
    });
  }, []);
  const remove = useCallback((idx: number) => {
    setRefs((prev) => prev.filter((_, i) => i !== idx));
  }, []);
  const clear = useCallback(() => setRefs([]), []);
  const value = useMemo(() => ({ refs, add, remove, clear }), [refs, add, remove, clear]);
  return <ReferenceContext.Provider value={value}>{children}</ReferenceContext.Provider>;
}

export function useChatReferences(): Ctx {
  const ctx = useContext(ReferenceContext);
  if (!ctx) throw new Error("useChatReferences must be used inside <ChatReferenceProvider>");
  return ctx;
}
