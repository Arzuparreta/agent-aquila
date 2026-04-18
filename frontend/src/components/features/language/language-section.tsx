"use client";

import { Card } from "@/components/ui/card";
import { SUPPORTED_LOCALES, useTranslation, type Locale, type TranslationKey } from "@/lib/i18n";

const OPTIONS: { value: Locale; labelKey: TranslationKey }[] = [
  { value: "en", labelKey: "language.option.en" },
  { value: "es", labelKey: "language.option.es" }
];

/**
 * Top-of-settings section that lets the user switch the UI language.
 * Persists to localStorage and updates `<html lang>` via LanguageProvider.
 */
export function LanguageSection() {
  const { t, locale, setLocale } = useTranslation();

  return (
    <Card className="mb-4 p-5">
      <h2 className="text-lg font-semibold text-slate-900">{t("language.sectionTitle")}</h2>
      <p className="mt-1 text-sm text-slate-600">{t("language.intro")}</p>

      <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <label htmlFor="language-select" className="text-sm font-medium text-slate-800 sm:min-w-[160px]">
          {t("language.label")}
        </label>
        <select
          id="language-select"
          className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 text-sm sm:w-auto"
          value={locale}
          onChange={(event) => setLocale(event.target.value as Locale)}
        >
          {OPTIONS.filter((opt) => SUPPORTED_LOCALES.includes(opt.value)).map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
      </div>
    </Card>
  );
}
