/** 2.2.0 (#256): the Donations page's Year-end statements and Donor report tabs.
 * - Year-end statements: one letter per donor and calendar year listing the donations received in it (money and items,
 *   items by description only). Register Users print one donor, or all donors (with an optional minimum total) as one
 *   PDF; the other financial roles and Auditors see them. Numbered per year, kept; Duplicate / Corrected like receipts.
 * - Donor report: totals per donor by year (up to 5), gifts, last gift, items and their internal estimated value; each
 *   donor expands to their donations. PDF and CSV. */
import { Fragment, useEffect, useState } from "react";
import { api, ApiError, withPreviewToken } from "../api";
import { useMe } from "../App";
import { EntityPicker, ErrorBox, Field, Loading, Modal, useConfirmable } from "../components";
import { PdfViewer, usePdf } from "./checkShared";
import { ReceiptEnvelopePanel } from "./Envelopes";

const KIND_LABEL: Record<string, string> = { ORIGINAL: "Original", DUPLICATE: "Duplicate", CORRECTED: "Corrected" };
const thisYear = new Date().getFullYear();
const YEARS = Array.from({ length: 8 }, (_, i) => thisYear - i);
const usd = (c: number) => `$${(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const toCents = (v: string) => { const t = v.replace(/[$,\s]/g, ""); return t && /^\d+(\.\d{1,2})?$/.test(t) ? Math.round(Number(t) * 100) : 0; };

async function getBlob(url: string) {
  const r = await fetch(url, { credentials: "same-origin" });
  if (!r.ok) {
    let body: any = null;
    try { body = await r.json(); } catch { /* not JSON */ }
    throw new ApiError(r.status, body);
  }
  return withPreviewToken(r, await r.blob());
}

// ------------------------------------------------------------------ Year-end statements
export function StatementsTab() {
  const { can } = useMe();
  const printer = can("donation.print");
  const [year, setYear] = useState(thisYear - 1);
  const [min, setMin] = useState("");
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState<string | null>(null);
  const { run, dialog } = useConfirmable();
  const load = () => api.get(`/api/donations/statements?year=${year}&min_cents=${toCents(min)}`).then(setData, setErr);
  useEffect(() => { setData(null); load(); }, [year]); // eslint-disable-line react-hooks/exhaustive-deps
  const printAll = async () => {
    setErr(null);
    try {
      const blob = await run((c) => api.postBlob(`/api/donations/statements/${year}/print-all`, { min_cents: toCents(min), confirmations: c }));
      if (!blob) return;
      setPdf(blob, `statements-${year}.pdf`); setViewing(`Year-end statements ${year}`); load();
    } catch (x) { setErr(x); }
  };
  return (
    <section aria-label="Year-end statements">
      <p className="hint">A year-end giving statement lists each donor's donations <b>received</b> in a calendar year: money deposited in the register and
        items ticked Received. Cancelled donations, voided deposits and money awaiting a deposit are left out. Items are listed by description only.
        Each printed statement is kept and numbered; printing the same content again prints a duplicate, a change prints a corrected statement.</p>
      <ErrorBox error={err} />
      {data?.setup_missing?.length ? <div className="alert warn">An Administrator must enter {data.setup_missing.join(" and ")} in System/About → Organization{data.setup_missing.some((m: string) => m.includes("EIN")) ? " (or turn off Include EIN on receipts in Donations Setup)" : ""} before statements can be printed.</div> : null}
      <form className="row filters" onSubmit={(e) => { e.preventDefault(); load(); }}>
        <Field label="Year"><select value={year} onChange={(e) => setYear(Number(e.target.value))} aria-label="Year">{YEARS.map((y) => <option key={y} value={y}>{y}</option>)}</select></Field>
        <Field label="Minimum total ($, optional)"><input inputMode="decimal" aria-label="Minimum total" value={min} onChange={(e) => setMin(e.target.value)} placeholder="e.g. 250" /></Field>
        <button type="submit" className="small">Show</button>
        {printer && data?.items.length ? <button type="button" className="primary" onClick={printAll}>Print all ({data.items.length})</button> : null}
      </form>
      {!data ? <Loading /> : !data.items.length ? <p className="muted">No donor has donations received in {year}{toCents(min) ? " with that minimum total" : ""}.</p> : (
        <table className="table" aria-label={`Year-end statements ${year}`}>
          <thead><tr><th>Donor</th><th className="num">Total (money)</th><th className="num">Gifts</th><th className="num">Items</th><th>Statement</th><th /></tr></thead>
          <tbody>
            {data.items.map((r: any) => (
              <tr key={r.donor_id}>
                <td>{r.donor}{!r.has_address ? <span className="muted"> (no address)</span> : null}</td>
                <td className="num">{r.total}</td><td className="num">{r.gifts}</td><td className="num">{r.items || ""}</td>
                <td>{r.current_statement || <span className="muted">Not printed</span>}{r.current_statement && r.next_kind === "CORRECTED" ? <span className="badge warn"> Changed since</span> : null}</td>
                <td className="actions-cell"><button className="small" onClick={() => setOpen(r.donor_id)} aria-label={`Open statement ${r.donor}`}>Open</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {open != null ? <StatementDialog year={year} donorId={open} printer={printer} onClose={() => setOpen(null)} onChanged={load} /> : null}
      {pdf && viewing ? <PdfViewer pdf={pdf} title={viewing} onClose={() => setViewing(null)} /> : null}
      {dialog}
    </section>
  );
}

function StatementDialog({ year, donorId, printer, onClose, onChanged }: { year: number; donorId: number; printer: boolean; onClose: () => void; onChanged: () => void }) {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState<string | null>(null);
  const [printedId, setPrintedId] = useState<number | null>(null);
  const { run, dialog } = useConfirmable();
  const url = `/api/donations/statements/${year}/donors/${donorId}`;
  const load = () => api.get(url).then(setD, setErr);
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const preview = async () => {
    setErr(null);
    try { setPdf(await api.postBlob(`${url}/preview`, {}), "statement-preview.pdf"); setViewing("Statement preview"); } catch (x) { setErr(x); }
  };
  const print = async () => {
    setErr(null);
    try {
      const blob = await run((c) => api.postBlob(url, { confirmations: c }));
      if (!blob) return;
      setPdf(blob, "statement.pdf"); setViewing("Year-end statement");
      const fresh = await api.get(url); setD(fresh);
      const last = fresh.statements[fresh.statements.length - 1];
      setPrintedId(last?.id ?? null); onChanged();
    } catch (x) { setErr(x); }
  };
  const view = async (s: any) => {
    setErr(null);
    try { setPdf(await getBlob(`/api/donations/statements/printed/${s.id}/document`), `statement-${s.number}.pdf`); setViewing(`Statement ${s.number}`); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={d ? `Year-end statement ${year} – ${d.donor.name}` : `Year-end statement ${year}`} onClose={onClose} wide>
      <ErrorBox error={err} />
      {!d ? <Loading /> : (
        <>
          <table className="table compact" aria-label="Donations in the year">
            <thead><tr><th>Date received</th><th>Receipt</th><th>Description</th><th className="num">Amount</th><th>Goods or services</th></tr></thead>
            <tbody>
              {d.rows.map((r: any, i: number) => (
                <tr key={i}><td>{r.date}</td><td>{r.receipt}</td><td>{r.kind === "ITEM" ? `Item: ${r.description}` : r.description}</td>
                  <td className="num">{r.amount ?? ""}</td><td>{r.goods ? `${r.goods}${r.goods_description ? ` (${r.goods_description})` : ""}` : "None"}</td></tr>
              ))}
            </tbody>
            <tfoot><tr><td colSpan={3}><b>Total (money)</b></td><td className="num"><b>{d.total}</b></td><td /></tr></tfoot>
          </table>
          {printer ? (
            <div className="actions left">
              <button onClick={preview}>Preview</button>
              <button className="primary" onClick={print}>{d.next_kind === "ORIGINAL" ? "Print statement" : d.next_kind === "DUPLICATE" ? "Print duplicate" : "Print corrected statement"}</button>
            </div>
          ) : null}
          {printedId != null ? <ReceiptEnvelopePanel basePath={`/api/donations/statements/printed/${printedId}`} /> : null}
          {d.statements.length ? (
            <section aria-label="Printed statements">
              <h4>Printed statements</h4>
              <table className="table compact" data-testid="statement-history">
                <thead><tr><th>Statement</th><th>Kind</th><th className="num">Total</th><th>Printed</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {d.statements.map((s: any) => (
                    <tr key={s.id}>
                      <td>{s.number}</td>
                      <td>{KIND_LABEL[s.kind]}{s.replaces && s.kind === "CORRECTED" ? <span className="muted"> (replaces {s.replaces})</span> : null}</td>
                      <td className="num">{s.total}</td><td>{s.printed_at.slice(0, 10)}{s.printed_by ? ` · ${s.printed_by}` : ""}</td>
                      <td>{s.superseded ? <span className="badge grey">Replaced</span> : <span className="badge green">In force</span>}</td>
                      <td><button className="small" onClick={() => view(s)}>View</button></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
        </>
      )}
      {pdf && viewing ? <PdfViewer pdf={pdf} title={viewing} onClose={() => setViewing(null)}>
        {viewing === "Statement preview" ? <p className="hint">Preview only: marked PREVIEW – NOT A STATEMENT. Nothing is kept or numbered.</p> : null}
      </PdfViewer> : null}
      {dialog}
    </Modal>
  );
}

// ------------------------------------------------------------------ Donor report
export function DonorReportTab() {
  const [from, setFrom] = useState(thisYear - 1);
  const [to, setTo] = useState(thisYear);
  const [min, setMin] = useState("");
  const [donor, setDonor] = useState("");
  const [entities, setEntities] = useState<any[]>([]);
  const [detail, setDetail] = useState(false);
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [expanded, setExpanded] = useState<Set<number>>(new Set());
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState(false);
  const query = () => `/api/donations/report?start_year=${from}&end_year=${to}&min_cents=${toCents(min)}${donor ? `&donor_id=${donor}` : ""}`;
  const load = () => { setErr(null); api.get(query()).then(setData, setErr); };
  useEffect(() => { api.get("/api/entities?status=active").then((es) => setEntities(es.filter((e: any) => !e.is_system && !e.is_organization)), () => setEntities([])); load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const download = async (format: "pdf" | "csv") => {
    setErr(null);
    try {
      const blob = await getBlob(`${query()}&format=${format}&detail=${detail}`);
      const name = `donor-report-${Math.min(from, to)}-${Math.max(from, to)}.${format}`;
      if (format === "pdf") { setPdf(blob, name); setViewing(true); return; }
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = name; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (x) { setErr(x); }
  };
  const toggle = (id: number) => setExpanded((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const span = Math.abs(to - from) + 1;
  return (
    <section aria-label="Donor report">
      <p className="hint">Money received from each donor by calendar year (up to 5 years), with the number of gifts, the last gift and the items with their
        estimated value. The estimate is for the organization's own records; it is never printed on a letter to a donor.</p>
      <ErrorBox error={err} />
      <form className="row filters" onSubmit={(e) => { e.preventDefault(); load(); }}>
        <Field label="From year"><select aria-label="From year" value={from} onChange={(e) => setFrom(Number(e.target.value))}>{YEARS.map((y) => <option key={y} value={y}>{y}</option>)}</select></Field>
        <Field label="To year"><select aria-label="To year" value={to} onChange={(e) => setTo(Number(e.target.value))}>{YEARS.map((y) => <option key={y} value={y}>{y}</option>)}</select></Field>
        <Field label="Minimum total ($, optional)"><input inputMode="decimal" aria-label="Report minimum total" value={min} onChange={(e) => setMin(e.target.value)} /></Field>
        <EntityPicker label="Donor (optional)" entities={entities} value={donor} onChange={setDonor} placeholder="All donors" />
        <button type="submit" className="small" disabled={span > 5}>Show</button>
      </form>
      {span > 5 ? <p className="error-text" role="alert">Choose at most 5 years.</p> : null}
      <div className="row">
        <label className="check"><input type="checkbox" checked={detail} onChange={(e) => setDetail(e.target.checked)} /> With each donation</label>
        <button className="small" onClick={() => download("pdf")} disabled={span > 5}>PDF</button>
        <button className="small" onClick={() => download("csv")} disabled={span > 5}>CSV</button>
      </div>
      {!data ? <Loading /> : !data.rows.length ? <p className="muted">No donations received in these years.</p> : (
        <div className="table-scroll">
          <table className="table" aria-label="Donor report">
            <thead><tr><th>Donor</th>{data.years.map((y: number) => <th key={y} className="num">{y}</th>)}<th className="num">Total</th><th className="num">Gifts</th><th>Last gift</th><th className="num">Items</th><th className="num">Items est. value</th></tr></thead>
            <tbody>
              {data.rows.map((r: any) => (
                <Fragment key={r.donor_id}>
                  <tr>
                    <td><button type="button" className="link" aria-expanded={expanded.has(r.donor_id)} onClick={() => toggle(r.donor_id)}>{expanded.has(r.donor_id) ? "▾" : "▸"} {r.donor}</button></td>
                    {data.years.map((y: number) => <td key={y} className="num">{usd(r.years[String(y)])}</td>)}
                    <td className="num"><b>{usd(r.total_cents)}</b></td><td className="num">{r.gifts}</td><td>{r.last_gift}</td>
                    <td className="num">{r.items || ""}</td><td className="num">{r.items ? usd(r.item_value_cents) : ""}</td>
                  </tr>
                  {expanded.has(r.donor_id) ? r.lines.map((x: any, i: number) => (
                    <tr key={`${r.donor_id}-${i}`} className="sub-row">
                      <td colSpan={data.years.length + 1}><span className="muted">{x.date}{x.receipt ? ` · ${x.receipt}` : ""} · </span>{x.kind === "ITEM" ? `Item: ${x.description}` : x.description}</td>
                      <td className="num">{x.amount ?? ""}</td><td /><td /><td /><td className="num">{x.item_value_cents ? usd(x.item_value_cents) : ""}</td>
                    </tr>
                  )) : null}
                </Fragment>
              ))}
            </tbody>
            <tfoot><tr><td><b>Total</b></td>{data.years.map((y: number) => <td key={y} className="num"><b>{usd(data.totals.years[String(y)])}</b></td>)}
              <td className="num"><b>{usd(data.totals.total_cents)}</b></td><td className="num">{data.totals.gifts}</td><td /><td className="num">{data.totals.items || ""}</td>
              <td className="num">{data.totals.items ? usd(data.totals.item_value_cents) : ""}</td></tr></tfoot>
          </table>
        </div>
      )}
      {pdf && viewing ? <PdfViewer pdf={pdf} title="Donor report" onClose={() => setViewing(false)} /> : null}
    </section>
  );
}
