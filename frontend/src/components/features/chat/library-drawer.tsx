"use client";

import { useCallback, useEffect, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type {
  AttachmentMeta,
  CalendarEvent,
  ChatEntityType,
  Contact,
  Deal,
  Email,
  EntityRef,
  TriageCategory
} from "@/types/api";

import { useChatReferences } from "./reference-context";

type Tab = "contacts" | "deals" | "events" | "emails" | "files";
type EmailFilter = "all" | "actionable" | "informational" | "noise";

const TAB_LABELS: Record<Tab, string> = {
  contacts: "Contactos",
  deals: "Tratos",
  events: "Eventos",
  emails: "Correos",
  files: "Archivos"
};

const TAB_ENTITY: Record<Tab, ChatEntityType> = {
  contacts: "contact",
  deals: "deal",
  events: "event",
  emails: "email",
  files: "attachment"
};

const TRIAGE_BADGE: Record<TriageCategory, { label: string; className: string }> = {
  actionable: { label: "Accionable", className: "bg-emerald-600/30 text-emerald-200" },
  informational: { label: "Info", className: "bg-surface-muted text-fg-muted" },
  noise: { label: "Silenciado", className: "bg-rose-700/30 text-rose-200" },
  unknown: { label: "Sin clasificar", className: "bg-surface-muted/90 text-fg-subtle" }
};

type RowsByTab = {
  contacts: Contact[];
  deals: Deal[];
  events: CalendarEvent[];
  emails: Email[];
  files: AttachmentMeta[];
};

const EMPTY: RowsByTab = { contacts: [], deals: [], events: [], emails: [], files: [] };

const ENDPOINTS: Record<Tab, string> = {
  contacts: "/contacts",
  deals: "/deals",
  events: "/events",
  emails: "/emails",
  files: "/files"
};

/**
 * "Everything visible at a glance" library drawer.
 *
 * Renders a tabbed read-only view over all the data the agent already knows about.
 * Tapping a row pushes a reference chip into the composer (via `useChatReferences`)
 * and closes the drawer — same UX intent as Cursor's @mention picker.
 *
 * For now this hits each domain endpoint directly with no pagination; everything is
 * single-tenant and lists are small. Files also expose an "Subir" button that POSTs
 * a multipart form to /files.
 */
export function LibraryDrawer({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<Tab>("contacts");
  const [data, setData] = useState<RowsByTab>(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [emailFilter, setEmailFilter] = useState<EmailFilter>("actionable");
  const refs = useChatReferences();

  const fetchTab = useCallback(
    async (t: Tab, filter: EmailFilter = emailFilter) => {
      setLoading(true);
      try {
        let url = ENDPOINTS[t];
        if (t === "emails" && filter !== "all") {
          url = `${url}?triage=${filter}`;
        }
        const rows = await apiFetch<unknown[]>(url);
        setData((prev) => ({ ...prev, [t]: rows as never }));
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Error al cargar.");
      } finally {
        setLoading(false);
      }
    },
    [emailFilter]
  );

  useEffect(() => {
    void fetchTab(tab);
  }, [tab, fetchTab]);

  const promoteEmail = useCallback(
    async (id: number) => {
      try {
        await apiFetch(`/emails/${id}/promote`, { method: "POST" });
        await fetchTab("emails");
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "No se pudo promover.");
      }
    },
    [fetchTab]
  );

  const suppressEmail = useCallback(
    async (id: number) => {
      try {
        await apiFetch(`/emails/${id}/suppress`, { method: "POST" });
        await fetchTab("emails");
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "No se pudo silenciar.");
      }
    },
    [fetchTab]
  );

  const reference = (entity_type: ChatEntityType, id: number, label: string) => {
    const ref: EntityRef = { type: entity_type, id, label };
    refs.add(ref);
    onClose();
  };

  const onUpload = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
      const resp = await fetch("/api/v1/files", {
        method: "POST",
        body: fd,
        headers: token ? { Authorization: `Bearer ${token}` } : undefined
      });
      if (!resp.ok) throw new Error(`Upload failed (${resp.status})`);
      await fetchTab("files");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Subida fallida.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="ml-auto flex h-full w-full max-w-md flex-col bg-surface-base text-fg shadow-2xl">
        <header className="pt-safe flex items-center gap-2 border-b border-border px-3 py-2">
          <button
            onClick={onClose}
            className="rounded-md p-2 text-fg-muted hover:bg-interactive-hover"
            aria-label="Cerrar"
          >
            ✕
          </button>
          <h2 className="flex-1 text-base font-semibold">Biblioteca</h2>
          {tab === "files" ? (
            <label className="cursor-pointer rounded-full bg-primary px-3 py-1 text-xs font-semibold text-primary-fg hover:opacity-90">
              Subir
              <input
                type="file"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void onUpload(f);
                  e.target.value = "";
                }}
              />
            </label>
          ) : null}
        </header>
        <nav className="flex gap-1 overflow-x-auto border-b border-border-subtle px-2 py-2 text-sm">
          {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`shrink-0 rounded-full px-3 py-1 ${
                t === tab ? "bg-primary text-primary-fg" : "text-fg-muted hover:bg-interactive-hover"
              }`}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </nav>
        {tab === "emails" ? (
          <div className="flex gap-1 overflow-x-auto border-b border-border-subtle bg-surface-elevated/80 px-2 py-1 text-xs">
            {(["actionable", "informational", "noise", "all"] as EmailFilter[]).map((f) => (
              <button
                key={f}
                onClick={() => {
                  setEmailFilter(f);
                  void fetchTab("emails", f);
                }}
                className={`shrink-0 rounded-full px-2 py-1 ${
                  emailFilter === f ? "bg-primary/25 text-fg" : "text-fg-subtle hover:bg-interactive-hover"
                }`}
              >
                {f === "all" ? "Todos" : TRIAGE_BADGE[f as TriageCategory].label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="scroll-stealth min-h-0 flex-1 overflow-y-auto p-2">
          {loading ? <div className="p-3 text-sm text-fg-subtle">Cargando…</div> : null}
          {error ? <div className="p-3 text-sm text-rose-300">{error}</div> : null}
          <LibraryRows
            tab={tab}
            data={data}
            onPick={reference}
            onPromoteEmail={promoteEmail}
            onSuppressEmail={suppressEmail}
          />
        </div>
        <footer className="pb-safe border-t border-border-subtle px-3 py-2 text-center text-[11px] text-fg-subtle">
          Toca un elemento para mencionarlo en la conversación.
        </footer>
      </div>
      <button
        onClick={onClose}
        className="flex-1 bg-scrim"
        aria-label="Cerrar fondo"
      />
    </div>
  );
}

function LibraryRows({
  tab,
  data,
  onPick,
  onPromoteEmail,
  onSuppressEmail
}: {
  tab: Tab;
  data: RowsByTab;
  onPick: (entity_type: ChatEntityType, id: number, label: string) => void;
  onPromoteEmail: (id: number) => Promise<void> | void;
  onSuppressEmail: (id: number) => Promise<void> | void;
}) {
  const entity_type = TAB_ENTITY[tab];

  if (tab === "emails") {
    if (data.emails.length === 0) {
      return (
        <div className="p-4 text-center text-sm text-fg-subtle">No hay nada todavía aquí.</div>
      );
    }
    return (
      <ul className="flex flex-col gap-1">
        {data.emails.map((e) => {
          const cat: TriageCategory = (e.triage_category ?? "unknown") as TriageCategory;
          const badge = TRIAGE_BADGE[cat] ?? TRIAGE_BADGE.unknown;
          const isNoise = cat === "noise" || cat === "informational";
          return (
            <li key={`emails-${e.id}`} className="rounded-md bg-surface-elevated">
              <button
                onClick={() => onPick(entity_type, e.id, e.subject || "(sin asunto)")}
                className="flex w-full flex-col items-start gap-0.5 rounded-t-md px-3 py-2 text-left text-sm text-fg hover:bg-surface-muted"
              >
                <span className="flex w-full items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium">
                    {e.subject || "(sin asunto)"}
                  </span>
                  <span
                    className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wide ${badge.className}`}
                    title={e.triage_reason ?? undefined}
                  >
                    {badge.label}
                  </span>
                </span>
                <span className="truncate text-xs text-fg-subtle">
                  {e.sender_name || e.sender_email}
                </span>
              </button>
              <div className="flex gap-2 border-t border-border-subtle px-3 py-1 text-xs">
                {isNoise ? (
                  <button
                    onClick={() => void onPromoteEmail(e.id)}
                    className="rounded-full bg-emerald-700/40 px-2 py-0.5 text-emerald-200 hover:bg-emerald-700/60"
                  >
                    Promover a accionable
                  </button>
                ) : null}
                {cat !== "noise" ? (
                  <button
                    onClick={() => void onSuppressEmail(e.id)}
                    className="rounded-full bg-surface-muted px-2 py-0.5 text-fg-muted hover:bg-surface-inset"
                  >
                    Silenciar
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    );
  }

  const rows = (() => {
    switch (tab) {
      case "contacts":
        return data.contacts.map((c) => ({
          id: c.id,
          label: c.name,
          sub: c.email || c.phone || c.role
        }));
      case "deals":
        return data.deals.map((d) => ({
          id: d.id,
          label: d.title,
          sub: `${d.status}${d.amount ? ` · ${d.amount} ${d.currency ?? ""}` : ""}`
        }));
      case "events":
        return data.events.map((e) => ({
          id: e.id,
          label: e.venue_name,
          sub: `${e.event_date}${e.city ? ` · ${e.city}` : ""}`
        }));
      case "files":
        return data.files.map((f) => ({
          id: f.id,
          label: f.filename,
          sub: `${(f.size_bytes / 1024).toFixed(1)} KB · ${f.mime_type}`
        }));
      default:
        return [];
    }
  })();

  if (rows.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-fg-subtle">No hay nada todavía aquí.</div>
    );
  }
  return (
    <ul className="flex flex-col gap-1">
      {rows.map((r) => (
        <li key={`${tab}-${r.id}`}>
          <button
            onClick={() => onPick(entity_type, r.id, r.label)}
            className="flex w-full flex-col items-start gap-0.5 rounded-md bg-surface-elevated px-3 py-2 text-left text-sm text-fg hover:bg-surface-muted"
          >
            <span className="truncate font-medium">{r.label}</span>
            {r.sub ? <span className="truncate text-xs text-fg-subtle">{r.sub}</span> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}
