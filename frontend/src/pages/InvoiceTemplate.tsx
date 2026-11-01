// 2.4.0 (#253 part 3): the invoice PDF template editor (Invoices Setup, Administrator) - built from the cover-letter
// editor's pieces: the live preview (sample data only, BR-003), the logo upload, {VARIABLES} with suggestions.
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading } from "../components";
import { LivePreview } from "./checkShared";

type Col = { key: string; heading: string };

export function InvoiceTemplateEditor() {
  const [t, setT] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [logoV, setLogoV] = useState(0);
  const load = () => api.get("/api/invoices/setup/template").then((x) => { setT(x); setCfg(x.config); }, setErr);
  useEffect(() => { load(); }, []);
  if (!t || !cfg) return <section className="card"><h2>Invoice PDF</h2><ErrorBox error={err} />{err ? null : <Loading />}</section>;
  const set = (k: string, v: any) => { setSaved(false); setCfg({ ...cfg, [k]: v }); };
  const lines = (k: "letterhead" | "bill_to") => (
    <fieldset><legend>{k === "letterhead" ? "Letterhead (up to 6 lines)" : "Bill to (up to 6 lines)"}</legend>
      {[...cfg[k], ...(cfg[k].length < 6 ? [""] : [])].map((v: string, n: number) => (
        <input key={n} aria-label={`${k === "letterhead" ? "Letterhead" : "Bill to"} line ${n + 1}`} maxLength={200} value={v}
          onChange={(e) => { const a = [...cfg[k]]; a[n] = e.target.value; set(k, a); }} />
      ))}
    </fieldset>
  );
  const cols: Col[] = cfg.columns;
  const has = (key: string) => cols.some((c) => c.key === key);
  const toggle = (key: string, label: string, on: boolean) => set("columns", on ? [...cols, { key, heading: label.split(" (")[0] }] : cols.filter((c) => c.key !== key));
  const move = (n: number, d: number) => { const a = [...cols]; [a[n], a[n + d]] = [a[n + d], a[n]]; set("columns", a); };
  const save = async () => {
    setErr(null);
    const clean = { ...cfg, letterhead: cfg.letterhead.filter((x: string) => x.trim()), bill_to: cfg.bill_to.filter((x: string) => x.trim()) };
    try { const x = await api.put("/api/invoices/setup/template", clean); setT(x); setCfg(x.config); setSaved(true); } catch (x) { setErr(x); }
  };
  const logo = async (f: File | null) => {
    setErr(null);
    try { setT(f ? await api.upload("/api/invoices/setup/template/logo", f) : await api.post("/api/invoices/setup/template/logo/remove")); setLogoV(logoV + 1); } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="inv-tpl-h" data-testid="invoice-template">
      <h2 id="inv-tpl-h">Invoice PDF</h2>
      <p className="hint">How every invoice PDF looks from now on (PDFs already kept for sent invoices don't change). The preview uses sample data. Texts can use {"{VARIABLES}"} - see the list below.</p>
      <ErrorBox error={err} />
      <div className="editor-split" style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: "1rem" }}>
        <div>
          <div className="row fields">
            <Field label="Font"><select value={cfg.font} onChange={(e) => set("font", e.target.value)}>{t.fonts.map((f: any) => <option key={f.key} value={f.key}>{f.label}</option>)}</select></Field>
            <Field label="Size"><input type="number" min={8} max={12} step={0.5} value={cfg.size} onChange={(e) => set("size", Number(e.target.value))} style={{ width: "5em" }} /></Field>
            <Field label="Accent color"><input type="color" value={cfg.accent} onChange={(e) => set("accent", e.target.value.toUpperCase())} /></Field>
          </div>
          <div className="row fields">
            <Field label="Logo">{t.has_logo ? <span><img src={`/api/invoices/setup/template/logo?v=${logoV}`} alt="Current logo" style={{ maxHeight: 40, verticalAlign: "middle" }} /> <button type="button" className="small" onClick={() => logo(null)}>Remove</button></span>
              : <input type="file" accept="image/png,image/jpeg" onChange={(e) => logo(e.target.files?.[0] || null)} />}</Field>
            <Field label="Logo position"><select value={cfg.logo_position} onChange={(e) => set("logo_position", e.target.value)}><option value="LEFT">Left, above the letterhead</option><option value="RIGHT">Right, above the title</option><option value="NONE">Don't print it</option></select></Field>
          </div>
          {lines("letterhead")}
          <div className="row fields">
            <Field label="Title"><input maxLength={40} value={cfg.title} onChange={(e) => set("title", e.target.value)} /></Field>
            <Field label="Bill to heading"><input maxLength={40} value={cfg.bill_to_heading} onChange={(e) => set("bill_to_heading", e.target.value)} /></Field>
          </div>
          {lines("bill_to")}
          <fieldset><legend>Line table columns</legend>
            <ol className="plain">{cols.map((c, n) => (
              <li key={c.key} className="row">
                <span style={{ minWidth: "9em" }}>{t.columns.find((x: any) => x.key === c.key)?.label}</span>
                <input aria-label={`Heading for ${c.key}`} maxLength={30} value={c.heading} onChange={(e) => set("columns", cols.map((x) => (x.key === c.key ? { ...x, heading: e.target.value } : x)))} />
                <button type="button" className="small" aria-label={`Move ${c.key} up`} disabled={!n} onClick={() => move(n, -1)}>↑</button>
                <button type="button" className="small" aria-label={`Move ${c.key} down`} disabled={n === cols.length - 1} onClick={() => move(n, 1)}>↓</button>
              </li>))}</ol>
            <div className="row">{t.columns.map((c: any) => (
              <label key={c.key} className="check"><input type="checkbox" checked={has(c.key)} disabled={c.key === "DESCRIPTION"} onChange={(e) => toggle(c.key, c.label, e.target.checked)} /> {c.label}</label>))}</div>
          </fieldset>
          <div className="row">
            <label className="check"><input type="checkbox" checked={cfg.show_fields} onChange={(e) => set("show_fields", e.target.checked)} /> Invoice fields</label>
            <label className="check"><input type="checkbox" checked={cfg.show_terms} onChange={(e) => set("show_terms", e.target.checked)} /> Terms</label>
            <label className="check"><input type="checkbox" checked={cfg.show_notes} onChange={(e) => set("show_notes", e.target.checked)} /> Notes</label>
          </div>
          <Field label="Footer" hint="e.g. Please pay {INVOICE.BALANCE} by {INVOICE.DUE_DATE}. Make checks payable to {ORG}."><textarea rows={3} maxLength={2000} value={cfg.footer} onChange={(e) => set("footer", e.target.value)} /></Field>
          <div className="actions left"><button className="primary" type="button" onClick={save}>Save template</button>{saved ? <span role="status" className="muted">Saved.</span> : null}</div>
          <details><summary>Variables</summary><ul className="small">{t.variables.map((v: any) => <li key={v.name}><code>{`{${v.name}}`}</code> — {v.description}</li>)}</ul></details>
        </div>
        <div>
          <LivePreview imageUrl="/api/invoices/setup/template/preview-image" pdfUrl="/api/invoices/setup/template/preview" body={cfg}
            title="Invoice preview (sample data)" aspect={8.5 / 11} deps={[JSON.stringify(cfg), logoV]} />
        </div>
      </div>
    </section>
  );
}
