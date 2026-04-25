"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Input } from "@/components/ui/input";
import { Table, TBody, TD, TH, THead, TR } from "@/components/ui/table";
import { ApiError, apiFetch } from "@/lib/api";
import type { AppUser } from "@/types/api";

type MeResponse = {
  id: number;
  email: string;
};

export function UsersSettingsSection() {
  const [users, setUsers] = useState<AppUser[]>([]);
  const [me, setMe] = useState<MeResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [deleting, setDeleting] = useState(false);

  const [newEmail, setNewEmail] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newFullName, setNewFullName] = useState("");
  const [creating, setCreating] = useState(false);

  const [oldPassword, setOldPassword] = useState("");
  const [nextPassword, setNextPassword] = useState("");
  const [changingPassword, setChangingPassword] = useState(false);

  const [resetPasswords, setResetPasswords] = useState<Record<number, string>>({});
  const [resettingUserId, setResettingUserId] = useState<number | null>(null);

  const deleteTarget = useMemo(
    () => users.find((user) => user.id === pendingDeleteId) ?? null,
    [pendingDeleteId, users],
  );

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [userList, currentUser] = await Promise.all([
        apiFetch<AppUser[]>("/users"),
        apiFetch<MeResponse>("/auth/me"),
      ]);
      setUsers(userList);
      setMe(currentUser);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  async function handleCreateUser(e: FormEvent) {
    e.preventDefault();
    setCreating(true);
    setError(null);
    setInfo(null);
    try {
      const created = await apiFetch<AppUser>("/users", {
        method: "POST",
        body: JSON.stringify({
          email: newEmail.trim(),
          password: newPassword,
          full_name: newFullName.trim() || null,
        }),
      });
      setUsers((prev) => [...prev, created].sort((a, b) => a.id - b.id));
      setNewEmail("");
      setNewPassword("");
      setNewFullName("");
      setInfo("User created");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create user");
    } finally {
      setCreating(false);
    }
  }

  async function handleToggleUserActive(user: AppUser) {
    setError(null);
    setInfo(null);
    try {
      const updated = await apiFetch<AppUser>(`/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          is_active: !user.is_active,
        }),
      });
      setUsers((prev) => prev.map((row) => (row.id === updated.id ? updated : row)));
      setInfo(updated.is_active ? "User reactivated" : "User deactivated");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not update user");
    }
  }

  async function handleDeleteUser() {
    if (!deleteTarget) return;
    setDeleting(true);
    setError(null);
    setInfo(null);
    try {
      await apiFetch<{ detail: string }>(`/users/${deleteTarget.id}`, { method: "DELETE" });
      setUsers((prev) =>
        prev.map((row) => (row.id === deleteTarget.id ? { ...row, is_active: false } : row)),
      );
      setInfo("User deactivated");
      setPendingDeleteId(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete user");
    } finally {
      setDeleting(false);
    }
  }

  async function handleResetPassword(user: AppUser) {
    const password = resetPasswords[user.id] ?? "";
    if (!password.trim()) {
      setError("Enter a temporary password first.");
      return;
    }
    setResettingUserId(user.id);
    setError(null);
    setInfo(null);
    try {
      await apiFetch<AppUser>(`/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify({ password }),
      });
      setResetPasswords((prev) => ({ ...prev, [user.id]: "" }));
      setInfo(`Password updated for ${user.email}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset password");
    } finally {
      setResettingUserId(null);
    }
  }

  async function handleChangeMyPassword(e: FormEvent) {
    e.preventDefault();
    setChangingPassword(true);
    setError(null);
    setInfo(null);
    try {
      await apiFetch<{ detail: string }>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ old_password: oldPassword, new_password: nextPassword }),
      });
      setOldPassword("");
      setNextPassword("");
      setInfo("Your password has been updated.");
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError(err instanceof Error ? err.message : "Could not change password");
      }
    } finally {
      setChangingPassword(false);
    }
  }

  return (
    <div className="space-y-5">
      {loading ? <p className="text-sm text-fg-muted">Loading users…</p> : null}
      {error ? <p className="text-sm text-red-500">{error}</p> : null}
      {info ? <p className="text-sm text-emerald-600">{info}</p> : null}

      <section className="space-y-3 rounded-md border border-border p-3">
        <h3 className="text-sm font-semibold">Create user</h3>
        <form className="grid gap-2 sm:grid-cols-3" onSubmit={handleCreateUser}>
          <Input
            placeholder="Email"
            type="email"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            required
          />
          <Input
            placeholder="Temporary password"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
          />
          <Input
            placeholder="Full name (optional)"
            value={newFullName}
            onChange={(e) => setNewFullName(e.target.value)}
          />
          <Button type="submit" disabled={creating} className="sm:col-span-3 sm:w-fit">
            {creating ? "Creating…" : "Create user"}
          </Button>
        </form>
      </section>

      <section className="space-y-3 rounded-md border border-border p-3">
        <h3 className="text-sm font-semibold">Manage users</h3>
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>Email</TH>
                <TH>Name</TH>
                <TH>Status</TH>
                <TH>Temporary password reset</TH>
                <TH className="text-right">Actions</TH>
              </TR>
            </THead>
            <TBody>
              {users.map((user) => {
                const isCurrent = user.id === me?.id;
                return (
                  <TR key={user.id}>
                    <TD>{user.email}</TD>
                    <TD>{user.full_name || "—"}</TD>
                    <TD>{user.is_active ? "Active" : "Inactive"}</TD>
                    <TD>
                      <div className="flex gap-2">
                        <Input
                          type="password"
                          placeholder="New temp password"
                          value={resetPasswords[user.id] ?? ""}
                          onChange={(e) =>
                            setResetPasswords((prev) => ({ ...prev, [user.id]: e.target.value }))
                          }
                        />
                        <Button
                          type="button"
                          onClick={() => void handleResetPassword(user)}
                          disabled={resettingUserId === user.id}
                        >
                          {resettingUserId === user.id ? "Saving…" : "Set"}
                        </Button>
                      </div>
                    </TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button type="button" onClick={() => void handleToggleUserActive(user)} disabled={isCurrent}>
                          {user.is_active ? "Deactivate" : "Reactivate"}
                        </Button>
                        <Button
                          type="button"
                          className="bg-red-600 text-white hover:bg-red-700"
                          disabled={isCurrent}
                          onClick={() => setPendingDeleteId(user.id)}
                        >
                          Delete
                        </Button>
                      </div>
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </div>
      </section>

      <section className="space-y-3 rounded-md border border-border p-3">
        <h3 className="text-sm font-semibold">Change my password</h3>
        <p className="text-xs text-fg-muted">
          This requires your current password. Use this to replace temporary credentials.
        </p>
        <form className="grid gap-2 sm:grid-cols-3" onSubmit={handleChangeMyPassword}>
          <Input
            type="password"
            placeholder="Current password"
            value={oldPassword}
            onChange={(e) => setOldPassword(e.target.value)}
            required
          />
          <Input
            type="password"
            placeholder="New password"
            value={nextPassword}
            onChange={(e) => setNextPassword(e.target.value)}
            required
          />
          <Button type="submit" disabled={changingPassword}>
            {changingPassword ? "Updating…" : "Update my password"}
          </Button>
        </form>
      </section>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title={deleteTarget ? `Delete ${deleteTarget.email}?` : "Delete user?"}
        description="For safety, deletion deactivates the account and revokes sessions."
        confirmLabel={deleting ? "Deleting…" : "Delete user"}
        onConfirm={() => void handleDeleteUser()}
        onCancel={() => setPendingDeleteId(null)}
        pending={deleting}
      />
    </div>
  );
}
