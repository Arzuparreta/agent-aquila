"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import { useAsyncAction } from "@/lib/useAsyncAction";
import { isNonEmpty, isValidEmail } from "@/lib/validation";
import { Email, EmailDraftResponse } from "@/types/api";

type Banner = { variant: "error" | "success" | "info"; message: string };
type FormErrors = { senderEmail?: TranslationKey; subject?: TranslationKey; body?: TranslationKey };

export default function EmailsPage() {
  const { t } = useTranslation();
  const [emails, setEmails] = useState<Email[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [senderEmail, setSenderEmail] = useState("");
  const [senderName, setSenderName] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [formErrors, setFormErrors] = useState<FormErrors>({});
  const [banner, setBanner] = useState<Banner | null>(null);

  const [draftFor, setDraftFor] = useState<number | null>(null);
  const [draftText, setDraftText] = useState<string | null>(null);

  const asyncAction = useAsyncAction();

  const load = useCallback(async () => {
    setListLoading(true);
    try {
      const data = await apiFetch<Email[]>("/emails");
      setEmails(data);
    } catch (e) {
      setBanner({
        variant: "error",
        message: e instanceof Error ? e.message : t("emails.errors.loadFailed")
      });
    } finally {
      setListLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const validateIngest = (): FormErrors => {
    const errs: FormErrors = {};
    if (!isValidEmail(senderEmail)) errs.senderEmail = "emails.errors.invalidSender";
    if (!isNonEmpty(subject)) errs.subject = "emails.errors.subjectRequired";
    if (!isNonEmpty(body)) errs.body = "emails.errors.bodyRequired";
    return errs;
  };

  const createEmail = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBanner(null);
    const errs = validateIngest();
    setFormErrors(errs);
    if (Object.keys(errs).length) return;

    const result = await asyncAction.run(() =>
      apiFetch<Email>("/emails", {
        method: "POST",
        body: JSON.stringify({
          sender_email: senderEmail.trim(),
          sender_name: senderName.trim() || null,
          subject: subject.trim(),
          body: body.trim()
        })
      })
    );
    if (result) {
      setSenderEmail("");
      setSenderName("");
      setSubject("");
      setBody("");
      setFormErrors({});
      setBanner({ variant: "success", message: t("emails.ingested") });
      await load();
    }
  };

  const requestDraft = async (emailId: number) => {
    setDraftFor(emailId);
    setDraftText(null);
    asyncAction.reset();
    const result = await asyncAction.run(() => apiFetch<EmailDraftResponse>(`/emails/${emailId}/draft`, { method: "POST" }));
    if (result) {
      setDraftText(result.draft);
    }
  };

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-4 text-2xl font-semibold">{t("emails.title")}</h1>

      {banner ? (
        <div className="mb-4">
          <AlertBanner variant={banner.variant} message={banner.message} onDismiss={() => setBanner(null)} />
        </div>
      ) : null}
      {asyncAction.error && !draftFor ? (
        <div className="mb-4">
          <AlertBanner variant="error" message={asyncAction.error} onDismiss={asyncAction.reset} />
        </div>
      ) : null}

      <Card className="mb-4">
        <form className="grid gap-2 md:grid-cols-2" onSubmit={createEmail}>
          <div>
            <Input placeholder={t("emails.senderEmailPlaceholder")} value={senderEmail} onChange={(e) => setSenderEmail(e.target.value)} aria-invalid={Boolean(formErrors.senderEmail)} />
            {formErrors.senderEmail ? <p className="mt-1 text-xs text-red-600">{t(formErrors.senderEmail)}</p> : null}
          </div>
          <Input placeholder={t("emails.senderNamePlaceholder")} value={senderName} onChange={(e) => setSenderName(e.target.value)} />
          <div className="md:col-span-2">
            <Input placeholder={t("emails.subjectPlaceholder")} value={subject} onChange={(e) => setSubject(e.target.value)} aria-invalid={Boolean(formErrors.subject)} />
            {formErrors.subject ? <p className="mt-1 text-xs text-red-600">{t(formErrors.subject)}</p> : null}
          </div>
          <div className="md:col-span-2">
            <Input placeholder={t("emails.bodyPlaceholder")} value={body} onChange={(e) => setBody(e.target.value)} aria-invalid={Boolean(formErrors.body)} />
            {formErrors.body ? <p className="mt-1 text-xs text-red-600">{t(formErrors.body)}</p> : null}
          </div>
          <Button className="md:col-span-2" type="submit" disabled={asyncAction.pending}>
            {t("emails.ingestButton")}
          </Button>
        </form>
      </Card>

      {draftFor ? (
        <Card className="mb-4">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="font-semibold">{t("emails.draftFor", { id: draftFor })}</h2>
            <Button
              className="text-xs"
              onClick={() => {
                setDraftFor(null);
                setDraftText(null);
                asyncAction.reset();
              }}
            >
              {t("common.close")}
            </Button>
          </div>
          {asyncAction.error ? (
            <div className="mb-2">
              <AlertBanner variant="error" message={asyncAction.error} onDismiss={asyncAction.reset} />
            </div>
          ) : null}
          {draftText ? <pre className="whitespace-pre-wrap rounded bg-slate-50 p-3 text-sm">{draftText}</pre> : null}
        </Card>
      ) : null}

      <Card>
        <Table>
          <THead>
            <TR>
              <TH>{t("emails.colSender")}</TH>
              <TH>{t("emails.colSubject")}</TH>
              <TH>{t("emails.colReceived")}</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {listLoading ? (
              <TR>
                <TD colSpan={4} className="text-slate-500">
                  {t("common.loading")}
                </TD>
              </TR>
            ) : emails.length === 0 ? (
              <TR>
                <TD colSpan={4} className="text-slate-600">
                  {t("emails.empty")}
                </TD>
              </TR>
            ) : (
              emails.map((email) => (
                <TR key={email.id}>
                  <TD>{email.sender_email}</TD>
                  <TD>{email.subject}</TD>
                  <TD>{new Date(email.received_at).toLocaleString()}</TD>
                  <TD>
                    <Button className="text-xs" type="button" onClick={() => void requestDraft(email.id)} disabled={asyncAction.pending}>
                      {t("emails.draftReply")}
                    </Button>
                  </TD>
                </TR>
              ))
            )}
          </TBody>
        </Table>
      </Card>
    </div>
  );
}
