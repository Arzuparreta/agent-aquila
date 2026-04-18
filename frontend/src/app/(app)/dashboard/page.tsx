"use client";

import { useEffect, useState } from "react";

import { Card } from "@/components/ui/card";
import { apiFetch } from "@/lib/api";
import { Contact, Deal, Email } from "@/types/api";

export default function DashboardPage() {
  const [emails, setEmails] = useState<Email[]>([]);
  const [deals, setDeals] = useState<Deal[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);

  useEffect(() => {
    void Promise.all([
      apiFetch<Email[]>("/emails"),
      apiFetch<Deal[]>("/deals?active_only=true"),
      apiFetch<Contact[]>("/contacts")
    ]).then(([emailsData, dealsData, contactsData]) => {
      setEmails(emailsData.slice(0, 10));
      setDeals(dealsData);
      setContacts(contactsData);
    });
  }, []);

  return (
    <div className="mx-auto max-w-6xl">
      <h1 className="mb-4 text-2xl font-semibold">Dashboard</h1>
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <h2 className="mb-2 font-semibold">Recent Emails</h2>
          {emails.map((email) => (
            <p key={email.id} className="text-sm">
              {email.subject}
            </p>
          ))}
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Active Deals</h2>
          {deals.map((deal) => (
            <p key={deal.id} className="text-sm">
              {deal.title} ({deal.status})
            </p>
          ))}
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">Contacts ({contacts.length})</h2>
          {contacts.slice(0, 8).map((contact) => (
            <p key={contact.id} className="text-sm">
              {contact.name}
            </p>
          ))}
        </Card>
      </div>
    </div>
  );
}
