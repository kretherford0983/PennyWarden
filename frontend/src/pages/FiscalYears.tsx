import { useEffect, useState, type FormEvent } from "react";
import { api, money, qs } from "../api";
import { ErrorBox, Field, FyStatus, Loading, Modal, useConfirmable, GuardedForm } from "../components";
import { useMe } from "../App";
import { Link, useRouter } from "../router";
import { reportPath } from "./reports/registry";

export default function FiscalYears() {
  const { can } = useMe();
  const [list, setList] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [creating, setCreating] = useState(false);
  const { navigate } = useRouter();
  const load = () => api.get("/api/fiscal-years").then(setList, setErr);
  useEffect(() => {
    load();
  }, []);
  if (!list) return <><ErrorBox error={err} /><Loading /></>;
  return (
    <div>
      <div className="page-head">
        <h1>Fiscal Years</h1>
        <div className="row">
          {/* #261; 2.3.0 (#375): a shortcut to the Planning Sheet in Reports */}
          {can("budget.manage") ? <button onClick={() => navigate(reportPath("planning-sheet"))}>Planning sheet…</button> : null}
          {can("fiscal_year.manage") ? <button className="primary" onClick={() => setCreating(true)}>New Fiscal Year</button> : null}
        </div>
      </div>
      <table className="table">
        <thead><tr><th>Fiscal Year</th><th>Start date</th><th>End date</th><th>Status</th></tr></thead>
        <tbody>
          {list.length === 0 ? <tr><td colSpan={4} className="muted">No Fiscal Years.</td></tr> : null}
          {list.map((f) => (
            <tr key={f.id}>
              <td><Link to={`/fiscal-years/${f.id}`}>{f.display_name}</Link></td>
              <td>{f.start_date}</td><td>{f.end_date}</td><td><FyStatus status={f.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {creating ? <CreateFy list={list} onClose={() => setCreating(false)} /> : null}
    </div>
  );
}

function addDay(iso: string, n: number) {
  const d = new Date(iso + "T00:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function CreateFy({ list, onClose }: { list: any[]; onClose: () => void }) {
  const { navigate } = useRouter();
  const last = list[list.length - 1];
  const start0 = last ? addDay(last.end_date, 1) : "";
  const end0 = start0 ? addDay(new Date(new Date(start0).setUTCFullYear(new Date(start0).getUTCFullYear() + 1)).toISOString().slice(0, 10), -1) : "";
  const [f, setF] = useState({ identifier: "", start_date: start0, end_date: end0, copy_from: "" });
  const [source, setSource] = useState<any>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [pre, setPre] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const { run, dialog } = useConfirmable();
  useEffect(() => {
    if (!f.copy_from) { setSource(null); return; }
    api.get(`/api/budgets${qs({ fiscal_year_id: f.copy_from })}`).then((t) => {
      setSource(t);
      setSelected(new Set([...t.income, ...t.expense].map((b: any) => b.id)));
    });
  }, [f.copy_from]);
  useEffect(() => {
    if (!f.start_date || !f.end_date) return;
    api.post("/api/fiscal-years/continuity-check", { start_date: f.start_date, end_date: f.end_date }).then((r) => setPre(r.warnings), () => setPre([]));
  }, [f.start_date, f.end_date]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const created = await run((confirmations) => api.post("/api/fiscal-years", {
        identifier: f.identifier, start_date: f.start_date, end_date: f.end_date,
        copy_from_fiscal_year_id: f.copy_from ? Number(f.copy_from) : null, copy_budget_ids: f.copy_from ? [...selected] : [],
        confirmations,
      }));
      if (created) navigate(`/fiscal-years/${created.id}`);
    } catch (x) { setErr(x); }
  };
  const toggle = (id: number) => { const s = new Set(selected); s.has(id) ? s.delete(id) : s.add(id); setSelected(s); };
  return (
    <Modal title="New Fiscal Year" onClose={onClose} wide>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Identifier" hint={`Displayed as FY${f.identifier || "…"}`}><input required pattern="[A-Za-z0-9-]{1,20}" value={f.identifier} onChange={(e) => setF({ ...f, identifier: e.target.value })} /></Field>
        <div className="row">
          <Field label="Start date"><input required type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /></Field>
          <Field label="End date"><input required type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></Field>
        </div>
        {pre.map((w) => <div key={w.code} className="alert warn" role="alert"><strong>{w.message}</strong></div>)}
        {last && !pre.length && f.start_date ? <p className="hint">Normal consecutive start date: {start0}</p> : null}
        <Field label="Copy budgets from (optional)">
          <select value={f.copy_from} onChange={(e) => setF({ ...f, copy_from: e.target.value })}>
            <option value="">— none —</option>
            {list.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
        </Field>
        {source ? (
          <fieldset>
            <legend>Budgets to copy as Draft (uncheck to remove)</legend>
            {[...source.income, ...source.expense].map((b: any) => (
              <label key={b.id} className="check">
                <input type="checkbox" checked={selected.has(b.id)} onChange={() => toggle(b.id)} /> {b.label} · {b.budget_type} · {money(b.amount)}
                {b.children.filter((c: any) => !c.is_other).length ? <span className="muted"> (with {b.children.filter((c: any) => !c.is_other).map((c: any) => c.display_code).join(", ")})</span> : null}
              </label>
            ))}
          </fieldset>
        ) : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Create Fiscal Year</button></div>
      </GuardedForm>
      {dialog}
    </Modal>
  );
}
