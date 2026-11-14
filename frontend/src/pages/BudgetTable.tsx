import { Fragment } from "react";
import { money } from "../api";
import { BudgetState, Remaining, RowMenu } from "../components";
import { Link } from "../router";

export interface BudgetActions {
  onEdit?: (row: any) => void;
  onAddChild?: (row: any) => void;
  onReject?: (row: any) => void;
  onInactivate?: (row: any) => void;
  onUnlock?: (row: any) => void;
  onLock?: (row: any) => void;
  onInvoicedIncome?: (row: any, on: boolean) => void;   // 2.4.0 (#250)
}

/** Holistic budget table: Q1-Q4 + yearly actuals, amount, remaining, state icon + text (BR-079/080). */
export function BudgetSection({ title, rows, summary, fyStatus, actions, showOutside, registerLinks, onHistory, historyForAll }: {
  title: string; rows: any[]; summary: any; fyStatus: string; actions?: BudgetActions; showOutside?: boolean;
  registerLinks?: boolean; // 1.7.3 (#105): each budget links to its transactions in the Register
  onHistory?: (row: any) => void; // 1.8.0 (#89): budgets linked across Fiscal Years
  historyForAll?: boolean; // 2.2.0 (#284): Budget Managers open History on any budget to enter earlier years
}) {
  const editable = !!actions && fyStatus !== "CLOSED";
  return (
    <section className="budget-section">
      <h3>{title}</h3>
      <div className="table-wrap">
        <table className="table budget-table">
          <thead>
            <tr>
              <th>Status</th><th>Budget</th><th className="num">Gross amount</th>
              <th className="num">Q1</th><th className="num">Q2</th><th className="num">Q3</th><th className="num">Q4</th>
              {showOutside ? <th className="num" title="Allocations dated outside this Fiscal Year (cross-FY)">Outside FY dates</th> : null}
              <th className="num">Actual (year)</th><th className="num">Remaining</th>{editable ? <th>Actions</th> : null}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? <tr><td colSpan={12} className="muted">No {title.toLowerCase()} budgets.</td></tr> : null}
            {rows.map((r) => (
              <Fragment key={r.id}>
                <Row r={r} level={0} editable={editable} actions={actions} showOutside={showOutside} registerLinks={registerLinks} onHistory={onHistory} historyForAll={historyForAll} />
                {r.children.map((c: any) => <Row key={c.id} r={c} level={1} editable={editable} actions={actions} parent={r} showOutside={showOutside} registerLinks={registerLinks} onHistory={onHistory} historyForAll={historyForAll} />)}
              </Fragment>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th /><th>Total</th><th className="num">{money(summary.amount)}</th>
              {summary.quarters.map((q: string, i: number) => <th key={i} className="num">{money(q)}</th>)}
              {showOutside ? <th /> : null}
              <th className="num">{money(summary.actual)}</th>
              <th className="num"><Remaining x={summary} /></th>{editable ? <th /> : null}
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  );
}

function Row({ r, level, editable, actions, parent, showOutside, registerLinks, onHistory, historyForAll }: { r: any; level: number; editable: boolean; actions?: BudgetActions; parent?: any; showOutside?: boolean; registerLinks?: boolean; onHistory?: (row: any) => void; historyForAll?: boolean }) {
  const tone = r.state.tone;
  const locked = parent ? parent.locked : r.locked;
  const canEdit = editable && !r.system_managed && !locked && !["REJECTED", "INACTIVE"].includes(r.status);
  return (
    <tr className={`bg-${tone}${level ? " child" : ""}`}>
      <td><BudgetState state={r.state} /></td>
      <td className={level ? "indent" : ""}>
        {registerLinks ? (
          <Link to={`/register?budget=${r.id}&fiscal_year=${r.fiscal_year_id}`} className="budget-link"
                aria-label={`${r.display_code} ${r.name}: show its transactions in the Register`} title="Show this budget's transactions in the Register">
            <span className="code">{r.display_code}</span> {r.name}
          </Link>
        ) : <><span className="code">{r.display_code}</span> {r.name}</>}
        {r.is_other ? <span className="muted"> (system-managed, calculated)</span> : null}
        {/* 2.4.0 (#250): icon plus text, never color only (BR-079) */}
        {r.invoiced_income && !r.is_other ? <span className="badge blue invoiced-badge" title="Invoiced Income: for payments of invoices"><span aria-hidden="true">🧾</span> Invoiced income</span> : null}
        {onHistory && (r.has_history || (historyForAll && (!r.system_managed || r.is_other))) ? <button type="button" className="link small history-link" aria-label={`History of ${r.display_code}`} title="This budget across Fiscal Years" onClick={() => onHistory(r)}>History</button> : null}
        {r.status === "REJECTED" && r.requested_amount ? <span className="muted"> · requested {money(r.requested_amount)}</span> : null}
      </td>
      <td className="num">{money(r.amount)}</td>
      {r.quarters.map((q: string, i: number) => <td key={i} className="num">{money(q)}</td>)}
      {showOutside ? <td className="num">{Number(r.outside_fiscal_year) ? money(r.outside_fiscal_year) : ""}</td> : null}
      <td className="num">{money(r.actual)}</td>
      <td className="num"><Remaining x={r} />{r.over_budget ? <span className="sr"> (over budget)</span> : null}</td>
      {editable ? (
        <td className="actions-cell">
          {canEdit && actions?.onEdit ? <button className="small" aria-label={`Edit ${r.display_code}`} title="Edit" onClick={() => actions.onEdit!(r)}>✎ Edit</button> : null}
          <RowMenu name={`${r.display_code} ${r.name}`} actions={[
            canEdit && level === 0 && actions?.onAddChild && { label: "+ Sub-budget", onClick: () => actions.onAddChild!(r) },
            level === 0 && !r.system_managed && r.status === "APPROVED" && r.locked && actions?.onUnlock && { label: "Unlock", onClick: () => actions.onUnlock!(r) },
            level === 0 && !r.system_managed && r.status === "APPROVED" && !r.locked && actions?.onLock && { label: "Lock", onClick: () => actions.onLock!(r) },
            level === 0 && canEdit && r.budget_type === "INCOME" && actions?.onInvoicedIncome && { label: r.invoiced_income ? "Clear Invoiced Income" : "Mark as Invoiced Income", onClick: () => actions.onInvoicedIncome!(r, !r.invoiced_income) },
            canEdit && actions?.onReject && { label: "Reject", onClick: () => actions.onReject!(r), danger: true },
            canEdit && actions?.onInactivate && { label: "Inactivate", onClick: () => actions.onInactivate!(r), danger: true },
          ]} />
        </td>
      ) : null}
    </tr>
  );
}
