/** 2.0.0 (#134): after the upgrade, the first Administrator to sign in completes the first and last name of every
 * account that has none (inactive ones too). It can't be skipped; once every account has names it never returns. */
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, GuardedForm, Loading } from "../components";

export default function NamesGate({ onDone, onLogout }: { onDone: () => void; onLogout: () => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/users/names-needed").then((r) => setRows(r.map((u: any) => ({ ...u, first_name: u.first_name || "", last_name: u.last_name || "" }))), setErr); }, []);
  const set = (i: number, k: string, v: string) => setRows((rs) => rs!.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const r = await api.put("/api/users/names", { users: rows!.map((u) => ({ id: u.id, first_name: u.first_name, last_name: u.last_name })) });
      if (r.remaining === 0) onDone();
    } catch (x) { setErr(x); }
  };
  if (!rows) return <div className="center"><ErrorBox error={err} /><Loading /></div>;
  return (
    <div className="center">
      <GuardedForm className="card names-gate" onSubmit={submit}>
        <h1>Add the users' real names</h1>
        <p>PennyWarden now keeps a <b>first and last name</b> for every account, so people with the same first name can be told apart in the Users
          list and in the audit log. Enter them for these {rows.length} account(s) to continue. If you don't know someone's real name, use a stand-in
          (for example the display name) and correct it later under <b>Users → Edit</b>.</p>
        <ErrorBox error={err} />
        <table className="table compact">
          <thead><tr><th>Username</th><th>Display name</th><th>Email</th><th>First name</th><th>Last name</th></tr></thead>
          <tbody>
            {rows.map((u, i) => (
              <tr key={u.id}>
                <td>{u.username}{u.active ? null : <span className="badge grey"> disabled</span>}</td><td>{u.display_name}</td><td>{u.email}</td>
                <td><input required maxLength={60} aria-label={`First name of ${u.username}`} value={u.first_name} onChange={(e) => set(i, "first_name", e.target.value)} /></td>
                <td><input required maxLength={60} aria-label={`Last name of ${u.username}`} value={u.last_name} onChange={(e) => set(i, "last_name", e.target.value)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="actions">
          <button type="button" onClick={onLogout}>Sign out</button>
          <button className="primary" type="submit">Save and continue</button>
        </div>
      </GuardedForm>
    </div>
  );
}
