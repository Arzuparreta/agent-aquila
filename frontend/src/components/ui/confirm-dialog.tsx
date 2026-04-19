"use client";

import { Button } from "@/components/ui/button";
import { useTranslation } from "@/lib/i18n";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  pending?: boolean;
};

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onCancel,
  pending = false
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  if (!open) return null;

  const resolvedConfirm = confirmLabel ?? t("confirm.defaultConfirm");
  const resolvedCancel = cancelLabel ?? t("confirm.defaultCancel");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-scrim"
        aria-label={t("confirm.closeAria")}
        onClick={onCancel}
        disabled={pending}
      />
      <div className="relative z-10 w-full max-w-md rounded-lg border border-border bg-surface-elevated p-4 text-fg shadow-lg">
        <h2 className="text-lg font-semibold">{title}</h2>
        {description ? <p className="mt-2 text-sm text-fg-muted">{description}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" className="border-dashed" onClick={onCancel} disabled={pending}>
            {resolvedCancel}
          </Button>
          <Button type="button" className="bg-red-600 text-white hover:bg-red-700" onClick={onConfirm} disabled={pending}>
            {pending ? t("common.ellipsis") : resolvedConfirm}
          </Button>
        </div>
      </div>
    </div>
  );
}
