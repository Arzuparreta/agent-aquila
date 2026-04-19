"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type {
  ChatThread,
  GmailMessageRow,
  GmailMessagesPage,
} from "@/types/api";

import { InboxDetail } from "./inbox-detail";
import { InboxList } from "./inbox-list";
import { InboxTopBar } from "./inbox-top-bar";
import { SilenceModal, type SilenceMode } from "./silence-modal";

type StatusMessage =
  | { kind: "ok"; text: string }
  | { kind: "error"; text: string };

type SilenceTarget = {
  messageId: string;
  threadId: string;
  senderEmail: string;
  senderName?: string | null;
};

const PAGE_SIZE = 25;

/**
 * Inbox surface, post-OpenClaw refactor. There is no local mirror anymore —
 * this page is a thin lens over the live ``/gmail/messages`` proxy:
 *
 * - One unified list (no triage chips, no classification).
 * - Free-form Gmail search (``q=`` passes straight through to Gmail).
 * - ``page_token``-based pagination via Gmail's own cursor.
 * - Per-row actions auto-execute against Gmail (mark read/unread, archive,
 *   trash, reply via chat, "Silenciar" opens a tiny modal that mutes or
 *   spams the sender directly in Gmail using a server-side filter).
 *
 * Reads ``?msg=<gmail-id>`` from the URL on mount so deep links land on the
 * right detail.
 */
