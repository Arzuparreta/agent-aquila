"use client";

import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/lib/auth";

/**
 * Compact bar with: hamburger (mobile only), title, settings menu.
 * The settings entry is intentionally tucked behind a small menu so the artist
 * can't accidentally open it in their pocket.
 */
export function ChatTopBar({
  title,
  onOpenDrawer
}: {
  title: string;
  onOpenDrawer: () => void;
}) {
  const { logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <header className="pt-safe flex items-center gap-2 border-b border-white/5 bg-slate-900 px-3 py-2">
      <button
        onClick={onOpenDrawer}
        className="rounded-md p-2 text-slate-300 hover:bg-white/5 md:hidden"
        aria-label="Abrir conversaciones"
      >
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
          <path d="M3 6h18M3 12h18M3 18h18" />
        </svg>
      </button>
      <div className="min-w-0 flex-1 truncate text-base font-semibold">{title}</div>
      <div className="relative">
        <button
          onClick={() => setMenuOpen((v) => !v)}
          className="rounded-md p-2 text-slate-300 hover:bg-white/5"
          aria-label="Menú"
        >
          <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2}>
            <circle cx="12" cy="5" r="1.5" />
            <circle cx="12" cy="12" r="1.5" />
            <circle cx="12" cy="19" r="1.5" />
          </svg>
        </button>
        {menuOpen ? (
          <div
            className="absolute right-0 top-full z-40 mt-2 w-56 overflow-hidden rounded-lg border border-white/10 bg-slate-900 py-1 text-sm shadow-xl"
            onMouseLeave={() => setMenuOpen(false)}
          >
            <Link
              href="/settings"
              className="block px-3 py-2 hover:bg-white/5"
              onClick={() => setMenuOpen(false)}
            >
              Ajustes técnicos (avanzado)
            </Link>
            <Link
              href="/automations"
              className="block px-3 py-2 hover:bg-white/5"
              onClick={() => setMenuOpen(false)}
            >
              Reglas aprendidas
            </Link>
            <button
              onClick={() => {
                setMenuOpen(false);
                logout();
              }}
              className="block w-full px-3 py-2 text-left text-rose-300 hover:bg-white/5"
            >
              Cerrar sesión
            </button>
          </div>
        ) : null}
      </div>
    </header>
  );
}
