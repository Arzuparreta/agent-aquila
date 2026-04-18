"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type {
  AttachmentMeta,
  CalendarEvent,
  ChatEntityType,
  Contact,
  Deal,
  Email,
  EntityRef
} from "@/types/api";

import { useChatReferences } from "./reference-context";

type Tab = "contacts" | "deals" | "events" | "emails" | "files";

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
  const refs = useChatReferences();

  const fetchTab = useCallback(async (t: Tab) => {
    setLoading(true);
    try {
      const rows = await apiFetch<unknown[]>(ENDPOINTS[t]);
      setData((prev) => ({ ...prev, [t]: rows as never }));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Error al cargar.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTab(tab);
  }, [tab, fetchTab]);

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
      <div className="ml-auto flex h-full w-full max-w-md flex-col bg-slate-950 shadow-2xl">
        <header className="pt-safe flex items-center gap-2 border-b border-white/10 px-3 py-2">
          <button
            onClick={onClose}
            className="rounded-md p-2 text-slate-300 hover:bg-white/5"
            aria-label="Cerrar"
          >
            ✕
          </button>
          <h2 className="flex-1 text-base font-semibold">Biblioteca</h2>
          {tab === "files" ? (
            <label className="cursor-pointer rounded-full bg-indigo-600 px-3 py-1 text-xs font-semibold text-white hover:bg-indigo-500">
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
        <nav className="flex gap-1 overflow-x-auto border-b border-white/5 px-2 py-2 text-sm">
          {(Object.keys(TAB_LABELS) as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`shrink-0 rounded-full px-3 py-1 ${
                t === tab ? "bg-indigo-600 text-white" : "text-slate-300 hover:bg-white/5"
              }`}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </nav>
        <div className="scroll-stealth min-h-0 flex-1 overflow-y-auto p-2">
          {loading ? <div className="p-3 text-sm text-slate-400">Cargando…</div> : null}
          {error ? <div className="p-3 text-sm text-rose-300">{error}</div> : null}
          <LibraryRows tab={tab} data={data} onPick={reference} />
        </div>
        <footer className="pb-safe border-t border-white/5 px-3 py-2 text-center text-[11px] text-slate-500">
          Toca un elemento para mencionarlo en la conversación.
        </footer>
      </div>
      <button
        onClick={onClose}
        className="flex-1 bg-black/40"
        aria-label="Cerrar fondo"
      />
    </div>
  );
}

function LibraryRows({
  tab,
  data,
  onPick
}: {
  tab: Tab;
  data: RowsByTab;
  onPick: (entity_type: ChatEntityType, id: number, label: string) => void;
}) {
  const rows = useMemo(() => {
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
      case "emails":
        return data.emails.map((e) => ({
          id: e.id,
          label: e.subject || "(sin asunto)",
          sub: e.sender_name || e.sender_email
        }));
      case "files":
        return data.files.map((f) => ({
          id: f.id,
          label: f.filename,
          sub: `${(f.size_bytes / 1024).toFixed(1)} KB · ${f.mime_type}`
        }));
    }
  }, [tab, data]);

  if (rows.length === 0) {
    return (
      <div className="p-4 text-center text-sm text-slate-500">No hay nada todavía aquí.</div>
    );
  }
  const entity_type = TAB_ENTITY[tab];
  return (
    <ul className="flex flex-col gap-1">
      {rows.map((r) => (
        <li key={`${tab}-${r.id}`}>
          <button
            onClick={() => onPick(entity_type, r.id, r.label)}
            className="flex w-full flex-col items-start gap-0.5 rounded-md bg-slate-900 px-3 py-2 text-left text-sm text-slate-100 hover:bg-slate-800"
          >
            <span className="truncate font-medium">{r.label}</span>
            {r.sub ? <span className="truncate text-xs text-slate-400">{r.sub}</span> : null}
          </button>
        </li>
      ))}
    </ul>
  );
}
