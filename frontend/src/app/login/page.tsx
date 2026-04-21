"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/$/, "");

function messageFromFastApiDetail(body: unknown): string | null {
  if (!body || typeof body !== "object") return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const rec = detail as Record<string, unknown>;
    if (typeof rec.message === "string" && rec.message.trim()) return rec.message.trim();
    if (typeof rec.detail === "string" && rec.detail.trim()) return rec.detail.trim();
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

/** Read error body: Next/proxies sometimes omit or mislabel Content-Type on 5xx. */
async function messageFromErrorResponse(
  response: Response,
  htmlFallback: string
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

export default function LoginPage() {
  const router = useRouter();
  const { setToken } = useAuth();
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    try {
      const response = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password })
      });

      if (!response.ok) {
        let message: string | null = await messageFromErrorResponse(
          response,
          t("login.errorHtmlResponse")
        );
        if (!message) {
          message =
            response.status === 401
              ? t("login.invalidCredentials")
              : t("login.requestFailed", { status: String(response.status) });
        }
        setError(message);
        return;
      }

      const data: { access_token: string } = await response.json();
      setToken(data.access_token);
      const params = new URLSearchParams(window.location.search);
      let dest = params.get("next") || "/";
      if (!dest.startsWith("/") || dest.startsWith("//")) {
        dest = "/";
      }
      router.push(dest);
    } catch {
      setError(t("login.networkError"));
    }
  };

  return (
    <main className="mx-auto mt-24 max-w-md px-4">
      <Card>
        <h1 className="mb-4 text-xl font-semibold">{t("login.title")}</h1>
        <form className="space-y-3" onSubmit={onSubmit}>
          <Input placeholder={t("login.email")} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <Input
            placeholder={t("login.password")}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error ? <p className="text-sm text-red-600">{error}</p> : null}
          <Button className="w-full" type="submit">
            {t("login.signIn")}
          </Button>
        </form>
      </Card>
    </main>
  );
}
