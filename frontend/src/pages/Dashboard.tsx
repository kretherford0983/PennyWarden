import { lazy, Suspense, useEffect, useRef, useState, type ReactNode } from "react";
import { api, money } from "../api";
import { ErrorBox, FyStatus, GROSS_BUDGET_NOTE, InfoTip, Loading, Remaining } from "../components";
import { Link } from "../router";
import { useMe } from "../App";
import { DashboardNotifications } from "./Notifications";
const DashboardCharts = lazy(() => import("./Charts")); // v1.4.1 CR-020: chart library loaded on demand

export default function Dashboard() {
  const { me } = useMe();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    api.get("/api/dashboard").then(setD, setErr);
  }, []);
  if (err) return <ErrorBox error={err} />;
  if (!d) return <Loading />;
  if (d.kind === "administrator")
    return (
      <div>
        <h1>Administration</h1>
        <div className="tiles">
          <div className="tile"><div className="tile-label">Users</div><div className="tile-value">{d.user_count}</div></div>
          <div className="tile"><div className="tile-label">Active users</div><div className="tile-value">{d.active_user_count}</div></div>
          <div className="tile"><div className="tile-label">Failed sign-ins (24h)</div><div className="tile-value">{d.failed_logins_24h}</div></div>
        </div>
        <h2>Active users by security domain</h2>
        <ul>{Object.entries(d.active_users_by_domain).map(([k, v]) => <li key={k}>{k}: {String(v)}</li>)}</ul>
        <p><Link to="/users">Manage users</Link> · <Link to="/audit-log">View audit log</Link></p>
      </div>
    );
  const fy = d.current_fiscal_year;
  // v1.5.0 CR-031: every section is a block that can be hidden and moved; the order is saved per user.
  const invoices = !!me.modules?.invoices && me.permissions.includes("invoice.view");     // 2.4.0 (#255)
  const sections: Record<string, ReactNode> = {
    notifications: <DashboardNotifications />, // v1.6.3 CR-036: due reminders (nothing when there are none)
    fiscal_year: (
      <section className="card">
        <h2>Current Fiscal Year</h2>
        {fy ? (
          <p><Link to={`/fiscal-years/${fy.id}`}>{fy.display_name}</Link> <FyStatus status={fy.status} /> {fy.start_date} – {fy.end_date}</p>
        ) : (
          <p className="muted">No Fiscal Year configured.</p>
        )}
        {d.fiscal_years?.length ? (
          <p className="muted">All Fiscal Years: {d.fiscal_years.map((f: any) => f.label).join(" · ")}</p>
        ) : null}
      </section>
    ),
    budget: d.budget_summary ? (
      <div className="tiles">
        {(["income", "expense"] as const).map((k) => (
          <div className="tile" key={k}>
            <div className="tile-label">{k === "income" ? "Income" : "Expense"} budget <InfoTip label="About budget amounts" text={GROSS_BUDGET_NOTE} /></div>
            <div className="tile-value">{money(d.budget_summary[k].amount)}</div>
            <div className="muted">Actual {money(d.budget_summary[k].actual)} · Remaining <Remaining x={d.budget_summary[k]} /></div>
          </div>
        ))}
      </div>
    ) : null,
    invoices: invoices ? <OverdueInvoices /> : null,
    review: d.review_summary ? (
      <section className="card">
        <h2>Review summary</h2>
        <div className="tiles">
          <Tile label="Transactions" v={d.review_summary.transaction_count} />
          <Tile label="Voided transactions" v={d.review_summary.voided_transaction_count} />
          <Tile label="Cross-FY allocations" v={d.review_summary.cross_fiscal_year_allocation_count} />
          <Tile label="Pending FY reviews" v={d.review_summary.pending_fiscal_year_reviews} />
          <Tile label="Rejected budgets with activity" v={d.review_summary.rejected_budgets_with_activity} />
        </div>
      </section>
    ) : null,
    bank: (
      <section className="card">
        <h2>Bank account balances</h2>
        {/* v1.5.0 CR-028: same two groups as the Bank Accounts page. v1.6.5 (issue #15): one table per group with a
            heading and space between them, then the grand total on its own - like the Bank Accounts page. */}
        {(d.bank_account_groups || []).filter((g: any) => g.account_ids.length).map((g: any) => (
          <div key={g.key} className="dash-bank-group" data-testid={`bank-group-${g.key}`}>
            <h3 id={`dash-bank-${g.key}`}>{g.label}</h3>
            <table className="table" aria-labelledby={`dash-bank-${g.key}`}>
              <thead><tr><th>Account</th><th className="num">Current balance</th></tr></thead>
              <tbody>
                {d.bank_accounts.filter((a: any) => g.account_ids.includes(a.id)).map((a: any) => (
                  <tr key={a.id}><td>{a.label} {a.is_primary ? <span className="pill">Primary</span> : null}</td><td className="num">{money(a.current_balance)}</td></tr>
                ))}
              </tbody>
              <tfoot><tr className="total-row"><th scope="row">Subtotal {g.label}</th><th className={`num ${Number(g.total) < 0 ? "neg" : ""}`}>{money(g.total)}</th></tr></tfoot>
            </table>
          </div>
        ))}
        {d.bank_accounts.length ? (
          <table className="table dash-bank-total">
            <tbody><tr className="total-row" data-testid="bank-total"><th scope="row">Total (all accounts)</th><th className={`num ${Number(d.bank_accounts_total) < 0 ? "neg" : ""}`}>{money(d.bank_accounts_total)}</th></tr></tbody>
          </table>
        ) : <p className="muted">No bank accounts.</p>}
      </section>
    ),
    attention: (
      <section className="card">
        <h2>Attention</h2>
        <ul>
          <li>Fiscal Year review items pending: <b>{d.attention.pending_fiscal_year_reviews}</b> {d.attention.pending_fiscal_year_reviews ? <Link to="/register?reviews=1">Review</Link> : null}</li>
          <li>Uncleared transactions: <b>{d.attention.uncleared_transactions}</b></li>
          {fy ? <li>Documentation review warnings ({fy.display_name}): <b>{d.attention.documentation_warnings}</b> {d.attention.documentation_warnings ? <Link to={`/fiscal-years/${fy.id}`}>Review</Link> : null}</li> : null}
        </ul>
      </section>
    ),
    charts: (
      <Suspense fallback={<section className="card"><h2>Charts</h2><p className="hint">Loading charts…</p></section>}>
        <DashboardCharts fys={d.fiscal_years || []} currentFyId={fy ? fy.id : null} />
      </Suspense>
    ),
  };
  // Sections this user can have: the Review summary exists for Auditors only; the overdue invoices card (2.4.0, #255)
  // when the Invoices module is on and the user can view invoices.
  const available = SECTIONS.filter((s) => (s.key !== "review" || d.review_summary) && (s.key !== "invoices" || invoices)).map((s) => s.key);
  return <FinancialDashboard title={me.security_domain === "AUDITOR" ? "Auditor dashboard" : "Dashboard"} sections={sections} available={available} />;
}

