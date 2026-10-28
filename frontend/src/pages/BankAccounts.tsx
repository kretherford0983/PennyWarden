import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, money, todayIso } from "../api";
import { ErrorBox, Field, Loading, Modal, GuardedForm, RowMenu } from "../components";
import { useMe } from "../App";
import { EntityForm } from "./Entities";

const TYPES = ["CHECKING", "SAVINGS", "MONEY_MARKET", "CERTIFICATE_OF_DEPOSIT", "INVESTMENT", "CASH", "OTHER"];
const GROUPS: [string, string][] = [["CHECKING_SAVINGS", "Checking & Savings"], ["INVESTMENTS_OTHER", "Investments and Other"]];
const REG_DEFAULT: Record<string, boolean> = { CHECKING: true, SAVINGS: true, INVESTMENT: false };

export default function BankAccounts() {
  const { can } = useMe();
  const [list, setList] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [modal, setModal] = useState<any>(null);
  const [revealed, setRevealed] = useState<Record<number, string>>({});
  const load = () => api.get("/api/bank-accounts").then(setList, setErr);
  useEffect(() => { load(); }, []);
  const manage = can("bank_account.manage");
  const reveal = async (a: any) => {
    if (revealed[a.id]) { const r = { ...revealed }; delete r[a.id]; setRevealed(r); return; }
    try {
      const r = await api.post(`/api/bank-accounts/${a.id}/reveal`);
      setRevealed({ ...revealed, [a.id]: r.account_number });
    } catch (e) { setErr(e); }
  };
  const primary = async (a: any) => { try { await api.post(`/api/bank-accounts/${a.id}/set-primary`); load(); } catch (e) { setErr(e); } };
  // 1.7.1 (#74): Budget Managers set the order within each group (used here, on the Dashboard and in the Register).
  // After a move the focus stays on the moved account's button and the new position is announced.
  const [announce, setAnnounce] = useState("");
  const refocus = useRef<{ id: number; dir: string } | null>(null);
  const move = async (a: any, dir: "up" | "down") => {
    try {
      const r = await api.post(`/api/bank-accounts/${a.id}/move`, { direction: dir });
      refocus.current = { id: a.id, dir };
      setList(await api.get("/api/bank-accounts"));
      const label = GROUPS.find(([k]) => k === r.group)?.[1] || "";
      setAnnounce(`${a.account_name} moved to position ${r.position} of ${r.group_size} in ${label}.`);
    } catch (e) { setErr(e); }
  };
  useEffect(() => {
    const t = refocus.current;
    if (!t) return;
    refocus.current = null;
    const btn = (d: string) => document.querySelector<HTMLButtonElement>(`[data-move="${t.id}-${d}"]`);
    const b = btn(t.dir);
    (b && !b.disabled ? b : btn(t.dir === "up" ? "down" : "up"))?.focus();
  }, [list]);
  const renderRow = (a: any, i: number, rows: any[]) => (
            <tr key={a.id} className={a.status === "CLOSED" ? "inactive" : ""}>
              {manage ? (
                <td className="order-cell">
                  <button type="button" className="small icon" data-move={`${a.id}-up`} disabled={i === 0}
                          aria-label={`Move ${a.account_name} up`} title="Move up" onClick={() => move(a, "up")}>▲</button>
                  <button type="button" className="small icon" data-move={`${a.id}-down`} disabled={i === rows.length - 1}
                          aria-label={`Move ${a.account_name} down`} title="Move down" onClick={() => move(a, "down")}>▼</button>
                </td>
              ) : null}
              <td>{a.account_name}</td>
              <td><code>{revealed[a.id] || a.account_number_masked}</code>{can("bank_account.reveal") ? <button className="small" onClick={() => reveal(a)}>{revealed[a.id] ? "Hide" : "Reveal"}</button> : null}</td>
              <td>{a.financial_institution?.display_name}</td><td>{a.account_type}{a.account_subtype ? ` / ${a.account_subtype}` : ""}</td>
              <td>{a.register_enabled ? "Yes" : "No"}</td><td>{a.is_primary ? "Primary" : ""}</td>
              <td className="num">{money(a.current_balance)}{!a.register_enabled ? (
                <div><button type="button" className="link small-link" onClick={() => setModal({ kind: "history", account: a })}
                  aria-label={`Balance history of ${a.account_name}`}>History</button></div>
              ) : null}</td><td>{a.status === "ACTIVE" ? "Active" : `Closed ${a.closed_date || ""}`}</td>
              {manage ? (
                <td className="actions-cell">
                  {a.status === "ACTIVE" ? (
                    <>
                      <button className="small" onClick={() => setModal({ kind: "edit", account: a })}>Edit</button>
                      <RowMenu name={a.account_name} actions={[
                        a.register_enabled && !a.is_primary && { label: "Make primary", onClick: () => primary(a) },
                        !a.register_enabled && { label: "Update balance", onClick: () => setModal({ kind: "balance", account: a }) },
                        { label: "Close…", onClick: () => setModal({ kind: "close", account: a }), danger: true },
                      ]} />
                    </>
                  ) : null}
                </td>
              ) : null}
            </tr>
  );
  if (!list) return <><ErrorBox error={err} /><Loading /></>;
  return (
    <div>
      <div className="page-head">
        <h1>Bank Accounts</h1>
        {manage ? <button className="primary" onClick={() => setModal({ kind: "edit", account: null })}>New bank account</button> : null}
      </div>
      <ErrorBox error={err} />
      {manage ? <p className="hint">Use ▲ and ▼ to set the order of the accounts in each group. The same order is used on the Dashboard and in the Register.</p> : null}
      <div className="sr-only" role="status" aria-live="polite" data-testid="order-status">{announce}</div>
      {/* v1.5.0 CR-028: one table per group, each with a total of its active accounts */}
      {GROUPS.map(([key, label]) => {
        const rows = list.filter((a) => a.group === key);
        const total = rows.filter((a) => a.status === "ACTIVE").reduce((t, a) => t + Math.round(Number(a.current_balance) * 100), 0);
        return (
          <section key={key} className="account-group" aria-labelledby={`grp-${key}`}>
            <h2 id={`grp-${key}`}>{label}</h2>
            <table className="table" data-testid={`accounts-${key}`}>
              <thead><tr>{manage ? <th className="order-cell">Order</th> : null}<th>Account</th><th>Account #</th><th>Financial Institution</th><th>Type</th><th>Register</th><th>Primary</th><th className="num">Current balance</th><th>Status</th>{manage ? <th /> : null}</tr></thead>
              <tbody>
                {rows.length === 0 ? <tr><td colSpan={manage ? 10 : 8} className="muted">No accounts in this group.</td></tr> : null}
                {rows.map(renderRow)}
              </tbody>
              {rows.length ? (
                <tfoot><tr className="total-row"><th colSpan={manage ? 7 : 6} scope="row">Total {label}{rows.some((a) => a.status !== "ACTIVE") ? " (active accounts)" : ""}</th>
                  <th className={`num ${total < 0 ? "neg" : ""}`}>{money((total / 100).toFixed(2))}</th><th colSpan={manage ? 2 : 1} /></tr></tfoot>
              ) : null}
            </table>
          </section>
        );
      })}
      {modal?.kind === "edit" ? <AccountForm account={modal.account} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} /> : null}
      {modal?.kind === "history" ? <HistoryDialog account={modal.account} onClose={() => setModal(null)} /> : null}
      {modal?.kind === "balance" ? <BalanceForm account={modal.account} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} /> : null}
      {modal?.kind === "close" ? <CloseForm account={modal.account} onClose={() => setModal(null)} onSaved={() => { setModal(null); load(); }} /> : null}
    </div>
  );
}

