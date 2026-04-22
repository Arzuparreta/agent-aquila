"use client";

import { intlLocaleTag, useTranslation } from "@/lib/i18n";
import type { ChatCard, ChatMessage } from "@/types/api";

import { ApprovalCard } from "./cards/approval-card";
import { ConnectorSetupCard } from "./cards/connector-setup-card";
import { KeyDecryptErrorCard } from "./cards/key-decrypt-error-card";
import { OAuthCard } from "./cards/oauth-card";
import { ProviderErrorCard } from "./cards/provider-error-card";

/** Matches backend ``_AGENT_REPLY_PLACEHOLDER`` (single Unicode ellipsis). */
const AGENT_REPLY_PLACEHOLDER = "\u2026";

function formatTime(iso: string, localeTag: string): string {
  return new Date(iso).toLocaleTimeString(localeTag, { hour: "2-digit", minute: "2-digit" });
}

export function MessageBubble({
  message,
  onMessageUpdate,
  onRetryFailedMessage,
  retryDisabled,
  pendingLabel
}: {
  message: ChatMessage;
  onMessageUpdate: (m: ChatMessage) => void;
  onRetryFailedMessage?: (messageId: number) => void;
  retryDisabled?: boolean;
  pendingLabel?: string | null;
}) {
  const { t, locale } = useTranslation();
  const localeTag = intlLocaleTag(locale);
  const isUser = message.role === "user";
  const isEvent = message.role === "event";
  const isSystem = message.role === "system";
  const hasRetryableErrorCard = (message.attachments ?? []).some(
    (c) => c.card_kind === "provider_error" || c.card_kind === "key_decrypt_error"
  );
  const showPlainSystemRetry =
    Boolean(onRetryFailedMessage) &&
    message.role === "system" &&
    !hasRetryableErrorCard &&
    Boolean(message.content?.trim());
  const isAssistantPlaceholder =
    message.role === "assistant" && message.content === AGENT_REPLY_PLACEHOLDER;

  if (isEvent) {
    return (
      <div className="mx-auto max-w-md rounded-md bg-surface-muted/80 px-3 py-2 text-center text-sm text-fg-muted">
        <pre className="whitespace-pre-wrap font-sans">{message.content}</pre>
      </div>
    );
  }

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="flex max-w-[85%] flex-col gap-2">
        {isAssistantPlaceholder ? (
          <div className="animate-pulse rounded-2xl bg-surface-muted px-4 py-2 text-base text-fg-muted shadow-sm">
            {pendingLabel || t("chat.threadView.thinking")}
          </div>
        ) : message.content ? (
          <div
            className={`rounded-2xl px-4 py-2 text-base shadow-sm ${
              isUser
                ? "bg-primary text-primary-fg"
                : isSystem
                ? "bg-rose-900/40 text-rose-100"
                : "bg-surface-muted text-fg"
            }`}
          >
            <pre className="whitespace-pre-wrap break-words font-sans">{message.content}</pre>
          </div>
        ) : null}
        {(message.attachments ?? []).map((card, idx) => (
          <CardRouter
            key={`${message.id}-${idx}`}
            card={card}
            onAfterAction={(patch) => onMessageUpdate({ ...message, ...patch })}
            onRetryFailedMessage={onRetryFailedMessage}
            retryDisabled={retryDisabled}
            hostMessageId={message.id}
          />
        ))}
        {showPlainSystemRetry ? (
          <button
            type="button"
            disabled={retryDisabled}
            onClick={() => onRetryFailedMessage?.(message.id)}
            className="self-start rounded-full bg-rose-600 px-3 py-1 text-xs font-semibold text-white hover:bg-rose-500 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t("chat.message.retry")}
          </button>
        ) : null}
        {!isAssistantPlaceholder ? (
          <div className={`text-xs text-fg-subtle ${isUser ? "text-right" : "text-left"}`}>
            {formatTime(message.created_at, localeTag)}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function CardRouter({
  card,
  onAfterAction,
  onRetryFailedMessage,
  retryDisabled,
  hostMessageId
}: {
  card: ChatCard;
  onAfterAction: (patch: Partial<ChatMessage>) => void;
  onRetryFailedMessage?: (messageId: number) => void;
  retryDisabled?: boolean;
  hostMessageId: number;
}) {
  const retry = onRetryFailedMessage ? () => onRetryFailedMessage(hostMessageId) : undefined;
  switch (card.card_kind) {
    case "approval":
      return <ApprovalCard card={card as never} />;
    case "connector_setup":
      return <ConnectorSetupCard card={card as never} />;
    case "oauth_authorize":
      return <OAuthCard card={card as never} />;
    case "provider_error":
      return (
        <ProviderErrorCard
          card={card as never}
          onRetry={retry}
          retryDisabled={retryDisabled}
        />
      );
    case "key_decrypt_error":
      return (
        <KeyDecryptErrorCard
          card={card as never}
          onRetry={retry}
          retryDisabled={retryDisabled}
        />
      );
    default:
      return null;
  }
}
