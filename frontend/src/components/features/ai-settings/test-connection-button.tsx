"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { TestConnectionResult } from "@/types/api";

type TestConnectionButtonProps = {
  onTest: () => void;
  pending: boolean;
  result: TestConnectionResult | null;
  disabled?: boolean;
};

export function TestConnectionButton({ onTest, pending, result, disabled }: TestConnectionButtonProps) {
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
            <Spinner /> Testing...
          </span>
        ) : result?.ok ? (
          "Test again"
        ) : (
          "Test connection"
        )}
      </Button>
      {result ? <StatusBadge result={result} /> : null}
    </div>
  );
}

function StatusBadge({ result }: { result: TestConnectionResult }) {
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
        <span className="font-semibold">{humanCode(result.code)}:</span> {result.message}
        {result.detail ? <span className="ml-1 text-red-600/70">({result.detail})</span> : null}
      </span>
    </span>
  );
}

function humanCode(code: string | null | undefined): string {
  switch (code) {
    case "invalid_api_key":
      return "Invalid API key";
    case "unauthorized":
      return "Unauthorized";
    case "not_found":
      return "Not found";
    case "network":
      return "Network error";
    case "timeout":
      return "Timed out";
    case "missing_field":
      return "Missing field";
    case "bad_response":
      return "Bad response";
    default:
      return "Failed";
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
