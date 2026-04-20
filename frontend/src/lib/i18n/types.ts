export type Locale = "en" | "es";

export const SUPPORTED_LOCALES: ReadonlyArray<Locale> = ["en", "es"];

export const DEFAULT_LOCALE: Locale = "es";

export const STORAGE_KEY = "ui.language";

/** BCP 47 tag for `Intl` / `toLocaleString` (matches UI locale). */
export function intlLocaleTag(locale: Locale): string {
  return locale === "en" ? "en-US" : "es-ES";
}
