"use client";

import { useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useTranslation } from "@/lib/i18n";

/**
 * Two-step confirmation before bulk-deleting archived threads (matches product
 * expectation of a deliberate, non-accidental destructive action).
 */
export function DeleteAllArchivedDialog({
  open,
  onOpenChange,
  onConfirm,
  pending
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => Promise<void>;
  pending: boolean;
}) {
  const { t } = useTranslation();
  const [step, setStep] = useState<1 | 2>(1);

  useEffect(() => {
    if (open) setStep(1);
  }, [open]);

  return (
    <>
      <ConfirmDialog
        open={open && step === 1}
        title={t("chat.archive.deleteAllStep1Title")}
        description={t("chat.archive.deleteAllStep1Description")}
        confirmLabel={t("chat.archive.deleteAllContinue")}
        confirmTone="primary"
        cancelLabel={t("common.cancel")}
        pending={false}
        onConfirm={() => setStep(2)}
        onCancel={() => onOpenChange(false)}
      />
      <ConfirmDialog
        open={open && step === 2}
        title={t("chat.archive.deleteAllStep2Title")}
        description={t("chat.archive.deleteAllStep2Description")}
        confirmLabel={t("chat.archive.deleteAllFinalConfirm")}
        cancelLabel={t("common.cancel")}
        pending={pending}
        onConfirm={() => {
          void onConfirm();
        }}
        onCancel={() => onOpenChange(false)}
      />
    </>
  );
}
