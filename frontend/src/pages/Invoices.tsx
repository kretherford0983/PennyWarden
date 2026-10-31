import { useEffect, useState, type FormEvent } from "react";
import { api, money } from "../api";
import { ErrorBox, Field, GuardedForm, Loading, Modal } from "../components";
import { useMe } from "../App";

// 2.4.0 (#251): the Invoices module. Its sections (invoices, products, payments, reports) arrive with the later 2.4.0
// builds (#252-#255); this page says what the module is for and who does what (separation of duties).
export default function Invoices() {
  const { can } = useMe();
  const [o, setO] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/invoices/overview").then(setO, setErr); }, []);
  if (!o) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  return (
    <div>
      <div className="page-head"><h1>Invoices</h1></div>
      <section className="card" aria-labelledby="inv-roles-h">
        <h2 id="inv-roles-h">Who does what</h2>
        <ul>
          <li><b>Budget Managers</b> decide the budgets and mark Income budgets as <b>Invoiced Income</b>.</li>
          <li><b>Invoice Managers</b> decide what is billed and for how much.</li>
          <li><b>Register Users</b> receive and record the money.</li>
          <li><b>Auditors</b> review everything.</li>
        </ul>
        <p className="hint">One person may hold several of these roles in a small organization; keeping them apart lets someone else check each step.</p>
        <p className="muted" data-testid="inv-coming">Invoices, payments and invoice reports appear here as they are added in this release.</p>
      </section>
      {/* 2.4.0 (#252): Invoice Managers keep it; Budget Managers, Budget Users and Auditors see it */}
      {can("invoice.catalog_view") ? <Catalog manage={can("invoice.catalog_manage")} /> : null}
    </div>
  );
}

// ------------------------------------------------------------------ 2.4.0 (#252): the product catalog
type Tab = "products" | "tax-rates" | "unit-types" | "categories";
const TABS: [Tab, string][] = [["products", "Products"], ["tax-rates", "Tax rates"], ["unit-types", "Unit types"], ["categories", "Categories"]];

function Catalog({ manage }: { manage: boolean }) {
  const [tab, setTab] = useState<Tab>("products");
  const [inactive, setInactive] = useState(false);
  const [rows, setRows] = useState<any[] | null>(null);
  const [edit, setEdit] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const load = () => { setRows(null); api.get(`/api/invoices/catalog/${tab}${inactive ? "?include_inactive=true" : ""}`).then(setRows, setErr); };
  useEffect(load, [tab, inactive]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = async (r: any) => {
    setErr(null);
    try { await api.post(`/api/invoices/catalog/${tab}/${r.id}/${r.active ? "inactivate" : "restore"}`); load(); } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="inv-cat-h" data-testid="inv-catalog">
      <div className="charts-head">
        <h2 id="inv-cat-h">Product catalog</h2>
        <div className="row">
          {manage ? <button className="small primary" onClick={() => setEdit({})}>New {TABS.find((t) => t[0] === tab)![1].toLowerCase().replace(/s$/, "")}</button> : null}
          <label className="check"><input type="checkbox" checked={inactive} onChange={(e) => setInactive(e.target.checked)} /> Show inactive</label>
        </div>
      </div>
      <div role="tablist" aria-label="Catalog" className="tabs">
        {TABS.map(([k, l]) => <button key={k} role="tab" aria-selected={tab === k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      <ErrorBox error={err} />
      {!rows ? <Loading /> : !rows.length ? <p className="muted">Nothing here yet.</p> : (
        <table className="table compact">
          <thead><tr>
            <th>Name</th>
            {tab === "products" ? <><th>Code</th><th className="num">Price</th><th>Unit</th><th>Category</th><th>Taxable</th><th>Budget</th></> : null}
            {tab === "tax-rates" ? <><th className="num">Rate</th><th>Budget</th></> : null}
            <th>Status</th>{manage ? <th /> : null}
          </tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}>
              <td>{r.name}{r.is_system ? <span className="badge grey">Built in</span> : null}</td>
              {tab === "products" ? <>
                <td>{r.code || ""}</td><td className="num">{r.is_system ? "—" : money(r.unit_price)}</td><td>{r.unit_type || "—"}</td>
                <td>{r.category || "—"}</td><td>{r.taxable ? "Yes" : "No"}</td>
                <td>{r.budget ? r.budget.label : "—"}{r.needs_budget ? <span className="badge red" title="No Invoiced Income budget continues it into the current Fiscal Year">Needs budget</span> : null}</td>
              </> : null}
              {tab === "tax-rates" ? <>
                <td className="num">{r.rate} %</td>
                <td>{r.budget ? r.budget.label : "—"}{r.needs_budget ? <span className="badge red">Needs budget</span> : null}</td>
              </> : null}
              <td>{r.active ? "Active" : "Inactive"}</td>
              {manage ? <td className="actions-cell">{r.is_system ? null : <>
                <button className="small" onClick={() => setEdit(r)}>Edit</button>{" "}
                <button className="small" onClick={() => toggle(r)}>{r.active ? "Inactivate" : "Restore"}</button></>}</td> : null}
            </tr>
          ))}</tbody>
        </table>
      )}
      {edit ? <CatalogForm tab={tab} row={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} /> : null}
    </section>
  );
}

