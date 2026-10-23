/** 2.0.0 (#164): Payments (Payments module, Register Users).
 *
 * New payment: the register's transaction form in payment mode (one line per invoice, payee search with "New entity",
 * documents per invoice or for the whole payment, the check amount previewed in numbers and words). Saving creates the
 * register transaction through the normal register API and opens the print screen; closing it is fine - the check can
 * be printed later. The bank account of the last payment is remembered per user.
 *
 * A withdrawal already in the register is paid with Create payment… in its details there (the same print screen, in a
 * dialog over the register); build 13 removed the separate /payments?txn=<id> page (product owner, 2026-10-14).
 * The module stores nothing about payments: the list below is the record copies of printed checks. */
import { useEffect, useState } from "react";
import { api, money } from "../api";
import { ErrorBox, Field, Loading } from "../components";
import { Link } from "../router";
import { PrintCheckDialog } from "./CheckPrint";
import { TxnForm } from "./Register";
import { useMe } from "../App";

export default function Payments() {
  const { can } = useMe();   // build 13: hidden while maintenance mode pauses changes
  const [accounts, setAccounts] = useState<any[] | null>(null);
  const [fys, setFys] = useState<any[]>([]);
  const [acctId, setAcctId] = useState("");
  const [opts, setOpts] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [form, setForm] = useState(false);
  const [printing, setPrinting] = useState<any>(null);
  const [recent, setRecent] = useState<any[] | null>(null);
  useEffect(() => {
    Promise.all([api.get("/api/bank-accounts"), api.get("/api/fiscal-years"), api.get("/api/checks/payments/options")]).then(([a, y, o]) => {
      const reg = a.filter((x: any) => x.register_enabled && x.status === "ACTIVE");
      setAccounts(reg);
      setFys(y);
      setOpts(o);
      const first = reg.find((x: any) => x.id === o.last_bank_account_id) || reg.find((x: any) => x.is_primary) || reg[0];
      setAcctId(first ? String(first.id) : "");
    }, setErr);
  }, []);
  const loadRecent = () => { if (acctId) api.get(`/api/checks/payments/recent?bank_account_id=${acctId}`).then(setRecent, setErr); };
  useEffect(() => { loadRecent(); }, [acctId]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!accounts) return <><ErrorBox error={err} /><Loading /></>;
  const acct = accounts.find((a) => String(a.id) === acctId);
  const saved = async (t: any) => {
    setForm(false);
    if (!t) return;
    api.put("/api/checks/payments/last-account", { bank_account_id: t.bank_account?.id ?? acct?.id }).catch(() => undefined);
    setPrinting(t);
    loadRecent();
  };

  return (
    <div className="payments">
      <h1>Payments</h1>
      <p className="hint">Enter a bill once: PennyWarden records it in the register (one line per invoice) and opens the check to print.</p>
      <ErrorBox error={err} />
      {opts && !opts.styles_available ? <div className="alert warn">No check styles are set up yet. Ask an Administrator to set up check styles in Payments Setup first.</div> : null}
      {!accounts.length ? <p className="muted">No active register bank accounts.</p> : (
        <div className="page-head">
          <Field label="Pay from">
            <select aria-label="Pay from bank account" value={acctId} onChange={(e) => setAcctId(e.target.value)}>
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}
            </select>
          </Field>
          {can("checks.print") ? <button className="primary" onClick={() => setForm(true)} disabled={!acct}>New payment</button> : null}
        </div>
      )}
      <section className="card" aria-labelledby="recent-h">
        <h2 id="recent-h">Recently printed checks{acct ? ` – ${acct.label}` : ""}</h2>
        {recent === null ? <Loading /> : recent.length === 0 ? <p className="muted">No checks printed from this account yet.</p> : (
          <table className="table compact">
            <thead><tr><th>Check #</th><th>Date</th><th>Payee</th><th className="num">Amount</th><th>Printed</th><th /></tr></thead>
            <tbody>
              {recent.map((r) => (
                <tr key={r.transaction_id}>
                  <td>{r.check_number}</td><td>{r.transaction_date}</td><td>{r.payee}</td><td className="num">{money(r.amount)}</td>
                  <td>{r.printed_at.slice(0, 10)}{r.status !== "ACTIVE" ? <span className="badge red">{r.status}</span> : null}</td>
                  <td className="actions-cell">
                    <Link to={`/register?account=${acct ? acct.id : ""}&txn=${r.transaction_id}`} className="small-link">Open in register</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
      {form && acct ? <TxnForm account={acct} txn={null} fys={fys} payment onClose={() => setForm(false)} onSaved={saved} /> : null}
      {printing ? <PrintCheckDialog txn={printing} onClose={() => { setPrinting(null); loadRecent(); }} onChanged={loadRecent} /> : null}
    </div>
  );
}
