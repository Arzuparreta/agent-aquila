"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { apiFetch, ApiError } from "@/lib/api";
import type { Email, TriageCategory } from "@/types/api";

import { InboxDetail } from "./inbox-detail";
import { InboxList, type EmailFilter } from "./inbox-list";
import { InboxTopBar } from "./inbox-top-bar";

/**
 * Primary inbox surface. Two-pane on md+ (list left, detail right); list-only with a
 * slide-in detail on mobile. The list filter chips and "solo no le\u00eddos" toggle live in
 * the top of the list pane.
 *
 * Reads ``?email=<id>`` from the URL on mount so push-notification taps land directly
 * on the right detail.
 */
export function InboxPage() {
  const router = useRouter();
  const params = useSearchParams();
  const initialEmailId = useMemo(() => {
    const v = Number(params.get("email"));
    return v > 0 ? v : null;
  }, [params]);

  const [emails, setEmails] = useState<Email[]>([]);
  const [filter, setFilter] = useState<EmailFilter>("actionable");
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<number | null>(initialEmailId);
  const [activeEmail, setActiveEmail] = useState<Email | null>(null);

  const refresh = useCallback(
    async (opts?: { filter?: EmailFilter; unreadOnly?: boolean }) => {
      setLoading(true);
      try {
        const f = opts?.filter ?? filter;
        const u = opts?.unreadOnly ?? unreadOnly;
        const qs = new URLSearchParams();
        if (f !== "all") qs.set("triage", f);
        if (u) qs.set("read", "false");
        const url = qs.toString() ? `/emails?${qs.toString()}` : "/emails";
        const rows = await apiFetch<Email[]>(url);
        setEmails(rows);
        setError(null);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "No se pudieron cargar los correos.");
      } finally {
        setLoading(false);
      }
    },
    [filter, unreadOnly]
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onPick = useCallback(
    async (email: Email) => {
      setActiveId(email.id);
      setActiveEmail(email);
      router.replace(`/inbox?email=${email.id}`);
      if (!email.is_read) {
        try {
          await apiFetch(`/emails/${email.id}/read`, {
            method: "PATCH",
            body: JSON.stringify({ is_read: true })
          });
          setEmails((prev) =>
            prev.map((e) => (e.id === email.id ? { ...e, is_read: true } : e))
          );
        } catch {
          // best-effort; the list will catch up on the next refresh
        }
      }
    },
    [router]
  );

  // Hydrate full email body from /emails/{id} when active changes (list rows may be lean).
  useEffect(() => {
    if (!activeId) return;
    let cancelled = false;
    void (async () => {
      try {
        const full = await apiFetch<Email>(`/emails/${activeId}`);
        if (!cancelled) setActiveEmail(full);
      } catch {
        // keep the row-level fallback in activeEmail
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activeId]);

  const onTriageChange = useCallback(
    (id: number, cat: TriageCategory) => {
      setEmails((prev) => prev.map((e) => (e.id === id ? { ...e, triage_category: cat } : e)));
      setActiveEmail((prev) => (prev && prev.id === id ? { ...prev, triage_category: cat } : prev));
      void refresh();
    },
    [refresh]
  );

  const onCloseDetail = useCallback(() => {
    setActiveId(null);
    setActiveEmail(null);
    router.replace("/inbox");
  }, [router]);

  return (
    <div className="flex h-screen w-screen flex-col bg-slate-950 text-slate-100">
      <InboxTopBar />
      <div className="flex min-h-0 flex-1">
        <section
          className={`flex min-w-0 flex-1 flex-col border-r border-white/5 md:max-w-md ${
            activeId ? "hidden md:flex" : "flex"
          }`}
        >
          <FilterBar
            filter={filter}
            unreadOnly={unreadOnly}
            onFilterChange={(next) => {
              setFilter(next);
              void refresh({ filter: next });
            }}
            onUnreadOnlyChange={(next) => {
              setUnreadOnly(next);
              void refresh({ unreadOnly: next });
            }}
          />
          <InboxList
            emails={emails}
            activeId={activeId}
            loading={loading}
            error={error}
            onPick={onPick}
          />
        </section>
        <section
          className={`min-w-0 flex-1 ${activeId ? "flex" : "hidden md:flex"} flex-col`}
        >
          {activeEmail ? (
            <InboxDetail
              key={activeEmail.id}
              email={activeEmail}
              onClose={onCloseDetail}
              onTriageChange={onTriageChange}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-slate-400">
              Selecciona un correo
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function FilterBar({
  filter,
  unreadOnly,
  onFilterChange,
  onUnreadOnlyChange
}: {
  filter: EmailFilter;
  unreadOnly: boolean;
  onFilterChange: (next: EmailFilter) => void;
  onUnreadOnlyChange: (next: boolean) => void;
}) {
  const chips: { id: EmailFilter; label: string }[] = [
    { id: "actionable", label: "Accionables" },
    { id: "informational", label: "Info" },
    { id: "noise", label: "Silenciados" },
    { id: "all", label: "Todos" }
  ];
  return (
    <div className="border-b border-white/5 bg-slate-900/60">
      <div className="flex gap-1 overflow-x-auto px-2 py-2 text-xs">
        {chips.map((c) => (
          <button
            key={c.id}
            onClick={() => onFilterChange(c.id)}
            className={`shrink-0 rounded-full px-3 py-1 ${
              filter === c.id
                ? "bg-indigo-600 text-white"
                : "text-slate-300 hover:bg-white/5"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
      <label className="flex items-center gap-2 px-3 pb-2 text-xs text-slate-300">
        <input
          type="checkbox"
          checked={unreadOnly}
          onChange={(e) => onUnreadOnlyChange(e.target.checked)}
          className="h-3.5 w-3.5 rounded border-slate-500 bg-slate-800"
        />
        Solo no leídos
      </label>
    </div>
  );
}