function CatalogForm({ tab, row, onClose, onSaved }: { tab: Tab; row: any; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState<any>({ name: row.name || "", code: row.code || "", description: row.description || "", unit_price: row.unit_price || "",
    unit_type_id: row.unit_type_id ? String(row.unit_type_id) : "", category_id: row.category_id ? String(row.category_id) : "", taxable: !!row.taxable,
    budget_id: row.budget_id ? String(row.budget_id) : "", rate: row.rate || "" });
  const [units, setUnits] = useState<any[]>([]);
  const [cats, setCats] = useState<any[]>([]);
  const [budgets, setBudgets] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    if (tab === "products") {
      api.get("/api/invoices/catalog/unit-types").then(setUnits, setErr);
      api.get("/api/invoices/catalog/categories").then(setCats, setErr);
    }
    if (tab === "products" || tab === "tax-rates") api.get("/api/invoices/catalog/budget-options").then(setBudgets, setErr);
  }, [tab]);
  const set = (k: string) => (e: any) => setV({ ...v, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const num = (x: string) => (x ? Number(x) : null);
    const body = tab === "products" ? { name: v.name, code: v.code || null, description: v.description || null, unit_price: v.unit_price,
      unit_type_id: num(v.unit_type_id), category_id: num(v.category_id), taxable: v.taxable, budget_id: num(v.budget_id) }
      : tab === "tax-rates" ? { name: v.name, rate: v.rate, budget_id: num(v.budget_id) } : { name: v.name };
    try {
      if (row.id) await api.put(`/api/invoices/catalog/${tab}/${row.id}`, body); else await api.post(`/api/invoices/catalog/${tab}`, body);
      onSaved();
    } catch (x) { setErr(x); }
  };
  const what = TABS.find((t) => t[0] === tab)![1].toLowerCase().replace(/s$/, "");
  const budgetPicker = (
    <Field label="Invoiced Income budget" hint="Where the money goes. Only Invoiced Income budgets are listed (a Budget Manager marks them).">
      <select required value={v.budget_id} onChange={set("budget_id")}>
        <option value="">— choose —</option>
        {budgets.map((g) => <optgroup key={g.fiscal_year.id} label={g.fiscal_year.display_name}>
          {g.budgets.map((b: any) => <option key={b.id} value={b.id}>{b.label}</option>)}
        </optgroup>)}
        {v.budget_id && !budgets.some((g) => g.budgets.some((b: any) => String(b.id) === v.budget_id)) && row.budget ? <option value={v.budget_id}>{row.budget.label} ({row.budget.fiscal_year})</option> : null}
      </select>
      {!budgets.length ? <span className="field-warn" role="note">No Invoiced Income budget yet — a Budget Manager marks one on the Budgets page.</span> : null}
    </Field>
  );
  return (
    <Modal title={row.id ? `Edit ${what}` : `New ${what}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Name"><input required maxLength={tab === "products" ? 120 : 80} value={v.name} onChange={set("name")} /></Field>
        {tab === "products" ? <>
          <Field label="Code (optional)"><input maxLength={30} value={v.code} onChange={set("code")} /></Field>
          <Field label="Description (optional)"><textarea rows={2} maxLength={1000} value={v.description} onChange={set("description")} /></Field>
          <div className="row fields">
            <Field label="Unit price"><input required inputMode="decimal" maxLength={20} value={v.unit_price} onChange={set("unit_price")} placeholder="e.g. 120.00" /></Field>
            <Field label="Unit type"><select required value={v.unit_type_id} onChange={set("unit_type_id")}><option value="">— choose —</option>{units.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</select></Field>
            <Field label="Category (optional)"><select value={v.category_id} onChange={set("category_id")}><option value="">— none —</option>{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></Field>
          </div>
          <label className="check"><input type="checkbox" checked={v.taxable} onChange={set("taxable")} /> Taxable</label>
          {budgetPicker}
        </> : null}
        {tab === "tax-rates" ? <>
          <Field label="Rate (%)" hint="For example 7 or 7.25."><input required inputMode="decimal" maxLength={12} value={v.rate} onChange={set("rate")} /></Field>
          {budgetPicker}
        </> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

// 2.4.0 (#251): the Administrator's module setup (numbering, terms, template and test print come with the Invoices
// build, #253). Administrators never see real invoices or products (BR-003).
export function InvoiceSetup() {
  const [o, setO] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/invoices/setup").then(setO, setErr); }, []);
  if (!o) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  return (
    <div>
      <div className="page-head"><h1>Invoices Setup</h1></div>
      <section className="card">
        <p>Invoice numbering, payment terms, custom fields, the invoice PDF template, overdue-reminder days and a test print with sample data will be set up here.</p>
        <p className="muted">Nothing to set up yet in this test build.</p>
      </section>
    </div>
  );
}
