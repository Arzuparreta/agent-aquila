"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import type {
  ChatThread,
  GmailMessageRow,
  GmailMessagesPage,
} from "@/types/api";

import { StatusToast } from "@/components/ui/status-toast";

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

type LoadError =
  | { kind: "rate_limited"; retryAfter: number }
  | { kind: "needs_reauth" }
  | { kind: "no_connection" }
  | { kind: "generic"; message: string };

/**
 * Default page size kept intentionally small. Each row hits Gmail's
 * `messages.get(format=metadata)` once because `messages.list` only returns
 * `{id, threadId}`; on the free Gmail tier the per-user QPS cap is tight,
 * so 10 rows + an in-process metadata cache (see `routes/gmail.py`) keeps
 * us comfortably below the limit even on rapid back/forward navigation.
 */
const PAGE_SIZE = 10;

function parseLoadError(
  err: unknown,
  t: (key: TranslationKey, params?: Record<string, string | number>) => string
): LoadError {
  if (err instanceof ApiError) {
    const detail = err.detail as Record<string, unknown> | undefined;
    const kind = detail && typeof detail === "object" ? detail.kind : undefined;
    if (kind === "gmail_rate_limited") {
      const retry = Number(detail?.retry_after_seconds);
      return {
        kind: "rate_limited",
        retryAfter: Number.isFinite(retry) && retry > 0 ? retry : 30
      };
    }
    if (kind === "needs_reauth" || err.status === 401) {
      return { kind: "needs_reauth" };
    }
    if (
      err.status === 400 &&
      err.message.toLowerCase().includes("no gmail connection")
    ) {
      return { kind: "no_connection" };
    }
    return { kind: "generic", message: err.message };
  }
  return {
    kind: "generic",
    message: err instanceof Error ? err.message : t("inbox.error.loadFailed")
  };
}

/**
 * Inbox surface, post-OpenClaw refactor. There is no local mirror anymore —
 * this page is a thin lens over the live ``/gmail/messages`` proxy:
 *
 * - One unified list (no triage chips, no classification).
 * - Free-form Gmail search (``q=`` passes straight through to Gmail).
 * - ``page_token``-based pagination via Gmail's own cursor.
 * - Per-row actions auto-execute against Gmail (mark read/unread, archive,
 *   trash, reply via chat, "Silenciar" opens a tiny modal that mutes or
 *   spam moves the thread via modify then adds a skip-inbox filter).
 *
 * Reads ``?msg=<gmail-id>`` from the URL on mount so deep links land on the
 * right detail.
 */
