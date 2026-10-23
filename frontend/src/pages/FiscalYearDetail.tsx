import { useEffect, useState } from "react";
import { api, money } from "../api";
import { Attachments, ErrorBox, Field, FyStatus, Loading, Modal } from "../components";
import { useMe } from "../App";
import { Link } from "../router";
import { BudgetSection } from "./BudgetTable";

export default function FiscalYearDetail({ id }: { id: number }) {
  const { can } = useMe();
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [dlg, setDlg] = useState<"approve" | "close" | null>(null);
  const load = () => api.get(`/api/fiscal-years/${id}`).then(setD, setErr);
  useEffect(() => {
    setD(null);
    load();
  }, [id]);
  if (!d) return <><ErrorBox error={err} />{err ? null : <Loading />}</>;
  const manage = can("fiscal_year.manage");
  const b = d.budgets;
  const showOutside = [...b.income, ...b.expense].some((r: any) => Number(r.outside_fiscal_year) !== 0);
  return (
    <div>
      <p><Link to="/fiscal-years">← Fiscal Years</Link></p>
      <div className="page-head">
        <h1>{d.display_name} <FyStatus status={d.status} /></h1>
        {manage && d.status === "DRAFT" ? <button className="primary" onClick={() => setDlg("approve")}>Approve…</button> : null}
        {manage && d.status === "APPROVED" ? <button className="primary" onClick={() => setDlg("close")}>Close Fiscal Year…</button> : null}
        {can("budget.manage") && d.status !== "CLOSED" ? <Link to={`/budgets?fiscal_year_id=${d.id}`}>Edit budgets</Link> : null}
      </div>
      <ErrorBox error={err} />
      <dl className="dl">
        <dt>Dates</dt><dd>{d.start_date} – {d.end_date}</dd>
        <dt>Quarters</dt><dd>{b.quarters.map((q: any) => `${q.name}: ${q.start_date} – ${q.end_date}`).join(" · ")}</dd>
        <dt>Created</dt><dd>{d.created_at?.replace("T", " ").slice(0, 16)}</dd>
        <dt>Approved</dt><dd>{d.approved_at ? d.approved_at.replace("T", " ").slice(0, 16) : "—"}</dd>
        <dt>Closed</dt><dd>{d.closed_at ? d.closed_at.replace("T", " ").slice(0, 16) : "—"}</dd>
        {d.exception_confirmed ? <><dt>Confirmed exceptions</dt><dd>{d.exception_confirmed}</dd></> : null}
      </dl>
      <BudgetSection title="Income" rows={b.income} summary={b.income_summary} fyStatus="CLOSED" showOutside={showOutside} />
      <BudgetSection title="Expense" rows={b.expense} summary={b.expense_summary} fyStatus="CLOSED" showOutside={showOutside} />
      {d.status !== "CLOSED" ? <Closure c={d.closure} /> : null}
      <DocumentationReview fyId={d.id} />
      <FyDocuments fy={d} manage={manage} onChanged={load} />
      {dlg === "approve" ? <Approve fy={d} onClose={() => setDlg(null)} onDone={() => { setDlg(null); load(); }} /> : null}
      {dlg === "close" ? <Close fy={d} onClose={() => setDlg(null)} onDone={() => { setDlg(null); load(); }} /> : null}
    </div>
  );
}

