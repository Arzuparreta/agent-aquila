"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useChatReferences } from "@/components/features/chat/reference-context";
import { apiFetch, ApiError } from "@/lib/api";
import { intlLocaleTag, useTranslation } from "@/lib/i18n";
import type {
  GmailMessageFull,
  GmailMessagePart,
  GmailMessageRow,
} from "@/types/api";

import { EmailActionsMenu } from "./email-actions-menu";

function header(parts: GmailMessagePart | undefined, name: string): string {
  if (!parts?.headers) return "";
  const target = name.toLowerCase();
  for (const h of parts.headers) {
    if (h.name.toLowerCase() === target) return h.value;
  }
  return "";
}

function decodeBase64Url(input: string): string {
  try {
    const normalized = input.replace(/-/g, "+").replace(/_/g, "/");
    const padded = normalized + "=".repeat((4 - (normalized.length % 4)) % 4);
    if (typeof window === "undefined") return "";
    const binary = window.atob(padded);
    // Decode as UTF-8.
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder("utf-8").decode(bytes);
  } catch {
    return "";
  }
}

function extractBody(payload: GmailMessagePart | undefined): string {
  if (!payload) return "";
  // Prefer text/plain, fall back to text/html stripped.
  let plain = "";
  let html = "";
  const walk = (part: GmailMessagePart) => {
    if (part.mimeType === "text/plain" && part.body?.data) {
      plain += decodeBase64Url(part.body.data);
    } else if (part.mimeType === "text/html" && part.body?.data) {
      html += decodeBase64Url(part.body.data);
    }
    for (const child of part.parts ?? []) walk(child);
  };
  walk(payload);
  if (plain) return plain;
  if (html) {
    return html
      .replace(/<style[\s\S]*?<\/style>/gi, "")
      .replace(/<script[\s\S]*?<\/script>/gi, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }
  return "";
}

function rowFromFull(full: GmailMessageFull): GmailMessageRow {
  const fromRaw = header(full.payload, "From");
  let senderName: string | null = null;
  let senderEmail = fromRaw;
  if (fromRaw.includes("<") && fromRaw.includes(">")) {
    const [namePart, rest] = fromRaw.split("<");
    senderName = namePart.replace(/"/g, "").trim() || null;
    senderEmail = rest.replace(">", "").trim();
  }
  const labels = full.labelIds ?? [];
  return {
    id: full.id,
    thread_id: full.threadId,
    snippet: full.snippet ?? "",
    subject: header(full.payload, "Subject"),
    sender_name: senderName,
    sender_email: senderEmail,
    to: header(full.payload, "To"),
    internal_date: full.internalDate ?? null,
    label_ids: labels,
    is_unread: labels.includes("UNREAD"),
  };
}

/**
 * Detail pane for a single Gmail message. Fetches the full payload from
 * ``/gmail/messages/{id}?format=full`` on mount; renders a best-effort plain
 * text body extracted from the MIME tree.
 */
export function InboxDetail({
  messageId,
  onClose,
  onArchive,
  onTrash,
  onSilence,
  onStartChat,
  onMarkRead,
}: {
  messageId: string;
  onClose: () => void;
  onArchive: (msg: GmailMessageRow) => void;
  onTrash: (msg: GmailMessageRow) => void;
  onSilence: (msg: GmailMessageRow) => void;
  onStartChat: (msg: GmailMessageRow) => void;
  onMarkRead: (msg: GmailMessageRow, next: boolean) => void;
}) {
  const { t, locale } = useTranslation();
  const router = useRouter();
  const refs = useChatReferences();
  const [full, setFull] = useState<GmailMessageFull | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setFull(null);
    setError(null);
    (async () => {
      try {
        const data = await apiFetch<GmailMessageFull>(
          `/gmail/messages/${messageId}?format=full`,
        );
        if (!cancelled) setFull(data);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : t("inbox.detail.loadError"));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [messageId, t]);

  if (error) {
    return (
      <div className="flex flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border-subtle bg-surface-elevated px-3 py-2">
          <button
            onClick={onClose}
            className="rounded-md p-2 text-fg-muted hover:bg-interactive-hover md:hidden"
            aria-label={t("common.back")}
          >
            ←
          </button>
          <div className="text-sm text-rose-300">{error}</div>
        </header>
      </div>
    );
  }
  if (!full) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-fg-subtle">
        {t("common.loading")}
      </div>
    );
  }

  const row = rowFromFull(full);
  const body = extractBody(full.payload);

  const onReference = () => {
    refs.add({
      type: "gmail_message",
      id: row.id,
      label: row.subject || row.sender_email,
    });
    router.push("/");
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-2 border-b border-border-subtle bg-surface-elevated px-3 py-2">
        <button
          onClick={onClose}
          className="rounded-md p-2 text-fg-muted hover:bg-interactive-hover md:hidden"
          aria-label={t("common.back")}
        >
          ←
        </button>
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-semibold">
            {row.subject || t("inbox.noSubject")}
          </div>
          <div className="truncate text-xs text-fg-subtle">
            {row.sender_name ? `${row.sender_name} · ` : ""}
            {row.sender_email}
          </div>
        </div>
        <EmailActionsMenu
          message={row}
          variant="bar"
          onMarkRead={onMarkRead}
          onArchive={onArchive}
          onTrash={onTrash}
          onSilence={onSilence}
          onStartChat={onStartChat}
        />
      </header>

      <div className="flex flex-wrap gap-2 border-b border-border-subtle bg-surface-elevated/70 px-3 py-2 text-xs">
        <button
          onClick={onReference}
          className="rounded-full bg-primary px-3 py-1 font-medium text-primary-fg hover:opacity-90"
        >
          {t("inbox.detail.referenceInChat")}
        </button>
        <button
          onClick={() => onStartChat(row)}
          className="rounded-full bg-primary/20 px-3 py-1 font-medium text-fg hover:bg-primary/30"
        >
          {t("inbox.email.startChat")}
        </button>
        <button
          onClick={() => onSilence(row)}
          className="rounded-full bg-rose-700/30 px-3 py-1 text-rose-200 hover:bg-rose-700/50"
        >
          {t("inbox.detail.silence")}
        </button>
        <span className="ml-auto self-center text-[11px] text-fg-subtle">
          {row.internal_date
            ? new Date(Number(row.internal_date)).toLocaleString(intlLocaleTag(locale))
            : ""}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-fg">
          {body || row.snippet || ""}
        </pre>
      </div>
    </div>
  );
}
