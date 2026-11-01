// 1.8.0 (#106): Financial Flow Report - parameters, then a review form (lines can be excluded with a reason and given
// a note for the report), then the PDF. Nothing is saved: leaving the form discards the review.
import { Fragment, useMemo, useState, type FormEvent } from "react";
import { api, ApiError, money } from "../api";
import { ErrorBox, Field, GuardedForm, Modal } from "../components";

type Line = { key: string; transaction_id: number; date: string; amount: string; description: string };
type Section = { id: number; label: string; income: Line[]; expense: Line[] };

const cents = (v: string) => Math.round(Number(v) * 100);
const fromCents = (c: number) => (c / 100).toFixed(2);
const usDate = (iso: string) => `${iso.slice(5, 7)}/${iso.slice(8, 10)}/${iso.slice(0, 4)}`;

export function Signed({ c }: { c: number }) {
  const cls = c > 0 ? "amount-up" : c < 0 ? "amount-down" : "";
  const txt = c > 0 ? `+${money(fromCents(c))}` : c < 0 ? `−${money(fromCents(-c))}` : money("0");
  return <b className={cls}>{txt}</b>;
}

export default function FlowReport({ accounts, initial = {}, onRun }: { accounts: any[]; initial?: Record<string, any>; onRun?: (params: Record<string, any>, label: string) => void }) {
  const open = accounts.filter((a) => a.status === "ACTIVE");
  // 2.3.0 (#375): the user's last title and dates are filled in (notes and the balance options are not remembered)
  const [p, setP] = useState({ title: String(initial.title || ""), date_from: String(initial.date_from || ""), date_to: String(initial.date_to || ""),
    include_balances: false, compare_date: "", notes: "", show_substitution_notes: false });
  const [ids, setIds] = useState<number[]>(open.map((a) => a.id));
  const [review, setReview] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const params = () => ({
    title: p.title, date_from: p.date_from, date_to: p.date_to || null, bank_account_ids: ids,
    include_balances: p.include_balances, compare_date: p.include_balances && p.compare_date ? p.compare_date : null, notes: p.notes || null,
    show_substitution_notes: p.include_balances && !!p.compare_date && p.show_substitution_notes,
  });
  const fieldErr = (f: string) => (err instanceof ApiError ? err.fieldErrors.find((x) => x.field === f)?.message : undefined);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      setReview({ data: await api.post("/api/reports/financial-flow/review", params()), params: params() });
      onRun?.({ title: p.title, date_from: p.date_from, date_to: p.date_to },
        `${p.title || "Financial Flow"} · ${p.date_from}${p.date_to ? ` – ${p.date_to}` : ""}`);
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  if (review) return <FlowReview review={review} onBack={() => setReview(null)} />;
  return (
    <>
      <p>The money that came in and went out of the chosen accounts in a period: every income and every expense with
        their totals and the Difference, one section per account. Transfers between accounts and VOID transactions are
        not listed. You review the lines before the PDF is made. Optionally adds the balance of every account.</p>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <div className="report-options">
          <Field label="Title"><input required maxLength={120} placeholder="e.g. August 2026" value={p.title} onChange={(e) => setP({ ...p, title: e.target.value })} /></Field>
          <Field label="From Date"><input type="date" required value={p.date_from} onChange={(e) => setP({ ...p, date_from: e.target.value })} /></Field>
          <Field label="Through Date" hint="Empty: today, printed as “Current”."><input type="date" value={p.date_to} onChange={(e) => setP({ ...p, date_to: e.target.value })} /></Field>
        </div>
        <fieldset className="account-picks">
          <legend>Account(s)</legend>
          {accounts.map((a) => (
            <label key={a.id} className="check">
              <input type="checkbox" checked={ids.includes(a.id)}
                     onChange={(e) => setIds(e.target.checked ? accounts.filter((x) => x.id === a.id || ids.includes(x.id)).map((x) => x.id) : ids.filter((x) => x !== a.id))} />
              {" "}{a.label}{a.status !== "ACTIVE" ? " (closed)" : ""}
            </label>
          ))}
          {!ids.length ? <p className="hint">Choose at least one account.</p> : null}
        </fieldset>
        <div className="report-options">
          <label className="check"><input type="checkbox" checked={p.include_balances} onChange={(e) => setP({ ...p, include_balances: e.target.checked })} /> Include Bank Balances</label>
          <Field label="Compare Date" hint={fieldErr("compare_date") || "Optional: shows each balance on this date and the change. Earlier than the Through Date."}>
            <input type="date" aria-label="Compare Date" disabled={!p.include_balances} value={p.compare_date} aria-invalid={fieldErr("compare_date") ? true : undefined}
                   onChange={(e) => setP({ ...p, compare_date: e.target.value })} />
          </Field>
          <label className="check" title="When an account has no data on the Compare Date, its earliest data is used instead of $0. This prints a note for each one.">
            <input type="checkbox" disabled={!p.include_balances || !p.compare_date} checked={p.show_substitution_notes}
                   onChange={(e) => setP({ ...p, show_substitution_notes: e.target.checked })} /> Show notes on substituted starting values</label>
        </div>
        <Field label="Notes" hint="Printed on the report."><textarea maxLength={4000} value={p.notes} onChange={(e) => setP({ ...p, notes: e.target.value })} /></Field>
        <div className="actions left"><button className="primary" type="submit" disabled={busy || !ids.length}>Review transactions</button></div>
      </GuardedForm>
    </>
  );
}

