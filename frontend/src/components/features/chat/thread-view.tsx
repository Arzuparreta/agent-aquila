"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { pollThreadUntilTitleReady } from "@/lib/chat-thread-title";
import { waitForRunTerminal } from "@/lib/realtime";
import {
  recordTelemetryAgentRunFailed,
  recordTelemetryAssistantWsError,
  recordTelemetryAssistantWsTimeout
} from "@/lib/telemetry/record";
import { useTranslation } from "@/lib/i18n";
import type { ChatMessage, ChatSendResult, ChatThread, EntityRef } from "@/types/api";

import { ChatComposer } from "./composer";
import { MessageBubble } from "./message-bubble";
import { useChatReferences } from "./reference-context";

/** Matches backend ``_AGENT_REPLY_PLACEHOLDER`` (single Unicode ellipsis). */
const AGENT_REPLY_PLACEHOLDER = "\u2026";

type PendingRunSnapshot = {
  id: number;
  status: string;
  error: string | null;
  attention?: {
    stage: string;
    last_event_at: string | null;
    hint: string | null;
  } | null;
};

function findPendingAgentRunId(rows: ChatMessage[]): number | null {
  for (let i = rows.length - 1; i >= 0; i--) {
    const m = rows[i];
    if (m.role !== "assistant" || m.agent_run_id == null) {
      continue;
    }
    if (m.content === AGENT_REPLY_PLACEHOLDER) {
      return m.agent_run_id;
    }
  }
  return null;
}

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
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingRunSnapshot, setPendingRunSnapshot] = useState<PendingRunSnapshot | null>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const optimisticIdRef = useRef(0);
  const refs = useChatReferences();
  const createIdempotencyKey = useCallback(
    () =>
      typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `msg-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`,
    []
  );

  const reload = useCallback(
    async (opts?: { silent?: boolean }): Promise<ChatMessage[] | null> => {
      if (!opts?.silent) {
        setLoading(true);
      }
      try {
        const rows = await apiFetch<ChatMessage[]>(`/threads/${thread.id}/messages`);
        setMessages(rows);
        if (!opts?.silent) {
          setError(null);
        }
        return rows;
      } catch (err) {
        setError(err instanceof ApiError ? err.message : t("chat.threadView.loadFailed"));
        return null;
      } finally {
        if (!opts?.silent) {
          setLoading(false);
        }
      }
    },
    [thread.id, t]
  );

  useEffect(() => {
    void reload();
  }, [reload]);

  const pendingRunId = useMemo(() => findPendingAgentRunId(messages), [messages]);
  const composerBusy = sending;
  const showEphemeralThinking = sending && pendingRunId == null;

  const stopActiveRun = useCallback(async () => {
    const rid = pendingRunId;
    if (rid == null) return;
    try {
      await apiFetch(`/agent/runs/${rid}/stop`, { method: "POST" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("chat.threadView.stopFailed"));
    }
  }, [pendingRunId, t]);

  const pendingLabel = useMemo(() => {
    if (sending && pendingRunSnapshot == null) {
      return t("chat.threadView.state.queued");
    }
    const snapshot = pendingRunSnapshot;
    if (!snapshot) return t("chat.threadView.thinking");
    if (snapshot.status === "pending") return t("chat.threadView.state.queued");
    if (snapshot.status === "running") {
      const stage = snapshot.attention?.stage;
      if (stage === "waiting_tool") return t("chat.threadView.state.waitingTool");
      if (stage === "waiting_llm") return t("chat.threadView.state.waitingLlm");
      return t("chat.threadView.state.running");
    }
    if (snapshot.status === "needs_attention") return t("chat.threadView.state.needsAttention");
    return t("chat.threadView.thinking");
  }, [pendingRunSnapshot, sending, t]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length, sending, pendingRunId]);

  const runAgentRunFollowUp = useCallback(
    async (runId: number) => {
      setError(null);
      try {
        const run = await waitForRunTerminal(runId, {
          onProgress: (snapshot) => setPendingRunSnapshot(snapshot)
        });
        setPendingRunSnapshot(run);
        if (run.status === "needs_attention") {
          setError(run.attention?.hint || run.error || t("chat.threadView.needsAttention"));
        }
        if (run.status === "failed") {
          recordTelemetryAgentRunFailed({ runId: run.id, error: run.error });
        }
        const refreshed = await reload({ silent: true });
        if (refreshed != null) {
          setError(null);
          try {
            const updatedThread = await pollThreadUntilTitleReady(thread.id, (id) =>
              apiFetch<ChatThread>(`/threads/${id}`)
            );
            if (updatedThread != null) {
              onThreadUpdated(updatedThread);
            }
          } catch {
            // Sidebar may lag; messages are already current.
          }
        }
      } catch (err) {
        setPendingRunSnapshot(null);
        const rows = await reload({ silent: true });
        if (err instanceof ApiError) {
          if (err.status === 408) {
            recordTelemetryAssistantWsTimeout();
          } else {
            recordTelemetryAssistantWsError({ runId, status: err.status, message: err.message });
          }
        }
        if (rows == null) {
          return;
        }
        const stillPending = findPendingAgentRunId(rows) != null;
        if (stillPending) {
          setError(err instanceof ApiError ? err.message : t("chat.threadView.sendFailed"));
        } else {
          setError(null);
          try {
            const updatedThread = await pollThreadUntilTitleReady(thread.id, (id) =>
              apiFetch<ChatThread>(`/threads/${id}`)
            );
            if (updatedThread != null) {
              onThreadUpdated(updatedThread);
            }
          } catch {
            // ignore
          }
        }
      }
      setPendingRunSnapshot(null);
    },
    [onThreadUpdated, reload, t, thread.id]
  );

  const reconcileUncertainSend = useCallback(
    async (
      content: string,
      idempotencyKey: string
    ): Promise<{ ok: boolean; pendingRunId: number | null }> => {
      const rows = await apiFetch<ChatMessage[]>(`/threads/${thread.id}/messages`);
      const matched = rows.some((m) => m.role === "user" && m.client_token === idempotencyKey);
      if (!matched) {
        const recentUser = [...rows].reverse().find((m) => m.role === "user");
        if (!recentUser || recentUser.content !== content) {
          return { ok: false, pendingRunId: null };
        }
      }
      const pendingRunId = findPendingAgentRunId(rows);
      setMessages(rows);
      return { ok: true, pendingRunId };
    },
    [thread.id]
  );

  const retryFailedMessage = useCallback(
    async (failedMessageId: number) => {
      setSending(true);
      setError(null);
      try {
        const retryKey = createIdempotencyKey();
        const result = await apiFetch<ChatSendResult>(
          `/threads/${thread.id}/messages/${failedMessageId}/retry`,
          { method: "POST", headers: { "X-Idempotency-Key": retryKey } }
        );
        setMessages((prev) => {
          const without = prev.filter((m) => m.id !== failedMessageId);
          return [...without, result.assistant_message];
        });
        onThreadUpdated(result.thread);
        if (result.agent_run_pending && result.assistant_message.agent_run_id != null) {
          setPendingRunSnapshot({
            id: result.assistant_message.agent_run_id,
            status: "pending",
            error: null,
            attention: null
          });
          setSending(false);
          await runAgentRunFollowUp(result.assistant_message.agent_run_id);
          return;
        }
        if (result.error) setError(result.error);
        else setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : t("chat.threadView.retryFailed"));
      } finally {
        setSending(false);
      }
    },
    [createIdempotencyKey, thread.id, onThreadUpdated, runAgentRunFollowUp, t]
  );

  const onSend = useCallback(
    async (content: string, references: EntityRef[]) => {
      const idempotencyKey = createIdempotencyKey();
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
          body: JSON.stringify({ content, references, idempotency_key: idempotencyKey })
        });
        setMessages((prev) => {
          const without = prev.filter((m) => m.id !== optimisticId);
          return [...without, result.user_message, result.assistant_message];
        });
        onThreadUpdated(result.thread);
        if (result.agent_run_pending && result.assistant_message.agent_run_id != null) {
          setPendingRunSnapshot({
            id: result.assistant_message.agent_run_id,
            status: "pending",
            error: null,
            attention: null
          });
          setSending(false);
          refs.clear();
          await runAgentRunFollowUp(result.assistant_message.agent_run_id);
          return;
        }
        if (result.error) setError(result.error);
        else setError(null);
        refs.clear();
      } catch (err) {
        try {
          const { ok, pendingRunId } = await reconcileUncertainSend(content, idempotencyKey);
          if (ok) {
            setSending(false);
            refs.clear();
            if (pendingRunId != null) {
              await runAgentRunFollowUp(pendingRunId);
            } else {
              setError(null);
            }
            return;
          }
        } catch {
          // Keep original send error flow below if reconciliation also fails.
        }
        setMessages((prev) => prev.filter((m) => m.id !== optimisticId));
        setError(err instanceof ApiError ? err.message : t("chat.threadView.sendFailed"));
        throw err;
      } finally {
        setSending(false);
      }
    },
    [
      createIdempotencyKey,
      thread.id,
      onThreadUpdated,
      reconcileUncertainSend,
      refs,
      runAgentRunFollowUp,
      t
    ]
  );

  const updateMessage = useCallback((updated: ChatMessage) => {
    setMessages((prev) => prev.map((m) => (m.id === updated.id ? updated : m)));
  }, []);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div ref={scrollerRef} className="scroll-stealth min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {loading ? <div className="text-center text-base text-fg-subtle">{t("common.loading")}</div> : null}
        {error ? (
          <div className="mx-auto mb-3 max-w-md rounded-md bg-rose-900/40 px-3 py-2 text-base text-rose-100">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
              <span className="min-w-0 flex-1">{error}</span>
              <button
                type="button"
                className="shrink-0 rounded-md bg-rose-100/20 px-3 py-1 text-sm font-semibold text-rose-50 hover:bg-rose-100/30"
                onClick={() => {
                  void (async () => {
                    const rows = await reload({ silent: true });
                    if (rows != null && findPendingAgentRunId(rows) == null) {
                      setError(null);
                    }
                  })();
                }}
              >
                {t("common.retry")}
              </button>
            </div>
          </div>
        ) : null}
        {pendingRunId != null && pendingRunSnapshot?.status === "needs_attention" ? (
          <div className="mx-auto mb-3 max-w-md rounded-md border border-amber-700/50 bg-amber-950/30 px-3 py-2 text-sm text-amber-100">
            <div className="flex items-center justify-between gap-3">
              <span>{pendingRunSnapshot.attention?.hint || t("chat.threadView.needsAttention")}</span>
              <button
                type="button"
                className="rounded-md bg-amber-200/20 px-3 py-1 text-xs font-semibold hover:bg-amber-200/30"
                onClick={() => void reload({ silent: true })}
              >
                {t("chat.threadView.refreshState")}
              </button>
            </div>
          </div>
        ) : null}
        {!loading && messages.length === 0 ? (
          <div className="mx-auto mt-12 max-w-sm text-center text-base text-fg-subtle">
            {t("chat.threadView.emptyHint")}
          </div>
        ) : null}
        <div className="mx-auto flex max-w-3xl flex-col gap-3">
          {messages.map((m) => (
            <MessageBubble
              key={m.id}
              message={m}
              onMessageUpdate={updateMessage}
              onRetryFailedMessage={retryFailedMessage}
              retryDisabled={composerBusy}
              pendingLabel={
                m.role === "assistant" &&
                m.content === AGENT_REPLY_PLACEHOLDER &&
                m.agent_run_id != null &&
                m.agent_run_id === pendingRunId
                  ? pendingLabel
                  : null
              }
            />
          ))}
          {showEphemeralThinking ? (
            <div className="self-start rounded-2xl bg-surface-muted px-4 py-2 text-base text-fg-muted">
              {pendingLabel}
            </div>
          ) : null}
        </div>
      </div>
      <ChatComposer
        onSend={onSend}
        onStop={() => {
          void stopActiveRun();
        }}
        showStop={pendingRunId != null}
        disabled={composerBusy}
        busyLabel={sending ? pendingLabel : t("chat.composer.placeholderBusy")}
      />
    </div>
  );
}
