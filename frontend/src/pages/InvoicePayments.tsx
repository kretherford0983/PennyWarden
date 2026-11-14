// 2.4.0 (#523): one payment for several invoices - one deposit, linked to each invoice (Register User). Started from a
// customer (or an invoice number typed off a payment stub) or from invoices ticked in the list. The amount received
// fills the open balances oldest due date first; each part can be changed. #544: the extra above the balances stays on
// a budget, is applied to the customer's other open invoices, is their credit (never while they owe) or is refunded
// (the Refund form opens once the payment is saved). A payer other than an invoice's customer is confirmed.
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { api, money, qs, todayIso } from "../api";
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

export type Extra = "" | "BUDGET" | "CREDIT" | "REFUND";

/** #544: what the customer of the invoice getting the extra still owes once this payment's parts are counted. */
function owedBy(rows: Row[], targetId: string): { owed: number; customer: number | null } {
  const t = rows.find((r) => String(r.id) === targetId) || rows.find((r) => r.on);
  const customer = t ? t.customer_entity_id : null;
  const owed = rows.filter((r) => r.customer_entity_id === customer)
    .reduce((s, r) => s + Math.max(0, (cents(r.open) || 0) - (r.on ? cents(r.amount) || 0 : 0)), 0);
  return { owed, customer };
}

/** #544 (decided with Kyle 2026-11-07): the same choices for the extra wherever a payment is recorded. "Apply it to the
 *  other open invoices" ticks them and fills them oldest due date first; account credit only when nothing is owed. */
function ExtraChoices({ left, rows, extra, setExtra, overTo, setOverTo, onOthers, budgetLabel, budgetPicker }: {
  left: number; rows: Row[]; extra: Extra; setExtra: (x: Extra) => void; overTo: string; setOverTo: (x: string) => void;
  onOthers: () => void; budgetLabel: string; budgetPicker?: ReactNode;
}) {
  const { owed } = owedBy(rows, overTo);
  return (
    <fieldset data-testid="apply-extra"><legend>The other {money(show(left))}</legend>
      {owed > 0 ? <label className="check"><input type="radio" name="apply-extra" checked={false} onChange={onOthers} /> Apply it to the other open
        invoices ({money(show(owed))} still owed), oldest due date first</label> : null}
      <label className="check"><input type="radio" name="apply-extra" checked={extra === "BUDGET"} onChange={() => setExtra("BUDGET")} /> {budgetLabel}</label>
      {extra === "BUDGET" ? budgetPicker : null}
      <label className={`check${owed > 0 ? " muted" : ""}`}><input type="radio" name="apply-extra" checked={extra === "CREDIT"} disabled={owed > 0}
        onChange={() => setExtra("CREDIT")} /> Kept as the customer's account credit</label>
      {owed > 0 ? <p className="hint" data-testid="no-credit-while-owed">Not while the customer still owes {money(show(owed))} on other invoices.</p> : null}
      <label className="check"><input type="radio" name="apply-extra" checked={extra === "REFUND"} onChange={() => setExtra("REFUND")} /> Refunded (the Refund
        form opens once the payment is saved)</label>
      {extra === "CREDIT" || extra === "REFUND" ? <Field label="On invoice"><select aria-label="Overpayment on invoice" value={overTo} onChange={(e) => setOverTo(e.target.value)}>
        {rows.filter((r) => r.on && (cents(r.amount) || 0) > 0).map((r) => <option key={r.id} value={r.id}>{r.number}</option>)}</select></Field> : null}
    </fieldset>
  );
}