function AccountForm({ account, onClose, onSaved }: any) {
  const isNew = !account;
  const [fis, setFis] = useState<any[]>([]);
  const [newFi, setNewFi] = useState(false);
  const [f, setF] = useState<any>(isNew ? { account_name: "", financial_institution_entity_id: "", account_type: "CHECKING", account_subtype: "", account_number: "",
    register_enabled: true, is_primary: false, interest_rate: "", opening_balance: "0.00", opening_balance_date: todayIso(), current_balance: "0.00", account_opened_date: "", notes: "" }
    : { ...account, account_number: "", interest_rate: account.interest_rate || "", account_subtype: account.account_subtype || "", account_opened_date: account.account_opened_date || "", notes: account.notes || "" });
  const [err, setErr] = useState<unknown>(null);
  const loadFis = () => api.get("/api/entities?financial_institution=true").then(setFis);
  useEffect(() => { loadFis(); }, []);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const setType = (t: string) => setF({ ...f, account_type: t, register_enabled: isNew ? (REG_DEFAULT[t] ?? false) : f.register_enabled });
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setErr(null);
    try {
      if (isNew) {
        await api.post("/api/bank-accounts", {
          account_name: f.account_name, financial_institution_entity_id: Number(f.financial_institution_entity_id), account_type: f.account_type,
          account_subtype: f.account_subtype || null, account_number: f.account_number, register_enabled: f.register_enabled,
          is_primary: f.register_enabled && f.is_primary, interest_rate: f.interest_rate || null, notes: f.notes || null,
          account_opened_date: f.account_opened_date || null,
          ...(f.register_enabled ? { opening_balance: f.opening_balance, opening_balance_date: f.opening_balance_date } : { current_balance: f.current_balance }),
        });
      } else {
        const body: any = { account_name: f.account_name, financial_institution_entity_id: Number(f.financial_institution_entity_id),
          account_type: f.account_type, account_subtype: f.account_subtype || null, interest_rate: f.interest_rate || null, notes: f.notes || null,
          account_opened_date: f.account_opened_date || null };
        if (f.account_number) body.account_number = f.account_number;
        if (!account.has_transactions && f.register_enabled) { body.opening_balance = f.opening_balance; body.opening_balance_date = f.opening_balance_date; }
        await api.patch(`/api/bank-accounts/${account.id}`, body);
      }
      onSaved();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={isNew ? "New bank account" : `Edit ${account.account_name}`} onClose={onClose} wide>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Account name"><input required value={f.account_name} onChange={set("account_name")} /></Field>
        <Field label="Financial Institution" hint="Only Entities flagged as Financial Institutions are listed.">
          <div className="row">
            <select required value={f.financial_institution_entity_id} onChange={set("financial_institution_entity_id")}>
              <option value="">— select —</option>
              {fis.map((e) => <option key={e.id} value={e.id}>{e.display_name} ({e.entity_number})</option>)}
            </select>
            <button type="button" className="small" onClick={() => setNewFi(true)}>+ New institution</button>
          </div>
        </Field>
        <div className="row">
          <Field label="Type"><select value={f.account_type} onChange={(e) => setType(e.target.value)}>{TYPES.map((t) => <option key={t}>{t}</option>)}</select></Field>
          <Field label="Subtype (optional)"><input value={f.account_subtype} onChange={set("account_subtype")} /></Field>
        </div>
        <Field label={isNew ? "Full account number" : "New full account number (leave blank to keep)"} hint="Encrypted at rest; displayed masked.">
          <input required={isNew} autoComplete="off" value={f.account_number} onChange={set("account_number")} />
        </Field>
        {isNew ? <label className="check"><input type="checkbox" checked={f.register_enabled} onChange={set("register_enabled")} /> Register enabled</label> : <p>Register enabled: {f.register_enabled ? "Yes" : "No"}</p>}
        {isNew && f.register_enabled ? <label className="check"><input type="checkbox" checked={f.is_primary} onChange={set("is_primary")} /> Primary register account</label> : null}
        <Field label="Interest rate % (optional)"><input inputMode="decimal" value={f.interest_rate} onChange={set("interest_rate")} /></Field>
        {f.register_enabled ? (
          <div className="row">
            <Field label="Opening balance"><input disabled={!isNew && account.has_transactions} value={f.opening_balance} onChange={set("opening_balance")} /></Field>
            <Field label="Opening balance date"><input type="date" disabled={!isNew && account.has_transactions} value={f.opening_balance_date || ""} onChange={set("opening_balance_date")} /></Field>
          </div>
        ) : isNew ? <Field label="Current balance (manually maintained)"><input value={f.current_balance} onChange={set("current_balance")} /></Field> : null}
        <Field label="Account opened (optional)" hint="Leave blank if the account existed before PennyWarden. Report comparisons to a date before it show $0; otherwise a date before any data uses the earliest data.">
          <input type="date" aria-label="Account opened" value={f.account_opened_date || ""} onChange={set("account_opened_date")} />
        </Field>
        <Field label="Notes"><textarea value={f.notes} onChange={set("notes")} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
      {newFi ? <EntityForm entity={{ entity_type: "ORGANIZATION" }} forceFi onClose={() => setNewFi(false)} onSaved={(e) => { setNewFi(false); loadFis().then(() => setF((p: any) => ({ ...p, financial_institution_entity_id: e.id }))); /* 1.7.1: the form as it is NOW - not as it was when the institution was saved */ }} /> : null}
    </Modal>
  );
}

