import { Fragment, useEffect, useState, type FormEvent } from "react";
import { api, money, qs } from "../api";
import { EntityPicker, ErrorBox, Field, GuardedForm, Loading, Modal, useConfirmable } from "../components";
import { Link, useRouter } from "../router";
import { useMe } from "../App";
import { OverdueInvoices } from "./Dashboard";
import { EmailLog, SendEmail } from "./Email";

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
        <p className="hint">Open invoices, aging, statements and the other invoice reports are under <Link to="/reports">Reports → Invoices</Link>.</p>
      </section>
      {can("invoice.manage") ? <OverdueInvoices reminders /> : null}
      <InvoiceList manage={can("invoice.manage")} />
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
  const [v, setV] = useState<any>(null);
  const [saved, setSaved] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get("/api/invoices/setup").then((x) => { setO(x); setV({ number_pattern: x.number_pattern, terms_days: String(x.terms_days), terms_text: x.terms_text || "", default_notes: x.default_notes || "", overdue_reminder_days: String(x.overdue_reminder_days ?? 0) }); }, setErr); }, []);
  if (!o || !v) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const set = (k: string) => (e: any) => { setSaved(false); setV({ ...v, [k]: e.target.value }); };
  const save = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try { const x = await api.put("/api/invoices/setup", { ...v, terms_days: Number(v.terms_days), overdue_reminder_days: Number(v.overdue_reminder_days) }); setO(x); setSaved(true); } catch (x) { setErr(x); }
  };
  return (
    <div>
      <div className="page-head"><h1>Invoices Setup</h1><a className="button" href="/api/invoices/setup/test-print" target="_blank" rel="noreferrer">Test print (sample data)</a></div>
      <section className="card">
        <GuardedForm onSubmit={save}>
          <ErrorBox error={err} />
          <Field label="Invoice number pattern" hint="{YYYY} or {YY} = the invoice date's year, {SEQ} = the number (one sequence that never restarts; {SEQ:4} pads to 4 digits).">
            <input required maxLength={40} value={v.number_pattern} onChange={set("number_pattern")} />
          </Field>
          <p className="hint">Next invoice: <b data-testid="inv-next-number">{o.next_number_example}</b></p>
          <div className="row fields">
            <Field label="Payment terms (days)"><input type="number" min={0} max={365} value={v.terms_days} onChange={set("terms_days")} /></Field>
            <Field label="Terms text" hint="Printed on the invoice, e.g. Net 30."><input maxLength={200} value={v.terms_text} onChange={set("terms_text")} /></Field>
          </div>
          <Field label="Default notes" hint="Printed at the bottom of new invoices (can be changed per invoice)."><textarea rows={3} maxLength={2000} value={v.default_notes} onChange={set("default_notes")} /></Field>
          <Field label="Overdue reminder (days after the due date)" hint="Invoice Managers see a reminder for each unpaid invoice from its due date plus this many days (0 = on the due date).">
            <input type="number" min={0} max={365} value={v.overdue_reminder_days} onChange={set("overdue_reminder_days")} />
          </Field>
          <div className="actions"><button className="primary" type="submit">Save</button>{saved ? <span role="status" className="muted">Saved.</span> : null}</div>
        </GuardedForm>
        <p className="muted">The invoice PDF template comes in a later test build.</p>
      </section>
      <FieldSetup fields={o.fields || []} onChanged={() => api.get("/api/invoices/setup").then(setO, setErr)} />
    </div>
  );
}

// ------------------------------------------------------------------ 2.4.0 (#253): invoices
const STATUSES: [string, string][] = [["", "All"], ["OPEN", "Open (sent, partly paid)"], ["DRAFT", "Draft"], ["SENT", "Sent"], ["PARTLY_PAID", "Partly paid"],
  ["PAID", "Paid"], ["VOID", "Void"], ["WRITTEN_OFF", "Written off"]];

