"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

import { useAuth } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";

export function ProtectedPage({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { isAuthenticated, authHydrated } = useAuth();
  const { t } = useTranslation();

  useEffect(() => {
    if (!authHydrated || isAuthenticated) return;
    const next = `${window.location.pathname}${window.location.search}`;
    router.replace(`/login?next=${encodeURIComponent(next)}`);
  }, [authHydrated, isAuthenticated, router]);

  if (!authHydrated) {
    return <div className="p-6">{t("auth.loadingSession")}</div>;
  }

  if (!isAuthenticated) {
    return <div className="p-6">{t("auth.redirecting")}</div>;
  }

  return <>{children}</>;
}
