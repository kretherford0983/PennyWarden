// 2.4.0 (#523): one payment for several invoices - one deposit, linked to each invoice (Register User). Started from a
// customer (or an invoice number typed off a payment stub) or from invoices ticked in the list. The amount received
// fills the open balances oldest due date first; each part can be changed; the extra above the balances is an
// overpayment on the invoice chosen (confirmed). A payer other than an invoice's customer is confirmed.
import { useEffect, useState, type FormEvent } from "react";
import { api, money, todayIso } from "../api";
import { EntityPicker, ErrorBox, Field, Loading, Modal, useConfirmable } from "../components";

export function useAccounts() {
  const [accts, setAccts] = useState<any[]>([]);
  // 2.4.0 polish (#504): only active register accounts take a deposit or a refund, in the Bank Accounts order
  useEffect(() => { api.get("/api/bank-accounts").then((l: any[]) => setAccts(l.filter((a) => a.status === "ACTIVE" && a.register_enabled))); }, []);
  return accts;
}

const cents = (s: string): number | null => {
  const t = (s || "").replace(/[$,\s]/g, "");
  if (!/^\d+(\.\d{0,2})?$/.test(t)) return null;
  return Math.round(Number(t) * 100);
};
const show = (c: number) => (c / 100).toFixed(2);

type Row = { id: number; number: string; due_date: string; invoice_date: string; open: string; customer_entity_id: number; customer: string; on: boolean; amount: string };

/** Fill the ticked invoices' balances, oldest due first, until the amount runs out. */
function spread(rows: Row[], total: number): Row[] {
  let left = total;
  return rows.map((r) => {
    if (!r.on) return { ...r, amount: "" };
    const take = Math.max(0, Math.min(left, cents(r.open) || 0));
    left -= take;
    return { ...r, amount: take ? show(take) : "" };
  });
}

