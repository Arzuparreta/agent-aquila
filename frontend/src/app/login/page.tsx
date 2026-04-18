"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/lib/auth";
import { useTranslation } from "@/lib/i18n";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "/api/v1").replace(/\/$/, "");

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
        setError(t("login.invalidCredentials"));
        return;
      }

      const data: { access_token: string } = await response.json();
      setToken(data.access_token);
      router.push("/");
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
