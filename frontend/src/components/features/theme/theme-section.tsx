"use client";

import { useTranslation } from "@/lib/i18n";
import { THEMES, useTheme, type ThemeId } from "@/lib/theme";

/**
 * Settings body: switch app theme (persisted via ThemeProvider / localStorage).
 */
export function ThemeSection() {
  const { t } = useTranslation();
  const { theme, setTheme } = useTheme();

  return (
    <>
      <p className="mt-1 text-sm text-fg-muted">{t("theme.intro")}</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <label htmlFor="theme-select" className="text-sm font-medium text-fg sm:min-w-[160px]">
          {t("theme.label")}
        </label>
        <select
          id="theme-select"
          className="w-full rounded-md border border-border bg-surface-inset px-3 py-2 text-sm text-fg sm:w-auto"
          value={theme}
          onChange={(event) => setTheme(event.target.value as ThemeId)}
        >
          {THEMES.map((opt) => (
            <option key={opt.id} value={opt.id}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
      </div>
    </>
  );
}
