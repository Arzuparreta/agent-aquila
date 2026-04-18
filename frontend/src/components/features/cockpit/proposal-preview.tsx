"use client";

import Link from "next/link";
import type { ReactNode } from "react";

import { useTranslation } from "@/lib/i18n";
import type { PendingProposal } from "@/types/api";

function entityHref(entityType: string, id: number): string {
  switch (entityType) {
    case "contact":
      return `/contacts#${id}`;
    case "deal":
      return `/deals#${id}`;
    case "email":
      return `/emails#${id}`;
    case "event":
      return `/events#${id}`;
    default:
      return "#";
  }
}

export function ProposalPreview({ proposal }: { proposal: PendingProposal }) {
  const { t } = useTranslation();
  const p = proposal.payload;

  const summaryLine = proposal.summary ? (
    <div className="mb-2 rounded border border-slate-100 bg-slate-50/80 px-2 py-1.5 text-xs font-medium text-slate-800">
      {proposal.summary}
    </div>
  ) : null;

  let body: ReactNode;
  switch (proposal.kind) {
    case "create_deal":
      body = (
        <div className="mt-0 space-y-1">
          <div>
            <span className="font-medium">{t("proposal.title")}</span> {String(p.title ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.contact")}</span>{" "}
            <Link href={entityHref("contact", Number(p.contact_id))} className="text-blue-700 underline">
              #{String(p.contact_id)}
            </Link>
          </div>
          <div>
            <span className="font-medium">{t("proposal.status")}</span> {String(p.status ?? "new")}
          </div>
        </div>
      );
      break;
    case "update_deal":
      body = (
        <div className="space-y-1">
          <div>
            <span className="font-medium">{t("proposal.deal")}</span>{" "}
            <Link href={entityHref("deal", Number(p.deal_id))} className="text-blue-700 underline">
              #{String(p.deal_id)}
            </Link>
          </div>
          <pre className="max-h-28 overflow-auto text-xs">{JSON.stringify(p, null, 2)}</pre>
        </div>
      );
      break;
    case "create_contact":
      body = (
        <div className="space-y-1">
          <div>
            <span className="font-medium">{t("proposal.name")}</span> {String(p.name ?? "")}
          </div>
          {p.email ? (
            <div>
              <span className="font-medium">{t("proposal.email")}</span> {String(p.email)}
            </div>
          ) : null}
        </div>
      );
      break;
    case "update_contact":
      body = (
        <div className="space-y-1">
          <div>
            <span className="font-medium">{t("proposal.contact")}</span>{" "}
            <Link href={entityHref("contact", Number(p.contact_id))} className="text-blue-700 underline">
              #{String(p.contact_id)}
            </Link>
          </div>
          <pre className="max-h-28 overflow-auto text-xs">{JSON.stringify(p, null, 2)}</pre>
        </div>
      );
      break;
    case "create_event":
      body = (
        <div className="space-y-1">
          <div>
            <span className="font-medium">{t("proposal.venue")}</span> {String(p.venue_name ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.date")}</span> {String(p.event_date ?? "")}
          </div>
        </div>
      );
      break;
    case "update_event":
      body = (
        <div className="space-y-1">
          <div>
            <span className="font-medium">{t("proposal.event")}</span>{" "}
            <Link href={entityHref("event", Number(p.event_id))} className="text-blue-700 underline">
              #{String(p.event_id)}
            </Link>
          </div>
          <pre className="max-h-28 overflow-auto text-xs">{JSON.stringify(p, null, 2)}</pre>
        </div>
      );
      break;
    case "connector_email_send":
      body = (
        <div className="space-y-1">
          <div>
            <span className="font-medium">{t("proposal.connection")}</span> #{String(p.connection_id ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.to")}</span>{" "}
            {Array.isArray(p.to) ? p.to.join(", ") : String(p.to ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.subject")}</span> {String(p.subject ?? "")}
          </div>
          <div className="max-h-24 overflow-auto whitespace-pre-wrap text-xs text-slate-600">{String(p.body ?? "")}</div>
        </div>
      );
      break;
    case "connector_calendar_create":
      body = (
        <div className="space-y-1 text-xs">
          <div>
            <span className="font-medium">{t("proposal.connection")}</span> #{String(p.connection_id ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.summaryLabel")}</span> {String(p.summary ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.start")}</span> {String(p.start_iso ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.end")}</span> {String(p.end_iso ?? "")}
          </div>
        </div>
      );
      break;
    case "connector_file_upload":
      body = (
        <div className="space-y-1 text-xs">
          <div>
            <span className="font-medium">{t("proposal.connection")}</span> #{String(p.connection_id ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.path")}</span> {String(p.path ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.mime")}</span> {String(p.mime_type ?? "")}
          </div>
        </div>
      );
      break;
    case "connector_teams_message":
      body = (
        <div className="space-y-1 text-xs">
          <div>
            <span className="font-medium">{t("proposal.connection")}</span> #{String(p.connection_id ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.team")}</span> {String(p.team_id ?? "")}
          </div>
          <div>
            <span className="font-medium">{t("proposal.channel")}</span> {String(p.channel_id ?? "")}
          </div>
          <div className="max-h-24 overflow-auto whitespace-pre-wrap text-slate-600">{String(p.body ?? "")}</div>
        </div>
      );
      break;
    default:
      body = <pre className="max-h-32 overflow-auto text-xs">{JSON.stringify(p, null, 2)}</pre>;
  }

  return (
    <>
      {summaryLine}
      {body}
    </>
  );
}