function BalanceForm({ account, onClose, onSaved }: any) {
  const [v, setV] = useState(account.current_balance);
  const [asOf, setAsOf] = useState(todayIso()); // 1.7.3 (#88): e.g. a month-end statement date
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post(`/api/bank-accounts/${account.id}/balance`, { current_balance: v, reason: reason || null, as_of_date: asOf }); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Update balance: ${account.account_name}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Balance"><input required value={v} onChange={(e) => setV(e.target.value)} /></Field>
        <Field label="As of" hint="The date of this balance, e.g. the statement date. Today or earlier."><input required type="date" max={todayIso()} value={asOf} onChange={(e) => setAsOf(e.target.value)} /></Field>
        <Field label="Reason"><input value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <p className="hint">Each update is kept in the balance history and audited. To correct a wrong entry, enter the right balance for the same date.</p>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

function CloseForm({ account, onClose, onSaved }: any) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post(`/api/bank-accounts/${account.id}/close`, { reason }); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Close ${account.account_name}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <p>Current balance: <b>{money(account.current_balance)}</b> · Uncleared transactions: <b>{account.uncleared_count}</b></p>
        <p className="hint">An account can be closed only with no uncleared transactions and a balance of exactly $0.00{account.register_enabled ? ", reached through register activity" : ", set through an audited balance update"}.</p>
        <Field label="Reason (required)"><input required value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary danger" type="submit">Close account</button></div>
      </GuardedForm>
    </Modal>
  );
}