const SECTIONS = [
  { key: "notifications", title: "Notifications (due reminders)" },
  { key: "fiscal_year", title: "Current Fiscal Year" },
  { key: "budget", title: "Budget (income and expense)" },
  { key: "review", title: "Review summary" },
  { key: "bank", title: "Bank account balances" },
  { key: "attention", title: "Attention" },
  { key: "invoices", title: "Overdue invoices" },
  { key: "charts", title: "Charts" },
];
const titleOf = (k: string) => SECTIONS.find((s) => s.key === k)?.title ?? k;
type Item = { key: string; visible: boolean };

function FinancialDashboard({ title, sections, available }: { title: string; sections: Record<string, ReactNode>; available: string[] }) {
  const { me, patchMe } = useMe();
  const [layout, setLayout] = useState<Item[]>(me.dashboard_layout ?? SECTIONS.map((s) => ({ key: s.key, visible: true })));
  const [customized, setCustomized] = useState(!!me.dashboard_layout_customized);
  const [edit, setEdit] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  // Saves run one after another (never in parallel), so the last change always wins on the server (as CR-020).
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const pending = useRef(0);
  const [saveState, setSaveState] = useState<"saving" | "saved" | null>(null);
  const save = (body: object, next: Item[], isCustom: boolean) => {
    setLayout(next);
    setCustomized(isCustom);
    patchMe({ dashboard_layout: next, dashboard_layout_customized: isCustom });
    pending.current += 1;
    setSaveState("saving");
    queue.current = queue.current
      .then(() => api.put("/api/me/preferences", body))
      .catch((e) => setErr(e))
      .finally(() => {
        pending.current -= 1;
        if (pending.current === 0) setSaveState("saved");
      });
  };
  const change = (next: Item[]) => save({ dashboard_layout: next }, next, true);
  const items = layout.filter((i) => available.includes(i.key));
  // Moving swaps with the neighbouring section this user can see in the list (hidden-for-role sections are skipped).
  const move = (key: string, dir: -1 | 1) => {
    const pos = items.findIndex((i) => i.key === key);
    const other = items[pos + dir];
    if (!other) return;
    const a = layout.findIndex((i) => i.key === key);
    const b = layout.findIndex((i) => i.key === other.key);
    const next = [...layout];
    [next[a], next[b]] = [next[b], next[a]];
    change(next);
  };
  const toggle = (key: string, visible: boolean) => change(layout.map((i) => (i.key === key ? { ...i, visible } : i)));
  const reset = () => save({ reset_dashboard_layout: true }, SECTIONS.map((s) => ({ key: s.key, visible: true })), false);
  const shown = items.filter((i) => i.visible);

  return (
    <div>
      <div className="page-head">
        <h1>{title}</h1>
        <div className="row">
          {saveState ? <span className="hint" role="status">{saveState === "saving" ? "Saving your dashboard layout…" : "Dashboard layout saved"}</span> : null}
          <button type="button" className="small" aria-expanded={edit} aria-controls="dash-customize" onClick={() => setEdit(!edit)}>{edit ? "Done" : "Customize dashboard"}</button>
        </div>
      </div>
      {edit ? (
        <fieldset className="dash-customize" id="dash-customize">
          <legend>Sections shown and their order (saved for your account)</legend>
          <ol>
            {items.map((i, n) => (
              <li key={i.key} data-testid={`layout-${i.key}`}>
                <label className="check"><input type="checkbox" checked={i.visible} onChange={(e) => toggle(i.key, e.target.checked)} /> {titleOf(i.key)}</label>
                <span className="move">
                  <button type="button" className="small" aria-label={`Move ${titleOf(i.key)} up`} disabled={n === 0} onClick={() => move(i.key, -1)}>↑</button>
                  <button type="button" className="small" aria-label={`Move ${titleOf(i.key)} down`} disabled={n === items.length - 1} onClick={() => move(i.key, 1)}>↓</button>
                </span>
              </li>
            ))}
          </ol>
          <div className="actions left"><button type="button" className="small" disabled={!customized} onClick={reset}>Reset to default</button></div>
        </fieldset>
      ) : null}
      <ErrorBox error={err} />
      {!shown.length ? <p className="muted">All sections are hidden. Use <b>Customize dashboard</b> to show some.</p> : null}
      {shown.map((i) => <div key={i.key} className="dash-section" data-section={i.key}>{sections[i.key]}</div>)}
    </div>
  );
}

