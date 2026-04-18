"use client";

type Card = {
  card_kind: "rule_learned";
  automation_id: number;
  title: string;
  instruction_natural_language: string;
};

export function RuleLearnedCard({ card }: { card: Card }) {
  return (
    <div className="rounded-2xl border border-fuchsia-400/30 bg-fuchsia-950/30 p-3 text-sm text-fuchsia-50">
      <div className="mb-1 text-xs uppercase tracking-wide text-fuchsia-300">Regla aprendida</div>
      <div className="font-semibold">{card.title}</div>
      <p className="mt-1 whitespace-pre-wrap text-fuchsia-100/90">
        {card.instruction_natural_language}
      </p>
      <a
        href="/automations"
        className="mt-2 inline-block text-xs text-fuchsia-200 underline hover:text-white"
      >
        Ver / modificar mis reglas
      </a>
    </div>
  );
}
