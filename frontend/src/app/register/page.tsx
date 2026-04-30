"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(
  /\/$/,
  "",
);

function messageFromFastApiDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const rec = detail as Record<string, unknown>;
    if (typeof rec.message === "string" && rec.message.trim())
      return rec.message.trim();
    if (typeof rec.detail === "string" && rec.detail.trim())
      return rec.detail.trim();
    const kind = typeof rec.kind === "string" ? rec.kind : "";
    if (kind) {
      try {
        return `${kind}: ${JSON.stringify(detail)}`.slice(0, 600);
      } catch {
        return kind;
      }
    }
  }
  if (Array.isArray(detail)) {
    const parts = detail
      .map((item) => {
        if (!item || typeof item !== "object") return "";
        const rec = item as { msg?: unknown; loc?: unknown };
        const msg = typeof rec.msg === "string" ? rec.msg : "";
        if (!Array.isArray(rec.loc)) return msg;
        const loc = rec.loc
          .filter((x) => x !== "body" && typeof x === "string")
          .join(".");
        return loc ? `${loc}: ${msg}` : msg;
      })
      .filter(Boolean);
    return parts.length ? parts.join("; ") : null;
  }
  return null;
}

async function messageFromErrorResponse(
  response: Response,
  htmlFallback: string,
): Promise<string | null> {
  const raw = await response.text();
  const trimmed = raw.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      return messageFromFastApiDetail(parsed);
    } catch {
      /* fall through */
    }
  }
  if (trimmed.startsWith("<!DOCTYPE") || trimmed.startsWith("<html")) {
    return htmlFallback;
  }
  return trimmed.length > 480 ? `${trimmed.slice(0, 480)}…` : trimmed;
}

export default function RegisterPage() {
  const router = useRouter();
  const { setToken } = useAuth();
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/auth/has-users`)
      .then((res) => (res.ok ? res.json() : null))
      .then((data: { users_exist?: boolean; registration_open?: boolean } | null) => {
        if (data && data.users_exist && !data.registration_open) {
          router.replace("/login");
        }
      })
      .catch(() => {});
  }, [router]);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      const response = await fetch(`${API_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          password,
          full_name: fullName.trim() || null,
        }),
      });

      if (!response.ok) {
        let message: string | null = await messageFromErrorResponse(
          response,
          t("login.errorHtmlResponse"),
        );
        if (!message) {
          message =
            response.status === 403
              ? t("register.disabled")
              : t("login.requestFailed", { status: String(response.status) });
        }
        setError(message);
        return;
      }

      const loginResponse = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
        credentials: "include",
      });

      if (!loginResponse.ok) {
        router.push("/login");
        return;
      }

      const data: { access_token: string; token_type: string } =
        await loginResponse.json();
      setToken(data.access_token);
      router.push("/");
    } catch {
      setError(t("login.networkError"));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="page-scroll bg-surface-base text-fg">
      <div className="mx-auto flex min-h-[100dvh] max-w-md flex-col justify-center px-4 pb-10 pt-[max(2.5rem,env(safe-area-inset-top))]">
        <Card>
          <h1 className="mb-4 text-xl font-semibold">{t("register.title")}</h1>
          <p className="mb-4 text-sm text-fg-muted">{t("register.intro")}</p>
          <form className="space-y-3" onSubmit={onSubmit}>
            <Input
              placeholder={t("register.email")}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
            <Input
              placeholder={t("register.password")}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
            />
            <Input
              placeholder={t("register.fullName")}
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
            {error ? <p className="text-sm text-red-600">{error}</p> : null}
            <Button className="w-full" type="submit" disabled={submitting}>
              {submitting ? t("register.creating") : t("register.createAccount")}
            </Button>
          </form>
          <p className="mt-4 text-center text-sm text-fg-muted">
            {t("register.hasAccount")}{" "}
            <a href="/login" className="text-accent underline">
              {t("register.signIn")}
            </a>
          </p>
        </Card>
      </div>
    </main>
  );
}
