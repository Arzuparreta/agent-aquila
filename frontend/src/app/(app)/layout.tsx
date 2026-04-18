"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, useCallback, useState } from "react";

import { ProtectedPage } from "@/components/features/protected-page";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import { SemanticSearchHit } from "@/types/api";

const NAV: { href: string; labelKey: TranslationKey }[] = [
  { href: "/cockpit", labelKey: "nav.cockpit" },
  { href: "/dashboard", labelKey: "nav.dashboard" },
  { href: "/contacts", labelKey: "nav.contacts" },
  { href: "/deals", labelKey: "nav.deals" },
  { href: "/emails", labelKey: "nav.emails" },
  { href: "/events", labelKey: "nav.events" },
  { href: "/automations", labelKey: "nav.automations" },
  { href: "/settings", labelKey: "nav.settings" }
];

export default function AppShellLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { logout } = useAuth();
  const { t } = useTranslation();
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<SemanticSearchHit[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);

  const runSearch = useCallback(async () => {
    const q = query.trim();
    if (!q) {
      setHits([]);
      return;
    }
    try {
      const data = await apiFetch<SemanticSearchHit[]>("/ai/search", {
        method: "POST",
        body: JSON.stringify({ query: q, limit_per_type: 4 })
      });
      setHits(data);
    } catch {
      setHits([]);
    }
  }, [query]);

  const onSearchSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await runSearch();
    setSearchOpen(true);
  };

  return (
    <ProtectedPage>
      <div className="flex min-h-screen bg-slate-50 text-slate-900">
        <aside className="flex w-56 flex-col border-r border-slate-200 bg-white">
          <div className="border-b border-slate-200 px-4 py-4 text-sm font-semibold">{t("nav.brand")}</div>
          <nav className="flex flex-col gap-1 p-3">
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-2 text-sm ${
                  pathname === item.href ? "bg-slate-900 text-white" : "text-slate-700 hover:bg-slate-100"
                }`}
              >
                {t(item.labelKey)}
              </Link>
            ))}
          </nav>
          <div className="mt-auto border-t border-slate-200 p-3">
            <Button className="w-full border-dashed" onClick={() => logout()}>
              {t("nav.logout")}
            </Button>
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-white px-6 py-3">
            <form className="flex min-w-[240px] flex-1 items-center gap-2" onSubmit={onSearchSubmit}>
              <Input
                placeholder={t("search.placeholder")}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <Button type="submit" className="bg-slate-900 text-white hover:bg-slate-800">
                {t("search.submit")}
              </Button>
            </form>
          </header>
          {searchOpen && hits.length > 0 ? (
            <div className="border-b border-slate-200 bg-white px-6 py-3 text-sm">
              <div className="mb-2 flex items-center justify-between">
                <span className="font-medium">{t("search.results")}</span>
                <Button className="text-xs" onClick={() => setSearchOpen(false)}>
                  {t("search.close")}
                </Button>
              </div>
              <ul className="space-y-2">
                {hits.map((hit) => (
                  <li key={`${hit.entity_type}-${hit.entity_id}`} className="rounded-md border border-slate-100 p-2">
                    <div className="text-xs uppercase text-slate-500">
                      {hit.entity_type} · {t("search.score")} {hit.score.toFixed(3)}
                      {hit.match_sources?.length ? ` · ${hit.match_sources.join("+")}` : ""}
                      {hit.rrf_score != null ? ` · ${t("search.rrf")} ${hit.rrf_score.toFixed(3)}` : ""}
                    </div>
                    <div className="font-medium">{hit.title}</div>
                    <div className="text-slate-600">{hit.snippet}</div>
                    <div className="text-xs text-slate-400">{hit.citation}</div>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          <div className="flex-1 overflow-auto p-6">{children}</div>
        </div>
      </div>
    </ProtectedPage>
  );
}
