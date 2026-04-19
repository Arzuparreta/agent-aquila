"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type {
  ChatMessage,
  ChatSendResult,
  ChatThread,
  EntityRef
} from "@/types/api";

import { ChatComposer } from "./composer";
import { MessageBubble } from "./message-bubble";
import { useChatReferences } from "./reference-context";

/**
 * Loads + renders a single chat thread:
 *   - Initial fetch of the last 200 messages (oldest at top, newest at bottom).
 *   - Composer at the bottom; on submit we show the user message optimistically,
 *     POST, then swap in the persisted user row plus the assistant reply.
 *   - "Pensando…" indicator while the agent reply is in flight.
 *   - Auto-scrolls to bottom whenever the message list grows.
 *
 * Cards (approval / undo / connector setup / oauth) are rendered inline via
 * `MessageBubble` → `<...Card />` components and have their own action handlers
 * that mutate state in place (e.g. flip an approval card to "approved").
 */
export function ChatThreadView({
  thread,
  onThreadUpdated
}: {
  thread: ChatThread;
  onThreadUpdated: (thread: ChatThread) => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const optimisticIdRef = useRef(0);
  const refs = useChatReferences();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await apiFetch<ChatMessage[]>(`/threads/${thread.id}/messages`);
      setMessages(rows);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "No se pudo cargar la conversación.");
    } finally {
      setLoading(false);
    }
  }, [thread.id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, sending]);

  const retryFailedMessage = useCallback(
    async (failedMessageId: number) => {
      setSending(true);
      setError(null);
      try {
        const result = await apiFetch<ChatSendResult>(
          `/threads/${thread.id}/messages/${failedMessageId}/retry`,
          { method: "POST" }
        );
        setMessages((prev) => {
          const without = prev.filter((m) => m.id !== failedMessageId);
          return [...without, result.assistant_message];
        });
        onThreadUpdated(result.thread);
        if (result.error) setError(result.error);
        else setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "El reintento falló.");
      } finally {
        setSending(false);
      }
    },
    [thread.id, onThreadUpdated]
  );

  const onSend = useCallback(
    async (content: string, references: EntityRef[]) => {
      const optimisticId = (optimisticIdRef.current -= 1);
      const optimistic: ChatMessage = {
        id: optimisticId,
        thread_id: thread.id,
        role: "user",
        content,
        attachments: null,
        agent_run_id: null,
        created_at: new Date().toISOString()
      };
      setMessages((prev) => [...prev, optimistic]);
      setSending(true);
      try {
        const result = await apiFetch<ChatSendResult>(`/threads/${thread.id}/messages`, {
          method: "POST",
          body: JSON.stringify({ content, references })
        });
        setMessages((prev) => {
          const without = prev.filter((m) => m.id !== optimisticId);
          return [...without, result.user_message, result.assistant_message];
        });
        onThreadUpdated(result.thread);
        if (result.error) setError(result.error);
        else setError(null);
        refs.clear();
      } catch (err) {
        setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
        setError(err instanceof ApiError ? err.message : "El envío falló.");
        throw err;
      } finally {
        setSending(false);
      }
    },
    [thread.id, onThreadUpdated, refs]
  );

  const updateMessage = useCallback((updated: ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollerRef} className="scroll-stealth min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {loading ? <div className="text-center text-base text-fg-subtle">Cargando…</div> : null}
        {error ? (
          <div className="mx-auto mb-3 max-w-md rounded-md bg-rose-900/40 px-3 py-2 text-base text-rose-100">
            {error}
          </div>
        ) : null}
        {!loading && messages.length === 0 ? (
          <div className="mx-auto mt-12 max-w-sm text-center text-base text-fg-subtle">
            Hola. Cuéntame qué necesitas y me encargo. También puedo avisarte cuando llegue
            algo importante (correos, eventos, propuestas).
          </div>
        ) : null}
        <div className="mx-auto flex max-w-3xl flex-col gap-3">
          {messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              onMessageUpdate={updateMessage}
              onRetryFailedMessage={retryFailedMessage}
              retryDisabled={sending}
            />
          ))}
          {sending ? (
            <div className="self-start rounded-2xl bg-surface-muted px-4 py-2 text-base text-fg-muted">
              Pensando…
            </div>
          ) : null}
        </div>
      </div>
      <ChatComposer onSend={onSend} disabled={sending} />
    </div>
  );
}
