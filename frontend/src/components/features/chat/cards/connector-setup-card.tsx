"use client";

type Card = {
  card_kind: "connector_setup";
  provider: string;
  step: string;
  title: string;
  body: string;
  cta?: { label: string; url?: string } | null;
};

/**
 * One step of a conversational connector wizard.
 *
 * The actual data exchange (e.g. pasting a client_id back) happens in the chat
 * itself: the artist replies with the value and the agent calls
 * ``submit_connector_credentials`` on the next turn. So this card is informational
 * only — title, explainer, and an optional CTA link to the provider console.
 */
export function ConnectorSetupCard({ card }: { card: Card }) {
  return (
    <div className="rounded-2xl border border-sky-400/30 bg-sky-950/40 p-3 text-sm text-sky-50">
      <div className="mb-1 text-xs uppercase tracking-wide text-sky-300">
        Conectar {card.provider} · paso {card.step}
      </div>
      <div className="mb-1 font-semibold">{card.title}</div>
      <p className="mb-2 whitespace-pre-wrap text-sky-100/90">{card.body}</p>
      {card.cta?.url ? (
        <a
          href={card.cta.url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-block rounded-full bg-sky-600 px-3 py-1 text-xs font-semibold text-white hover:bg-sky-500"
        >
          {card.cta.label || "Abrir"}
        </a>
      ) : null}
    </div>
  );
}
