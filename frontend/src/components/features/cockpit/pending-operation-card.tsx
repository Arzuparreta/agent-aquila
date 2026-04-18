"use client";

import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { ProposalPreview } from "@/components/features/cockpit/proposal-preview";
import type { PendingOperationPreview, PendingProposal } from "@/types/api";

type Props = {
  proposal: PendingProposal;
  busy: boolean;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
};

export function PendingOperationCard({ proposal, busy, onApprove, onReject }: Props) {
  const [structured, setStructured] = useState<PendingOperationPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setPreviewError(null);
    void (async () => {
      try {
        const data = await apiFetch<PendingOperationPreview>(`/agent/pending-operations/${proposal.id}/preview`);
        if (!cancelled) {
          setStructured(data);
        }
      } catch (e) {
        if (!cancelled) {
          setStructured(null);
          setPreviewError(e instanceof Error ? e.message : "Preview failed");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [proposal.id]);

  return (
    <Card className="p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2 text-xs uppercase text-slate-500">
        <span>
          {proposal.kind} · #{proposal.id}
        </span>
        {proposal.risk_tier ? (
          <span className="rounded bg-amber-100 px-1.5 py-0.5 font-normal normal-case text-amber-900">
            {proposal.risk_tier}
          </span>
        ) : null}
        {proposal.idempotency_key ? (
          <span className="font-mono text-[10px] normal-case text-slate-500">idem: {proposal.idempotency_key}</span>
        ) : null}
      </div>
      <ProposalPreview proposal={proposal} />
      {structured ? (
        <details className="mt-2 text-xs text-slate-600">
          <summary className="cursor-pointer font-medium text-slate-800">Structured preview (API)</summary>
          <pre className="mt-1 max-h-40 overflow-auto rounded border border-slate-100 bg-slate-50 p-2 font-mono text-[11px]">
            {JSON.stringify(structured.preview, null, 2)}
          </pre>
        </details>
      ) : null}
      {previewError ? <p className="mt-1 text-[11px] text-amber-800">{previewError}</p> : null}
      <div className="mt-3 flex gap-2">
        <Button
          type="button"
          className="bg-emerald-700 text-white hover:bg-emerald-800"
          disabled={busy}
          onClick={() => onApprove(proposal.id)}
        >
          Approve
        </Button>
        <Button type="button" className="border-dashed" disabled={busy} onClick={() => onReject(proposal.id)}>
          Reject
        </Button>
      </div>
    </Card>
  );
}