function Tile({ label, v }: { label: string; v: any }) {
  return <div className="tile"><div className="tile-label">{label}</div><div className="tile-value">{v}</div></div>;
}

/** 2.4.0 (#255): invoices past their due date with a balance open, for everyone who can view invoices. */
export function OverdueInvoices({ reminders = false }: { reminders?: boolean }) {
  const [o, setO] = useState<any>(null);
  useEffect(() => { api.get("/api/invoices/overdue").then(setO, () => setO(false)); }, []);
  if (o === null) return <section className="card"><h2>Overdue invoices</h2><Loading /></section>;
  if (o === false) return null;
  if (reminders) {
    if (!o.reminders.length) return null;
    return (
      <div className="alert warn" role="note" data-testid="inv-reminders">
        <b>Invoice reminders</b> ({o.reminder_days ? `${o.reminder_days} days after the due date` : "from the due date"}):
        <ul>{o.reminders.map((x: any) => <li key={x.id}><Link to={`/invoices/${x.id}`}>{x.number}</Link> — {x.customer}, due {x.due_date}, open {money(x.open)}</li>)}</ul>
      </div>
    );
  }
  return (
    <section className="card" data-testid="dash-overdue">
      <h2>Overdue invoices</h2>
      {o.count ? <>
        <p><b>{o.count}</b> overdue, {money(o.open)} open. <Link to="/reports/inv-aging">Aging report</Link></p>
        <table className="table"><thead><tr><th>Invoice</th><th>Customer</th><th>Due</th><th className="num">Days</th><th className="num">Open</th></tr></thead>
          <tbody>{o.items.map((x: any) => <tr key={x.id}><td><Link to={`/invoices/${x.id}`}>{x.number}</Link></td><td>{x.customer}</td><td>{x.due_date}</td><td className="num">{x.days}</td><td className="num">{money(x.open)}</td></tr>)}</tbody></table>
      </> : <p className="muted">No overdue invoices.</p>}
    </section>
  );
}
