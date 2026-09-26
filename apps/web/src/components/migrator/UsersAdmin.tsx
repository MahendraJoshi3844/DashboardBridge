"use client";

/**
 * Users & access (administrators only).
 *
 * Who may use which migration product. Tableau, MicroStrategy and Qlik → Power
 * BI are separate products: the licence says which this deployment may run, and
 * this screen says who may use them. Administrators always have every licensed
 * product - their row shows that rather than checkboxes that would not matter.
 *
 * Every change is saved as it is made and read back from the server's answer,
 * so the screen never shows a grant the server did not keep.
 */

import { useEffect, useState, type FormEvent } from "react";

import { addUser, listUsers, toApiError, updateUser } from "@/lib/api/client";
import { PRODUCTS, defaultProducts, productBlocked, toggled } from "@/lib/admin/products";
import { useDirections } from "@/lib/hooks/useDirections";
import { useCurrentUser } from "@/lib/hooks/useSession";
import type { ApiError, UserAccount, UserList } from "@/types/contracts";

import { AppShell } from "./AppShell";

export function UsersAdmin() {
  const me = useCurrentUser();
  const probe = useDirections();
  const [list, setList] = useState<UserList | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [form, setForm] = useState({ email: "", display_name: "", password: "" });
  const [newProducts, setNewProducts] = useState<string[] | null>(null);

  useEffect(() => {
    listUsers().then(setList).catch((cause) => setError(toApiError(cause)));
  }, []);

  const chosen = newProducts ?? defaultProducts(probe);

  function replace(user: UserAccount) {
    setList((current) => current && { ...current, users: (current.users ?? []).map((u) => (u.user_id === user.user_id ? user : u)) });
  }

  async function change(user: UserAccount, patch: Parameters<typeof updateUser>[1]) {
    setError(null);
    setSaving(user.user_id);
    try {
      replace(await updateUser(user.user_id, patch));
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setSaving(null);
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    setError(null);
    setSaving("new");
    try {
      const user = await addUser({ ...form, products: chosen });
      setList((current) => current && { ...current, users: [...(current.users ?? []), user], seats_used: (current.seats_used ?? 0) + 1 });
      setForm({ email: "", display_name: "", password: "" });
      setNewProducts(null);
    } catch (cause) {
      setError(toApiError(cause));
    } finally {
      setSaving(null);
    }
  }

  if (me && !me.is_admin) {
    return (
      <AppShell crumbs={[{ label: "Users & access" }]}>
        <h1 className="mg-h1">Users &amp; access</h1>
        <p className="mg-empty">Only an administrator can manage who uses which product.</p>
      </AppShell>
    );
  }

  const seats = list?.seats_total != null ? `${list.seats_used} of ${list.seats_total} seats used` : `${list?.seats_used ?? 0} active users`;

  return (
    <AppShell crumbs={[{ label: "Users & access" }]}>
      <h1 className="mg-h1">Users &amp; access</h1>
      <p className="mg-sub">
        Choose who may use each migration product. Administrators have every product this licence includes. {list && seats}
      </p>

      {error && (
        <div className="mg-error" role="alert">
          {error.message}
        </div>
      )}

      <div className="mg-card">
        {list === null ? (
          <p className="mg-empty">Loading…</p>
        ) : (
          <table className="mg-table">
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Active</th>
                <th scope="col">Administrator</th>
                {PRODUCTS.map((p) => (
                  <th key={p.id} scope="col" title={productBlocked(probe, p) ?? undefined}>
                    {p.label}
                    {productBlocked(probe, p) && <span className="mg-note"> (unavailable)</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(list.users ?? []).map((user) => {
                const busy = saving === user.user_id;
                const self = me?.user_id === user.user_id;
                return (
                  <tr key={user.user_id} aria-busy={busy}>
                    <td>
                      <strong>{user.display_name || user.email}</strong>
                      <div className="mg-note">{user.email}</div>
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${user.email} active`}
                        checked={user.is_active ?? true}
                        disabled={busy || self}
                        title={self ? "You cannot deactivate yourself" : undefined}
                        onChange={(e) => void change(user, { is_active: e.target.checked })}
                      />
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={`${user.email} administrator`}
                        checked={user.is_admin ?? false}
                        disabled={busy || self}
                        title={self ? "You cannot remove your own administrator access" : undefined}
                        onChange={(e) => void change(user, { is_admin: e.target.checked })}
                      />
                    </td>
                    {PRODUCTS.map((p) => {
                      const blocked = productBlocked(probe, p);
                      const products = user.products ?? [];
                      if (user.is_admin) {
                        return (
                          <td key={p.id} className="mg-note" title="Administrators have every licensed product">
                            {blocked ? "—" : "All (admin)"}
                          </td>
                        );
                      }
                      return (
                        <td key={p.id}>
                          <input
                            type="checkbox"
                            aria-label={`${user.email} ${p.label}`}
                            checked={products.includes(p.id)}
                            disabled={busy || blocked !== null}
                            title={blocked ?? undefined}
                            onChange={(e) => void change(user, { products: toggled(products, p.id, e.target.checked) })}
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <form className="mg-card" style={{ marginTop: 16, padding: 16 }} onSubmit={(e) => void add(e)}>
        <h2 style={{ margin: "0 0 10px", fontSize: 16 }}>Add a person</h2>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 10 }}>
          <label>
            <span className="mg-field-label">Email</span>
            <input className="mg-input" type="email" required value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label>
            <span className="mg-field-label">Name</span>
            <input className="mg-input" value={form.display_name}
              onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </label>
          <label>
            <span className="mg-field-label">Initial password</span>
            <input className="mg-input" type="password" required minLength={12} value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </label>
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: "12px 0 0" }}>
          <legend className="mg-field-label">Products</legend>
          {PRODUCTS.map((p) => {
            const blocked = productBlocked(probe, p);
            return (
              <label key={p.id} style={{ marginRight: 16 }} title={blocked ?? undefined}>
                <input
                  type="checkbox"
                  checked={chosen.includes(p.id)}
                  disabled={blocked !== null}
                  onChange={(e) => setNewProducts(toggled(chosen, p.id, e.target.checked))}
                />{" "}
                {p.label}
              </label>
            );
          })}
        </fieldset>
        <button type="submit" className="mg-btn mg-btn--primary" style={{ marginTop: 12 }} disabled={saving === "new"}>
          {saving === "new" ? "Adding…" : "Add person"}
        </button>
      </form>
    </AppShell>
  );
}
