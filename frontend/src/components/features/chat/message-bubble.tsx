"use client";

import type { ChatCard, ChatMessage } from "@/types/api";

import { ApprovalCard } from "./cards/approval-card";
import { ConnectorSetupCard } from "./cards/connector-setup-card";
import { KeyDecryptErrorCard } from "./cards/key-decrypt-error-card";
import { OAuthCard } from "./cards/oauth-card";
import { ProviderErrorCard } from "./cards/provider-error-card";

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
}

export function MessageBubble({
  message,
  onMessageUpdate
}: {
  message: ChatMessage;
  onMessageUpdate: (m: ChatMessage) => void;
}) {
  const isUser = message.role === "user";
  const isEvent = message.role === "event";
  const isSystem = message.role === "system";

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
        {message.content ? (
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
          />
        ))}
        <div className={`text-xs text-fg-subtle ${isUser ? "text-right" : "text-left"}`}>
          {formatTime(message.created_at)}
        </div>
      </div>
    </div>
  );
}

function CardRouter({
  card,
  onAfterAction
}: {
  card: ChatCard;
  onAfterAction: (patch: Partial<ChatMessage>) => void;
}) {
  switch (card.card_kind) {
    case "approval":
      return <ApprovalCard card={card as never} />;
    case "connector_setup":
      return <ConnectorSetupCard card={card as never} />;
    case "oauth_authorize":
      return <OAuthCard card={card as never} />;
    case "provider_error":
      return <ProviderErrorCard card={card as never} />;
    case "key_decrypt_error":
      return <KeyDecryptErrorCard card={card as never} />;
    default:
      return null;
  }
}
