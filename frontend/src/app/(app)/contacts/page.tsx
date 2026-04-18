"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import { AlertBanner } from "@/components/ui/alert-banner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { apiFetch } from "@/lib/api";
import { useAsyncAction } from "@/lib/useAsyncAction";
import { isNonEmpty, isValidEmail } from "@/lib/validation";
import { Contact } from "@/types/api";

type Banner = { variant: "error" | "success" | "info"; message: string };

function validateContactFields(name: string, email: string) {
  const errs: { name?: string; email?: string } = {};
  if (!isNonEmpty(name)) errs.name = "Name is required";
  if (email.trim() && !isValidEmail(email)) errs.email = "Enter a valid email or leave blank";
  return errs;
}

export default function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [createErrors, setCreateErrors] = useState<{ name?: string; email?: string }>({});
  const [banner, setBanner] = useState<Banner | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editName, setEditName] = useState("");
  const [editEmail, setEditEmail] = useState("");
  const [editErrors, setEditErrors] = useState<{ name?: string; email?: string }>({});

  const [deleteTarget, setDeleteTarget] = useState<Contact | null>(null);

  const asyncAction = useAsyncAction();

  const load = useCallback(async () => {
    setListLoading(true);
    try {
      const data = await apiFetch<Contact[]>("/contacts");
      setContacts(data);
    } catch (e) {
      setBanner({
        variant: "error",
        message: e instanceof Error ? e.message : "Could not load contacts"
      });
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const createContact = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBanner(null);
    const errs = validateContactFields(name, email);
    setCreateErrors(errs);
    if (Object.keys(errs).length) return;

    const result = await asyncAction.run(() =>
      apiFetch<Contact>("/contacts", {
        method: "POST",
        body: JSON.stringify({ name: name.trim(), email: email.trim() || null })
      })
    );
    if (result) {
      setName("");
      setEmail("");
      setCreateErrors({});
      setBanner({ variant: "success", message: "Contact created" });
      await load();
    }
  };

  const startEdit = (c: Contact) => {
    setEditErrors({});
    setEditingId(c.id);
    setEditName(c.name);
    setEditEmail(c.email ?? "");
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditErrors({});
  };

  const saveEdit = async () => {
    if (editingId === null) return;
    const errs = validateContactFields(editName, editEmail);
    setEditErrors(errs);
    if (Object.keys(errs).length) return;

    const result = await asyncAction.run(() =>
      apiFetch<Contact>(`/contacts/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify({ name: editName.trim(), email: editEmail.trim() || null })
      })
    );
    if (result) {
      setEditingId(null);
      setBanner({ variant: "success", message: "Contact updated" });
      await load();
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    const result = await asyncAction.run(() => apiFetch(`/contacts/${id}`, { method: "DELETE" }));
    if (result !== undefined) {
      setDeleteTarget(null);
      setBanner({ variant: "success", message: "Contact deleted" });
      if (editingId === id) setEditingId(null);
      await load();
    }
  };

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-4 text-2xl font-semibold">Contacts</h1>

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
        <form className="flex flex-col gap-2 md:flex-row md:items-start" onSubmit={createContact}>
          <div className="min-w-0 flex-1">
            <Input placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} aria-invalid={Boolean(createErrors.name)} />
            {createErrors.name ? <p className="mt-1 text-xs text-red-600">{createErrors.name}</p> : null}
          </div>
          <div className="min-w-0 flex-1">
            <Input placeholder="Email (optional)" value={email} onChange={(e) => setEmail(e.target.value)} aria-invalid={Boolean(createErrors.email)} />
            {createErrors.email ? <p className="mt-1 text-xs text-red-600">{createErrors.email}</p> : null}
          </div>
          <Button type="submit" disabled={asyncAction.pending}>
            Create
          </Button>
        </form>
      </Card>

      <Card>
        <Table>
          <THead>
            <TR>
              <TH>Name</TH>
              <TH>Email</TH>
              <TH>Role</TH>
              <TH className="w-[200px]">Actions</TH>
            </TR>
          </THead>
          <TBody>
            {listLoading ? (
              <TR>
                <TD colSpan={4} className="text-slate-500">
                  Loading…
                </TD>
              </TR>
            ) : contacts.length === 0 ? (
              <TR>
                <TD colSpan={4} className="text-slate-600">
                  No contacts yet. Add one above.
                </TD>
              </TR>
            ) : (
              contacts.map((contact) => (
                <TR key={contact.id}>
                  {editingId === contact.id ? (
                    <>
                      <TD>
                        <Input value={editName} onChange={(e) => setEditName(e.target.value)} aria-invalid={Boolean(editErrors.name)} />
                        {editErrors.name ? <p className="mt-1 text-xs text-red-600">{editErrors.name}</p> : null}
                      </TD>
                      <TD>
                        <Input value={editEmail} onChange={(e) => setEditEmail(e.target.value)} aria-invalid={Boolean(editErrors.email)} />
                        {editErrors.email ? <p className="mt-1 text-xs text-red-600">{editErrors.email}</p> : null}
                      </TD>
                      <TD>{contact.role}</TD>
                      <TD>
                        <div className="flex flex-wrap gap-1">
                          <Button type="button" className="text-xs" onClick={() => void saveEdit()} disabled={asyncAction.pending}>
                            Save
                          </Button>
                          <Button type="button" className="text-xs border-dashed" onClick={cancelEdit} disabled={asyncAction.pending}>
                            Cancel
                          </Button>
                        </div>
                      </TD>
                    </>
                  ) : (
                    <>
                      <TD>{contact.name}</TD>
                      <TD>{contact.email || "-"}</TD>
                      <TD>{contact.role}</TD>
                      <TD>
                        <div className="flex flex-wrap gap-1">
                          <Button type="button" className="text-xs" onClick={() => startEdit(contact)}>
                            Edit
                          </Button>
                          <Button type="button" className="text-xs text-red-700" onClick={() => setDeleteTarget(contact)}>
                            Delete
                          </Button>
                        </div>
                      </TD>
                    </>
                  )}
                </TR>
              ))
            )}
          </TBody>
        </Table>
      </Card>

      <ConfirmDialog
        open={deleteTarget !== null}
        title="Delete contact?"
        description={deleteTarget ? `Remove “${deleteTarget.name}” permanently?` : undefined}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        pending={asyncAction.pending}
      />
    </div>
  );
}
