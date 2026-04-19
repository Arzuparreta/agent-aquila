"use client";

import { Button } from "@/components/ui/button";
import { useTranslation } from "@/lib/i18n";

export type AlertVariant = "error" | "success" | "info";

const styles: Record<AlertVariant, string> = {
  error: "border-red-200 bg-red-50 text-red-900",
  success: "border-green-200 bg-green-50 text-green-900",
  info: "border-border bg-surface-muted text-fg"
};

type AlertBannerProps = {
  variant: AlertVariant;
  message: string;
  onDismiss?: () => void;
};

export function AlertBanner({ variant, message, onDismiss }: AlertBannerProps) {
  const { t } = useTranslation();
  return (
    <div
      className={`flex items-start justify-between gap-3 rounded-md border px-3 py-2 text-sm ${styles[variant]}`}
      role="alert"
    >
      <span className="min-w-0 flex-1">{message}</span>
      {onDismiss ? (
        <Button
          type="button"
          className="shrink-0 border-0 bg-transparent px-2 py-0 text-xs hover:bg-interactive-hover"
          onClick={onDismiss}
        >
          {t("common.dismiss")}
        </Button>
      ) : null}
    </div>
  );
}
