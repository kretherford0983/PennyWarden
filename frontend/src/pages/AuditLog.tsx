import { Fragment, useEffect, useState } from "react";
import { api, qs } from "../api";
import { ErrorBox, Field, Loading } from "../components";

export default function AuditLog() {
  const [f, setF] = useState({ object_type: "", action: "", actor: "", category: "", date_from: "", date_to: "", direction: "desc" });
  const [page, setPage] = useState(0);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<number | null>(null);
  const limit = 50;
  useEffect(() => {
    setErr(null);
    api.get(`/api/audit-events${qs({ ...f, limit, offset: page * limit })}`).then(setData, setErr);
  }, [f, page]);
  const set = (k: keyof typeof f) => (e: any) => { setPage(0); setF({ ...f, [k]: e.target.value }); };
  return (
    <div>
      <h1>Audit Log</h1>
      <p className="muted">Append-only. Audit events cannot be edited or deleted.</p>
      <div className="filters">
        <Field label="Object type">
          <select value={f.object_type} onChange={set("object_type")}>
            <option value="">All</option>
            {["user", "workspace", "fiscal_year", "budget", "entity", "bank_account", "register_transaction", "attachment", "fiscal_year_review"].map((o) => <option key={o}>{o}</option>)}
          </select>
        </Field>
        <Field label="Action"><input value={f.action} onChange={set("action")} placeholder="e.g. LOGIN_FAILED" /></Field>
        <Field label="Actor"><input value={f.actor} onChange={set("actor")} /></Field>
        <Field label="Category"><select value={f.category} onChange={set("category")}><option value="">All</option><option>BUSINESS</option><option>SECURITY</option></select></Field>
        <Field label="From"><input type="date" value={f.date_from} onChange={set("date_from")} /></Field>
        <Field label="To"><input type="date" value={f.date_to} onChange={set("date_to")} /></Field>
        <Field label="Order"><select value={f.direction} onChange={set("direction")}><option value="desc">Newest first</option><option value="asc">Oldest first</option></select></Field>
      </div>
      <ErrorBox error={err} />
      {!data ? <Loading /> : (
        <>
          <table className="table">
            <thead><tr><th>Time (UTC)</th><th>Actor</th><th>Action</th><th>Object</th><th>Category</th><th /></tr></thead>
            <tbody>
              {data.items.map((e: any) => (
                <Fragment key={e.id}>
                  <tr>
                    <td>{e.timestamp.replace("T", " ").slice(0, 19)}</td><td>{e.actor_name && e.actor_username ? `${e.actor_name} - ${e.actor_username}` : e.actor_username || "—"}</td><td><code>{e.action}</code></td>
                    <td>{e.object_type} {e.object_id ? `#${e.object_id}` : ""}</td><td>{e.category}</td>
                    <td><button className="small" onClick={() => setOpen(open === e.id ? null : e.id)} aria-expanded={open === e.id}>{open === e.id ? "Hide" : "Details"}</button></td>
                  </tr>
                  {open === e.id ? (
                    <tr className="detail-row">
                      <td colSpan={6}>
                        {e.snapshots_withheld ? <p className="muted">Financial snapshot content is withheld for Administrators.</p> : (
                          <div className="snapshots">
                            <div><h4>Before</h4><pre>{e.before ? JSON.stringify(e.before, null, 2) : "null"}</pre></div>
                            <div><h4>After</h4><pre>{e.after ? JSON.stringify(e.after, null, 2) : "null"}</pre></div>
                          </div>
                        )}
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span>{page * limit + 1}–{Math.min((page + 1) * limit, data.total)} of {data.total}</span>
            <button disabled={(page + 1) * limit >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </>
      )}
    </div>
  );
}
