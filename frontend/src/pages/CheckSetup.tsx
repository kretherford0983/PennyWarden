/** 2.0.0 (#156, #158, #159): Check Printing setup for Administrators - check styles (from presets), the field layout
 * with a live preview drawn to scale, fonts, amount styles, feed modes, the default memo, signers and their signature
 * images, the signature limit, test prints with dummy data and the calibration page. No financial data is shown here
 * (BR-003): test prints use built-in dummy data. */
import { DocumentsSection } from "./CheckDocuments";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Field, GuardedForm, Loading, Modal } from "../components";
import { BrowserTips, CheckPreview, FIELD_LABELS, PatternInput, PdfViewer, TEXT_FIELDS, useCheckFonts, usePdf, type FieldText } from "./checkShared";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

export default function CheckSetup() {
  const [s, setS] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [editing, setEditing] = useState<any>(null);
  const [preset, setPreset] = useState("");
  const [name, setName] = useState("");
  const [copyOf, setCopyOf] = useState<any>(null);
  const load = () => api.get("/api/checks/setup").then((x) => { setS(x); setPreset((p) => p || x.presets[0]?.key || ""); }, setErr);
  useEffect(() => { load(); }, []);
  useCheckFonts(s?.fonts);
  if (err && !s) return <ErrorBox error={err} />;
  if (!s) return <Loading />;
  const create = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try { const st = await api.post("/api/checks/styles", { preset_key: preset, name: name || null }); setName(""); await load(); setEditing(st); } catch (x) { setErr(x); }
  };
  const setActive = async (st: any, active: boolean) => {
    setErr(null);
    try { await api.post(`/api/checks/styles/${st.id}/active`, { active }); load(); } catch (x) { setErr(x); }
  };
  if (editing) {
    return <StyleEditor setup={s} style={editing} onClose={() => { setEditing(null); load(); }} onSaved={(st) => { setEditing(st); load(); }} />;
  }
  return (
    <div className="check-setup">
      <h1>Payments Setup</h1>
      <p className="hint">Set up how checks, cover letters and envelopes print for the Payments module. Register Users print checks from the register; they choose the
        check style for each bank account the first time they print from it. Test prints here use sample data only.</p>
      <ErrorBox error={err} />
      <section className="card" aria-labelledby="styles-h">
        <h2 id="styles-h">Check styles</h2>
        {s.styles.length ? (
          <table className="table compact">
            <thead><tr><th>Name</th><th>Checks per sheet</th><th>Feed modes</th><th>Status</th><th /></tr></thead>
            <tbody>
              {s.styles.map((st: any) => (
                <tr key={st.id}>
                  <td>{st.name}</td><td>{st.checks_per_sheet}</td><td>{st.feed_modes.map((m: any) => m.label).join("; ")}</td>
                  <td>{st.active ? "Active" : <span className="badge grey">Deactivated</span>}</td>
                  <td className="actions-cell">
                    <button className="small" onClick={() => setEditing(st)}>Edit</button>{" "}
                    <button className="small" onClick={() => setCopyOf(st)}>Copy…</button>{" "}
                    {st.active ? <button className="small" onClick={() => setActive(st, false)}>Deactivate</button>
                      : <button className="small" onClick={() => setActive(st, true)}>Activate</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">No check styles yet. Start from a preset below.</p>}
        <GuardedForm onSubmit={create} className="row">
          <Field label="New check style from preset">
            <select value={preset} onChange={(e) => setPreset(e.target.value)}>
              {s.presets.map((p: any) => <option key={p.key} value={p.key}>{p.name}</option>)}
            </select>
          </Field>
          <Field label="Name (optional)"><input maxLength={80} value={name} onChange={(e) => setName(e.target.value)} placeholder="Preset name" /></Field>
          <button type="submit" className="primary">Create</button>
        </GuardedForm>
        <p className="hint">{s.presets.find((p: any) => p.key === preset)?.description}</p>
      </section>
      <Signers setup={s} onChanged={load} />
      <DocumentsSection setup={s} onChanged={load} />
      {copyOf ? <CopyStyle style={copyOf} onClose={() => setCopyOf(null)} onDone={() => { setCopyOf(null); load(); }} /> : null}
    </div>
  );
}

function CopyStyle({ style, onClose, onDone }: { style: any; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(`${style.name} (copy)`.slice(0, 80));
  const [err, setErr] = useState<unknown>(null);
  const go = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post(`/api/checks/styles/${style.id}/copy`, { name }); onDone(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Copy "${style.name}"`} onClose={onClose}>
      <GuardedForm onSubmit={go}>
        <ErrorBox error={err} />
        <Field label="Name of the copy"><input required maxLength={80} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Copy</button></div>
      </GuardedForm>
    </Modal>
  );
}

// ------------------------------------------------------------------ #167: dual signatures and voucher stubs
function MoneyIn({ value, onChange }: { value: number | null; onChange: (cents: number | null) => void }) {
  const [text, setText] = useState(value == null ? "" : (value / 100).toFixed(2));
  return <input inputMode="decimal" value={text} onChange={(e) => { setText(e.target.value); const v = e.target.value.trim(); onChange(v ? Math.round(num(v) * 100) || null : null); }}
                onBlur={() => setText(value == null ? "" : (value / 100).toFixed(2))} />;
}

/** One or two signature lines. Two lines: the first moves down above the bank-number zone and the second goes above
 * it, the same width (the Administrator fine-tunes both under Field positions). */
function setLines(c: any, n: number, def: any) {
  c.stock.signature_lines = n;
  if (n === 2) {
    const s = c.fields.signature;
    const h = Math.min(s.h, def?.h ?? 0.42);
    const bottom = c.stock.check_height - 0.625 - 0.03;
    c.fields.signature = { ...s, h, y: Math.round((bottom - h) * 1000) / 1000 };
    c.fields.signature2 = c.fields.signature2 || { x: s.x, w: s.w, h, y: Math.round((bottom - 2 * h - 0.05) * 1000) / 1000 };
  } else {
    c.fields.signature2 = null; c.second_line_limit_cents = null; c.default_signer2_id = null;
  }
}

const STUB_COLS: [string, string][] = [["INVOICE", "Invoice #"], ["INVOICE_DATE", "Invoice Date"], ["DESCRIPTION", "Description"], ["BUDGET", "Budget"], ["NOTES", "Notes"], ["AMOUNT", "Amount"]];

function StubsSection({ cfg, setup, change }: { cfg: any; setup: any; change: (fn: (c: any) => void) => void }) {
  const cols: any[] = cfg.stub_columns;
  const unused = STUB_COLS.filter(([k]) => !cols.some((c) => c.key === k));
  const move = (i: number, d: number) => change((c) => { const [it] = c.stub_columns.splice(i, 1); c.stub_columns.splice(i + d, 0, it); });
  return (
    <Section id="stubs" title="Stubs (voucher check)">
      <p className="hint">The detail stubs below the check list the transaction's lines. Positions are inches from the top of the sheet. The vendor copy never
        shows budgets; the office copy adds the budget column and OFFICE COPY. The check number prints on the stubs only (from the register), never on
        the check. A transaction with more lines than fit shows "…and N more, see enclosed letter", and the user is warned before printing.</p>
      <div className="table-wrap">
        <table className="table compact">
          <thead><tr><th>Stub</th><th>Top</th><th>Height</th><th>Copy</th><th>Title</th><th>Check #</th><th>Memo</th><th>Font</th><th>Size</th><th>Margin</th><th /></tr></thead>
          <tbody>
            {cfg.stubs.map((st: any, i: number) => (
              <tr key={i}>
                <th scope="row">{i + 1}</th>
                <td><NumIn label={`Stub ${i + 1} top`} value={st.top} onChange={(v) => change((c) => { c.stubs[i].top = v; })} /></td>
                <td><NumIn label={`Stub ${i + 1} height`} value={st.height} onChange={(v) => change((c) => { c.stubs[i].height = v; })} /></td>
                <td><select aria-label={`Stub ${i + 1} copy`} value={st.copy_kind} onChange={(e) => change((c) => { c.stubs[i].copy_kind = e.target.value; })}>
                  <option value="VENDOR">Vendor copy</option><option value="OFFICE">Office copy</option></select></td>
                <td><PatternInput id={`stub-title-${i}`} label={`Stub ${i + 1} title`} value={st.title} variables={setup.stub_variables} hint={false} onChange={(v) => change((c) => { c.stubs[i].title = v; })} /></td>
                <td><input type="checkbox" aria-label={`Stub ${i + 1} prints the check number`} checked={st.show_check_number} onChange={(e) => change((c) => { c.stubs[i].show_check_number = e.target.checked; })} /></td>
                <td><input type="checkbox" aria-label={`Stub ${i + 1} prints the memo`} checked={st.show_memo} onChange={(e) => change((c) => { c.stubs[i].show_memo = e.target.checked; })} /></td>
                <td><select aria-label={`Stub ${i + 1} font`} value={st.font} onChange={(e) => change((c) => { c.stubs[i].font = e.target.value; })}>
                  {setup.fonts.map((x: any) => <option key={x.key} value={x.key}>{x.label.split(" (")[0]}</option>)}</select></td>
                <td><NumIn label={`Stub ${i + 1} size`} unit="pt" step={0.5} min={6} max={12} value={st.size} onChange={(v) => change((c) => { c.stubs[i].size = v; })} /></td>
                <td><NumIn label={`Stub ${i + 1} margin`} value={st.margin} onChange={(v) => change((c) => { c.stubs[i].margin = v; })} /></td>
                <td><button className="small" onClick={() => change((c) => { c.stubs.splice(i, 1); })}>Remove</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cfg.stubs.length < 2 ? (
        <div className="actions left"><button className="small" onClick={() => change((c) => {
          const last = c.stubs[c.stubs.length - 1];
          const top = last ? last.top + last.height : c.stock.check_tops[0] + c.stock.check_height;
          c.stubs.push({ top, height: Math.max(1.5, Math.min(3.5, 11 - top)), copy_kind: "OFFICE", title: "{ORG}", show_check_number: true, font: "SANS", size: 9, margin: 0.4, show_memo: true });
        })}>Add stub</button></div>
      ) : null}
      <h3>Line table</h3>
      <table className="table compact">
        <thead><tr><th>Column</th><th>Heading</th><th /></tr></thead>
        <tbody>
          {cols.map((col, i) => (
            <tr key={col.key}>
              <td>{STUB_COLS.find(([k]) => k === col.key)?.[1]}{col.key === "BUDGET" ? " (office copy only)" : ""}</td>
              <td><input aria-label={`Stub heading for ${col.key}`} maxLength={40} value={col.heading} onChange={(e) => change((c) => { c.stub_columns[i].heading = e.target.value; })} /></td>
              <td className="actions-cell">
                <button className="small" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">↑</button>{" "}
                <button className="small" disabled={i === cols.length - 1} onClick={() => move(i, 1)} aria-label="Move down">↓</button>{" "}
                <button className="small" disabled={cols.length === 1} onClick={() => change((c) => { c.stub_columns.splice(i, 1); })}>Remove</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {unused.length ? <div className="row form-row">{unused.map(([k, h]) => <button key={k} className="small" onClick={() => change((c) => { c.stub_columns.push({ key: k, heading: h }); })}>+ {h}</button>)}</div> : null}
      <p className="hint">The stubs are drawn on the test print and the calibration page (sample data); the preview above shows the check only.</p>
    </Section>
  );
}

// ------------------------------------------------------------------ editor
/** #174: which editor sections are collapsed and whether the preview is pinned - kept in memory while the app is open
 * (AC-SEC-006: the app keeps nothing in browser storage). */
const viewState = new Map<string, boolean>();

/** #174: a section of the editor that can be collapsed. */
function Section({ id, title, children, extra, className = "" }: { id: string; title: string; children: React.ReactNode; extra?: React.ReactNode; className?: string }) {
  const key = `pw-check-setup-${id}`;
  const [open, setOpen] = useState(() => viewState.get(key) ?? true);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    viewState.set(key, next);
  };
  return (
    <section className={`card collapsible ${open ? "open" : "closed"} ${className}`} aria-labelledby={`${id}-h`}>
      <div className="collapsible-head">
        <h2 id={`${id}-h`}>
          <button type="button" className="collapse-btn" aria-expanded={open} aria-controls={`${id}-body`} onClick={toggle}>
            <span aria-hidden="true" className="chev">{open ? "▾" : "▸"}</span> {title}
          </button>
        </h2>
        {extra}
      </div>
      <div id={`${id}-body`} hidden={!open}>{children}</div>
    </section>
  );
}

function num(v: string) { const n = parseFloat(v); return Number.isFinite(n) ? n : 0; }

function NumIn({ label, value, onChange, step = 0.005, min, max, unit = "in" }: {
  label: string; value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number; unit?: string;
}) {
  const [txt, setTxt] = useState(String(value));
  const last = useRef(value);
  useEffect(() => { if (value !== last.current) { setTxt(String(value)); last.current = value; } }, [value]);
  return (
    <label className="num-in">
      <span className="sr-only">{label}</span>
      <input type="number" aria-label={label} step={step} min={min} max={max} value={txt}
             onChange={(e) => { setTxt(e.target.value); const n = num(e.target.value); last.current = n; onChange(n); }} />
      <span className="unit">{unit}</span>
    </label>
  );
}

function StyleEditor({ setup, style, onClose, onSaved }: { setup: any; style: any; onClose: () => void; onSaved: (s: any) => void }) {
  const [cfg, setCfg] = useState<any>(clone(style.config));
  const [name, setName] = useState(style.name);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [sample, setSample] = useState<"NORMAL" | "LONG">("NORMAL");
  const [texts, setTexts] = useState<Record<string, FieldText> | null>(null);
  const [fitErr, setFitErr] = useState<unknown>(null);
  const [hl, setHl] = useState<string | null>(null);
  const [pin, setPin] = useState(() => viewState.get("pw-check-setup-pin") ?? false);
  useEffect(() => { viewState.set("pw-check-setup-pin", pin); }, [pin]);
  const [testFeed, setTestFeed] = useState(style.config.feed_modes[0]?.key);
  const [testSigner, setTestSigner] = useState("");
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fonts = setup.fonts;
  useCheckFonts(fonts);
  const change = (fn: (c: any) => void) => { const c = clone(cfg); fn(c); setCfg(c); setDirty(true); setSaved(false); };
  // live fit check with the sample data (debounced)
  useEffect(() => {
    const t = setTimeout(() => {
      api.post("/api/checks/sample-layout", { config: cfg, sample }).then((x) => { setTexts(x); setFitErr(null); }, (x) => setFitErr(x));
    }, 250);
    return () => clearTimeout(t);
  }, [cfg, sample]);
  const save = async () => {
    setErr(null);
    try { const st = await api.put(`/api/checks/styles/${style.id}`, { name, config: cfg }); setDirty(false); setSaved(true); onSaved(st); } catch (x) { setErr(x); }
  };
  const pdfReq = async (kind: "test-print" | "calibration") => {
    setErr(null); setBusy(true);
    try {
      const body: any = { feed_key: testFeed, config: cfg };
      if (kind === "test-print") { body.sample = sample; body.signer_id = testSigner ? Number(testSigner) : null; }
      setPdf(await api.postBlob(`/api/checks/styles/${style.id}/${kind}`, body), `check-${kind}.pdf`);
      setViewing(kind === "test-print" ? "Test print" : "Calibration page");   // #174: shown at once, Print is one click
    } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const setField = (n: string, k: string, v: any) => change((c) => { c.fields[n][k] = v; });
  const fm = cfg.feed_modes.find((m: any) => m.key === testFeed);
  const problems = texts ? Object.entries(texts).filter(([, t]) => !t.fits) : [];
  return (
    <div className="check-setup">
      <div className="row space-between">
        <h1>Check style: {style.name}</h1>
        <button onClick={() => { if (!dirty || window.confirm("Leave without saving your changes?")) onClose(); }}>Back to check styles</button>
      </div>
      <ErrorBox error={err} />
      <Section id="pv" title="Preview (drawn to scale, sample data)" className={pin ? "pinned" : ""} extra={
        <div className="row form-row">
          <label className="check"><input type="radio" checked={sample === "NORMAL"} onChange={() => setSample("NORMAL")} /> Sample</label>
          <label className="check"><input type="radio" checked={sample === "LONG"} onChange={() => setSample("LONG")} /> Long text sample</label>
          <label className="check"><input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} /> Keep at the top</label>
        </div>
      }>
        <CheckPreview cfg={cfg} fonts={fonts} texts={texts} highlight={hl} />
        <ErrorBox error={fitErr} />
        {problems.length ? (
          <div className="alert warn" role="status">
            <strong>Does not fit at the smallest size:</strong>{" "}
            {problems.map(([n]) => FIELD_LABELS[n]).join(", ")}. When this happens with real data, the user sees the full text and a shortened
            version (payee and memo) and must accept or edit it before printing; for the date and amounts printing is blocked.
          </div>
        ) : null}
        {texts && Object.values(texts).some((t) => t.shrunk) ? <p className="hint">Some text was printed smaller to fit (down to each field's smallest size).</p> : null}
        <p className="hint">The grey outline is what is pre-printed on the stock (for orientation only – it never prints). The shaded strip at the bottom is
          the bank number zone, which must stay clear.</p>
      </Section>

      <Section id="gen" title="General">
        <div className="row form-row">
          <Field label="Name"><input maxLength={80} value={name} onChange={(e) => { setName(e.target.value); setDirty(true); }} /></Field>
          <Field label="How the sheet is used">
            <select value={cfg.stock.sheet_usage} onChange={(e) => change((c) => { c.stock.sheet_usage = e.target.value; })}>
              <option value="TEAR_TOP">Print the top check and tear it off (last check fed on its own)</option>
              <option value="POSITIONS">Print each position in turn on the same sheet (top, middle, bottom)</option>
            </select>
          </Field>
          <Field label="Date format">
            <select value={cfg.date_format} onChange={(e) => change((c) => { c.date_format = e.target.value; })}>
              {setup.date_formats.map((d: string) => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
        </div>
        <p className="hint">Stock: {cfg.stock.check_tops.length} check(s) of {cfg.stock.check_width}" × {cfg.stock.check_height}" on a Letter sheet.
          {cfg.stock.stock_note ? ` ${cfg.stock.stock_note}` : ""}</p>
        <div className="row form-row">
          <Field label="Default font">
            <select value={cfg.defaults.font} onChange={(e) => change((c) => { c.defaults.font = e.target.value; })}>
              {fonts.map((f: any) => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </Field>
          <Field label="Default size (pt)"><NumIn label="Default size" unit="pt" step={0.5} min={setup.font_sizes.min} max={setup.font_sizes.max} value={cfg.defaults.size} onChange={(v) => change((c) => { c.defaults.size = v; })} /></Field>
          <label className="check"><input type="checkbox" checked={cfg.defaults.upper} onChange={(e) => change((c) => { c.defaults.upper = e.target.checked; })} /> Print everything in capitals</label>
        </div>
      </Section>

      <Section id="fields" title="Field positions">
        <p className="hint">Inches from the top-left corner of the check. Text sits on the bottom of its box, so a box placed on a pre-printed line puts
          the writing on the line. Font and size left blank use the defaults above.</p>
        <div className="table-wrap">
          <table className="table compact field-table">
            <thead><tr><th>Field</th><th>Left (x)</th><th>Top (y)</th><th>Width</th><th>Height</th><th>Font</th><th>Size</th><th>Bold</th><th>Capitals</th><th>Align</th><th>Shrink to fit (min pt)</th></tr></thead>
            <tbody>
              {[...TEXT_FIELDS, "signature", ...(cfg.stock.signature_lines === 2 ? ["signature2"] : [])].map((n) => {
                const f = cfg.fields[n];
                const isText = !n.startsWith("signature");
                return (
                  <tr key={n} onFocus={() => setHl(n)} onMouseEnter={() => setHl(n)} onMouseLeave={() => setHl(null)}>
                    <th scope="row">{FIELD_LABELS[n]}</th>
                    {(["x", "y", "w", "h"] as const).map((k) => <td key={k}><NumIn label={`${FIELD_LABELS[n]} ${k}`} value={f[k]} onChange={(v) => setField(n, k, v)} /></td>)}
                    {isText ? (
                      <>
                        <td><select aria-label={`${FIELD_LABELS[n]} font`} value={f.font || ""} onChange={(e) => setField(n, "font", e.target.value || null)}>
                          <option value="">Default</option>{fonts.map((x: any) => <option key={x.key} value={x.key}>{x.label.split(" (")[0]}</option>)}
                        </select></td>
                        <td><input type="number" aria-label={`${FIELD_LABELS[n]} size`} step={0.5} min={setup.font_sizes.min} max={setup.font_sizes.max} value={f.size ?? ""} placeholder={String(cfg.defaults.size)}
                                   onChange={(e) => setField(n, "size", e.target.value ? num(e.target.value) : null)} /></td>
                        <td><input type="checkbox" aria-label={`${FIELD_LABELS[n]} bold`} checked={!!f.bold} onChange={(e) => setField(n, "bold", e.target.checked)} /></td>
                        <td><select aria-label={`${FIELD_LABELS[n]} capitals`} value={f.upper == null ? "" : f.upper ? "1" : "0"} onChange={(e) => setField(n, "upper", e.target.value === "" ? null : e.target.value === "1")}>
                          <option value="">Default</option><option value="1">Yes</option><option value="0">No</option></select></td>
                        <td><select aria-label={`${FIELD_LABELS[n]} align`} value={f.align} onChange={(e) => setField(n, "align", e.target.value)}>
                          <option value="LEFT">Left</option><option value="CENTER">Center</option><option value="RIGHT">Right</option></select></td>
                        <td><label className="check"><input type="checkbox" aria-label={`${FIELD_LABELS[n]} shrink to fit`} checked={f.shrink} onChange={(e) => setField(n, "shrink", e.target.checked)} /></label>{" "}
                          <input type="number" aria-label={`${FIELD_LABELS[n]} smallest size`} step={0.5} min={setup.font_sizes.min} max={setup.font_sizes.max} value={f.min_size} onChange={(e) => setField(n, "min_size", num(e.target.value))} style={{ width: 60 }} /></td>
                      </>
                    ) : <td colSpan={6} className="hint">The signature image is scaled to fit the box.</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Section>

      <Section id="amt" title="Amounts">
        <p className="hint">Both amounts are always generated from the transaction total; nobody types them.</p>
        <div className="row form-row">
          <Field label="'AND' in the amount in words">
            <select value={cfg.amount_words.and_mode} onChange={(e) => change((c) => { c.amount_words.and_mode = e.target.value; })}>
              <option value="CENTS">Only before the cents (bank convention)</option><option value="HUNDREDS">Also after hundreds ("ONE HUNDRED AND EIGHT")</option>
            </select>
          </Field>
          <label className="check"><input type="checkbox" checked={cfg.amount_words.hyphens} onChange={(e) => change((c) => { c.amount_words.hyphens = e.target.checked; })} /> Hyphens (NINETY-NINE)</label>
          <Field label="Capitals">
            <select value={cfg.amount_words.case} onChange={(e) => change((c) => { c.amount_words.case = e.target.value; })}>
              <option value="UPPER">UPPER CASE</option><option value="TITLE">Title Case</option><option value="LOWER">lower case</option>
            </select>
          </Field>
          <Field label="Whole dollars">
            <select value={cfg.amount_words.cents} onChange={(e) => change((c) => { c.amount_words.cents = e.target.value; })}>
              <option value="NN">00/100</option><option value="NO">NO/100</option>
            </select>
          </Field>
        </div>
        <div className="row form-row">
          <Field label="Protective fill">
            <select value={cfg.amount_words.fill} onChange={(e) => change((c) => { c.amount_words.fill = e.target.value; })}>
              <option value="DOTS">Centered dots</option><option value="DASHES">Centered dashes</option><option value="LINE">Solid centered line</option><option value="STARS">Asterisks</option>
            </select>
          </Field>
          <Field label="Fill placement">
            <select value={cfg.amount_words.fill_placement} onChange={(e) => change((c) => { c.amount_words.fill_placement = e.target.value; })}>
              <option value="BETWEEN">Between the words and the cents (cents at the right end)</option><option value="AFTER">After the cents</option>
            </select>
          </Field>
          <Field label="Word after the amount" hint="Leave blank when the stock pre-prints DOLLARS."><input maxLength={20} value={cfg.amount_words.trailing_word} onChange={(e) => change((c) => { c.amount_words.trailing_word = e.target.value; })} /></Field>
        </div>
        <div className="row form-row">
          <label className="check"><input type="checkbox" checked={cfg.amount_number.commas} onChange={(e) => change((c) => { c.amount_number.commas = e.target.checked; })} /> Thousands commas</label>
          <label className="check"><input type="checkbox" checked={cfg.amount_number.dollar_sign} onChange={(e) => change((c) => { c.amount_number.dollar_sign = e.target.checked; })} /> Print a $ (off when the stock pre-prints it)</label>
          <Field label="Leading fill">
            <select value={cfg.amount_number.lead_fill} onChange={(e) => change((c) => { c.amount_number.lead_fill = e.target.value; })}>
              <option value="">None</option><option value="*">*</option><option value="**">**</option><option value="***">***</option>
            </select>
          </Field>
        </div>
      </Section>

      <Section id="memo" title="Memo and signature">
        <PatternInput id="memo-default" label="Default memo" value={cfg.memo_default} variables={setup.variables} onChange={(v) => change((c) => { c.memo_default = v; })} placeholder="e.g. {BUDGET_CODE}, INVOICE {INVOICE}" />
        {(fitErr as any)?.code === "PATTERN_INVALID" ? <p className="error-text" role="alert">{(fitErr as any).message}</p> : null}
        <p className="hint">The preview and the test print show this memo filled in with the sample transaction.</p>
        <div className="row form-row">
          <Field label="Default signer">
            <select value={cfg.default_signer_id ?? ""} onChange={(e) => change((c) => { c.default_signer_id = e.target.value ? Number(e.target.value) : null; })}>
              <option value="">None</option>
              {setup.signers.filter((x: any) => x.active).map((x: any) => <option key={x.id} value={x.id}>{x.name}{x.title ? ` (${x.title})` : ""}</option>)}
            </select>
          </Field>
          <Field label="No signature above this amount ($, optional)" hint="Above it the signature does not print; the check is signed by hand.">
            <MoneyIn value={cfg.signature_limit_cents} onChange={(v) => change((c) => { c.signature_limit_cents = v; })} />
          </Field>
        </div>
        <div className="row form-row">
          <Field label="Signature lines">
            <select value={cfg.stock.signature_lines} onChange={(e) => change((c) => setLines(c, Number(e.target.value), setup.signature2_default))}>
              <option value={1}>One signature line</option><option value={2}>Two signature lines (two signers)</option>
            </select>
          </Field>
          {cfg.stock.signature_lines === 2 ? (
            <>
              <Field label="Second default signer">
                <select value={cfg.default_signer2_id ?? ""} onChange={(e) => change((c) => { c.default_signer2_id = e.target.value ? Number(e.target.value) : null; })}>
                  <option value="">None (signed by hand)</option>
                  {setup.signers.filter((x: any) => x.active).map((x: any) => <option key={x.id} value={x.id}>{x.name}{x.title ? ` (${x.title})` : ""}</option>)}
                </select>
              </Field>
              <Field label="Only one signature above this amount ($, optional)" hint="Above it the second line is left to be signed by hand. Must be below the no-signature amount.">
                <MoneyIn value={cfg.second_line_limit_cents} onChange={(v) => change((c) => { c.second_line_limit_cents = v; })} />
              </Field>
            </>
          ) : null}
        </div>
        {cfg.stock.signature_lines === 2 ? <p className="hint">The two lines need two different signers. Place the second line under Field positions.</p> : null}
      </Section>

      <Section id="feed" title="Feed modes">
        <p className="hint">How the paper goes into the printer. The user picks one when printing (the sheet counter suggests it). The offset moves everything on the
          check (right / down positive) for this feed mode only; each user can also save a small adjustment for their own printer.</p>
        <table className="table compact">
          <thead><tr><th>Label</th><th>Kind</th><th>Details</th><th>Offset right</th><th>Offset down</th><th>Printer note</th><th /></tr></thead>
          <tbody>
            {cfg.feed_modes.map((m: any, i: number) => (
              <tr key={m.key}>
                <td><input aria-label="Feed mode label" maxLength={60} value={m.label} onChange={(e) => change((c) => { c.feed_modes[i].label = e.target.value; })} /></td>
                <td>{m.kind === "SHEET" ? "Sheet" : "Single check"}</td>
                <td>
                  {m.kind === "SHEET" ? (
                    <select aria-label="Position on the sheet" value={m.position} onChange={(e) => change((c) => { c.feed_modes[i].position = Number(e.target.value); })}>
                      {cfg.stock.check_tops.map((_: number, p: number) => <option key={p} value={p}>{["Top", "Middle", "Bottom"][p] || `#${p + 1}`} check</option>)}
                    </select>
                  ) : (
                    <>
                      <select aria-label="Which end feeds first" value={m.lead} onChange={(e) => change((c) => { c.feed_modes[i].lead = e.target.value; })}>
                        <option value="DATE_END">Date end first</option><option value="PAYTO_END">Pay-to end first</option>
                      </select>{" "}
                      <select aria-label="Page size" value={m.page} onChange={(e) => change((c) => { c.feed_modes[i].page = e.target.value; })}>
                        <option value="LETTER">Letter page (no printer setup needed)</option><option value="CHECK">Check-sized page</option>
                      </select>{" "}
                      {m.page === "LETTER" ? (
                        <select aria-label="Manual-feed guides" value={m.guide} onChange={(e) => change((c) => { c.feed_modes[i].guide = e.target.value; })}>
                          <option value="CENTER">Guides center the paper</option><option value="LEFT">Against the left guide</option><option value="RIGHT">Against the right guide</option>
                        </select>
                      ) : null}
                    </>
                  )}
                </td>
                <td><NumIn label="Offset right" value={m.dx} step={0.0625} min={-setup.limits.feed_offset_max} max={setup.limits.feed_offset_max} onChange={(v) => change((c) => { c.feed_modes[i].dx = v; })} /></td>
                <td><NumIn label="Offset down" value={m.dy} step={0.0625} min={-setup.limits.feed_offset_max} max={setup.limits.feed_offset_max} onChange={(v) => change((c) => { c.feed_modes[i].dy = v; })} /></td>
                <td><input aria-label="Printer note" maxLength={200} value={m.note || ""} onChange={(e) => change((c) => { c.feed_modes[i].note = e.target.value || null; })} /></td>
                <td>{cfg.feed_modes.length > 1 ? <button className="small" onClick={() => change((c) => { c.feed_modes.splice(i, 1); })}>Remove</button> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="actions left">
          <button className="small" onClick={() => change((c) => { c.feed_modes.push({ key: `sheet_${Date.now() % 100000}`, label: "Sheet – middle check", kind: "SHEET", position: Math.min(1, c.stock.check_tops.length - 1), lead: "DATE_END", page: "LETTER", guide: "CENTER", dx: 0, dy: 0, note: null }); })}
                  disabled={cfg.feed_modes.length >= 6}>Add sheet feed mode</button>
          <button className="small" onClick={() => change((c) => { c.feed_modes.push({ key: `single_${Date.now() % 100000}`, label: "Single check – envelope feed", kind: "SINGLE", position: 0, lead: "DATE_END", page: "LETTER", guide: "CENTER", dx: 0, dy: 0, note: null }); })}
                  disabled={cfg.feed_modes.length >= 6}>Add single-check feed mode</button>
        </div>
      </Section>

      {cfg.stubs?.length ? <StubsSection cfg={cfg} setup={setup} change={change} /> : null}

      <Section id="tp" title="Test print and calibration">
        <p className="hint">Print on plain paper first and hold it over a blank check against a light. The calibration page shows rulers and where each field
          starts; the test print shows the sample check. Both use your unsaved changes.</p>
        <div className="row form-row">
          <Field label="Feed mode">
            <select value={testFeed} onChange={(e) => setTestFeed(e.target.value)}>
              {cfg.feed_modes.map((m: any) => <option key={m.key} value={m.key}>{m.label}</option>)}
            </select>
          </Field>
          <Field label="Signature on the test print">
            <select value={testSigner} onChange={(e) => setTestSigner(e.target.value)}>
              <option value="">Outlined box only</option>
              {setup.signers.filter((x: any) => x.active && x.has_image).map((x: any) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select>
          </Field>
          <button disabled={busy} onClick={() => pdfReq("calibration")}>Calibration page</button>
          <button disabled={busy} onClick={() => pdfReq("test-print")}>Test print</button>
          {pdf && !viewing ? <button className="link" onClick={() => setViewing("Last test page")}>Show the last page again</button> : null}
        </div>
        {fm?.note ? <p className="hint">Printer note: {fm.note}</p> : null}
        <BrowserTips singleFeed={fm?.kind === "SINGLE"} />
        {pdf && viewing ? <PdfViewer pdf={pdf} title={viewing} singleFeed={fm?.kind === "SINGLE"} onClose={() => setViewing(null)} /> : null}
      </Section>
      <div className="actions sticky-actions">
        {saved ? <span className="hint" role="status">Saved.</span> : null}
        <button onClick={() => { setCfg(clone(style.config)); setName(style.name); setDirty(false); }} disabled={!dirty}>Undo changes</button>
        <button className="primary" onClick={save} disabled={!dirty}>Save check style</button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ signers (#159)
function Signers({ setup, onChanged }: { setup: any; onChanged: () => void }) {
  const [err, setErr] = useState<unknown>(null);
  const [add, setAdd] = useState(false);
  const [edit, setEdit] = useState<any>(null);
  const [v, setV] = useState(0);
  const act = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); setV(v + 1); onChanged(); } catch (x) { setErr(x); } };
  return (
    <section className="card" aria-labelledby="signers-h">
      <h2 id="signers-h">Signers and signatures</h2>
      <p className="hint">A signature image (PNG) is stored encrypted and can never be downloaded again – only a small preview marked SAMPLE is shown.
        It prints only on real checks and, when you choose it, on your test prints. Every print that uses it is recorded in the audit log.</p>
      <ErrorBox error={err} />
      {setup.signers.length ? (
        <table className="table compact">
          <thead><tr><th>Name</th><th>Title</th><th>Signature</th><th>Status</th><th /></tr></thead>
          <tbody>
            {setup.signers.map((x: any) => (
              <tr key={x.id}>
                <td>{x.name}</td><td>{x.title || ""}</td>
                <td>{x.has_image ? <img src={`/api/checks/signers/${x.id}/preview?v=${v}-${x.image_uploaded_at}`} alt={`Sample of ${x.name}'s signature`} height={40} /> : <span className="muted">No image</span>}</td>
                <td>{x.active ? "Active" : <span className="badge grey">Deactivated</span>}</td>
                <td className="actions-cell">
                  <button className="small" onClick={() => setEdit(x)}>Edit…</button>{" "}
                  <label className="button small">Upload image<input type="file" accept="image/png" hidden onChange={(e) => {
                    const f = e.target.files?.[0]; e.target.value = "";
                    if (f) act(() => api.upload(`/api/checks/signers/${x.id}/image`, f));
                  }} /></label>{" "}
                  {x.has_image ? <button className="small" onClick={() => window.confirm(`Remove ${x.name}'s signature image?`) && act(() => api.post(`/api/checks/signers/${x.id}/image/remove`))}>Remove image</button> : null}{" "}
                  <button className="small" onClick={() => act(() => api.post(`/api/checks/signers/${x.id}/active`, { active: !x.active }))}>{x.active ? "Deactivate" : "Activate"}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">No signers yet.</p>}
      <div className="actions left"><button onClick={() => setAdd(true)}>Add signer…</button></div>
      {add ? <SignerForm onClose={() => setAdd(false)} onDone={() => { setAdd(false); onChanged(); }} /> : null}
      {edit ? <SignerForm signer={edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); onChanged(); }} /> : null}
    </section>
  );
}

function SignerForm({ signer, onClose, onDone }: { signer?: any; onClose: () => void; onDone: () => void }) {
  const [name, setName] = useState(signer?.name || "");
  const [title, setTitle] = useState(signer?.title || "");
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const go = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      if (signer) await api.put(`/api/checks/signers/${signer.id}`, { name, title: title || null });
      else {
        const fd = new FormData();
        fd.append("name", name);
        if (title) fd.append("title", title);
        if (file) fd.append("file", file);
        await api.postForm("/api/checks/signers", fd);
      }
      onDone();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={signer ? `Edit ${signer.name}` : "Add signer"} onClose={onClose}>
      <GuardedForm onSubmit={go}>
        <ErrorBox error={err} />
        <Field label="Name (prints on record copies as 'SIGNATURE ON FILE: NAME')"><input required maxLength={120} value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Title (optional)"><input maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Treasurer" /></Field>
        {!signer ? <Field label="Signature image (PNG, optional now)" hint="A scan or photo of the signature on white paper, cropped close. Transparent backgrounds work best.">
          <input type="file" accept="image/png" onChange={(e) => setFile(e.target.files?.[0] || null)} /></Field> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}