function InvoiceList({ manage }: { manage: boolean }) {
  const { navigate } = useRouter();
  const [rows, setRows] = useState<any[] | null>(null);
  const [status, setStatus] = useState("");
  const [search, setSearch] = useState("");
  const [creating, setCreating] = useState(false);
  const [batching, setBatching] = useState(false);              // 2.4.0 (#248)
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    const h = setTimeout(() => {
      const p = new URLSearchParams();
      if (status) p.set("status", status);
      if (search.trim()) p.set("search", search.trim());
      api.get(`/api/invoices?${p.toString()}`).then(setRows, setErr);
    }, 200);
    return () => clearTimeout(h);
  }, [status, search]);
  return (
    <section className="card" aria-labelledby="inv-list-h">
      <div className="charts-head">
        <h2 id="inv-list-h">Invoices</h2>
        <div className="row">
          <Field label="Status"><select aria-label="Invoice status filter" value={status} onChange={(e) => setStatus(e.target.value)}>{STATUSES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></Field>
          <Field label="Search"><input aria-label="Search invoices" maxLength={100} value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Number or customer" /></Field>
          {manage ? <button className="primary" onClick={() => setCreating(true)}>New invoice</button> : null}
          {manage ? <button onClick={() => setBatching(true)}>New batch…</button> : null}
        </div>
      </div>
      <ErrorBox error={err} />
      {!rows ? <Loading /> : !rows.length ? <p className="muted">No invoices.</p> : (
        <table className="table" data-testid="invoice-list">
          <thead><tr><th>Number</th><th>Customer</th><th>Date</th><th>Due</th><th>Status</th><th className="num">Total</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}>
              <td><Link to={`/invoices/${r.id}`}>{r.number}</Link></td><td>{r.customer?.name}</td><td>{r.invoice_date}</td>
              <td>{r.due_date}{r.overdue ? <span className="badge red">Overdue</span> : null}</td>
              <td>{r.status_label}{r.write_off_status === "PENDING" ? <span className="badge yellow">Write-off pending</span> : null}</td>
              <td className="num">{money(r.total)}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
      {creating ? <InvoiceForm onClose={() => setCreating(false)} onSaved={(i) => navigate(`/invoices/${i.id}`)} /> : null}
      {batching ? <InvoiceForm batch onClose={() => setBatching(false)} onSaved={(b) => navigate(`/invoices/batches/${b.id}`)} /> : null}
      <Batches />
    </section>
  );
}

export function InvoiceDetail({ id }: { id: number }) {
  const { can } = useMe();
  const [i, setI] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [editing, setEditing] = useState(false);
  const [ask, setAsk] = useState<null | { title: string; label: string; url: string; body?: (t: string) => any; optional?: boolean }>(null);
  const [mail, setMail] = useState<any>(null);                     // 2.4.0 (#249): the email log and form defaults
  const [emailing, setEmailing] = useState(false);
  const load = () => api.get(`/api/invoices/${id}`).then(setI, setErr);
  const loadMail = () => api.get(`/api/invoices/${id}/email`).then(setMail, () => setMail(null));
  useEffect(() => { load(); loadMail(); }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!i) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const manage = can("invoice.manage");
  const act = async (url: string, body?: any) => { setErr(null); try { setI(await api.post(url, body)); } catch (x) { setErr(x); } };
  return (
    <div>
      <p><Link to="/invoices">← Invoices</Link></p>
      <div className="page-head">
        <h1>Invoice {i.number} <span className="badge grey" data-testid="inv-status">{i.status_label}</span>{i.write_off?.status === "PENDING" ? <span className="badge yellow">Write-off pending</span> : null}</h1>
        <a className="button" href={`/api/invoices/${i.id}/pdf`} target="_blank" rel="noreferrer">{i.status === "DRAFT" ? "Preview PDF" : "PDF"}</a>
        {manage ? <div className="row">
          {i.can.edit ? <button onClick={() => setEditing(true)}>Edit</button> : null}
          {i.can.send ? <button className="primary" onClick={() => act(`/api/invoices/${i.id}/send`)}>Mark as sent</button> : null}
          {mail?.defaults && ["SENT", "PARTLY_PAID", "PAID"].includes(i.status) ? <button onClick={() => setEmailing(true)}>Email…</button> : null}
          {i.can.revise ? <button onClick={() => setAsk({ title: "Revise invoice", label: "Why is it revised?", url: `/api/invoices/${i.id}/revise` })}>Revise…</button> : null}
          {i.can.write_off ? <button onClick={() => setAsk({ title: "Request a write-off", label: "Reason", url: `/api/invoices/${i.id}/write-off` })}>Request write-off…</button> : null}
          {i.can.void ? <button className="danger" onClick={() => setAsk({ title: "Void invoice", label: "Reason (the number is not reused)", url: `/api/invoices/${i.id}/void` })}>Void…</button> : null}
        </div> : null}
        {can("invoice.write_off_decide") && i.can.decide_write_off ? <div className="row">
          <button className="primary" onClick={() => act(`/api/invoices/${i.id}/write-off/decision`, { approve: true })}>Approve write-off</button>
          <button onClick={() => setAsk({ title: "Reject write-off", label: "Why is it rejected?", url: `/api/invoices/${i.id}/write-off/decision`, body: (t) => ({ approve: false, note: t }) })}>Reject…</button>
        </div> : null}
      </div>
      <ErrorBox error={err} />
      {i.write_off ? <div className={`alert ${i.write_off.status === "REJECTED" ? "info" : "warn"}`} role="note">Write-off {i.write_off.status.toLowerCase()}: {i.write_off.reason}{i.write_off.note ? ` — ${i.write_off.note}` : ""}{i.write_off.self_approved ? " (self-approved)" : ""}</div> : null}
      {i.void_reason ? <div className="alert info" role="note">Void: {i.void_reason}</div> : null}
      <dl className="dl">
        <dt>Customer</dt><dd>{i.customer?.name}</dd>
        {i.batch_id ? <><dt>Batch</dt><dd><Link to={`/invoices/batches/${i.batch_id}`}>Open the batch</Link></dd></> : null}
        <dt>Invoice date</dt><dd>{i.invoice_date}</dd>
        <dt>Due</dt><dd>{i.due_date}{i.overdue ? <span className="badge red">Overdue</span> : null}</dd>
        {i.terms_text ? <><dt>Terms</dt><dd>{i.terms_text}</dd></> : null}
        {i.notes ? <><dt>Notes</dt><dd className="pre-wrap">{i.notes}</dd></> : null}
        {(i.fields || []).map((x: any) => <Fragment key={x.field_id}><dt>{x.name}{x.retired ? " (retired)" : ""}</dt><dd>{x.value}</dd></Fragment>)}
      </dl>
      <table className="table" data-testid="inv-lines">
        <thead><tr><th>Description</th><th className="num">Qty</th><th className="num">Unit price</th><th className="num">Amount</th><th className="num">Net</th><th>Budget</th></tr></thead>
        <tbody>{i.lines.map((l: any) => (
          <tr key={l.id}>
            <td>{l.description}{l.unit_type ? <span className="muted"> ({l.unit_type})</span> : null}{l.taxable ? <span className="badge grey">Taxable</span> : null}
              {(l.fields || []).length ? <div className="muted">{l.fields.map((x: any) => `${x.name}: ${x.value}`).join("; ")}</div> : null}
              {l.discount ? <div className="muted">Discount {l.discount.kind === "PERCENT" ? `${l.discount.value} %` : money(l.discount.value)} — {l.discount.reason} (−{money(l.discount.amount)})</div> : null}</td>
            <td className="num">{l.quantity}</td><td className="num">{money(l.unit_price)}</td><td className="num">{money(l.gross)}</td><td className="num">{money(l.net)}</td>
            <td>{l.budget?.label}</td>
          </tr>
        ))}</tbody>
      </table>
      <dl className="dl" data-testid="inv-totals">
        <dt>Subtotal</dt><dd>{money(i.totals.subtotal)}</dd>
        {Number(i.totals.line_discounts) ? <><dt>Line discounts</dt><dd>−{money(i.totals.line_discounts)}</dd></> : null}
        {i.discount ? <><dt>Invoice discount</dt><dd>−{money(i.totals.invoice_discount)} ({i.discount.kind === "PERCENT" ? `${i.discount.value} %` : "fixed"} — {i.discount.reason})</dd></> : null}
        {i.tax ? <><dt>{i.tax.name} ({i.tax.rate} %)</dt><dd>{money(i.totals.tax)}</dd></> : null}
        <dt><b>Total</b></dt><dd><b>{money(i.totals.total)}</b></dd>
      </dl>
      {i.versions.length ? (
        <section className="card"><h2>Sent versions</h2>
          <ul>{i.versions.map((v: any) => <li key={v.revision}><a href={v.pdf_url} target="_blank" rel="noreferrer">{v.number}</a> — {money(v.total)}, sent {String(v.sent_at).slice(0, 10)}{v.reason ? <span className="muted"> · revised: {v.reason}</span> : null}</li>)}</ul>
        </section>
      ) : null}
      {i.payments && i.status !== "DRAFT" ? <Payments i={i} onChanged={setI} /> : null}
      {mail ? <EmailLog rows={mail.log} /> : null}
      {emailing && mail?.defaults ? <SendEmail title={`Email invoice ${i.number}`} defaults={mail.defaults} url={`/api/invoices/${i.id}/email`}
        attachment={`invoice-${i.number}.pdf (the sent version)`} onClose={() => { setEmailing(false); loadMail(); }} onSent={() => { setEmailing(false); loadMail(); }} /> : null}
      {editing ? <InvoiceForm current={i} onClose={() => setEditing(false)} onSaved={(x) => { setEditing(false); setI(x); }} /> : null}
      {ask ? <AskText {...ask} onClose={() => setAsk(null)} onDone={async (t) => { await act(ask.url, ask.body ? ask.body(t) : { reason: t }); setAsk(null); }} /> : null}
    </div>
  );
}

function AskText({ title, label, onClose, onDone }: { title: string; label: string; onClose: () => void; onDone: (t: string) => void }) {
  const [t, setT] = useState("");
  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={(e) => { e.preventDefault(); if (t.trim()) onDone(t.trim()); }}>
        <Field label={label}><textarea required rows={3} maxLength={500} value={t} onChange={(e) => setT(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={!t.trim()}>OK</button></div>
      </form>
    </Modal>
  );
}

type LineV = { id?: number; product_id: string; quantity: string; discount_kind: string; discount_value: string; discount_reason: string; custom?: Record<string, string> };

function InvoiceForm({ current, batch, onClose, onSaved }: { current?: any; batch?: boolean; onClose: () => void; onSaved: (i: any) => void }) {
  const [picked, setPicked] = useState<string[]>([]);               // 2.4.0 (#248): batch customers
  const [find, setFind] = useState("");
  const [batchName, setBatchName] = useState("");
  const [products, setProducts] = useState<any[]>([]);
  const [taxes, setTaxes] = useState<any[]>([]);
  const [entities, setEntities] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [v, setV] = useState({ customer: current?.customer ? String(current.customer.id) : "", invoice_date: current?.invoice_date || new Date().toISOString().slice(0, 10),
    due_date: current?.due_date || "", tax_rate_id: current?.tax ? String(current.tax.id) : "", notes: current?.notes ?? "", terms_text: current?.terms_text ?? "",
    discount_kind: current?.discount?.kind || "", discount_value: current?.discount?.value || "", discount_reason: current?.discount?.reason || "" });
  const [lines, setLines] = useState<LineV[]>(current ? current.lines.map((l: any) => ({ id: l.id, product_id: String(l.product_id), quantity: l.quantity,
    discount_kind: l.discount?.kind || "", discount_value: l.discount?.value || "", discount_reason: l.discount?.reason || "", custom: { ...(l.custom_values || {}) } })) : [{ product_id: "", quantity: "1", discount_kind: "", discount_value: "", discount_reason: "", custom: {} }]);
  const [fields, setFields] = useState<any[]>([]);                    // 2.4.0 (#253 part 2)
  const [custom, setCustom] = useState<Record<string, string>>({ ...(current?.custom_values || {}) });
  useEffect(() => {
    api.get("/api/invoices/catalog/products").then((p) => setProducts(p.filter((x: any) => !x.is_system)), () => setProducts([]));
    api.get("/api/invoices/catalog/tax-rates").then(setTaxes, () => setTaxes([]));
    api.get("/api/entities").then(setEntities, setErr);
    api.get("/api/invoices/fields").then(setFields, () => setFields([]));
  }, []);
  const set = (k: string) => (e: any) => setV({ ...v, [k]: e.target.value });
  const setLine = (k: number, patch: Partial<LineV>) => setLines(lines.map((l, i) => (i === k ? { ...l, ...patch } : l)));
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body: any = { customer_entity_id: Number(v.customer), invoice_date: v.invoice_date, due_date: v.due_date || null,
      tax_rate_id: v.tax_rate_id ? Number(v.tax_rate_id) : null, notes: v.notes, terms_text: v.terms_text,
      discount: v.discount_kind ? { kind: v.discount_kind, value: v.discount_value, reason: v.discount_reason } : null,
      lines: lines.map((l) => ({ ...(l.id ? { id: l.id } : {}), product_id: Number(l.product_id), quantity: l.quantity,
        discount_kind: l.discount_kind || null, discount_value: l.discount_kind ? l.discount_value : null, discount_reason: l.discount_kind ? l.discount_reason : null,
        custom_values: Object.fromEntries(fields.filter((f) => f.level === "LINE").map((f) => [String(f.id), (l.custom || {})[String(f.id)] || null])) })),
      custom_values: Object.fromEntries(fields.filter((f) => f.level === "INVOICE").map((f) => [String(f.id), custom[String(f.id)] || null])) };
    if (!current) { delete body.notes; delete body.terms_text; if (!v.notes) body.notes = null; }
    if (batch) {
      delete body.customer_entity_id;
      try { onSaved(await api.post("/api/invoices/batches", { ...body, name: batchName || null, customer_entity_ids: picked.map(Number) })); } catch (x) { setErr(x); }
      return;
    }
    try { onSaved(current ? await api.put(`/api/invoices/${current.id}`, body) : await api.post("/api/invoices", body)); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={current ? `Edit invoice ${current.number}` : batch ? "New batch of invoices" : "New invoice"} onClose={onClose} wide>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {batch ? <BatchCustomers entities={entities} picked={picked} setPicked={setPicked} find={find} setFind={setFind} name={batchName} setName={setBatchName} />
          : <EntityPicker label="Customer" entities={entities} value={v.customer} onChange={(id) => setV({ ...v, customer: id })} />}
        <div className="row fields">
          <Field label="Invoice date"><input type="date" required value={v.invoice_date} onChange={set("invoice_date")} /></Field>
          <Field label="Due date" hint="Empty = from the terms."><input type="date" value={v.due_date} onChange={set("due_date")} /></Field>
          <Field label="Sales tax"><select value={v.tax_rate_id} onChange={set("tax_rate_id")}><option value="">— none —</option>{taxes.map((t) => <option key={t.id} value={t.id}>{t.name} ({t.rate} %)</option>)}</select></Field>
        </div>
        <fieldset><legend>Lines (from the catalog)</legend>
          {lines.map((l, k) => (
            <div key={k} className="row fields inv-line">
              <Field label={`Line ${k + 1} product`}><select required value={l.product_id} onChange={(e) => setLine(k, { product_id: e.target.value, id: undefined })}>
                <option value="">— choose —</option>{products.map((p) => <option key={p.id} value={p.id} disabled={p.needs_budget}>{p.name} — {money(p.unit_price)}{p.unit_type ? ` / ${p.unit_type}` : ""}{p.needs_budget ? " (needs budget)" : ""}</option>)}</select></Field>
              <Field label={`Line ${k + 1} quantity`}><input required inputMode="decimal" maxLength={14} value={l.quantity} onChange={(e) => setLine(k, { quantity: e.target.value })} /></Field>
              <Field label={`Line ${k + 1} discount`}><select value={l.discount_kind} onChange={(e) => setLine(k, { discount_kind: e.target.value })}><option value="">— none —</option><option value="AMOUNT">Amount ($)</option><option value="PERCENT">Percent (%)</option></select></Field>
              {l.discount_kind ? <>
                <Field label={`Line ${k + 1} discount value`}><input required inputMode="decimal" maxLength={20} value={l.discount_value} onChange={(e) => setLine(k, { discount_value: e.target.value })} /></Field>
                <Field label={`Line ${k + 1} discount reason`}><input required maxLength={200} value={l.discount_reason} onChange={(e) => setLine(k, { discount_reason: e.target.value })} /></Field>
              </> : null}
              {fields.filter((f) => f.level === "LINE").map((f) => <FieldInput key={f.id} f={f} prefix={`Line ${k + 1} `} value={(l.custom || {})[String(f.id)] || ""} onChange={(x) => setLine(k, { custom: { ...(l.custom || {}), [String(f.id)]: x } })} />)}
              {lines.length > 1 ? <button type="button" className="small" onClick={() => setLines(lines.filter((_x, i) => i !== k))}>Remove</button> : null}
            </div>
          ))}
          <button type="button" className="small" onClick={() => setLines([...lines, { product_id: "", quantity: "1", discount_kind: "", discount_value: "", discount_reason: "", custom: {} }])}>+ Line</button>
          {!products.length ? <p className="muted">No products yet — add them in the Product catalog.</p> : null}
        </fieldset>
        <div className="row fields">
          <Field label="Invoice discount"><select value={v.discount_kind} onChange={set("discount_kind")}><option value="">— none —</option><option value="AMOUNT">Amount ($)</option><option value="PERCENT">Percent (%)</option></select></Field>
          {v.discount_kind ? <>
            <Field label="Invoice discount value"><input required inputMode="decimal" maxLength={20} value={v.discount_value} onChange={set("discount_value")} /></Field>
            <Field label="Invoice discount reason" hint="Printed on the invoice."><input required maxLength={200} value={v.discount_reason} onChange={set("discount_reason")} /></Field>
          </> : null}
        </div>
        {fields.filter((f) => f.level === "INVOICE").length ? <div className="row fields">
          {fields.filter((f) => f.level === "INVOICE").map((f) => <FieldInput key={f.id} f={f} value={custom[String(f.id)] || ""} onChange={(x) => setCustom({ ...custom, [String(f.id)]: x })} />)}
        </div> : null}
        {current ? <>
          <Field label="Terms"><input maxLength={200} value={v.terms_text} onChange={set("terms_text")} /></Field>
          <Field label="Notes"><textarea rows={2} maxLength={2000} value={v.notes} onChange={set("notes")} /></Field>
        </> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={!!batch && !picked.length}>{current ? "Save" : batch ? `Create ${picked.length} drafts` : "Create draft"}</button></div>
      </GuardedForm>
    </Modal>
  );
}


// ------------------------------------------------------------------ 2.4.0 (#253 part 2): custom fields
const FIELD_TYPES: [string, string][] = [["TEXT", "Text"], ["NUMBER", "Number"], ["DATE", "Date"], ["PICKLIST", "Pick-list"]];

function FieldSetup({ fields, onChanged }: { fields: any[]; onChanged: () => void }) {
  const [edit, setEdit] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const toggle = async (f: any) => { setErr(null); try { await api.post(`/api/invoices/setup/fields/${f.id}/${f.active ? "retire" : "restore"}`); onChanged(); } catch (x) { setErr(x); } };
  return (
    <section className="card" aria-labelledby="inv-fields-h">
      <div className="charts-head"><h2 id="inv-fields-h">Custom fields</h2><button className="small primary" onClick={() => setEdit({})}>New field</button></div>
      <p className="hint">Extra fields on invoices or on their lines (for example a purchase order number). Retire a field you no longer use; values already entered stay.</p>
      <ErrorBox error={err} />
      {!fields.length ? <p className="muted">No custom fields.</p> : (
        <table className="table compact"><thead><tr><th>Name</th><th>On</th><th>Type</th><th>Required</th><th>On the PDF</th><th>Status</th><th /></tr></thead>
          <tbody>{fields.map((f) => <tr key={f.id}>
            <td>{f.name}{f.options?.length ? <span className="muted"> ({f.options.join(", ")})</span> : null}</td><td>{f.level === "LINE" ? "Lines" : "Invoice"}</td>
            <td>{FIELD_TYPES.find((t) => t[0] === f.field_type)?.[1]}</td><td>{f.required ? "Yes" : "No"}</td><td>{f.show_on_pdf ? "Yes" : "No"}</td>
            <td>{f.active ? "Active" : "Retired"}</td>
            <td className="actions-cell"><button className="small" onClick={() => setEdit(f)}>Edit</button> <button className="small" onClick={() => toggle(f)}>{f.active ? "Retire" : "Restore"}</button></td>
          </tr>)}</tbody></table>
      )}
      {edit ? <FieldForm f={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); onChanged(); }} /> : null}
    </section>
  );
}

function FieldForm({ f, onClose, onSaved }: { f: any; onClose: () => void; onSaved: () => void }) {
  const [v, setV] = useState({ name: f.name || "", level: f.level || "INVOICE", field_type: f.field_type || "TEXT", options: (f.options || []).join("\n"),
    required: !!f.required, show_on_pdf: f.show_on_pdf ?? true });
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body: any = { name: v.name, required: v.required, show_on_pdf: v.show_on_pdf,
      options: v.field_type === "PICKLIST" ? v.options.split("\n").map((x: string) => x.trim()).filter(Boolean) : [] };
    if (!f.id) { body.level = v.level; body.field_type = v.field_type; }
    try { if (f.id) await api.put(`/api/invoices/setup/fields/${f.id}`, body); else await api.post("/api/invoices/setup/fields", body); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={f.id ? `Edit field ${f.name}` : "New custom field"} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Name"><input required maxLength={60} value={v.name} onChange={(e) => setV({ ...v, name: e.target.value })} /></Field>
        <div className="row fields">
          <Field label="On"><select disabled={!!f.id} value={v.level} onChange={(e) => setV({ ...v, level: e.target.value })}><option value="INVOICE">The invoice</option><option value="LINE">Each line</option></select></Field>
          <Field label="Type"><select disabled={!!f.id} value={v.field_type} onChange={(e) => setV({ ...v, field_type: e.target.value })}>{FIELD_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        </div>
        {v.field_type === "PICKLIST" ? <Field label="Choices" hint="One per line."><textarea required rows={4} value={v.options} onChange={(e) => setV({ ...v, options: e.target.value })} /></Field> : null}
        <label className="check"><input type="checkbox" checked={v.required} onChange={(e) => setV({ ...v, required: e.target.checked })} /> Required</label>
        <label className="check"><input type="checkbox" checked={v.show_on_pdf} onChange={(e) => setV({ ...v, show_on_pdf: e.target.checked })} /> Show on the invoice PDF</label>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

function FieldInput({ f, value, onChange, prefix = "" }: { f: any; value: string; onChange: (v: string) => void; prefix?: string }) {
  const label = `${prefix}${f.name}${f.required ? "" : " (optional)"}`;
  if (f.field_type === "PICKLIST") return <Field label={label}><select required={f.required} value={value} onChange={(e) => onChange(e.target.value)}><option value="">— choose —</option>{f.options.map((o: string) => <option key={o} value={o}>{o}</option>)}</select></Field>;
  if (f.field_type === "DATE") return <Field label={label}><input type="date" required={f.required} value={value} onChange={(e) => onChange(e.target.value)} /></Field>;
  return <Field label={label}><input required={f.required} inputMode={f.field_type === "NUMBER" ? "decimal" : undefined} maxLength={200} value={value} onChange={(e) => onChange(e.target.value)} /></Field>;
}

// 2.4.0 (#254): payments. A Register User records the money (a deposit on the lines' Invoiced Income budgets) or
// refunds an overpayment; an Invoice Manager or Register User links an existing deposit; a Register User unlinks.
function Payments({ i, onChanged }: { i: any; onChanged: (i: any) => void }) {
  const { can } = useMe();
  const [mode, setMode] = useState<null | "pay" | "refund" | "link">(null);
  const [unlink, setUnlink] = useState<any>(null);
  const p = i.payments;
  const open = ["SENT", "PARTLY_PAID", "PAID"].includes(i.status) && i.write_off?.status !== "PENDING";
  const live = p.links.filter((x: any) => !x.unlinked);
  return (
    <section className="card" aria-labelledby="inv-pay-h" data-testid="inv-payments">
      <h2 id="inv-pay-h">Payments</h2>
      <dl className="dl">
        <dt>Paid</dt><dd data-testid="inv-paid">{money(p.paid)}</dd>
        <dt>Open balance</dt><dd data-testid="inv-open">{money(p.open)}</dd>
        {Number(p.overpaid) ? <><dt>Overpaid</dt><dd>{money(p.overpaid)}{Number(p.refunded) ? ` (refunded ${money(p.refunded)})` : ""}</dd></> : null}
      </dl>
      {live.length ? (
        <table className="table">
          <thead><tr><th>Date</th><th>Kind</th><th className="num">Amount</th><th>Budget</th><th>Register</th><th /></tr></thead>
          <tbody>{live.map((x: any) => (
            <tr key={x.id} className={x.status !== "ACTIVE" ? "muted" : undefined}>
              <td>{x.date}</td>
              <td>{x.kind === "PAYMENT" ? "Payment" : x.kind === "OVERPAYMENT" ? "Overpayment" : "Refund"}{x.status !== "ACTIVE" ? <span className="badge grey">Void</span> : null}</td>
              <td className="num">{x.kind === "REFUND" ? "−" : ""}{money(x.amount)}</td>
              <td>{x.budget?.label}</td>
              <td>{can("register.view") && x.bank_account_id ? <Link to={`/register?account=${x.bank_account_id}&txn=${x.transaction_id}`}>Transaction #{x.transaction_id}</Link> : `#${x.transaction_id}`}</td>
              <td>{can("transaction.manage") && x.status === "ACTIVE" && x.kind !== "REFUND" ? <button className="small" onClick={() => setUnlink(x)}>Unlink…</button> : null}</td>
            </tr>
          ))}</tbody>
        </table>
      ) : <p className="muted">No payments yet.</p>}
      {open ? <div className="row">
        {can("invoice.record_payment") ? <button className="primary" onClick={() => setMode("pay")}>Record payment…</button> : null}
        {can("invoice.link_payment") && Number(p.open) > 0 ? <button onClick={() => setMode("link")}>Link a deposit…</button> : null}
        {can("invoice.record_payment") && Number(p.refundable) > 0 ? <button onClick={() => setMode("refund")}>Refund overpayment…</button> : null}
      </div> : null}
      {mode === "pay" || mode === "refund" ? <MoneyForm i={i} refund={mode === "refund"} onClose={() => setMode(null)} onDone={(x) => { setMode(null); onChanged(x); }} /> : null}
      {mode === "link" ? <LinkForm i={i} onClose={() => setMode(null)} onDone={(x) => { setMode(null); onChanged(x); }} /> : null}
      {unlink ? <UnlinkForm i={i} link={unlink} onClose={() => setUnlink(null)} onDone={(x) => { setUnlink(null); onChanged(x); }} /> : null}
    </section>
  );
}

function useAccounts() {
  const [accts, setAccts] = useState<any[]>([]);
  useEffect(() => { api.get("/api/bank-accounts").then((l: any[]) => setAccts(l.filter((a) => a.status === "ACTIVE"))); }, []);
  return accts;
}

function MoneyForm({ i, refund, onClose, onDone }: { i: any; refund: boolean; onClose: () => void; onDone: (i: any) => void }) {
  const accts = useAccounts();
  const { run, dialog } = useConfirmable();
  const [err, setErr] = useState<unknown>(null);
  const [v, setV] = useState({ bank_account_id: "", amount: refund ? i.payments.refundable : i.payments.open, transaction_date: new Date().toISOString().slice(0, 10), check_number: "", notes: "" });
  useEffect(() => { if (accts.length === 1 && !v.bank_account_id) setV((x) => ({ ...x, bank_account_id: String(accts[0].id) })); }, [accts]); // eslint-disable-line react-hooks/exhaustive-deps
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const r: any = await run((codes) => api.post(`/api/invoices/${i.id}/${refund ? "refunds" : "payments"}`, {
        bank_account_id: Number(v.bank_account_id), amount: v.amount, transaction_date: v.transaction_date || null, notes: v.notes || null,
        ...(refund ? { check_number: v.check_number || null, confirmations: codes } : { confirm_overpayment: codes.includes("OVERPAYMENT"), confirmations: codes.filter((c) => c !== "OVERPAYMENT") }),
      }));
      if (r) onDone(r.invoice);
    } catch (x) { setErr(x); }
  }
  return (
    <Modal title={refund ? "Refund overpayment" : "Record payment"} onClose={onClose}>
      <form onSubmit={submit}>
        <ErrorBox error={err} />
        <p className="hint">{refund
          ? `A withdrawal that reduces the Invoiced Income budget (up to ${money(i.payments.refundable)}).`
          : `A deposit for invoice ${i.number}, spread over its lines' Invoiced Income budgets. Open balance ${money(i.payments.open)}; more than that is recorded as an overpayment.`}</p>
        <Field label="Bank account"><select required value={v.bank_account_id} onChange={(e) => setV({ ...v, bank_account_id: e.target.value })}>
          <option value="">Choose…</option>{accts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}</select></Field>
        <Field label="Amount"><input required inputMode="decimal" value={v.amount} onChange={(e) => setV({ ...v, amount: e.target.value })} /></Field>
        <Field label="Date"><input type="date" required value={v.transaction_date} onChange={(e) => setV({ ...v, transaction_date: e.target.value })} /></Field>
        {refund ? <Field label="Check number"><input maxLength={20} value={v.check_number} onChange={(e) => setV({ ...v, check_number: e.target.value })} /></Field> : null}
        <Field label="Notes"><textarea rows={2} maxLength={4000} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">{refund ? "Record refund" : "Record payment"}</button></div>
      </form>
      {dialog}
    </Modal>
  );
}

function LinkForm({ i, onClose, onDone }: { i: any; onClose: () => void; onDone: (i: any) => void }) {
  const { run, dialog } = useConfirmable();
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get(`/api/invoices/${i.id}/link-candidates`).then(setRows, setErr); }, [i.id]);
  async function pick(aid: number) {
    setErr(null);
    try { const r = await run((codes) => api.post(`/api/invoices/${i.id}/links`, { allocation_id: aid, confirmations: codes })); if (r) onDone(r); }
    catch (x) { setErr(x); }
  }
  return (
    <Modal title="Link a deposit" onClose={onClose}>
      <ErrorBox error={err} />
      <p className="hint">Deposit lines on an Invoiced Income budget that aren't linked yet. A line larger than the open balance ({money(i.payments.open)}) is split in the register first.</p>
      {rows === null ? <Loading /> : rows.length ? (
        <table className="table"><thead><tr><th>Date</th><th>From</th><th>Budget</th><th className="num">Amount</th><th /></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.allocation_id}><td>{r.date}</td><td>{r.entity || "—"}</td><td>{r.budget?.label}</td><td className="num">{money(r.amount)}</td>
            <td><button className="small" onClick={() => pick(r.allocation_id)}>Link</button></td></tr>)}</tbody></table>
      ) : <p className="muted">No unlinked deposits on Invoiced Income budgets.</p>}
      <div className="actions"><button type="button" onClick={onClose}>Close</button></div>
      {dialog}
    </Modal>
  );
}

