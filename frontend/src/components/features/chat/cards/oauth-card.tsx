"use client";

import { useTranslation } from "@/lib/i18n";

type Card = {
  card_kind: "oauth_authorize";
  provider: string;
  authorize_url: string;
  label?: string | null;
};

export function OAuthCard({ card }: { card: Card }) {
  const { t } = useTranslation();
  return (
    <a
      href={card.authorize_url}
      target="_blank"
      rel="noopener noreferrer"
      className="block rounded-2xl border border-violet-400/30 bg-violet-950/40 p-3 text-sm text-violet-50 hover:bg-violet-950/60"
    >
      <div className="text-xs uppercase tracking-wide text-violet-300">
        {t("cards.oauth.authorize", { provider: card.provider })}
      </div>
      <div className="mt-1 font-semibold">{card.label || t("cards.oauth.defaultLabel")}</div>
      <div className="mt-1 text-xs text-violet-200/80">{t("cards.oauth.hint")}</div>
    </a>
  );
}