function FlowReview({ review, onBack }: { review: any; onBack: () => void }) {
  const data = review.data;
  const [excluded, setExcluded] = useState<Record<string, string>>({});   // key -> reason
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [asking, setAsking] = useState<{ line: Line; reason: string } | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [pdf, setPdf] = useState<{ url: string; name: string } | null>(null);
  const totals = useMemo(() => {
    const sum = (l: Line[]) => l.filter((x) => !(x.key in excluded)).reduce((s, x) => s + cents(x.amount), 0);
    return data.sections.map((s: Section) => ({ inc: sum(s.income), exp: sum(s.expense) }));
  }, [data, excluded]);
  const toggle = (line: Line, checked: boolean) => {
    if (checked) {  // checking the line again discards its reason
      const { [line.key]: _, ...rest } = excluded;
      setExcluded(rest);
    } else setAsking({ line, reason: "" });
  };
  const generate = async () => {
    setErr(null);
    setBusy(true);
    try {
      const body = {
        ...review.params,
        exclusions: Object.entries(excluded).map(([key, reason]) => ({ key, reason })),
        line_notes: Object.entries(notes).filter(([, n]) => n.trim()).map(([key, note]) => ({ key, note })),
      };
      const blob = await api.postBlob("/api/reports/financial-flow", body);
      if (pdf) URL.revokeObjectURL(pdf.url);
      const safe = (review.params.title || "report").replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-|-$/g, "").slice(0, 60) || "report";
      setPdf({ url: URL.createObjectURL(blob), name: `financial-flow-${safe}.pdf` });
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const lineRows = (lines: Line[], empty: string) => (
    lines.length ? lines.map((x) => {
      const off = x.key in excluded;
      return (
        <tr key={x.key} className={off ? "excluded" : ""} data-testid={`flow-line-${x.key}`}>
          <td><input type="checkbox" aria-label={`Include ${usDate(x.date)} ${money(x.amount)} ${x.description}`} checked={!off} onChange={(e) => toggle(x, e.target.checked)} /></td>
          <td>{usDate(x.date)}</td><td className="num">{money(x.amount)}</td><td>{x.description}</td>
          <td>
            {off ? (
              <span className="muted">Excluded: {excluded[x.key]} <button type="button" className="link small" onClick={() => setAsking({ line: x, reason: excluded[x.key] })}>Edit reason</button></span>
            ) : (
              <input aria-label={`Note for ${usDate(x.date)} ${money(x.amount)}`} maxLength={1000} placeholder="Note for the report (optional)"
                     value={notes[x.key] || ""} onChange={(e) => setNotes({ ...notes, [x.key]: e.target.value })} />
            )}
          </td>
        </tr>
      );
    }) : <tr><td colSpan={5} className="muted">{empty}</td></tr>
  );
  const allInc = totals.reduce((s: number, t: any) => s + t.inc, 0);
  const allExp = totals.reduce((s: number, t: any) => s + t.exp, 0);
  return (
    <section className="card flow-review">
      <div className="row space-between">
        <h2>{data.title} — Financial Flow Report · {data.period}</h2>
        <button type="button" onClick={onBack}>Change parameters</button>
      </div>
      <p className="hint">Uncheck a line to leave it out of the report and its totals (a reason is asked for; it is recorded in the
        audit log, never printed). A note typed on a line is printed with it; the transaction itself is not changed.
        Leaving this page discards the review.</p>
      <ErrorBox error={err} />
      {data.sections.map((s: Section, i: number) => (
        <div key={s.id} className="flow-section" data-testid={`flow-section-${s.id}`}>
          <h3>{s.label}</h3>
          {(["income", "expense"] as const).map((k) => (
            <Fragment key={k}>
              <h4>{k === "income" ? "Income" : "Expenses"}</h4>
              <div className="table-wrap">
                <table className="table" aria-label={`${s.label} ${k === "income" ? "income" : "expenses"}`}>
                  <thead><tr><th>Include</th><th>Date</th><th className="num">Amount</th><th>Description</th><th>Note</th></tr></thead>
                  <tbody>{lineRows(s[k], k === "income" ? "No income in this period" : "No expenses in this period")}</tbody>
                  <tfoot><tr><td /><td><b>Total</b></td><td className="num"><b data-testid={`flow-total-${s.id}-${k}`}>{money(fromCents(k === "income" ? totals[i].inc : totals[i].exp))}</b></td><td colSpan={2} /></tr></tfoot>
                </table>
              </div>
            </Fragment>
          ))}
          <p className="flow-diff" data-testid={`flow-diff-${s.id}`}>Difference: <Signed c={totals[i].inc - totals[i].exp} /></p>
        </div>
      ))}
      {data.sections.length > 1 ? (
        <div className="flow-section" data-testid="flow-summary">
          <h3>Summary of all selected accounts</h3>
          <p>Total income <b>{money(fromCents(allInc))}</b> · Total expenses <b>{money(fromCents(allExp))}</b> · Difference <Signed c={allInc - allExp} /></p>
        </div>
      ) : null}
      {data.balances ? <p className="hint">The PDF also lists the balance of every account open on {usDate(data.balances.date)}{data.balances.compare_date ? `, compared with ${usDate(data.balances.compare_date)}` : ""}.</p> : null}
      {data.balances?.substitutions?.length ? (
        <ul className="hint substitutions" data-testid="flow-substitutions">
          {data.balances.substitutions.map((s: any) => (
            <li key={s.id}><span className="subst-marker" title={s.hint} aria-label={s.hint} tabIndex={0}>ⓘ</span> {s.text}</li>
          ))}
        </ul>
      ) : null}
      <div className="actions left">
        <button className="primary" type="button" onClick={generate} disabled={busy}>{busy ? "Generating…" : "Generate PDF"}</button>
        {pdf ? <><a className="button" href={pdf.url} target="_blank" rel="noopener">Open PDF</a><a className="button" href={pdf.url} download={pdf.name}>Download PDF</a></> : null}
      </div>
      {asking ? (
        <Modal title="Exclude this line" onClose={() => setAsking(null)}>
          <GuardedForm onSubmit={(e: FormEvent) => { e.preventDefault(); if (asking.reason.trim()) { setExcluded({ ...excluded, [asking.line.key]: asking.reason.trim() }); setAsking(null); } }}>
            <p><b>{usDate(asking.line.date)} · {money(asking.line.amount)}</b> — {asking.line.description}</p>
            <p className="hint">Why is this line left out of the report? The reason is recorded in the audit log with the report; it is not printed.</p>
            <Field label="Reason (required)"><textarea required maxLength={1000} value={asking.reason} onChange={(e) => setAsking({ ...asking, reason: e.target.value })} /></Field>
            <div className="actions"><button type="button" onClick={() => setAsking(null)}>Cancel</button><button className="primary" type="submit" disabled={!asking.reason.trim()}>Exclude line</button></div>
          </GuardedForm>
        </Modal>
      ) : null}
    </section>
  );
}
