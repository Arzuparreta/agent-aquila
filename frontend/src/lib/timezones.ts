/**
 * IANA time zone ids for the settings combobox.
 * Prefers `Intl.supportedValuesOf` when available (Chromium, modern Safari).
 */
export function listIanaTimeZones(): string[] {
  try {
    const intl = Intl as unknown as {
      supportedValuesOf?: (key: string) => string[];
    };
    if (typeof intl.supportedValuesOf === "function") {
      return intl.supportedValuesOf("timeZone").slice().sort((a, b) => a.localeCompare(b));
    }
  } catch {
    /* ignore */
  }
  return [
    "UTC",
    "Europe/Madrid",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
    "America/Mexico_City",
    "America/Sao_Paulo",
    "Asia/Tokyo",
    "Asia/Shanghai",
    "Australia/Sydney"
  ];
}

export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}
