/** Trim and check non-empty string. */
export function isNonEmpty(s: string): boolean {
  return s.trim().length > 0;
}

/** Basic email shape check (HTML5 email is similar; backend uses EmailStr). */
export function isValidEmail(s: string): boolean {
  const t = s.trim();
  if (!t) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(t);
}

/** `YYYY-MM-DD` from `<input type="date" />` or equivalent. */
export function isValidISODate(s: string): boolean {
  const t = s.trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t)) return false;
  const d = new Date(`${t}T12:00:00`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === t;
}

export function toNumberOrNull(s: string): number | null {
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}