function UnlinkForm({ i, link, onClose, onDone }: { i: any; link: any; onClose: () => void; onDone: (i: any) => void }) {
  const [opts, setOpts] = useState<any[]>([]);
  const [v, setV] = useState({ budget: "", reason: "" });
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    api.get(`/api/budgets/selectable${qs({ fiscal_year_id: link.budget?.fiscal_year_id, transaction_type: "DEPOSIT" })}`)
      .then((o: any[]) => setOpts(o.filter((b) => !b.invoiced_income)), setErr);
  }, [link]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try { onDone(await api.post(`/api/invoices/${i.id}/links/${link.id}/unlink`, { move_to_budget_id: Number(v.budget), reason: v.reason })); }
    catch (x) { setErr(x); }
  }
  return (
    <Modal title="Unlink payment" onClose={onClose}>
      <form onSubmit={submit}>
        <ErrorBox error={err} />
        <p className="hint">The {money(link.amount)} line stays in the register and moves to another budget in the same step; the invoice's open balance goes back up.</p>
        <Field label="Move the line to"><select required value={v.budget} onChange={(e) => setV({ ...v, budget: e.target.value })}>
          <option value="">Choose…</option>{opts.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}</select></Field>
        <Field label="Reason"><textarea required rows={2} maxLength={500} value={v.reason} onChange={(e) => setV({ ...v, reason: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit" disabled={!v.budget || !v.reason.trim()}>Unlink</button></div>
      </form>
    </Modal>
  );
}

// ------------------------------------------------------------------ 2.4.0 (#248): batches
function BatchCustomers({ entities, picked, setPicked, find, setFind, name, setName }: {
  entities: any[]; picked: string[]; setPicked: (x: string[]) => void; find: string; setFind: (x: string) => void; name: string; setName: (x: string) => void;
}) {
  const t = find.trim().toLowerCase();
  const shown = entities.filter((e) => !t || String(e.display_name).toLowerCase().includes(t));
  const toggle = (id: string, on: boolean) => setPicked(on ? [...picked, id] : picked.filter((x) => x !== id));
  return (
    <fieldset data-testid="batch-customers"><legend>Customers ({picked.length} chosen)</legend>
      <Field label="Batch name" hint="For finding the batch later, e.g. 2027 dues."><input maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <div className="row">
        <Field label="Find customers"><input value={find} onChange={(e) => setFind(e.target.value)} placeholder="Name" /></Field>
        <button type="button" className="small" onClick={() => setPicked(Array.from(new Set([...picked, ...shown.map((e) => String(e.id))])))}>Choose all shown</button>
        <button type="button" className="small" disabled={!picked.length} onClick={() => setPicked([])}>Clear</button>
      </div>
      <div className="check-list" style={{ maxHeight: "14rem", overflowY: "auto" }}>
        {shown.map((e) => <label key={e.id} className="check"><input type="checkbox" checked={picked.includes(String(e.id))} onChange={(x) => toggle(String(e.id), x.target.checked)} /> {e.display_name}</label>)}
      </div>
      <p className="hint">One draft invoice is created for each customer, with the lines and dates below. Review them, then mark them all as sent and print one PDF.</p>
    </fieldset>
  );
}

function Batches() {
  const [rows, setRows] = useState<any[] | null>(null);
  useEffect(() => { api.get("/api/invoices/batches").then(setRows, () => setRows([])); }, []);
  if (!rows || !rows.length) return null;
  return (
    <div data-testid="batch-list"><h3>Batches</h3>
      <ul>{rows.map((b) => <li key={b.id}><Link to={`/invoices/batches/${b.id}`}>{b.name}</Link> — {b.count} invoices{b.drafts ? `, ${b.drafts} draft${b.drafts === 1 ? "" : "s"}` : ""}</li>)}</ul>
    </div>
  );
}

export function InvoiceBatch({ id }: { id: number }) {
  const { can } = useMe();
  const [b, setB] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api.get(`/api/invoices/batches/${id}`).then(setB, setErr); }, [id]);
  if (!b) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const sendAll = async () => {
    setErr(null);
    setBusy(true);
    try { setB(await api.post(`/api/invoices/batches/${id}/send`)); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  return (
    <div>
      <p><Link to="/invoices">← Invoices</Link></p>
      <div className="page-head">
        <h1>Batch: {b.name}</h1>
        <a className="button" href={`/api/invoices/batches/${id}/pdf`} target="_blank" rel="noreferrer">Combined PDF</a>
        {can("invoice.manage") && b.drafts ? <button className="primary" disabled={busy} onClick={sendAll}>Mark all {b.drafts} drafts as sent</button> : null}
      </div>
      <ErrorBox error={err} />
      {b.result?.failed?.length ? <div className="alert warn" role="note">Not sent: {b.result.failed.map((f: any) => `${f.number} (${f.message})`).join("; ")}</div> : null}
      {b.result?.sent?.length ? <div className="alert info" role="status">Marked as sent: {b.result.sent.length}.</div> : null}
      <p className="hint">Each invoice can still be opened, changed (while a draft) or voided on its own. Total (not void): <b>{money(b.total)}</b></p>
      <table className="table" data-testid="batch-invoices">
        <thead><tr><th>Number</th><th>Customer</th><th>Date</th><th>Due</th><th>Status</th><th className="num">Total</th></tr></thead>
        <tbody>{b.invoices.map((r: any) => (
          <tr key={r.id}><td><Link to={`/invoices/${r.id}`}>{r.number}</Link></td><td>{r.customer?.name}</td><td>{r.invoice_date}</td><td>{r.due_date}</td><td>{r.status_label}</td><td className="num">{money(r.total)}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}