// v1.2 CR-005: documentation review (warnings only - never blocks approval or closure)
function DocumentationReview({ fyId }: { fyId: number }) {
  const [items, setItems] = useState<any[] | null>(null);
  useEffect(() => { api.get(`/api/fiscal-years/${fyId}/documentation-review`).then((r) => setItems(r.items), () => setItems([])); }, [fyId]);
  if (!items) return null;
  return (
    <section className="card">
      <h3>Documentation review <span className="muted">(warnings – not a closure blocker)</span></h3>
      {items.length ? <p className="hint">Click a transaction number to open it in the Register, where a document can be attached.</p> : null}
      {items.length === 0 ? <p className="ok-text">All transactions affecting this Fiscal Year have supporting attachments or a stated reason for having none.</p> : (
        <table className="table compact">
          <thead><tr><th>Txn #</th><th>Date</th><th>Account</th><th>Type</th><th>Entity / description</th><th className="num">Amount</th><th>Warning</th></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.transaction_id}>
                <td><Link to={`/register?account=${i.bank_account.id}&txn=${i.transaction_id}`} title="Open this transaction in the Register" aria-label={`Open transaction ${i.transaction_id} in the Register`}>{i.transaction_id}</Link></td><td>{i.transaction_date}</td><td>{i.bank_account.label}</td>
                <td>{i.is_transfer ? "Transfer" : i.transaction_type.charAt(0) + i.transaction_type.slice(1).toLowerCase()}{i.is_split ? " (split)" : ""}</td>
                <td>{i.entity?.display_name || i.description || ""}</td><td className="num">{money(i.total)}</td>
                <td>{i.category === "NO_ATTACHMENT_MARKED"
                  ? <><span className="badge grey">No attachment – no reason given</span></>
                  : <><span className="badge yellow">Missing attachment</span>{i.is_split && i.allocations_without_documentation.length ? ` ${i.allocations_without_documentation.length} of ${i.allocation_count} allocations undocumented` : ""}</>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function Closure({ c }: { c: any }) {
  return (
    <section className="card">
      <h3>Closure readiness</h3>
      {c.blockers.length ? (
        <ul className="blockers">{c.blockers.map((b: any) => <li key={b.code}><span className="badge red">Blocker</span> {b.message}</li>)}</ul>
      ) : <p className="ok-text">No closure blockers.</p>}
      {c.warnings.length ? <ul>{c.warnings.map((w: any) => <li key={w.code}><span className="badge yellow">Warning</span> {w.message}</li>)}</ul> : null}
    </section>
  );
}

// v1.3 CR-007: typed Fiscal Year documents. Approval document: required before approving (or the "no approval
// document" mark). Audit Signoff: required to close. Other documents: no effect. Close report: system generated.
function FyDocuments({ fy, manage, onChanged }: { fy: any; manage: boolean; onChanged: () => void }) {
  const [k, setK] = useState(0);
  const [markDlg, setMarkDlg] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const open = fy.status !== "CLOSED";
  const counts = fy.document_counts || {};
  const changed = () => { setK((x) => x + 1); onChanged(); };
  const unmark = async () => {
    try { await api.post(`/api/fiscal-years/${fy.id}/approval-no-attachment`, { no_attachment: false }); changed(); } catch (e) { setErr(e); }
  };
  const common = { ownerType: "fiscal_year" as const, ownerId: fy.id, canUpload: manage, canRemove: manage && open, canRetype: manage && open, reloadKey: k, onChanged: changed };
  return (
    <section className="card fy-docs">
      <h2>Fiscal Year documents</h2>
      <ErrorBox error={err} />
      <Attachments {...common} documentTypes={["APPROVAL"]} title="Approval document"
        hint={<p className="hint">Required before the Fiscal Year can be approved: the record that the budget was reviewed and approved (signed approval, meeting minutes, …).</p>} />
      {!counts.APPROVAL ? (
        <div className={fy.approval_no_attachment ? "alert warn" : ""}>
          <label className="check">
            <input type="checkbox" checked={!!fy.approval_no_attachment} disabled={!manage || !open}
              onChange={(e) => (e.target.checked ? setMarkDlg(true) : unmark())} />
            No approval document — this organization does not produce one
          </label>
          {fy.approval_no_attachment ? <p>Marked{fy.approval_no_attachment_reason ? `: ${fy.approval_no_attachment_reason}` : ""}. This is listed as a warning in the Fiscal Year review. Uploading an approval document removes the mark.</p> : null}
        </div>
      ) : null}
      <Attachments {...common} documentTypes={["AUDIT_SIGNOFF"]} title="Audit Signoff"
        hint={<p className="hint">Required to close the Fiscal Year: signoff that the audit review is complete and the year may be closed.</p>} />
      <Attachments {...common} documentTypes={["UNSPECIFIED"]} title="Other documents" canReorder={common.canRemove} />
      {!open || counts.CLOSE_REPORT ? <Attachments {...common} canUpload={false} canRemove={false} canRetype={false} documentTypes={["CLOSE_REPORT"]} title="Close report" /> : null}
      {markDlg ? <ApprovalMark fy={fy} onClose={() => setMarkDlg(false)} onDone={() => { setMarkDlg(false); changed(); }} /> : null}
    </section>
  );
}

function ApprovalMark({ fy, onClose, onDone }: any) {
  const [reason, setReason] = useState("");
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => {
    if (busy) return;
    setBusy(true);
    try { await api.post(`/api/fiscal-years/${fy.id}/approval-no-attachment`, { no_attachment: true, reason: reason || null }); onDone(); }
    catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Modal title="No approval document?" onClose={onClose}>
      <ErrorBox error={err} />
      <div className="alert error" role="alert">
        <strong>The budget approval should be documented.</strong> Auditors normally expect evidence that the budget was
        reviewed and approved by whoever is responsible (signed approval, minutes of the meeting where it was voted, …).
        Only use this when your organization genuinely does not produce such a document. The Fiscal Year will be
        flagged with a warning in the Fiscal Year review and the Close report.
      </div>
      <Field label="Reason (optional)"><input maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Budget approved verbally at the annual meeting" /></Field>
      <label className="check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> I understand and confirm there is no approval document.</label>
      <div className="actions"><button onClick={onClose}>Cancel</button><button className="primary danger" disabled={!ok || busy} onClick={go}>Mark as no approval document</button></div>
    </Modal>
  );
}

function Approve({ fy, onClose, onDone }: any) {
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const hasDoc = !!(fy.document_counts || {}).APPROVAL;
  const go = async () => {
    if (busy) return;
    setBusy(true);
    try { await api.post(`/api/fiscal-years/${fy.id}/approve`, { confirm_irreversible: true }); onDone(); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Approve ${fy.display_name}`} onClose={onClose}>
      <ErrorBox error={err} />
      {!hasDoc && !fy.approval_no_attachment ? (
        <div className="alert error" role="alert">Attach the Approval document (under Fiscal Year documents) — or mark that your organization produces none — before approving.</div>
      ) : null}
      {!hasDoc && fy.approval_no_attachment ? <div className="alert warn" role="alert">No approval document: this Fiscal Year is marked as having none. It will be listed as a warning in the Fiscal Year review.</div> : null}
      <div className="alert warn">Approval is irreversible and locks all active budgets. Amendments later require an explicit, audited unlock.</div>
      <label className="check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> I understand approval cannot be reversed.</label>
      <div className="actions"><button onClick={onClose}>Cancel</button><button className="primary" disabled={!ok || busy || (!hasDoc && !fy.approval_no_attachment)} onClick={go}>{busy ? "Saving…" : "Approve"}</button></div>
    </Modal>
  );
}

function Close({ fy, onClose, onDone }: any) {
  const [ok, setOk] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const go = async () => {
    if (busy) return;
    setBusy(true);
    try { await api.post(`/api/fiscal-years/${fy.id}/close`, { confirm_reviewed: true }); onDone(); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Modal title={`Close ${fy.display_name}`} onClose={onClose}>
      <ErrorBox error={err} />
      <Closure c={fy.closure} />
      <div className="alert warn">Closure is irreversible. Budgets and allocations of a Closed Fiscal Year become immutable. The Fiscal Year Close report is generated and kept with the Fiscal Year documents.</div>
      <label className="check"><input type="checkbox" checked={ok} onChange={(e) => setOk(e.target.checked)} /> I confirm this Fiscal Year has been reviewed and is approved for closure.</label>
      <div className="actions"><button onClick={onClose}>Cancel</button><button className="primary danger" disabled={!ok || busy || !fy.closure.can_close} onClick={go}>{busy ? "Closing… (creating the Close report)" : "Close Fiscal Year"}</button></div>
    </Modal>
  );
}
