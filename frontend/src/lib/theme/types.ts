import type { TranslationKey } from "@/lib/i18n";

/** Extend this union and add a [data-theme] block in globals.css to add skins. */
export type ThemeId = "dark" | "light";

export const DEFAULT_THEME: ThemeId = "dark";

export type ThemeDefinition = {
  id: ThemeId;
  labelKey: TranslationKey;
};

export const THEMES: readonly ThemeDefinition[] = [
  { id: "dark", labelKey: "theme.option.dark" },
  { id: "light", labelKey: "theme.option.light" }
] as const;