// 1.7.3 (#88): dated balance history of a non-register account (newest first)
function HistoryDialog({ account, onClose }: { account: any; onClose: () => void }) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get(`/api/bank-accounts/${account.id}/balance-history`).then(setRows, setErr); }, [account.id]);
  return (
    <Modal title={`Balance history: ${account.account_name}`} onClose={onClose} wide>
      <ErrorBox error={err} />
      {!rows ? <Loading /> : (
        <table className="table" data-testid="balance-history">
          <thead><tr><th>As of</th><th className="num">Balance</th><th className="num">Change</th><th>Entered by</th><th>Entered on</th><th>Reason</th></tr></thead>
          <tbody>
            {rows.length === 0 ? <tr><td colSpan={6} className="muted">No balance entries.</td></tr> : null}
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{r.as_of_date}</td><td className="num">{money(r.balance)}</td>
                <td className={`num ${r.change && Number(r.change) < 0 ? "neg" : ""}`}>{r.change === null ? "" : `${Number(r.change) > 0 ? "+" : ""}${money(r.change)}`}</td>
                <td>{r.entered_by || (r.source === "UPGRADE" ? "(upgrade)" : "")}</td><td>{r.entered_at.slice(0, 10)}</td><td>{r.reason || ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="actions"><button type="button" onClick={onClose}>Close</button></div>
    </Modal>
  );
}