export function InboxPage() {
  const { t } = useTranslation();
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
  const [loadError, setLoadError] = useState<LoadError | null>(null);
  const [activeId, setActiveId] = useState<string | null>(initialMessageId);
  const [status, setStatus] = useState<StatusMessage | null>(null);
  const [silenceTarget, setSilenceTarget] = useState<SilenceTarget | null>(null);
  // Tracks the most recent fetch so React Strict Mode's double-fire (or a
  // user spamming search) doesn't issue overlapping Gmail calls — only the
  // newest call is allowed to write back into state.
  const loadSeq = useRef(0);

  const loadPage = useCallback(
    async (opts?: { q?: string; pageToken?: string | null }) => {
      const q = opts?.q ?? submittedQuery;
      const token = opts?.pageToken ?? null;
      const seq = ++loadSeq.current;
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
        if (seq !== loadSeq.current) return;
        setMessages(data.messages);
        setNextPageToken(data.next_page_token);
        setLoadError(null);
      } catch (err) {
        if (seq !== loadSeq.current) return;
        setLoadError(parseLoadError(err, t));
        setMessages([]);
        setNextPageToken(null);
      } finally {
        if (seq === loadSeq.current) setLoading(false);
      }
    },
    [submittedQuery, t],
  );

  // Initial load + reload on submitted-query change.
  useEffect(() => {
    setPageToken(null);
    setPageStack([]);
    void loadPage({ pageToken: null });
  }, [loadPage]);

  // When the inbox is rate-limited, count down on the visible banner so the
  // user has a clear sense of when retrying is worthwhile (instead of
  // refreshing a few times and burning the rest of the QPS budget).
  const rateLimitRemaining =
    loadError?.kind === "rate_limited" ? loadError.retryAfter : 0;
  useEffect(() => {
    if (rateLimitRemaining <= 0) return;
    const id = window.setInterval(() => {
      setLoadError((prev) =>
        prev?.kind === "rate_limited"
          ? { ...prev, retryAfter: Math.max(0, prev.retryAfter - 1) }
          : prev,
      );
    }, 1000);
    return () => window.clearInterval(id);
  }, [rateLimitRemaining]);

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
          text: next ? t("inbox.markRead") : t("inbox.markUnread")
        });
      } catch (err) {
        // Revert on failure.
        patchRow(msg.id, {
          is_unread: msg.is_unread,
          label_ids: msg.label_ids,
        });
        setStatus({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("inbox.error.update")
        });
      }
    },
    [patchRow, t],
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
        setStatus({ kind: "ok", text: t("inbox.archived") });
      } catch (err) {
        setMessages((prev) => [msg, ...prev]);
        setStatus({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("inbox.error.archive")
        });
      }
    },
    [activeId, messages, onCloseDetail, t],
  );

  const onTrash = useCallback(
    async (msg: GmailMessageRow) => {
      const remaining = messages.filter((m) => m.id !== msg.id);
      setMessages(remaining);
      if (activeId === msg.id) onCloseDetail();
      try {
        await apiFetch(`/gmail/messages/${msg.id}/trash`, { method: "POST" });
        setStatus({ kind: "ok", text: t("inbox.trashed") });
      } catch (err) {
        setMessages((prev) => [msg, ...prev]);
        setStatus({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("inbox.error.trash")
        });
      }
    },
    [activeId, messages, onCloseDetail, t],
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
        // Gmail API rejects SPAM in filter addLabelIds — only thread/message
        // modify can move mail to Spam. For future mail we use the same
        // skip-inbox+mark-read filter as mute (Gmail has no API to force
        // the Spam folder on incoming mail via filters).
        if (mode === "spam") {
          await apiFetch(`/gmail/threads/${target.threadId}/modify`, {
            method: "POST",
            body: JSON.stringify({
              add_label_ids: ["SPAM"],
              remove_label_ids: ["INBOX"],
            }),
          });
        }

        const filterAction = { removeLabelIds: ["INBOX", "UNREAD"] };
        await apiFetch(`/gmail/filters`, {
          method: "POST",
          body: JSON.stringify({
            criteria: { from: target.senderEmail },
            action: filterAction,
          }),
        });

        if (mode === "mute") {
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
              ? t("inbox.silence.spamOk", { email: target.senderEmail })
              : t("inbox.silence.muteOk", { email: target.senderEmail })
        });
      } catch (err) {
        setStatus({
          kind: "error",
          text: err instanceof ApiError ? err.message : t("inbox.error.filter")
        });
      } finally {
        setSilenceTarget(null);
      }
    },
    [activeId, onCloseDetail, t],
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
          text: err instanceof ApiError ? err.message : t("inbox.error.startChat")
        });
      }
    },
    [router, t],
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
        <StatusToast
          kind={status.kind}
          text={status.text}
          onDismiss={() => setStatus(null)}
          dismissAriaLabel={t("chat.dismissToast")}
        />
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
          {loadError ? (
            <LoadErrorBanner
              error={loadError}
              onRetry={() => void loadPage({ pageToken })}
            />
          ) : null}
          <InboxList
            messages={messages}
            activeId={activeId}
            loading={loading}
            error={null}
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
              {t("inbox.selectMessage")}
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
  const { t } = useTranslation();
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
          placeholder={t("inbox.searchPlaceholder")}
          className="min-w-0 flex-1 bg-transparent text-base text-fg outline-none placeholder:text-fg-subtle md:text-sm"
        />
        <button
          type="submit"
          disabled={disabled}
          className="shrink-0 rounded bg-primary px-2 py-0.5 text-xs font-medium text-primary-fg disabled:opacity-60"
        >
          {t("search.submit")}
        </button>
      </label>
    </form>
  );
}

function LoadErrorBanner({
  error,
  onRetry,
}: {
  error: LoadError;
  onRetry: () => void;
}) {
  const { t } = useTranslation();
  if (error.kind === "rate_limited") {
    const waiting = error.retryAfter > 0;
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
        <span>
          {t("inbox.rateLimit.body")}
          {waiting
            ? t("inbox.rateLimit.retryIn", { seconds: error.retryAfter })
            : t("inbox.rateLimit.ready")}
        </span>
        <button
          type="button"
          onClick={onRetry}
          disabled={waiting}
          className="rounded bg-amber-500/20 px-2 py-0.5 font-medium text-amber-100 hover:bg-amber-500/30 disabled:opacity-50"
        >
          {t("common.retry")}
        </button>
      </div>
    );
  }
  if (error.kind === "needs_reauth" || error.kind === "no_connection") {
    const msg =
      error.kind === "needs_reauth" ? t("inbox.error.needsReauth") : t("inbox.error.noConnection");
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-sky-500/30 bg-sky-500/10 px-3 py-2 text-xs text-sky-200">
        <span>{msg}</span>
        <a
          href="/settings"
          className="rounded bg-sky-500/20 px-2 py-0.5 font-medium text-sky-100 hover:bg-sky-500/30"
        >
          {t("inbox.goToSettings")}
        </a>
      </div>
    );
  }
  if (error.kind !== "generic") return null;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
      <span className="min-w-0 flex-1 break-words">{error.message}</span>
      <button
        type="button"
        onClick={onRetry}
        className="rounded bg-rose-500/20 px-2 py-0.5 font-medium text-rose-100 hover:bg-rose-500/30"
      >
        {t("common.retry")}
      </button>
    </div>
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
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between border-t border-border-subtle bg-surface-elevated/80 px-3 py-2 text-xs">
      <button
        type="button"
        onClick={onPrev}
        disabled={!hasPrev || disabled}
        className="rounded px-2 py-1 text-fg-muted hover:bg-interactive-hover disabled:opacity-40"
      >
        {t("inbox.pagination.prev")}
      </button>
      <button
        type="button"
        onClick={onNext}
        disabled={!hasNext || disabled}
        className="rounded px-2 py-1 text-fg-muted hover:bg-interactive-hover disabled:opacity-40"
      >
        {t("inbox.pagination.next")}
      </button>
    </div>
  );
}