/** Tick every open invoice and fill them from the amount, oldest due date first. */
const tickAll = (rows: Row[], total: number) => spread(rows.map((r) => ({ ...r, on: true })), total);

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
  const [extra, setExtra] = useState<Extra>("");
  const [budget, setBudget] = useState("");
  const [budgets, setBudgets] = useState<any[]>([]);
  const [refund, setRefund] = useState<null | { invoice_id: number; number: string; amount: string }>(null);
  const [v, setV] = useState({ bank_account_id: "", transaction_date: todayIso(), notes: "" });
  const [credit, setCredit] = useState<any>(null);
  useEffect(() => { api.get("/api/entities").then(setEntities, () => setEntities([])); }, []);
  useEffect(() => {
    const start = accts.length === 1 ? accts[0] : accts.find((a) => a.is_primary);
    if (start && !v.bank_account_id) setV((x) => ({ ...x, bank_account_id: String(start.id) }));
  }, [accts]); // eslint-disable-line react-hooks/exhaustive-deps
  // #544: the budgets the rest can stay on are those of the deposit date's Fiscal Year
  useEffect(() => {
    api.get(`/api/invoices/payments/extra-budgets${qs({ date: v.transaction_date || null })}`).then(setBudgets, () => setBudgets([]));
  }, [v.transaction_date]);
  // #544: the customer's other open invoices are listed too (unticked), so the extra can go to them
  const load = (list: any[], only?: number[]) => {
    const all = list.map((x) => ({ ...x, customer: x.customer || "", on: !only || only.includes(x.id), amount: "" }));
    all.sort((a, b) => (a.due_date || "9999").localeCompare(b.due_date || "9999") || a.id - b.id);
    const picked = all.filter((r) => r.on);
    setRows(all);
    setReceived(show(picked.reduce((s, r) => s + (cents(r.open) || 0), 0)));
    setOverTo(picked.length ? String(picked[picked.length - 1].id) : "");
    setPayer(picked.length ? String(picked[0].customer_entity_id) : "");
    return all;
  };
  const fetchOpen = async (params: Record<string, string>) => {
    const r: any = await api.get(`/api/invoices/payments/open?${new URLSearchParams(params).toString()}`);
    setCredit(r.credit && Number(r.credit.total) ? r.credit : null);                // 2.4.0 (#534)
    return (r.invoices as any[]).map((x) => ({ ...x, customer: r.customer.name }));
  };
  const fill = (got: Row[]) => setRows(spread(got, got.filter((r) => r.on).reduce((s, r) => s + (cents(r.open) || 0), 0)));
  // ticked in the list (or one invoice's Record payment): their customers' open invoices, those ticked
  useEffect(() => {
    if (!invoiceIds?.length) return;
    (async () => {
      try {
        const all: any[] = [];
        for (const c of [...new Set(customerIds || [])]) all.push(...await fetchOpen({ customer_entity_id: String(c) }));
        fill(load(all, invoiceIds));
      } catch (x) { setErr(x); setRows([]); }
    })();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const find = async (params: Record<string, string>) => {
    setErr(null);
    try { fill(load(await fetchOpen(params))); } catch (x) { setErr(x); }
  };
  if (refund) {
    return <RefundForm invoiceId={refund.invoice_id} number={refund.number} amount={refund.amount} bankAccountId={v.bank_account_id}
      date={v.transaction_date} afterPayment onClose={onDone} onDone={() => onDone()} />;
  }
  if (rows === null) return <Modal title="Record a payment" onClose={onClose}><ErrorBox error={err} /><Loading /></Modal>;
  const total = cents(received);
  const parts = rows.filter((r) => r.on).map((r) => cents(r.amount) ?? -1);
  const applied = parts.filter((c) => c > 0).reduce((s, c) => s + c, 0);
  const bad = parts.some((c) => c < 0) || rows.some((r) => r.on && (cents(r.amount) || 0) > (cents(r.open) || 0));
  const over = total !== null ? total - applied : 0;
  const { owed } = owedBy(rows, overTo);
  const extraOk = over <= 0 || (extra === "BUDGET" ? !!budget : extra === "REFUND" ? !!overTo : extra === "CREDIT" ? !!overTo && owed === 0 : false);
  const customers = [...new Set(rows.filter((r) => r.on).map((r) => r.customer_entity_id))];
  const ready = rows.some((r) => r.on && (cents(r.amount) || 0) > 0) && total !== null && total > 0 && !bad && over >= 0 && extraOk && !!v.bank_account_id;
  const paidRows = rows.filter((r) => r.on && (cents(r.amount) || 0) > 0);
  const target = paidRows.some((r) => String(r.id) === overTo) ? overTo : paidRows.length ? String(paidRows[paidRows.length - 1].id) : "";
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    const items = paidRows.map((r) => ({ invoice_id: r.id, amount: r.amount }));
    try {
      const r = await run((codes) => api.post("/api/invoices/payments", {
        bank_account_id: Number(v.bank_account_id), transaction_date: v.transaction_date || null, notes: v.notes || null, items,
        payer_entity_id: payer ? Number(payer) : null,
        ...(over > 0 ? { overpayment: show(over), overpayment_kind: extra,
          ...(extra === "BUDGET" ? { overpayment_budget_id: Number(budget) } : { overpayment_invoice_id: Number(target) }) } : {}),
        confirm_overpayment: codes.includes("OVERPAYMENT"), confirmations: codes.filter((c) => c !== "OVERPAYMENT"),
      }));
      if (!r) return;
      if (over > 0 && extra === "REFUND") {
        setRefund({ invoice_id: Number(target), number: rows!.find((x) => String(x.id) === target)?.number || "", amount: show(over) });
      } else onDone();
    } catch (x) { setErr(x); }
  }
  const setRow = (id: number, patch: Partial<Row>) => setRows(rows.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  const many = customers.length > 1 || [...new Set(rows.map((r) => r.customer_entity_id))].length > 1;
  return (
    <Modal title="Record a payment" onClose={onClose} wide>
      <form onSubmit={submit} data-testid="multi-payment">
        <ErrorBox error={err} />
        <p className="hint">One deposit for a check or transfer that pays one or more invoices. Each invoice's part is spread over its lines'
          Invoiced Income budgets and tax.</p>
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
        {credit ? <p className="hint" data-testid="multi-payment-credit">This customer has {money(credit.total)} of account credit (overpayments on{" "}
          {credit.invoices.map((x: any) => x.number).join(", ")}). It is applied when their next invoice is sent, or refunded on that invoice.</p> : null}
        {rows.length ? (
          <>
            <Field label="Amount received" hint="Fills the ticked balances oldest due date first; change any invoice's part below.">
              <input aria-label="Amount received" required inputMode="decimal" value={received}
                onChange={(e) => { setReceived(e.target.value); const c = cents(e.target.value); if (c !== null) setRows(spread(rows, c)); }} />
            </Field>
            <table className="table compact" data-testid="multi-payment-invoices">
              <thead><tr><th /><th>Invoice</th>{many ? <th>Customer</th> : null}<th>Due</th><th className="num">Open</th><th className="num">This payment</th></tr></thead>
              <tbody>{rows.map((r) => (
                <tr key={r.id}>
                  <td><input type="checkbox" aria-label={`Include ${r.number}`} checked={r.on}
                    onChange={(e) => { const next = rows.map((x) => (x.id === r.id ? { ...x, on: e.target.checked } : x)); setRows(total !== null ? spread(next, total) : next); }} /></td>
                  <td>{r.number}</td>{many ? <td>{r.customer}</td> : null}<td>{r.due_date}</td>
                  <td className="num">{money(r.open)}</td>
                  <td className="num"><input aria-label={`Amount for ${r.number}`} inputMode="decimal" disabled={!r.on} value={r.amount} style={{ width: "8em", textAlign: "right" }}
                    onChange={(e) => setRow(r.id, { amount: e.target.value })} /></td>
                </tr>))}</tbody>
              <tfoot><tr><td colSpan={many ? 5 : 4}>Applied to invoices</td><td className="num" data-testid="multi-applied">{money(show(applied))}</td></tr></tfoot>
            </table>
            {bad ? <p className="error" role="alert">An invoice's part can't be more than its open balance.</p> : null}
            {total !== null && over < 0 ? <p className="error" role="alert">The parts add up to {money(show(applied))}, more than the {money(show(total))} received.</p> : null}
            {over > 0 && paidRows.length ? (
              <ExtraChoices left={over} rows={rows} extra={extra} setExtra={setExtra} overTo={target} setOverTo={setOverTo}
                onOthers={() => { if (total !== null) setRows(tickAll(rows, total)); setExtra(""); }}
                budgetLabel="Kept on a budget (e.g. a donation or a fundraiser)"
                budgetPicker={<Field label="Budget"><select aria-label="Budget for the rest" required value={budget} onChange={(e) => setBudget(e.target.value)}>
                  <option value="">Choose…</option>{budgets.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}</select></Field>} />
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

/** #544: refund an overpayment - a withdrawal linked to the invoice. Opened after a payment whose extra is to be
 *  refunded (pre-filled), or from "Refund credit…" on the invoice. Cancelled, the overpayment stays the customer's. */
export function RefundForm({ invoiceId, number, amount, bankAccountId, date, afterPayment, onClose, onDone }: {
  invoiceId: number; number: string; amount: string; bankAccountId?: string; date?: string; afterPayment?: boolean;
  onClose: () => void; onDone: (invoice: any) => void;
}) {
  const accts = useAccounts();
  const { run, dialog } = useConfirmable();
  const [err, setErr] = useState<unknown>(null);
  const [v, setV] = useState({ bank_account_id: bankAccountId || "", amount, transaction_date: date || todayIso(), check_number: "", notes: "" });
  useEffect(() => {
    const start = accts.length === 1 ? accts[0] : accts.find((a) => a.is_primary);
    if (start && !v.bank_account_id) setV((x) => ({ ...x, bank_account_id: String(start.id) }));
  }, [accts]); // eslint-disable-line react-hooks/exhaustive-deps
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const r: any = await run((codes) => api.post(`/api/invoices/${invoiceId}/refunds`, {
        bank_account_id: Number(v.bank_account_id), amount: v.amount, transaction_date: v.transaction_date || null,
        check_number: v.check_number || null, notes: v.notes || null, confirmations: codes }));
      if (r) onDone(r.invoice);
    } catch (x) { setErr(x); }
  }
  return (
    <Modal title={`Refund – ${number}`} onClose={onClose}>
      <form onSubmit={submit} data-testid="refund-form">
        <ErrorBox error={err} />
        {afterPayment ? <p className="alert info" role="status">The payment is recorded. Its {money(amount)} above the invoices is an overpayment on {number}:
          record the refund now. If you cancel, it stays the customer's credit and can be refunded from the invoice later.</p> : null}
        <p className="hint">A withdrawal to the customer, linked to invoice {number}, that reduces its Invoiced Income budget (up to {money(amount)}).</p>
        <Field label="Bank account"><select required value={v.bank_account_id} onChange={(e) => setV({ ...v, bank_account_id: e.target.value })}>
          <option value="">Choose…</option>{accts.map((a) => <option key={a.id} value={a.id}>{a.label || `${a.account_name} - ${a.account_number_masked}`}</option>)}</select></Field>
        <Field label="Amount"><input aria-label="Refund amount" required inputMode="decimal" value={v.amount} onChange={(e) => setV({ ...v, amount: e.target.value })} /></Field>
        <Field label="Date"><input type="date" required value={v.transaction_date} onChange={(e) => setV({ ...v, transaction_date: e.target.value })} /></Field>
        <Field label="Check number"><input aria-label="Refund check number" maxLength={20} value={v.check_number} onChange={(e) => setV({ ...v, check_number: e.target.value })} /></Field>
        <Field label="Notes"><textarea rows={2} maxLength={4000} value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>{afterPayment ? "Not now" : "Cancel"}</button>
          <button className="primary" type="submit">Record refund</button></div>
      </form>
      {dialog}
    </Modal>
  );
}

// ------------------------------------------------------------------ 2.4.0 (#533): Apply to invoice (Register form)
export type Applied = { invoices: { invoice_id: number; number: string; amount: string }[]; extra: Extra; extra_invoice_id: string };

/** The open invoices of the allocation's entity; the allocation's amount fills them oldest due date first; the extra
 *  above them (#544) stays on the line's budget, goes to the other open invoices, is the customer's credit (never
 *  while they owe) or is refunded - the Refund form opens once the deposit is saved. */
export function ApplyToInvoiceModal({ entityId, entityName, amount, current, onClose, onApply }: {
  entityId: string; entityName: string; amount: string; current?: Applied; onClose: () => void; onApply: (a: Applied | null) => void;
}) {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [total, setTotal] = useState(amount);
  const [extra, setExtra] = useState<Extra>(current?.extra || "BUDGET");
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
  const paidRows = rows.filter((r) => r.on && (cents(r.amount) || 0) > 0);
  const target = paidRows.some((r) => String(r.id) === overTo) ? overTo : paidRows.length ? String(paidRows[paidRows.length - 1].id) : "";
  const { owed } = owedBy(rows, target);
  const ok = t !== null && applied > 0 && !bad && left >= 0 && (left === 0 || extra === "BUDGET" || extra === "REFUND" || (extra === "CREDIT" && owed === 0));
  const apply = () => onApply({
    invoices: paidRows.map((r) => ({ invoice_id: r.id, number: r.number, amount: show(cents(r.amount) || 0) })),
    extra: left > 0 ? extra : "", extra_invoice_id: target,
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
            {left > 0 && paidRows.length ? (
              <ExtraChoices left={left} rows={rows} extra={extra} setExtra={setExtra} overTo={target} setOverTo={setOverTo}
                onOthers={() => { if (t !== null) setRows(tickAll(rows, t)); }}
                budgetLabel="Kept on this allocation's budget (e.g. a fundraiser or a donation)" />
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
