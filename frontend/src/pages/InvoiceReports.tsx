// 2.4.0 (#255): the Invoices group of the Reports catalog - seven reports, one page each, shown on screen and as
// PDF / CSV (the customer statement is PDF only). Options are remembered like every other report's.
import { useEffect, useState } from "react";
import { api, qs } from "../api";
import { EntityPicker, ErrorBox, Field, Loading } from "../components";
import type { ActionsFn, RunFn } from "./reports/common";

type Props = { rid: string; fys: any[]; initial: Record<string, any>; onRun: RunFn; actions: ActionsFn };

const AS_OF = new Set(["inv-open", "inv-aging"]);
const today = () => new Date().toISOString().slice(0, 10);
function monthStart() { const d = new Date(); return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10); }

export function InvoiceReport({ rid, initial, onRun, actions }: Props) {
  const asOf = AS_OF.has(rid);
  const [v, setV] = useState<Record<string, any>>({
    as_of: initial.as_of || today(), date_from: initial.date_from || monthStart(), date_to: initial.date_to || today(),
    customer_entity_id: initial.customer_entity_id ? String(initial.customer_entity_id) : "",
    status: initial.status || "", by: initial.by || "product",
  });
  const [data, setData] = useState<any>(null);
  const [entities, setEntities] = useState<any[]>([]);
  useEffect(() => { if (rid === "inv-open" || rid === "inv-statement") api.get("/api/entities?status=all").then(setEntities, () => undefined); }, [rid]);
  const [err, setErr] = useState<unknown>(null);
  const needCustomer = rid === "inv-statement";
  const params: Record<string, any> = asOf
    ? { as_of: v.as_of, customer_entity_id: rid === "inv-open" ? v.customer_entity_id : null }
    : { date_from: v.date_from, date_to: v.date_to, customer_entity_id: needCustomer ? v.customer_entity_id : null,
        status: rid === "inv-register" ? v.status || null : null, by: rid === "inv-sales" ? v.by : null };
  const ready = !needCustomer || !!v.customer_entity_id;
  const url = (format: string, download = false) => ready ? `/api/invoices/reports/${rid}${qs({ ...params, format, download: download || null })}` : null;
  const key = JSON.stringify(params);
  useEffect(() => {
    setData(null);
    setErr(null);
    if (!ready) return;
    api.get(url("json")!).then(setData, setErr);
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  const cname = entities.find((e) => String(e.id) === v.customer_entity_id)?.display_name;
  const remember = () => onRun(params, asOf ? `as of ${v.as_of}` : `${v.date_from} to ${v.date_to}${needCustomer && cname ? ` · ${cname}` : ""}`);
  return (
    <>
      <div className="report-options">
        {asOf ? <Field label="As of"><input type="date" value={v.as_of} onChange={(e) => setV({ ...v, as_of: e.target.value })} /></Field> : <>
          <Field label="From"><input type="date" value={v.date_from} onChange={(e) => setV({ ...v, date_from: e.target.value })} /></Field>
          <Field label="To"><input type="date" value={v.date_to} onChange={(e) => setV({ ...v, date_to: e.target.value })} /></Field>
        </>}
        {needCustomer || rid === "inv-open" ? (
          <EntityPicker label={needCustomer ? "Customer" : "Customer (optional)"} entities={entities} value={v.customer_entity_id}
            onChange={(id) => setV({ ...v, customer_entity_id: id })} placeholder={needCustomer ? "Type to search…" : "All customers"} />
        ) : null}
        {rid === "inv-register" ? (
          <Field label="Status"><select value={v.status} onChange={(e) => setV({ ...v, status: e.target.value })}>
            <option value="">All</option>{[["DRAFT", "Draft"], ["SENT", "Sent"], ["PARTLY_PAID", "Partly paid"], ["PAID", "Paid"], ["VOID", "Void"], ["WRITTEN_OFF", "Written off"]]
              .map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        ) : null}
        {rid === "inv-sales" ? (
          <Field label="Group by"><select value={v.by} onChange={(e) => setV({ ...v, by: e.target.value })}>
            <option value="product">Product</option><option value="category">Category</option><option value="budget">Income budget</option></select></Field>
        ) : null}
      </div>
      {actions({ open: url("pdf"), download: url("pdf", true), csv: needCustomer ? undefined : url("csv", true), onRun: remember })}
      <ErrorBox error={err} />
      {!ready ? <p className="muted">Choose the customer.</p> : !data ? (err ? null : <Loading />) : <ReportTables r={data} />}
    </>
  );
}

function ReportTables({ r }: { r: any }) {
  return (
    <div data-testid="inv-report">
      <p className="hint">{r.subtitle}{r.note ? ` · ${r.note}` : ""}</p>
      {r.sections.map((s: any, n: number) => (
        <div key={n}>
          {s.heading ? <h3>{s.heading}</h3> : null}
          {s.rows.length ? (
            <div className="table-wrap"><table className="table">
              <thead><tr>{s.columns.map((c: any) => <th key={c.key} className={c.kind === "text" || c.kind === "date" ? "" : "num"}>{c.label}</th>)}</tr></thead>
              <tbody>{s.rows.map((row: any, i: number) => <tr key={i}>{s.columns.map((c: any) => <td key={c.key} className={c.kind === "text" || c.kind === "date" ? "" : "num"}>{row[c.key]}</td>)}</tr>)}</tbody>
              {s.totals ? <tfoot><tr className="total-row">{s.columns.map((c: any) => <th key={c.key} className={c.kind === "text" || c.kind === "date" ? "" : "num"}>{s.totals[c.key] ?? ""}</th>)}</tr></tfoot> : null}
            </table></div>
          ) : <p className="muted">Nothing to show.</p>}
        </div>
      ))}
    </div>
  );
}
