import { DEFAULT_THEME, type ThemeId } from "./types";

/** Keep in sync with the inline script in app/layout.tsx */
export const THEME_STORAGE_KEY = "manager-theme";

const KNOWN: readonly ThemeId[] = ["dark", "light"];

export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && (KNOWN as readonly string[]).includes(value);
}

export function parseTheme(raw: string | null): ThemeId {
  return isThemeId(raw) ? raw : DEFAULT_THEME;
}