export function InboxPage() {
  const router = useRouter();
  const params = useSearchParams();
  const initialMessageId = useMemo(() => params.get("msg"), [params]);

  const [search, setSearch] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState<string>("");
  const [messages, setMessages] = useState<GmailMessageRow[]>([]);
  const [pageToken, setPageToken] = useState<string | null>(null);
  const [nextPageToken, setNextPageToken] = useState<string | null>(null);
  const [pageStack, setPageStack] = useState<(string | null)[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(initialMessageId);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [silenceTarget, setSilenceTarget] = useState<SilenceTarget | null>(null);

  const loadPage = useCallback(
    async (opts?: { q?: string; pageToken?: string | null }) => {
      const q = opts?.q ?? submittedQuery;
      const token = opts?.pageToken ?? null;
      setLoading(true);
      try {
        const qs = new URLSearchParams();
        qs.set("detail", "metadata");
        qs.set("max_results", String(PAGE_SIZE));
        if (q.trim()) qs.set("q", q.trim());
        if (token) qs.set("page_token", token);
        const data = await apiFetch<GmailMessagesPage>(
          `/gmail/messages?${qs.toString()}`,
        );
        setMessages(data.messages);
        setNextPageToken(data.next_page_token);
        setError(null);
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          setError(
            "Gmail necesita reconectarse. Ve a Ajustes → Conectores y vuelve a autorizar.",
          );
        } else {
          setError(
            err instanceof ApiError
              ? err.message
              : "No se pudieron cargar los correos.",
          );
        }
        setMessages([]);
        setNextPageToken(null);
      } finally {
        setLoading(false);
      }
    },
    [submittedQuery],
  );

  // Initial load + reload on submitted-query change.
  useEffect(() => {
    setPageToken(null);
    setPageStack([]);
    void loadPage({ pageToken: null });
  }, [loadPage]);

  useEffect(() => {
    if (!status) return;
    const id = window.setTimeout(() => setStatus(null), 4000);
    return () => window.clearTimeout(id);
  }, [status]);

  const onSubmitSearch = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      setSubmittedQuery(search);
    },
    [search],
  );

  const onPick = useCallback(
    (msg: GmailMessageRow) => {
      setActiveId(msg.id);
      router.replace(`/inbox?msg=${msg.id}`);
      // Optimistically clear the unread label locally; Gmail itself will
      // update once the detail pane fetches the message in `format=full`.
      if (msg.is_unread) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msg.id
              ? {
                  ...m,
                  is_unread: false,
                  label_ids: m.label_ids.filter((l) => l !== "UNREAD"),
                }
              : m,
          ),
        );
        void apiFetch(`/gmail/messages/${msg.id}/modify`, {
          method: "POST",
          body: JSON.stringify({ remove_label_ids: ["UNREAD"] }),
        }).catch(() => {
          // Best effort. The next refresh will reconcile.
        });
      }
    },
    [router],
  );

  const onCloseDetail = useCallback(() => {
    setActiveId(null);
    router.replace("/inbox");
  }, [router]);

  const patchRow = useCallback(
    (id: string, patch: Partial<GmailMessageRow>) =>
      setMessages((prev) =>
        prev.map((m) => (m.id === id ? { ...m, ...patch } : m)),
      ),
    [],
  );

  const onMarkRead = useCallback(
    async (msg: GmailMessageRow, next: boolean) => {
      const labels = msg.label_ids.filter((l) => l !== "UNREAD");
      patchRow(msg.id, {
        is_unread: !next,
        label_ids: next ? labels : [...labels, "UNREAD"],
      });
      try {
        await apiFetch(`/gmail/messages/${msg.id}/modify`, {
          method: "POST",
          body: JSON.stringify(
            next
              ? { remove_label_ids: ["UNREAD"] }
              : { add_label_ids: ["UNREAD"] },
          ),
        });
        setStatus({
          kind: "ok",
          text: next ? "Marcado como leído." : "Marcado como no leído.",
        });
      } catch (err) {
        // Revert on failure.
        patchRow(msg.id, {
          is_unread: msg.is_unread,
          label_ids: msg.label_ids,
        });
        setStatus({
          kind: "error",
          text: err instanceof ApiError ? err.message : "No se pudo actualizar.",
        });
      }
    },
    [patchRow],
  );

  const onArchive = useCallback(
    async (msg: GmailMessageRow) => {
      const remaining = messages.filter((m) => m.id !== msg.id);
      setMessages(remaining);
      if (activeId === msg.id) onCloseDetail();
      try {
        await apiFetch(`/gmail/messages/${msg.id}/modify`, {
          method: "POST",
          body: JSON.stringify({ remove_label_ids: ["INBOX"] }),
        });
        setStatus({ kind: "ok", text: "Archivado." });
      } catch (err) {
        setMessages((prev) => [msg, ...prev]);
        setStatus({
          kind: "error",
          text: err instanceof ApiError ? err.message : "No se pudo archivar.",
        });
      }
    },
    [activeId, messages, onCloseDetail],
  );

  const onTrash = useCallback(
    async (msg: GmailMessageRow) => {
      const remaining = messages.filter((m) => m.id !== msg.id);
      setMessages(remaining);
      if (activeId === msg.id) onCloseDetail();
      try {
        await apiFetch(`/gmail/messages/${msg.id}/trash`, { method: "POST" });
        setStatus({ kind: "ok", text: "Movido a la papelera." });
      } catch (err) {
        setMessages((prev) => [msg, ...prev]);
        setStatus({
          kind: "error",
          text:
            err instanceof ApiError
              ? err.message
              : "No se pudo mover a la papelera.",
        });
      }
    },
    [activeId, messages, onCloseDetail],
  );

  const onAskSilence = useCallback((msg: GmailMessageRow) => {
    setSilenceTarget({
      messageId: msg.id,
      threadId: msg.thread_id,
      senderEmail: msg.sender_email,
      senderName: msg.sender_name,
    });
  }, []);

  const onConfirmSilence = useCallback(
    async (target: SilenceTarget, mode: SilenceMode) => {
      try {
        // A server-side Gmail filter is the only way to make the action
        // sticky for *future* messages from this sender. We always create
        // it; the action set varies by mode (skip-inbox+mark-read for mute,
        // hard SPAM label for spam).
        const action =
          mode === "spam"
            ? { addLabelIds: ["SPAM"], removeLabelIds: ["INBOX"] }
            : { removeLabelIds: ["INBOX", "UNREAD"] };
        await apiFetch(`/gmail/filters`, {
          method: "POST",
          body: JSON.stringify({
            criteria: { from: target.senderEmail },
            action,
          }),
        });

        // For the current message in front of the user, also apply the
        // change immediately so the row visibly disappears from the inbox.
        if (mode === "spam") {
          await apiFetch(`/gmail/threads/${target.threadId}/modify`, {
            method: "POST",
            body: JSON.stringify({
              add_label_ids: ["SPAM"],
              remove_label_ids: ["INBOX"],
            }),
          });
        } else {
          await apiFetch(`/gmail/threads/${target.threadId}/modify`, {
            method: "POST",
            body: JSON.stringify({
              remove_label_ids: ["INBOX", "UNREAD"],
            }),
          });
        }
        setMessages((prev) => prev.filter((m) => m.id !== target.messageId));
        if (activeId === target.messageId) onCloseDetail();
        setStatus({
          kind: "ok",
          text:
            mode === "spam"
              ? `Marcado como spam: ${target.senderEmail}`
              : `Silenciado: ${target.senderEmail}`,
        });
      } catch (err) {
        setStatus({
          kind: "error",
          text:
            err instanceof ApiError
              ? err.message
              : "No se pudo crear el filtro de Gmail.",
        });
      } finally {
        setSilenceTarget(null);
      }
    },
    [activeId, onCloseDetail],
  );

  const onStartChat = useCallback(
    async (msg: GmailMessageRow) => {
      try {
        const thread = await apiFetch<ChatThread>(`/threads`, {
          method: "POST",
          body: JSON.stringify({
            title: msg.subject || msg.sender_email,
          }),
        });
        // The agent will use its Gmail tools to fetch the message body. We
        // pass the id in the URL so the chat surface can pre-stage a
        // reference chip for the next user message.
        router.push(`/?thread=${thread.id}&gmail_msg=${msg.id}`);
      } catch (err) {
        setStatus({
          kind: "error",
          text:
            err instanceof ApiError
              ? err.message
              : "No se pudo iniciar el chat.",
        });
      }
    },
    [router],
  );

  const goNextPage = useCallback(() => {
    if (!nextPageToken) return;
    setPageStack((prev) => [...prev, pageToken]);
    setPageToken(nextPageToken);
    void loadPage({ pageToken: nextPageToken });
  }, [loadPage, nextPageToken, pageToken]);

  const goPrevPage = useCallback(() => {
    setPageStack((prev) => {
      if (prev.length === 0) return prev;
      const stack = [...prev];
      const target = stack.pop() ?? null;
      setPageToken(target);
      void loadPage({ pageToken: target });
      return stack;
    });
  }, [loadPage]);

  return (
    <div className="app-shell bg-surface-base text-fg">
      <InboxTopBar />
      {status ? (
        <div
          className={`flex items-center justify-center gap-3 px-4 py-2 text-center text-xs ${
            status.kind === "ok"
              ? "bg-emerald-900/60 text-emerald-100"
              : "bg-rose-900/60 text-rose-100"
          }`}
        >
          <span>{status.text}</span>
          <button
            type="button"
            onClick={() => setStatus(null)}
            className="rounded p-0.5 text-fg-muted hover:bg-interactive-hover-strong hover:text-fg"
            aria-label="Cerrar mensaje"
          >
            <svg
              viewBox="0 0 24 24"
              className="h-3 w-3"
              fill="none"
              stroke="currentColor"
              strokeWidth={2.5}
            >
              <path d="M6 6l12 12M6 18 18 6" />
            </svg>
          </button>
        </div>
      ) : null}
      <div className="flex min-h-0 flex-1">
        <section
          className={`flex min-w-0 flex-1 flex-col border-r border-border-subtle md:max-w-md ${
            activeId ? "hidden md:flex" : "flex"
          }`}
        >
          <SearchBar
            value={search}
            onChange={setSearch}
            onSubmit={onSubmitSearch}
            disabled={loading}
          />
          <InboxList
            messages={messages}
            activeId={activeId}
            loading={loading}
            error={error}
            onPick={onPick}
            onMarkRead={onMarkRead}
            onArchive={onArchive}
            onTrash={onTrash}
            onSilence={onAskSilence}
            onStartChat={onStartChat}
          />
          <Pagination
            hasPrev={pageStack.length > 0}
            hasNext={!!nextPageToken}
            disabled={loading}
            onPrev={goPrevPage}
            onNext={goNextPage}
          />
        </section>
        <section
          className={`min-w-0 flex-1 ${
            activeId ? "flex" : "hidden md:flex"
          } flex-col`}
        >
          {activeId ? (
            <InboxDetail
              key={activeId}
              messageId={activeId}
              onClose={onCloseDetail}
              onArchive={(msg) => void onArchive(msg)}
              onTrash={(msg) => void onTrash(msg)}
              onSilence={(msg) => onAskSilence(msg)}
              onStartChat={(msg) => void onStartChat(msg)}
              onMarkRead={(msg, next) => void onMarkRead(msg, next)}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-fg-subtle">
              Selecciona un correo
            </div>
          )}
        </section>
      </div>
      {silenceTarget ? (
        <SilenceModal
          senderEmail={silenceTarget.senderEmail}
          senderName={silenceTarget.senderName}
          onCancel={() => setSilenceTarget(null)}
          onConfirm={(mode) => void onConfirmSilence(silenceTarget, mode)}
        />
      ) : null}
    </div>
  );
}