export function MultiPaymentForm({ invoiceIds, customerIds, onClose, onDone }: {
  invoiceIds?: number[]; customerIds?: number[]; onClose: () => void; onDone: () => void;
}) {
  const accts = useAccounts();
  const { run, dialog } = useConfirmable();
  const [err, setErr] = useState<unknown>(null);
  const [entities, setEntities] = useState<any[]>([]);
  const [customer, setCustomer] = useState("");
  const [number, setNumber] = useState("");
  const [rows, setRows] = useState<Row[] | null>(invoiceIds?.length ? null : []);
  const [received, setReceived] = useState("");
  const [payer, setPayer] = useState("");
  const [overTo, setOverTo] = useState("");
  const [v, setV] = useState({ bank_account_id: "", transaction_date: todayIso(), notes: "" });
  useEffect(() => { api.get("/api/entities").then(setEntities, () => setEntities([])); }, []);
  useEffect(() => {
    const start = accts.length === 1 ? accts[0] : accts.find((a) => a.is_primary);
    if (start && !v.bank_account_id) setV((x) => ({ ...x, bank_account_id: String(start.id) }));
  }, [accts]); // eslint-disable-line react-hooks/exhaustive-deps
  const load = (list: any[], only?: number[]) => {
    const picked = list.filter((x) => !only || only.includes(x.id))
      .map((x) => ({ ...x, customer: x.customer || "", on: true, amount: "" }));
    picked.sort((a, b) => (a.due_date || "9999").localeCompare(b.due_date || "9999") || a.id - b.id);
    setRows(picked);
    setReceived(show(picked.reduce((s, r) => s + (cents(r.open) || 0), 0)));
    setOverTo(picked.length ? String(picked[picked.length - 1].id) : "");
    setPayer(picked.length ? String(picked[0].customer_entity_id) : "");
    return picked;
  };
  const fetchOpen = async (params: Record<string, string>) => {
    const r: any = await api.get(`/api/invoices/payments/open?${new URLSearchParams(params).toString()}`);
    return (r.invoices as any[]).map((x) => ({ ...x, customer: r.customer.name }));
  };
  // ticked in the list: their customers' open invoices, keeping only the ticked ones
  useEffect(() => {
    if (!invoiceIds?.length) return;
    (async () => {
      try {
        const all: any[] = [];
        for (const c of [...new Set(customerIds || [])]) all.push(...await fetchOpen({ customer_entity_id: String(c) }));
        const got = load(all, invoiceIds);
        setRows(spread(got, got.reduce((s, r) => s + (cents(r.open) || 0), 0)));
      } catch (x) { setErr(x); setRows([]); }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const find = async (params: Record<string, string>) => {
    setErr(null);
    try {
      const got = load(await fetchOpen(params));
      setRows(spread(got, got.reduce((s, r) => s + (cents(r.open) || 0), 0)));
    } catch (x) { setErr(x); }
  };
  if (rows === null) return <Modal title="Record a payment" onClose={onClose}><ErrorBox error={err} /><Loading /></Modal>;
  const total = cents(received);
  const parts = rows.filter((r) => r.on).map((r) => cents(r.amount) ?? -1);
  const applied = parts.filter((c) => c > 0).reduce((s, c) => s + c, 0);
  const bad = parts.some((c) => c < 0) || rows.some((r) => r.on && (cents(r.amount) || 0) > (cents(r.open) || 0));
  const over = total !== null ? total - applied : 0;
  const customers = [...new Set(rows.filter((r) => r.on).map((r) => r.customer_entity_id))];
  const ready = rows.some((r) => r.on && (cents(r.amount) || 0) > 0) && total !== null && total > 0 && !bad && over >= 0 && !!v.bank_account_id;
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    const items = rows!.filter((r) => r.on && (cents(r.amount) || 0) > 0).map((r) => ({ invoice_id: r.id, amount: r.amount }));
    try {
      const r = await run((codes) => api.post("/api/invoices/payments", {
        bank_account_id: Number(v.bank_account_id), transaction_date: v.transaction_date || null, notes: v.notes || null, items,
        payer_entity_id: payer ? Number(payer) : null,
        ...(over > 0 ? { overpayment: show(over), overpayment_invoice_id: Number(overTo) } : {}),
        confirm_overpayment: codes.includes("OVERPAYMENT"), confirmations: codes.filter((c) => c !== "OVERPAYMENT"),
      }));
      if (r) onDone();
    } catch (x) { setErr(x); }
  }
  const setRow = (id: number, patch: Partial<Row>) => setRows(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  return (
    <Modal title="Record a payment" onClose={onClose} wide>
      <form onSubmit={submit} data-testid="multi-payment">
        <ErrorBox error={err} />
        <p className="hint">One deposit for a check or transfer that pays one or more invoices. Each invoice's part is spread over its lines'
          Invoiced Income budgets, as Record payment on the invoice does.</p>
        {!invoiceIds?.length ? (
          <div className="row form-row">
            <EntityPicker label="Customer" entities={entities} value={customer} onChange={(id) => { setCustomer(id); if (id) find({ customer_entity_id: id }); }} />
            <Field label="Or an invoice number" hint="From a payment stub: shows that customer's open invoices.">
              <span className="row"><input aria-label="Invoice number" maxLength={60} value={number} onChange={(e) => setNumber(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (number.trim()) find({ number: number.trim() }); } }} />
              <button type="button" disabled={!number.trim()} onClick={() => find({ number: number.trim() })}>Find</button></span>
            </Field>
          </div>
        ) : null}
        {rows.length ? (
          <>
            <Field label="Amount received" hint="Fills the balances oldest due date first; change any invoice's part below.">
              <input aria-label="Amount received" required inputMode="decimal" value={received}
                onChange={(e) => { setReceived(e.target.value); const c = cents(e.target.value); if (c !== null) setRows(spread(rows, c)); }} />
            </Field>
            <table className="table compact" data-testid="multi-payment-invoices">
              <thead><tr><th /><th>Invoice</th>{customers.length > 1 || invoiceIds?.length ? <th>Customer</th> : null}<th>Due</th><th className="num">Open</th><th className="num">This payment</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.id}>
                  <td><input type="checkbox" aria-label={`Include ${r.number}`} checked={r.on}
                    onChange={(e) => { const next = rows.map((x) => (x.id === r.id ? { ...x, on: e.target.checked } : x)); setRows(total !== null ? spread(next, total) : next); }} /></td>
                  <td>{r.number}</td>{customers.length > 1 || invoiceIds?.length ? <td>{r.customer}</td> : null}<td>{r.due_date}</td>
                  <td className="num">{money(r.open)}</td>
                  <td className="num"><input aria-label={`Amount for ${r.number}`} inputMode="decimal" disabled={!r.on} value={r.amount} style={{ width: "8em", textAlign: "right" }}
                    onChange={(e) => setRow(r.id, { amount: e.target.value })} /></td>
                </tr>))}</tbody>
              <tfoot><tr><td colSpan={customers.length > 1 || invoiceIds?.length ? 5 : 4}>Applied to invoices</td><td className="num" data-testid="multi-applied">{money(show(applied))}</td></tr></tfoot>
            </table>
            {bad ? <p className="error" role="alert">An invoice's part can't be more than its open balance (put the extra as an overpayment).</p> : null}
            {total !== null && over < 0 ? <p className="error" role="alert">The parts add up to {money(show(applied))}, more than the {money(show(total))} received.</p> : null}
            {over > 0 ? (
              <Field label={`Overpayment of ${money(show(over))} goes on`} hint="It is recorded as an overpayment on that invoice and can be refunded there.">
                <select aria-label="Overpayment invoice" value={overTo} onChange={(e) => setOverTo(e.target.value)}>
                  {rows.filter((r) => r.on).map((r) => <option key={r.id} value={r.id}>{r.number}</option>)}</select>
              </Field>
            ) : null}
            <EntityPicker label="Paid by" entities={entities} value={payer} onChange={setPayer} />
            {customers.length > 1 ? <p className="hint">These invoices are for different customers: the deposit is recorded as from the payer, and you'll be asked to confirm.</p> : null}
            <div className="row form-row">
              <Field label="Bank account"><select required value={v.bank_account_id} onChange={(e) => setV({ ...v, bank_account_id: e.target.value })}>
                <option value="">Choose…</option>{accts.map((a) => <option key={a.id} value={a.id}>{a.label || `${a.account_name} - ${a.account_number_masked}`}</option>)}</select></Field>
              <Field label="Date"><input type="date" required value={v.transaction_date} onChange={(e) => setV({ ...v, transaction_date: e.target.value })} /></Field>
            </div>
            <Field label="Notes"><textarea rows={2} maxLength={4000} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></Field>
          </>
        ) : customer || invoiceIds?.length ? <p className="muted">No open invoices for this customer.</p> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button>
          <button className="primary" type="submit" disabled={!ready}>Record payment</button></div>
      </form>
      {dialog}
    </Modal>
  );
}

// ------------------------------------------------------------------ 2.4.0 (#533): Apply to invoice (Register form)
export type Applied = { invoices: { invoice_id: number; number: string; amount: string }[]; extra: "" | "BUDGET" | "CREDIT" | "REFUND"; extra_invoice_id: string };

/** The open invoices of the allocation's entity; the allocation's amount fills them oldest due date first; the extra
 *  above them stays on the line's budget, is kept as credit (an overpayment on an invoice) or is refunded at once. */
export function ApplyToInvoiceModal({ entityId, entityName, amount, current, onClose, onApply }: {
  entityId: string; entityName: string; amount: string; current?: Applied; onClose: () => void; onApply: (a: Applied | null) => void;
}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [total, setTotal] = useState(amount);
  const [extra, setExtra] = useState<Applied["extra"]>(current?.extra || "BUDGET");
  const [overTo, setOverTo] = useState(current?.extra_invoice_id || "");
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    api.get(`/api/invoices/payments/open?customer_entity_id=${entityId}`).then((r: any) => {
      let got: Row[] = (r.invoices as any[]).map((x) => ({ ...x, customer: r.customer.name, on: true, amount: "" }));
      const all = got.reduce((s, x) => s + (cents(x.open) || 0), 0);
      const amt = cents(amount) ?? all;
      if (current?.invoices.length) {
        got = got.map((x) => { const c = current.invoices.find((y) => y.invoice_id === x.id); return { ...x, on: !!c, amount: c ? c.amount : "" }; });
      } else got = spread(got, amt);
      setTotal(show(amt));
      setRows(got);
      if (!overTo && got.length) setOverTo(String(got[got.length - 1].id));
    }, setErr);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (!rows) return <Modal title="Apply to invoice" onClose={onClose}><ErrorBox error={err} />{err ? null : <Loading />}</Modal>;
  const t = cents(total);
  const applied = rows.filter((r) => r.on).reduce((s, r) => s + (cents(r.amount) || 0), 0);
  const bad = rows.some((r) => r.on && ((cents(r.amount) ?? -1) < 0 || (cents(r.amount) || 0) > (cents(r.open) || 0)));
  const left = t !== null ? t - applied : 0;
  const ok = t !== null && applied > 0 && !bad && left >= 0;
  const apply = () => onApply({
    invoices: rows.filter((r) => r.on && (cents(r.amount) || 0) > 0).map((r) => ({ invoice_id: r.id, number: r.number, amount: show(cents(r.amount) || 0) })),
    extra: left > 0 ? extra : "", extra_invoice_id: overTo,
  });
  return (
    <Modal title="Apply to invoice" onClose={onClose} wide>
      <div data-testid="apply-to-invoice">
        <p className="hint">{entityName}'s open invoices, oldest due date first. When the deposit is saved, the part applied to each invoice is spread over
          its lines' Invoiced Income budgets and tax (as Record payment does) and linked to it.</p>
        {!rows.length ? <p className="muted">{entityName} has no open invoices.</p> : (
          <>
            <Field label="Amount of this allocation"><input aria-label="Allocation amount to apply" inputMode="decimal" value={total}
              onChange={(e) => { setTotal(e.target.value); const c = cents(e.target.value); if (c !== null) setRows(spread(rows, c)); }} /></Field>
            <table className="table compact">
              <thead><tr><th /><th>Invoice</th><th>Due</th><th className="num">Open</th><th className="num">Apply</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.id}>
                  <td><input type="checkbox" aria-label={`Apply to ${r.number}`} checked={r.on}
                    onChange={(e) => { const n = rows.map((x) => (x.id === r.id ? { ...x, on: e.target.checked } : x)); setRows(t !== null ? spread(n, t) : n); }} /></td>
                  <td>{r.number}</td><td>{r.due_date}</td><td className="num">{money(r.open)}</td>
                  <td className="num"><input aria-label={`Apply amount for ${r.number}`} inputMode="decimal" disabled={!r.on} value={r.amount} style={{ width: "8em", textAlign: "right" }}
                    onChange={(e) => setRows(rows.map((x) => (x.id === r.id ? { ...x, amount: e.target.value } : x)))} /></td>
                </tr>))}</tbody>
            </table>
            {bad ? <p className="error" role="alert">An invoice's part can't be more than its open balance.</p> : null}
            {t !== null && left < 0 ? <p className="error" role="alert">{money(show(applied))} is applied but the allocation is {money(show(t))}.</p> : null}
            {left > 0 ? (
              <fieldset data-testid="apply-extra"><legend>The other {money(show(left))}</legend>
                <label className="check"><input type="radio" name="apply-extra" checked={extra === "BUDGET"} onChange={() => setExtra("BUDGET")} /> Keep it on this allocation's budget (e.g. a fundraiser or a donation)</label>
                <label className="check"><input type="radio" name="apply-extra" checked={extra === "CREDIT"} onChange={() => setExtra("CREDIT")} /> Overpayment kept as the customer's credit</label>
                <label className="check"><input type="radio" name="apply-extra" checked={extra === "REFUND"} onChange={() => setExtra("REFUND")} /> Overpayment refunded (a refund withdrawal is recorded with the deposit)</label>
                {extra !== "BUDGET" ? <Field label="On invoice"><select aria-label="Overpayment on invoice" value={overTo} onChange={(e) => setOverTo(e.target.value)}>
                  {rows.filter((r) => r.on).map((r) => <option key={r.id} value={r.id}>{r.number}</option>)}</select></Field> : null}
              </fieldset>
            ) : null}
          </>
        )}
        <div className="actions">
          {current ? <button type="button" onClick={() => onApply(null)}>Don't apply</button> : null}
          <button type="button" onClick={onClose}>Cancel</button>
          <button type="button" className="primary" disabled={!ok} onClick={apply}>Apply</button>
        </div>
      </div>
    </Modal>
  );
}
