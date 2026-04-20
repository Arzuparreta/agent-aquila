"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { apiFetch, ApiError } from "@/lib/api";
import { useTranslation } from "@/lib/i18n";

/**
 * Settings card body that lets the artist hard-delete the legacy auto-spawned
 * chat threads (Mozilla / LinkedIn / Correo \u00b7 X / Evento \u00b7 Y / etc.) created by the
 * old proactive layer. Only deletes threads with zero user-typed messages, so it
 * never destroys real conversations.
 */
export function MaintenanceSection() {
  const { t } = useTranslation();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onConfirm = async () => {
    setPending(true);
    setError(null);
    try {
      const res = await apiFetch<{ deleted: number }>("/maintenance/purge-proactive-threads", {
        method: "POST"
      });
      setResult(
        res.deleted === 0
          ? t("maintenance.resultNone")
          : t("maintenance.resultCount", { count: res.deleted })
      );
      setConfirmOpen(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("maintenance.errorClean"));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-fg-subtle">{t("maintenance.intro")}</p>
      <div className="flex items-center gap-3">
        <Button
          onClick={() => setConfirmOpen(true)}
          className="bg-red-600 text-white hover:bg-red-700"
          disabled={pending}
        >
          {t("maintenance.button")}
        </Button>
        {result ? <span className="text-sm text-emerald-700">{result}</span> : null}
        {error ? <span className="text-sm text-rose-600">{error}</span> : null}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        title={t("maintenance.confirmTitle")}
        description={t("maintenance.confirmDescription")}
        confirmLabel={t("common.delete")}
        cancelLabel={t("common.cancel")}
        pending={pending}
        onConfirm={onConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
