"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { ProviderForm } from "@/components/features/ai-settings/provider-form";
import { ProviderList } from "@/components/features/ai-settings/provider-list";
import { useProviderConfigs } from "@/components/features/ai-settings/use-provider-configs";
import { ConnectorsSection } from "@/components/features/connectors/connectors-section";
import { LanguageSection } from "@/components/features/language/language-section";
import { MaintenanceSection } from "@/components/features/maintenance/maintenance-section";
import { MemorySection } from "@/components/features/memory/memory-section";
import { ProtectedPage } from "@/components/features/protected-page";
import { SkillsSection } from "@/components/features/skills/skills-section";
import { ThemeSection } from "@/components/features/theme/theme-section";
import { Card } from "@/components/ui/card";
import { useProviderRegistry } from "@/lib/ai-providers";
import { useTranslation } from "@/lib/i18n";
import { listIanaTimeZones } from "@/lib/timezones";
import type { TimeFormatPreference } from "@/types/api";

/**
 * Technical / advanced settings.
 *
 * Hidden behind the top-bar menu; the artist should rarely come here.
 *
 * The AI section is now a list-rail + form-pane layout that owns every
 * saved provider for the user (`/ai/providers/configs`). Switching the
 * rail selection no longer overwrites the previously-saved row, so keys
 * survive seamlessly when toggling between e.g. Google AI Studio and
 * Ollama.
 */
export default function SettingsPage() {
  const { t } = useTranslation();
  const { providers, loading: providersLoading } = useProviderRegistry();
  const api = useProviderConfigs({ providers, providersLoading });
  const [aiToggleSaving, setAiToggleSaving] = useState(false);
  const [tzDraft, setTzDraft] = useState("");
  const tzOptions = useMemo(() => listIanaTimeZones(), []);

  useEffect(() => {
    setTzDraft(api.userTimezone);
  }, [api.userTimezone]);

  return (
    <ProtectedPage>
      <div className="min-h-screen bg-surface-base text-fg">
        <header className="sticky top-0 z-10 flex items-center gap-3 border-b border-border bg-surface-elevated px-4 py-3 shadow-sm">
          <Link
            href="/"
            className="rounded-md px-2 py-1 text-sm text-fg-muted hover:bg-surface-muted"
          >
            ← Volver al chat
          </Link>
          <h1 className="text-base font-semibold">Ajustes técnicos</h1>
        </header>
        <main className="mx-auto flex max-w-4xl flex-col gap-4 px-4 py-4">
          <Card>
            <div className="mb-3 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold">Modelos de IA</h2>
                <p className="mt-1 text-xs text-fg-subtle">
                  Trae tu propia clave (BYOK). Guarda varios proveedores y cambia el activo
                  cuando quieras — tus claves se conservan cifradas por separado.
                </p>
              </div>
              <label className="inline-flex items-center gap-2 text-sm text-fg">
                <input
                  type="checkbox"
                  checked={api.aiDisabled}
                  disabled={aiToggleSaving}
                  onChange={async (e) => {
                    setAiToggleSaving(true);
                    try {
                      await api.setAIDisabled(e.target.checked);
                    } finally {
                      setAiToggleSaving(false);
                    }
                  }}
                />
                Desactivar IA temporalmente
              </label>
              <label className="flex flex-col gap-1 text-sm text-fg">
                <span className="text-fg-muted">Modo harness del agente (herramientas)</span>
                <select
                  className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
                  value={api.harnessMode}
                  onChange={async (e) => {
                    const v = e.target.value as "auto" | "native" | "prompted";
                    await api.setHarnessMode(v);
                  }}
                >
                  <option value="auto">Auto (recomendado — detecta Ollama qwen3/hermes)</option>
                  <option value="native">Nativo (API tools + tool_choice)</option>
                  <option value="prompted">Prompted (&lt;tool_call&gt; en texto)</option>
                </select>
                <span className="text-xs text-fg-subtle">
                  Si un modelo local ignora tool calling, usa Auto o Prompted. Ver docs/PROVIDERS.md.
                </span>
              </label>
              <div className="flex min-w-[16rem] flex-col gap-1 text-sm text-fg">
                <span className="text-fg-muted">Zona horaria del agente (IANA)</span>
                <input
                  className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
                  list="iana-timezones"
                  value={tzDraft}
                  onChange={(e) => setTzDraft(e.target.value)}
                  onBlur={() => {
                    const t = tzDraft.trim();
                    if (t !== (api.userTimezone || "").trim()) {
                      void api.setUserTimezone(t || null);
                    }
                  }}
                  placeholder="Europe/Madrid"
                  autoComplete="off"
                />
                <datalist id="iana-timezones">
                  {tzOptions.map((z) => (
                    <option key={z} value={z} />
                  ))}
                </datalist>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    className="rounded-md border border-border bg-surface-muted px-2 py-1 text-xs text-fg hover:bg-surface-base"
                    onClick={() => void api.applyBrowserTimeZone()}
                  >
                    Usar zona del navegador
                  </button>
                </div>
                <span className="text-xs text-fg-subtle">
                  El reloj del sistema (hoy / mañana / citas) usa esta zona. Déjalo vacío para UTC.
                </span>
              </div>
              <label className="flex min-w-[12rem] flex-col gap-1 text-sm text-fg">
                <span className="text-fg-muted">Formato de hora (agente)</span>
                <select
                  className="rounded-md border border-border bg-surface-base px-2 py-1.5 text-fg"
                  value={api.timeFormat}
                  onChange={(e) => {
                    const v = e.target.value as TimeFormatPreference;
                    void api.setTimeFormat(v);
                  }}
                >
                  <option value="auto">24 h (automático)</option>
                  <option value="24">24 h</option>
                  <option value="12">12 h (AM/PM)</option>
                </select>
              </label>
            </div>

            {api.loadError ? (
              <p
                role="alert"
                className="mb-3 rounded-md border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/40 dark:text-rose-200"
              >
                {api.loadError}
              </p>
            ) : null}

            {api.loading && providers.length === 0 ? (
              <p className="text-sm text-fg-subtle">Cargando proveedores…</p>
            ) : (
              <div className="grid gap-4 md:grid-cols-[16rem_1fr]">
                <ProviderList
                  providers={providers}
                  configs={api.configs}
                  activeKind={api.activeKind}
                  selectedKind={api.selectedKind}
                  onSelect={api.selectKind}
                  onStartNew={api.startNew}
                />
                <ProviderForm api={api} />
              </div>
            )}

            <Toast message={api.toast} />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">{t("theme.sectionTitle")}</h2>
            <ThemeSection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">{t("language.sectionTitle")}</h2>
            <LanguageSection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">Conectores</h2>
            <p className="mb-3 text-xs text-fg-subtle">
              Casi siempre tu mánager te guiará para conectar Gmail, Outlook o Google Drive
              desde el chat. Esta zona es para inspeccionar o quitar manualmente conexiones.
            </p>
            <ConnectorsSection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">Memoria del agente</h2>
            <MemorySection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">Habilidades del agente</h2>
            <SkillsSection />
          </Card>

          <Card>
            <h2 className="mb-1 text-base font-semibold">Mantenimiento</h2>
            <MaintenanceSection />
          </Card>
        </main>
      </div>
    </ProtectedPage>
  );
}

function Toast({ message }: { message: string | null }) {
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    if (!message) return;
    setVisible(true);
    const id = window.setTimeout(() => setVisible(false), 2400);
    return () => window.clearTimeout(id);
  }, [message]);
  if (!message || !visible) return null;
  return (
    <div className="pointer-events-none fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-full bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-lg">
      {message}
    </div>
  );
}
