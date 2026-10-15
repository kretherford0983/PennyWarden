import { Fragment, useEffect, useState } from "react";
import { api, qs } from "../api";
import { ErrorBox, Field, Loading } from "../components";
import { PdfViewer, type PdfFile } from "./checkShared";

/** 2.0.0 (#133): times in the viewer's own time zone (UTC on hover). */
const local = (iso: string) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

function SubTable({ t, caption }: { t: { columns: string[]; rows: any[][] } | null; caption: string }) {
  if (!t) return <span className="muted">—</span>;
  return (
    <table className="table compact sub-table">
      <caption className="sr-only">{caption}</caption>
      <thead><tr>{t.columns.map((c) => <th key={c} scope="col">{c}</th>)}</tr></thead>
      <tbody>{t.rows.map((r, i) => <tr key={i}>{r.map((v, j) => <td key={j}>{String(v)}</td>)}</tr>)}</tbody>
    </table>
  );
}

/** The readable entry: summary, "What changed" (the word "changed" marks a change - not colour alone) and the raw
 * JSON in a collapsed "Show technical details". Everything is rendered as text (no HTML). */
function Readable({ e }: { e: any }) {
  const r = e.readable;
  return (
    <div className="audit-readable">
      <p className="audit-summary"><strong>{r?.summary}</strong>, {local(e.timestamp)}</p>
      {e.snapshots_withheld ? <p className="muted">Financial content is withheld for Administrators: only who, the kind of action and when are shown.</p> : null}
      {r?.changes?.length ? (
        <table className="table compact what-changed">
          <caption>What changed</caption>
          <thead><tr><th scope="col">Field</th><th scope="col">Before</th><th scope="col">After</th><th scope="col"><span className="sr-only">Changed</span></th></tr></thead>
          <tbody>
            {r.changes.map((c: any) => (
              <tr key={c.field} className={c.changed ? "is-changed" : ""}>
                <th scope="row">{c.label}</th>
                <td>{"before_table" in c ? <SubTable t={c.before_table} caption={`${c.label} before`} /> : String(c.before ?? "—")}</td>
                <td>{"after_table" in c ? <SubTable t={c.after_table} caption={`${c.label} after`} /> : String(c.after ?? "—")}</td>
                <td>{c.changed ? <span className="badge">changed</span> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : !e.snapshots_withheld ? <p className="muted">No recorded values.</p> : null}
      {!e.snapshots_withheld ? (
        <details className="technical">
          <summary>Show technical details</summary>
          <p className="muted small-text"><code>{e.action}</code> · {e.object_type} {e.object_id ? `#${e.object_id}` : ""} · {e.timestamp} UTC{e.correlation_id ? ` · ${e.correlation_id}` : ""}</p>
          <div className="snapshots">
            <div><h4>Before</h4><pre>{e.before ? JSON.stringify(e.before, null, 2) : "null"}</pre></div>
            <div><h4>After</h4><pre>{e.after ? JSON.stringify(e.after, null, 2) : "null"}</pre></div>
          </div>
        </details>
      ) : null}
    </div>
  );
}

export default function AuditLog() {
  const [f, setF] = useState({ object_type: "", action: "", actor: "", category: "", date_from: "", date_to: "", direction: "desc" });
  const [page, setPage] = useState(0);
  const [data, setData] = useState<any>(null);
  const [meta, setMeta] = useState<any>({ actions: [], object_types: [] });
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<number | null>(null);
  const limit = 50;
  useEffect(() => { api.get("/api/audit-events/meta").then(setMeta, () => undefined); }, []);
  useEffect(() => {
    setErr(null);
    api.get(`/api/audit-events${qs({ ...f, limit, offset: page * limit })}`).then(setData, setErr);
  }, [f, page]);
  const set = (k: keyof typeof f) => (e: any) => { setPage(0); setF({ ...f, [k]: e.target.value }); };
  // 2.0.0 build 12 (#188): export the filtered list (all pages) as CSV or a printable PDF - same entries and wording as
  // here, built by the server (financial content withheld for Administrators); every export is recorded in this log
  const [busy, setBusy] = useState<"" | "csv" | "pdf">("");
  const [pdf, setPdf] = useState<PdfFile | null>(null);
  const [exportErr, setExportErr] = useState<unknown>(null);
  const exportAs = async (format: "csv" | "pdf") => {
    setExportErr(null);
    setBusy(format);
    try {
      const body: Record<string, string> = { format };
      for (const [k, v] of Object.entries(f)) if (v) body[k] = v;
      try { body.time_zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ""; } catch { /* UTC */ }
      if (!body.time_zone) delete body.time_zone;
      const blob = await api.postBlob("/api/audit-events/export", body);
      const d = new Date();
      const p2 = (n: number) => String(n).padStart(2, "0");
      const name = `audit-log-${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}-${p2(d.getHours())}${p2(d.getMinutes())}${p2(d.getSeconds())}.${format}`;
      const url = URL.createObjectURL(blob);
      if (format === "pdf") {
        if (pdf) URL.revokeObjectURL(pdf.url);
        setPdf({ url, name, preview: blob.previewToken });
      } else {
        const a = document.createElement("a");
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 30_000);
      }
      setPage(0);
      api.get(`/api/audit-events${qs({ ...f, limit, offset: 0 })}`).then(setData, () => undefined);   // shows the export entry
    } catch (x) { setExportErr(x); } finally { setBusy(""); }
  };
  return (
    <div>
      <div className="page-head">
        <h1>Audit Log</h1>
        <button type="button" onClick={() => exportAs("csv")} disabled={!!busy || !data?.total}>{busy === "csv" ? "Exporting…" : "Export CSV"}</button>
        <button type="button" onClick={() => exportAs("pdf")} disabled={!!busy || !data?.total}>{busy === "pdf" ? "Exporting…" : "Printable PDF"}</button>
      </div>
      <p className="muted">Append-only. Audit events cannot be edited or deleted. Times are in your time zone.
        {" "}<span className="hint">Export CSV and Printable PDF hold every entry matching the filters below (all pages, up to 10,000), with the same
        summaries and changes as here; each export is recorded in this log.</span></p>
      <ErrorBox error={exportErr} />
      {pdf ? <PdfViewer pdf={pdf} title="Audit log export" onClose={() => setPdf(null)} /> : null}
      <div className="filters">
        <Field label="Object type">
          <select value={f.object_type} onChange={set("object_type")}>
            <option value="">All</option>
            {meta.object_types.map((o: any) => <option key={o.code} value={o.code}>{o.label}</option>)}
          </select>
        </Field>
        <Field label="Action">
          <select value={f.action} onChange={set("action")}>
            <option value="">All</option>
            {[...meta.actions].sort((a: any, b: any) => a.label.localeCompare(b.label)).map((a: any) => <option key={a.code} value={a.code}>{a.label}</option>)}
          </select>
        </Field>
        <Field label="Actor (username)"><input value={f.actor} onChange={set("actor")} /></Field>
        <Field label="Category"><select value={f.category} onChange={set("category")}><option value="">All</option><option value="BUSINESS">Business</option><option value="SECURITY">Security</option></select></Field>
        <Field label="From"><input type="date" value={f.date_from} onChange={set("date_from")} /></Field>
        <Field label="To"><input type="date" value={f.date_to} onChange={set("date_to")} /></Field>
        <Field label="Order"><select value={f.direction} onChange={set("direction")}><option value="desc">Newest first</option><option value="asc">Oldest first</option></select></Field>
      </div>
      <ErrorBox error={err} />
      {!data ? <Loading /> : (
        <>
          <table className="table audit-table">
            <thead><tr><th scope="col">Time</th><th scope="col">Actor</th><th scope="col">What happened</th><th scope="col">Category</th><th /></tr></thead>
            <tbody>
              {data.items.map((e: any) => (
                <Fragment key={e.id}>
                  <tr>
                    <td title={`${e.timestamp.replace("T", " ").slice(0, 19)} UTC`}>{local(e.timestamp)}</td>
                    <td>{e.actor_name && e.actor_username ? `${e.actor_name} - ${e.actor_username}` : e.actor_username || "—"}</td>
                    <td title={e.action}><span className="audit-action">{e.readable?.action_label || e.action}</span>{" "}
                      <span className="muted">{e.readable?.summary ? e.readable.summary.split(" — ").slice(1).join(" — ") : `${e.object_type} ${e.object_id ? `#${e.object_id}` : ""}`}</span></td>
                    <td>{e.category === "SECURITY" ? "Security" : "Business"}</td>
                    <td><button className="small" onClick={() => setOpen(open === e.id ? null : e.id)} aria-expanded={open === e.id} aria-controls={`audit-${e.id}`}>{open === e.id ? "Hide" : "Details"}</button></td>
                  </tr>
                  {open === e.id ? (
                    <tr className="detail-row" id={`audit-${e.id}`}>
                      <td colSpan={5}><Readable e={e} /></td>
                    </tr>
                  ) : null}
                </Fragment>
              ))}
            </tbody>
          </table>
          <div className="pager">
            <button disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
            <span>{page * limit + 1}–{Math.min((page + 1) * limit, data.total)} of {data.total}</span>
            <button disabled={(page + 1) * limit >= data.total} onClick={() => setPage(page + 1)}>Next</button>
          </div>
        </>
      )}
    </div>
  );
}
