// 2.4.0 (#253 part 3): the invoice PDF template editor (Invoices Setup, Administrator) - built from the cover-letter
// editor's pieces: the live preview (sample data only, BR-003), the logo upload, {VARIABLES} with suggestions.
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading } from "../components";
import { Lines, LivePreview, PatternInput } from "./checkShared";

type Col = { key: string; heading: string };

export function InvoiceTemplateEditor() {
  const [t, setT] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [logoV, setLogoV] = useState(0);
  const dragFrom = useRef<number | null>(null);          // #480: the row being dragged
  const load = () => api.get("/api/invoices/setup/template").then((x) => { setT(x); setCfg(x.config); }, setErr);
  useEffect(() => { load(); }, []);
  if (!t || !cfg) return <section className="card"><h2>Invoice PDF</h2><ErrorBox error={err} />{err ? null : <Loading />}</section>;
  const set = (k: string, v: any) => { setSaved(false); setCfg({ ...cfg, [k]: v }); };
  // 2.4.0 polish (#477): one line per row with {VARIABLE} suggestions, as on the cover letter
  const lines = (k: "letterhead" | "bill_to") => (
    <Lines label={k === "letterhead" ? "Letterhead" : "Bill to"} idBase={`inv-${k}`} max={6}
      lines={cfg[k]} variables={t.variables} onChange={(l) => set(k, l)} />
  );
  const num = (k: string) => (e: any) => set(k, Number(e.target.value) || 0);
  const cols: Col[] = cfg.columns;
  const has = (key: string) => cols.some((c) => c.key === key);
  const toggle = (key: string, label: string, on: boolean) => set("columns", on ? [...cols, { key, heading: label.split(" (")[0] }] : cols.filter((c) => c.key !== key));
  const move = (n: number, d: number) => { const a = [...cols]; [a[n], a[n + d]] = [a[n + d], a[n]]; set("columns", a); };
  // 2.4.0 polish (#480): drag a row by its handle to reorder (↑/↓ stay for the keyboard)
  const dropAt = (n: number) => {
    const from = dragFrom.current;
    dragFrom.current = null;
    if (from === null || from === n) return;
    const a = [...cols];
    const [x] = a.splice(from, 1);
    a.splice(n, 0, x);
    set("columns", a);
  };
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
            <Field label="Logo position"><select value={cfg.logo_position} onChange={(e) => set("logo_position", e.target.value)}><option value="LEFT">Left, above the letterhead</option><option value="CENTER">Center, between the letterhead and the title</option><option value="RIGHT">Right, above the title</option><option value="NONE">Don't print it</option></select></Field>
          </div>
          {lines("letterhead")}
          <div className="row fields">
            <PatternInput id="inv-title" label="Title" maxLength={40} value={cfg.title} variables={t.variables} hint={false} onChange={(v) => set("title", v)} />
            <PatternInput id="inv-billto-h" label="Bill to heading" maxLength={40} value={cfg.bill_to_heading} variables={t.variables} hint={false} onChange={(v) => set("bill_to_heading", v)} />
          </div>
          {lines("bill_to")}
          <fieldset><legend>Line table columns</legend>
            <ol className="plain column-order" data-testid="inv-columns">{cols.map((c, n) => (
              <li key={c.key} className="column-row" draggable onDragStart={() => { dragFrom.current = n; }}
                  onDragOver={(e) => e.preventDefault()} onDrop={() => dropAt(n)}>
                <span className="drag-handle" aria-hidden="true" title="Drag to reorder">⠿</span>
                <label htmlFor={`inv-col-${c.key}`}>{t.columns.find((x: any) => x.key === c.key)?.label}</label>
                <input id={`inv-col-${c.key}`} aria-label={`Heading for ${c.key}`} maxLength={30} value={c.heading} onChange={(e) => set("columns", cols.map((x) => (x.key === c.key ? { ...x, heading: e.target.value } : x)))} />
                <button type="button" className="small" aria-label={`Move ${c.key} up`} disabled={!n} onClick={() => move(n, -1)}>↑</button>
                <button type="button" className="small" aria-label={`Move ${c.key} down`} disabled={n === cols.length - 1} onClick={() => move(n, 1)}>↓</button>
              </li>))}</ol>
            <p className="hint">Drag a row by ⠿, or use ↑ and ↓, to change the column order.</p>
            <div className="row">{t.columns.map((c: any) => (
              <label key={c.key} className="check"><input type="checkbox" checked={has(c.key)} disabled={c.key === "DESCRIPTION"} onChange={(e) => toggle(c.key, c.label, e.target.checked)} /> {c.label}</label>))}</div>
          </fieldset>
          <div className="row">
            <label className="check"><input type="checkbox" checked={cfg.show_fields} onChange={(e) => set("show_fields", e.target.checked)} /> Invoice fields</label>
            <label className="check"><input type="checkbox" checked={cfg.show_terms} onChange={(e) => set("show_terms", e.target.checked)} /> Terms</label>
            <label className="check"><input type="checkbox" checked={cfg.show_notes} onChange={(e) => set("show_notes", e.target.checked)} /> Notes</label>
          </div>
          <PatternInput id="inv-footer" label="Footer" multiline maxLength={2000} value={cfg.footer} variables={t.variables} hint={false} onChange={(v) => set("footer", v)} />
          <p className="hint">e.g. Please pay {"{INVOICE.BALANCE}"} by {"{INVOICE.DUE_DATE}"}. Make checks payable to {"{ORG}"}.</p>
          {/* 2.4.0 polish (#479): the #10 double-window layout and fold marks, as on the check cover letter */}
          <fieldset><legend>Window envelope (#10 double-window)</legend>
            <Field label="Address for a window envelope">
              <select value={cfg.window} onChange={(e) => { setSaved(false); setCfg({ ...cfg, window: e.target.value,
                fold_marks: e.target.value !== "NONE" && cfg.window === "NONE" && cfg.fold_marks === "NONE" ? "FRONT" : cfg.fold_marks }); }}>
                <option value="NONE">None (a plain envelope)</option>
                <option value="LETTER">On the invoice: addresses at the top, the invoice starts below the first fold</option>
              </select>
            </Field>
            {cfg.window !== "NONE" ? (
              <>
                <label className="check"><input type="checkbox" checked={cfg.window_return} onChange={(e) => set("window_return", e.target.checked)} /> Return address (the letterhead lines) in the upper window</label>
                <p className="hint">The page is folded in three with the addresses on the top panel facing the windows; the Bill to lines show in the lower
                  window. If your envelope differs, move each address (inches; right and down are positive). The preview and test print draw the windows and
                  mark the folds: print it on plain paper, fold it and hold it behind the envelope.</p>
                <div className="row form-row">
                  <Field label="Return address – right (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={cfg.return_dx} onChange={num("return_dx")} /></Field>
                  <Field label="Return address – down (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={cfg.return_dy} onChange={num("return_dy")} /></Field>
                  <Field label="Bill to – right (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={cfg.payee_dx} onChange={num("payee_dx")} /></Field>
                  <Field label="Bill to – down (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={cfg.payee_dy} onChange={num("payee_dy")} /></Field>
                </div>
              </>
            ) : null}
          </fieldset>
          <fieldset><legend>Fold marks</legend>
            <Field label="Print fold marks">
              <select aria-label="Print fold marks" value={cfg.fold_marks} onChange={(e) => set("fold_marks", e.target.value)}>
                <option value="NONE">No</option>
                <option value="FRONT">On the front of the page</option>
                <option value="BACK">On the back of the page (needs two-sided printing)</option>
              </select>
            </Field>
            {cfg.fold_marks === "BACK" ? <p className="hint" role="note">The PDF gets a back page for every page (the marks behind page 1, the others blank), so print it two-sided (flip on long edge).</p> : null}
            {cfg.fold_marks !== "NONE" ? (
              <div className="row form-row">
                <Field label="Tick length (in)"><input type="number" aria-label="Tick length" step={0.05} min={0.1} max={0.5} value={cfg.fold_length} onChange={num("fold_length")} /></Field>
                <Field label="From the paper edge (in)"><input type="number" aria-label="Tick distance from the edge" step={0.05} min={0.1} max={0.5} value={cfg.fold_edge} onChange={num("fold_edge")} /></Field>
                <Field label="Line weight"><select aria-label="Tick line weight" value={cfg.fold_weight} onChange={(e) => set("fold_weight", e.target.value)}>
                  <option value="HAIRLINE">Hairline</option><option value="THIN">Thin</option><option value="MEDIUM">Medium</option></select></Field>
                <Field label="Shade"><select aria-label="Tick shade" value={cfg.fold_shade} onChange={(e) => set("fold_shade", e.target.value)}>
                  <option value="LIGHT">Light gray</option><option value="MEDIUM">Medium gray</option><option value="DARK">Dark gray</option></select></Field>
              </div>
            ) : null}
          </fieldset>
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
