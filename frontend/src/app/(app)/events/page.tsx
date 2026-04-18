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
import { useAsyncAction } from "@/lib/useAsyncAction";
import { isNonEmpty, isValidISODate } from "@/lib/validation";
import { CalendarEvent, Deal } from "@/types/api";

type Banner = { variant: "error" | "success" | "info"; message: string };

export default function EventsPage() {
  const [events, setEvents] = useState<CalendarEvent[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [venue, setVenue] = useState("");
  const [eventDate, setEventDate] = useState("");
  const [city, setCity] = useState("");
  const [dealId, setDealId] = useState("");
  const [createErrors, setCreateErrors] = useState<{ venue?: string; eventDate?: string }>({});
  const [banner, setBanner] = useState<Banner | null>(null);

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editVenue, setEditVenue] = useState("");
  const [editEventDate, setEditEventDate] = useState("");
  const [editCity, setEditCity] = useState("");
  const [editDealId, setEditDealId] = useState("");
  const [editStatus, setEditStatus] = useState("");
  const [editErrors, setEditErrors] = useState<{ venue?: string; eventDate?: string }>({});

  const [deleteTarget, setDeleteTarget] = useState<CalendarEvent | null>(null);

  const asyncAction = useAsyncAction();

  const load = useCallback(async () => {
    setListLoading(true);
    try {
      const [ev, dls] = await Promise.all([apiFetch<CalendarEvent[]>("/events"), apiFetch<Deal[]>("/deals")]);
      setEvents(ev);
      setDeals(dls);
    } catch (e) {
      setBanner({
        variant: "error",
        message: e instanceof Error ? e.message : "Could not load data"
      });
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const validateEventFields = (venueVal: string, dateVal: string) => {
    const errs: { venue?: string; eventDate?: string } = {};
    if (!isNonEmpty(venueVal)) errs.venue = "Venue is required";
    if (!dateVal.trim()) errs.eventDate = "Date is required";
    else if (!isValidISODate(dateVal)) errs.eventDate = "Use a valid date";
    return errs;
  };

  const createEvent = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBanner(null);
    const errs = validateEventFields(venue, eventDate);
    setCreateErrors(errs);
    if (Object.keys(errs).length) return;

    const result = await asyncAction.run(() =>
      apiFetch<CalendarEvent>("/events", {
        method: "POST",
        body: JSON.stringify({
          venue_name: venue.trim(),
          event_date: eventDate.trim(),
          city: city.trim() || null,
          deal_id: dealId ? Number(dealId) : null
        })
      })
    );
    if (result) {
      setVenue("");
      setEventDate("");
      setCity("");
      setDealId("");
      setCreateErrors({});
      setBanner({ variant: "success", message: "Event created" });
      await load();
    }
  };

  const startEdit = (ev: CalendarEvent) => {
    setEditErrors({});
    setEditingId(ev.id);
    setEditVenue(ev.venue_name);
    setEditEventDate(ev.event_date.slice(0, 10));
    setEditCity(ev.city ?? "");
    setEditDealId(ev.deal_id != null ? String(ev.deal_id) : "");
    setEditStatus(ev.status);
  };

  const cancelEdit = () => {
    setEditingId(null);
    setEditErrors({});
  };

  const saveEdit = async () => {
    if (editingId === null) return;
    const errs = validateEventFields(editVenue, editEventDate);
    setEditErrors(errs);
    if (Object.keys(errs).length) return;

    const result = await asyncAction.run(() =>
      apiFetch<CalendarEvent>(`/events/${editingId}`, {
        method: "PATCH",
        body: JSON.stringify({
          venue_name: editVenue.trim(),
          event_date: editEventDate.trim(),
          city: editCity.trim() || null,
          deal_id: editDealId ? Number(editDealId) : null,
          status: editStatus.trim() || undefined
        })
      })
    );
    if (result) {
      setEditingId(null);
      setBanner({ variant: "success", message: "Event updated" });
      await load();
    }
  };

  const confirmDelete = async () => {
    if (!deleteTarget) return;
    const id = deleteTarget.id;
    const result = await asyncAction.run(() => apiFetch(`/events/${id}`, { method: "DELETE" }));
    if (result !== undefined) {
      setDeleteTarget(null);
      setBanner({ variant: "success", message: "Event deleted" });
      if (editingId === id) setEditingId(null);
      await load();
    }
  };

  const noDeals = deals.length === 0;

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-4 text-2xl font-semibold">Events</h1>

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
        <form className="grid gap-2 md:grid-cols-2" onSubmit={createEvent}>
          <div>
            <Input placeholder="Venue name" value={venue} onChange={(e) => setVenue(e.target.value)} aria-invalid={Boolean(createErrors.venue)} />
            {createErrors.venue ? <p className="mt-1 text-xs text-red-600">{createErrors.venue}</p> : null}
          </div>
          <div>
            <Input type="date" value={eventDate} onChange={(e) => setEventDate(e.target.value)} aria-invalid={Boolean(createErrors.eventDate)} />
            {createErrors.eventDate ? <p className="mt-1 text-xs text-red-600">{createErrors.eventDate}</p> : null}
          </div>
          <Input placeholder="City (optional)" value={city} onChange={(e) => setCity(e.target.value)} />
          <div>
            <Select value={dealId} onChange={(e) => setDealId(e.target.value)}>
              <option value="">— No deal —</option>
              {deals.map((d) => (
                <option key={d.id} value={String(d.id)}>
                  {d.title} (#{d.id})
                </option>
              ))}
            </Select>
            {noDeals ? (
              <p className="mt-1 text-sm text-slate-600">
                No deals yet.{" "}
                <Link href="/deals" className="text-slate-900 underline">
                  Create a deal
                </Link>{" "}
                to link an event.
              </p>
            ) : null}
          </div>
          <Button className="md:col-span-2" type="submit" disabled={asyncAction.pending}>
            Create event
          </Button>
        </form>
      </Card>

      <Card>
        <Table>
          <THead>
            <TR>
              <TH>Venue</TH>
              <TH>Date</TH>
              <TH>City</TH>
              <TH>Deal</TH>
              <TH>Status</TH>
              <TH className="w-[220px]">Actions</TH>
            </TR>
          </THead>
          <TBody>
            {listLoading ? (
              <TR>
                <TD colSpan={6} className="text-slate-500">
                  Loading…
                </TD>
              </TR>
            ) : events.length === 0 ? (
              <TR>
                <TD colSpan={6} className="text-slate-600">
                  No events yet. Create one above.
                </TD>
              </TR>
            ) : (
              events.map((ev) => {
                const deal = ev.deal_id != null ? deals.find((d) => d.id === ev.deal_id) : null;
                return (
                  <TR key={ev.id}>
                    {editingId === ev.id ? (
                      <>
                        <TD>
                          <Input value={editVenue} onChange={(e) => setEditVenue(e.target.value)} aria-invalid={Boolean(editErrors.venue)} />
                          {editErrors.venue ? <p className="mt-1 text-xs text-red-600">{editErrors.venue}</p> : null}
                        </TD>
                        <TD>
                          <Input type="date" value={editEventDate} onChange={(e) => setEditEventDate(e.target.value)} aria-invalid={Boolean(editErrors.eventDate)} />
                          {editErrors.eventDate ? <p className="mt-1 text-xs text-red-600">{editErrors.eventDate}</p> : null}
                        </TD>
                        <TD>
                          <Input value={editCity} onChange={(e) => setEditCity(e.target.value)} placeholder="City" />
                        </TD>
                        <TD>
                          <Select value={editDealId} onChange={(e) => setEditDealId(e.target.value)}>
                            <option value="">— No deal —</option>
                            {deals.map((d) => (
                              <option key={d.id} value={String(d.id)}>
                                {d.title}
                              </option>
                            ))}
                          </Select>
                        </TD>
                        <TD>
                          <Input value={editStatus} onChange={(e) => setEditStatus(e.target.value)} placeholder="Status" />
                        </TD>
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
                        <TD>{ev.venue_name}</TD>
                        <TD>{ev.event_date}</TD>
                        <TD>{ev.city || "-"}</TD>
                        <TD>{deal ? `${deal.title} (#${ev.deal_id})` : ev.deal_id ?? "-"}</TD>
                        <TD>{ev.status}</TD>
                        <TD>
                          <div className="flex flex-wrap gap-1">
                            <Button type="button" className="text-xs" onClick={() => startEdit(ev)}>
                              Edit
                            </Button>
                            <Button type="button" className="text-xs text-red-700" onClick={() => setDeleteTarget(ev)}>
                              Delete
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
        title="Delete event?"
        description={deleteTarget ? `Remove “${deleteTarget.venue_name}” on ${deleteTarget.event_date}?` : undefined}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => void confirmDelete()}
        pending={asyncAction.pending}
      />
    </div>
  );
}