function SearchBar({
  value,
  onChange,
  onSubmit,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  disabled: boolean;
}) {
  return (
    <form
      onSubmit={onSubmit}
      className="border-b border-border-subtle bg-surface-elevated/80 px-3 py-2"
    >
      <label className="flex items-center gap-2 rounded-md bg-surface-muted px-2 py-1.5">
        <svg
          viewBox="0 0 24 24"
          className="h-4 w-4 shrink-0 text-fg-subtle"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
        >
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="Buscar en Gmail (ej. from:bob is:unread)"
          className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-fg-subtle"
        />
        <button
          type="submit"
          disabled={disabled}
          className="shrink-0 rounded bg-primary px-2 py-0.5 text-xs font-medium text-primary-fg disabled:opacity-60"
        >
          Buscar
        </button>
      </label>
    </form>
  );
}

function Pagination({
  hasPrev,
  hasNext,
  disabled,
  onPrev,
  onNext,
}: {
  hasPrev: boolean;
  hasNext: boolean;
  disabled: boolean;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex items-center justify-between border-t border-border-subtle bg-surface-elevated/80 px-3 py-2 text-xs">
      <button
        type="button"
        onClick={onPrev}
        disabled={!hasPrev || disabled}
        className="rounded px-2 py-1 text-fg-muted hover:bg-interactive-hover disabled:opacity-40"
      >
        ← Anterior
      </button>
      <button
        type="button"
        onClick={onNext}
        disabled={!hasNext || disabled}
        className="rounded px-2 py-1 text-fg-muted hover:bg-interactive-hover disabled:opacity-40"
      >
        Siguiente →
      </button>
    </div>
  );
}
