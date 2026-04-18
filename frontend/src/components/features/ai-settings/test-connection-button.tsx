"use client";

import { Button } from "@/components/ui/button";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { TestConnectionResult } from "@/types/api";

type TestConnectionButtonProps = {
  onTest: () => void;
  pending: boolean;
  result: TestConnectionResult | null;
  disabled?: boolean;
};

export function TestConnectionButton({ onTest, pending, result, disabled }: TestConnectionButtonProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Button
        type="button"
        onClick={onTest}
        disabled={disabled || pending}
        className={cn(
          "bg-slate-900 text-white hover:bg-slate-800",
          (disabled || pending) && "cursor-not-allowed opacity-60 hover:bg-slate-900"
        )}
      >
        {pending ? (
          <span className="inline-flex items-center gap-2">
            <Spinner /> {t("settings.test.testing")}
          </span>
        ) : result?.ok ? (
          t("settings.test.again")
        ) : (
          t("settings.test.button")
        )}
      </Button>
      {result ? <StatusBadge result={result} /> : null}
    </div>
  );
}

function StatusBadge({ result }: { result: TestConnectionResult }) {
  const { t } = useTranslation();
  if (result.ok) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-green-200 bg-green-50 px-2.5 py-1 text-xs font-medium text-green-800">
        <CheckIcon /> {result.message}
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-start gap-1.5 rounded-md border border-red-200 bg-red-50 px-2.5 py-1 text-xs font-medium text-red-800"
      role="status"
    >
      <AlertIcon />
      <span>
        <span className="font-semibold">{t(humanCodeKey(result.code))}:</span> {result.message}
        {result.detail ? <span className="ml-1 text-red-600/70">({result.detail})</span> : null}
      </span>
    </span>
  );
}

function humanCodeKey(code: string | null | undefined): TranslationKey {
  switch (code) {
    case "invalid_api_key":
      return "settings.test.code.invalid_api_key";
    case "unauthorized":
      return "settings.test.code.unauthorized";
    case "not_found":
      return "settings.test.code.not_found";
    case "network":
      return "settings.test.code.network";
    case "timeout":
      return "settings.test.code.timeout";
    case "missing_field":
      return "settings.test.code.missing_field";
    case "bad_response":
      return "settings.test.code.bad_response";
    default:
      return "settings.test.code.unknown";
  }
}

function Spinner() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true" className="animate-spin">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25" fill="none" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 6.5L5 9L9.5 3.5" stroke="currentColor" strokeWidth="1.75" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function AlertIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className="mt-[1px]">
      <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.25" fill="none" />
      <path d="M6 3.5V6.5M6 8.25V8.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}
