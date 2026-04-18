"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
import { useTranslation, type TranslationKey } from "@/lib/i18n";
import { useAsyncAction } from "@/lib/useAsyncAction";
import { isNonEmpty } from "@/lib/validation";
import { Contact, Deal } from "@/types/api";

type Banner = { variant: "error" | "success" | "info"; message: string };

export default function DealsPage() {
  const { t } = useTranslation();
  const [deals, setDeals] = useState<Deal[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [contactId, setContactId] = useState("");
  const [title, setTitle] = useState("");
  const [createErrors, setCreateErrors] = useState<{ contactId?: TranslationKey; title?: TranslationKey }>({});
  const [banner, setBanner] = useState<Banner | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [editStatus, setEditStatus] = useState("");
  const [editErrors, setEditErrors] = useState<{ title?: TranslationKey }>({});

  const [deleteTarget, setDeleteTarget] = useState<Deal | null>(null);

  const asyncAction = useAsyncAction();

  const load = useCallback(async () => {
    setListLoading(true);
    try {
      const [dealsData, contactsData] = await Promise.all([
        apiFetch<Deal[]>("/deals"),
        apiFetch<Contact[]>("/contacts")
      ]);
      setDeals(dealsData);
      setContacts(contactsData);
    } catch (e) {
      setBanner({
        variant: "error",
        message: e instanceof Error ? e.message : t("deals.errors.loadFailed")
      });
    } finally {
      setListLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const createDeal = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBanner(null);
    const errs: { contactId?: TranslationKey; title?: TranslationKey } = {};
    if (!contactId) errs.contactId = "deals.errors.contactRequired";
    if (!isNonEmpty(title)) errs.title = "deals.errors.titleRequired";
    setCreateErrors(errs);
    if (Object.keys(errs).length) return;

    const result = await asyncAction.run(() =>
      apiFetch<Deal>("/deals", {
        method: "POST",
        body: JSON.stringify({
          contact_id: Number(contactId),
          title: title.trim()
        })
      })
    );
    if (result) {
      setContactId("");
      setTitle("");
      setCreateErrors({});
      setBanner({ variant: "success", message: t("deals.created") });
      await load();
    }
  };

  const startEdit = (d: Deal) => {
    setEditErrors({});
    setEditingId(d.id);
    setEditTitle(d.title);
    setEditStatus(d.status);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditErrors({});
  };

  const saveEdit = async () => {
    if (editingId === null) return;
    const errs: { title?: TranslationKey } = {};
    if (!isNonEmpty(editTitle)) errs.title = "deals.errors.titleRequired";
    setEditErrors(errs);
    if (Object.keys(errs).length) return;

    const result = await asyncAction.run(() =>
      apiFetch<Deal>(`/deals/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify({ title: editTitle.trim(), status: editStatus.trim() || undefined })
      })
    );
    if (result) {
      setEditingId(null);
      setBanner({ variant: "success", message: t("deals.updated") });
      await load();
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    const result = await asyncAction.run(() => apiFetch(`/deals/${id}`, { method: "DELETE" }));
    if (result !== undefined) {
      setDeleteTarget(null);
      setBanner({ variant: "success", message: t("deals.deleted") });
      if (editingId === id) setEditingId(null);
      await load();
    }
  };

  const noContacts = contacts.length === 0;

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-4 text-2xl font-semibold">{t("deals.title")}</h1>

      {banner ? (
        <div className="mb-4">
          <AlertBanner variant={banner.variant} message={banner.message} onDismiss={() => setBanner(null)} />
        </div>
      ) : null}
      {asyncAction.error ? (
        <div className="mb-4">
          <AlertBanner variant="error" message={asyncAction.error} onDismiss={asyncAction.reset} />
        </div>
      ) : null}

      <Card className="mb-4">
        <form className="flex flex-col gap-2 md:flex-row md:items-start" onSubmit={createDeal}>
          <div className="min-w-0 flex-1">
            <Select
              value={contactId}
              onChange={(e) => setContactId(e.target.value)}
              disabled={noContacts}
              aria-invalid={Boolean(createErrors.contactId)}
            >
              <option value="">{noContacts ? t("deals.noContactsOption") : t("deals.selectContact")}</option>
              {contacts.map((c) => (
                <option key={c.id} value={String(c.id)}>
                  {c.name} {c.email ? `(${c.email})` : ""}
                </option>
              ))}
            </Select>
            {createErrors.contactId ? <p className="mt-1 text-xs text-red-600">{t(createErrors.contactId)}</p> : null}
            {noContacts ? (
              <p className="mt-1 text-sm text-slate-600">
                <Link href="/contacts" className="text-slate-900 underline">
                  {t("deals.createContactCta")}
                </Link>{" "}
                {t("deals.beforeAdding")}
              </p>
            ) : null}
          </div>
          <div className="min-w-0 flex-1">
            <Input placeholder={t("deals.dealTitlePlaceholder")} value={title} onChange={(e) => setTitle(e.target.value)} aria-invalid={Boolean(createErrors.title)} />
            {createErrors.title ? <p className="mt-1 text-xs text-red-600">{t(createErrors.title)}</p> : null}
          </div>
          <Button type="submit" disabled={asyncAction.pending || noContacts}>
            {t("common.create")}
          </Button>
        </form>
      </Card>

      <Card>
        <Table>
          <THead>
            <TR>
              <TH>{t("deals.colTitle")}</TH>
              <TH>{t("deals.colStatus")}</TH>
              <TH>{t("deals.colContact")}</TH>
              <TH className="w-[200px]">{t("common.actions")}</TH>
            </TR>
          </THead>
          <TBody>
            {listLoading ? (
              <TR>
                <TD colSpan={4} className="text-slate-500">
                  {t("common.loading")}
                </TD>
              </TR>
            ) : deals.length === 0 ? (
              <TR>
                <TD colSpan={4} className="text-slate-600">
                  {t("deals.empty")}
                </TD>
              </TR>
            ) : (
              deals.map((deal) => {
                const contact = contacts.find((c) => c.id === deal.contact_id);
                return (
                  <TR key={deal.id}>
                    {editingId === deal.id ? (
                      <>
                        <TD>
                          <Input value={editTitle} onChange={(e) => setEditTitle(e.target.value)} aria-invalid={Boolean(editErrors.title)} />
                          {editErrors.title ? <p className="mt-1 text-xs text-red-600">{t(editErrors.title)}</p> : null}
                        </TD>
                        <TD>
                          <Input value={editStatus} onChange={(e) => setEditStatus(e.target.value)} placeholder={t("deals.statusPlaceholder")} />
                        </TD>
                        <TD>{contact ? contact.name : deal.contact_id}</TD>
                        <TD>
                          <div className="flex flex-wrap gap-1">
                            <Button type="button" className="text-xs" onClick={() => void saveEdit()} disabled={asyncAction.pending}>
                              {t("common.save")}
                            </Button>
                            <Button type="button" className="text-xs border-dashed" onClick={cancelEdit} disabled={asyncAction.pending}>
                              {t("common.cancel")}
                            </Button>
                          </div>
                        </TD>
                      </>
                    ) : (
                      <>
                        <TD>{deal.title}</TD>
                        <TD>{deal.status}</TD>
                        <TD>{contact ? `${contact.name} (#${deal.contact_id})` : `#${deal.contact_id}`}</TD>
                        <TD>
                          <div className="flex flex-wrap gap-1">
                            <Button type="button" className="text-xs" onClick={() => startEdit(deal)}>
                              {t("common.edit")}
                            </Button>
                            <Button type="button" className="text-xs text-red-700" onClick={() => setDeleteTarget(deal)}>
                              {t("common.delete")}
                            </Button>
                          </div>
                        </TD>
                      </>
                    )}
                  </TR>
                );
              })
            )}
          </TBody>
        </Table>
      </Card>

      <ConfirmDialog
        open={deleteTarget !== null}
        title={t("deals.deleteTitle")}
        description={deleteTarget ? t("deals.deleteDescription", { title: deleteTarget.title }) : undefined}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        pending={asyncAction.pending}
      />
    </div>
  );
}
