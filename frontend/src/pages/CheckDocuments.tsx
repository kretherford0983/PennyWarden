/** 2.0.0 (#165, #166): cover letter and #10 envelope templates on the Administrator's Payments Setup screen.
 * Text sections use the pattern syntax with autocomplete; test prints use sample data only (BR-003). */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, RowMenu } from "../components";
import { LivePreview, PatternInput, PdfViewer, Section, usePdf, viewState } from "./checkShared";
import { EnvelopeLibrary, SharedNotice } from "./Envelopes";

const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));
const DOC_FONTS: [string, string][] = [["CARLITO", "Carlito (Calibri-compatible)"], ["SANS", "Liberation Sans (Arial-compatible)"], ["SERIF", "Liberation Serif (Times-compatible)"]];

/** Where an editor opens: "name" selects the name (a new or duplicated template, #217); "window" opens the letter's
 * Window envelope section. */
export type DocFocus = "name" | "window" | undefined;

/** The template lists on the Payments Setup page: cover letters and envelopes, each its own section. Editing a
 * template opens its editor on a page of its own (DocumentEditor, shown by Payments Setup in place of the page).
 * Build 11 (#217): new templates get a free name ("… 2"), Duplicate copies one, and the Envelopes section points to the
 * cover letter's Window envelope settings (a window envelope needs no envelope printing - the letter carries the
 * addresses). Templates are never deleted (BR-001): deactivate one instead. Build 13: New and Duplicate open a DRAFT -
 * nothing is stored until its first Save, so backing out keeps nothing. */
export function DocumentsSection({ setup, onChanged, onEdit }: { setup: any; onChanged: () => void; onEdit: (doc: any, focus?: DocFocus) => void }) {
  const [err, setErr] = useState<unknown>(null);
  const act = async (fn: () => Promise<any>) => { setErr(null); try { await fn(); onChanged(); } catch (x) { setErr(x); } };
  const draft = (q: string) => act(async () => onEdit(await api.get(`/api/checks/documents/draft?${q}`), "name"));
  const create = (kind: "LETTER" | "ENVELOPE", preset?: "WINDOW") => draft(`kind=${kind}${preset ? `&preset=${preset}` : ""}`);
  const duplicate = (d: any) => draft(`kind=${d.kind}&duplicate_of=${d.id}`);
  const docs = setup.documents || [];
  const letters = docs.filter((d: any) => d.kind === "LETTER");
  const windowLetter = letters.find((d: any) => d.active && d.config?.window !== "NONE")
    || letters.find((d: any) => d.active && d.is_default) || letters.find((d: any) => d.active);
  const card = (kind: "LETTER" | "ENVELOPE", id: string, label: string, intro: React.ReactNode, buttons: React.ReactNode, note?: React.ReactNode) => {
    const list = docs.filter((d: any) => d.kind === kind);
    return (
      <section className="card" aria-labelledby={id}>
        <h2 id={id}>{label}</h2>
        <p className="hint">{intro}</p>
        {note}
        {list.length ? (
          <table className="table compact">
            <thead><tr><th>Name</th><th>Default</th><th>Status</th><th /></tr></thead>
            <tbody>
              {list.map((d: any) => (
                <tr key={d.id}>
                  <td>{d.name}{" "}{kind === "LETTER" && d.config?.window && d.config.window !== "NONE" ? <span className="badge grey">Window envelope</span> : null}</td>
                  <td>{d.is_default ? "Default" : ""}</td>
                  <td>{d.active ? "Active" : <span className="badge grey">Deactivated</span>}</td>
                  <td className="actions-cell">
                    <button className="small" onClick={() => onEdit(d)}>Edit</button>
                    <RowMenu name={d.name} actions={[
                      { label: "Duplicate", onClick: () => duplicate(d) },
                      d.active && !d.is_default && { label: "Make default", onClick: () => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { is_default: true })) },
                      d.active ? { label: "Deactivate", onClick: () => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { active: false })), danger: true }
                        : { label: "Activate", onClick: () => act(() => api.post(`/api/checks/documents/${d.id}/flags`, { active: true })) },
                    ]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="muted">None yet.</p>}
        <div className="actions left">{buttons}</div>
      </section>
    );
  };
  return (
    <>
      <ErrorBox error={err} />
      {card("LETTER", "letters-h", "Cover letters",
        "Optional: a letter listing the invoices paid, printed with the check (or on its own for a check written by hand) and attached to the transaction. Keep as many as you need (for example invoices, a refund, a donation); the letter is chosen for each payment when printing.",
        <>
          <button onClick={() => create("LETTER")}>New cover letter</button>
          <button onClick={() => create("LETTER", "WINDOW")}>New window-envelope letter</button>
        </>)}
      {/* 2.2.0 (#325): envelopes are one library shared with Donations; this page lists Payments' own */}
      <EnvelopeLibrary feature="PAYMENTS" docs={docs.filter((d: any) => d.kind === "ENVELOPE")} onChanged={onChanged} onEdit={onEdit} note={
        <div className="alert info" data-testid="window-pointer">
          <b>Using #10 double-window envelopes?</b> Nothing is printed on a window envelope: the cover letter carries the return and payee addresses, so it is
          set up on a cover letter, in its <i>Window envelope</i> section.{" "}
          {windowLetter ? <button type="button" className="linklike" onClick={() => onEdit(windowLetter, "window")}>Open the window envelope settings of “{windowLetter.name}”</button>
            : <button type="button" className="linklike" onClick={() => create("LETTER", "WINDOW")}>Start a window-envelope letter</button>}
        </div>} />
    </>
  );
}

/** A cover letter or envelope template's editor - the whole page, nothing else from Payments Setup above it. */
export function DocumentEditor({ setup, doc, focus, onClose, onSaved, onOpen, feature = "PAYMENTS", backLabel = "Back to Payments Setup" }: {
  setup: any; doc: any; focus?: DocFocus; onClose: () => void; onSaved: (d: any) => void; onOpen: (d: any, focus?: DocFocus) => void;
  feature?: string | null; backLabel?: string;   // 2.2.0 (#325): the page the envelope editor was opened from (null: Envelopes)
}) {
  const Editor = doc.kind === "LETTER" ? LetterEditor : EnvelopeEditor;
  return <Editor key={doc.id} setup={setup} doc={doc} focus={focus} onClose={onClose} onSaved={onSaved} onOpen={onOpen} feature={feature} backLabel={backLabel} />;
}

type EditorProps = { setup: any; doc: any; focus?: DocFocus; onClose: () => void; onSaved: (d: any) => void; onOpen: (d: any, focus?: DocFocus) => void; feature?: string | null; backLabel?: string };

/** #217: a new or duplicated template opens with its name selected, ready to type over. */
function NameField({ e, focus }: { e: ReturnType<typeof useEditor>; focus?: DocFocus }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => { if (focus === "name" && ref.current) { ref.current.focus(); ref.current.select(); } }, [focus]);
  return <Field label="Name"><input ref={ref} maxLength={80} value={e.name} onChange={(ev) => e.setName(ev.target.value)} /></Field>;
}

/** Build 13: a draft (`doc.id` null: new or duplicated, not stored yet) previews and test-prints through the draft
 * endpoints and is created by its first Save. */
function useEditor(doc: any, onSaved: (d: any) => void) {
  const isDraft = doc.id == null;
  const [cfg, setCfg] = useState<any>(clone(doc.config));
  const [name, setName] = useState(doc.name);
  const [err, setErr] = useState<unknown>(null);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(!!doc.justCreated);   // a draft's first Save reopens the editor on the stored template
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState(false);
  const change = (fn: (c: any) => void) => { const c = clone(cfg); fn(c); setCfg(c); setDirty(true); setSaved(false); };
  const save = async () => {
    setErr(null);
    try {
      const d = isDraft
        ? await api.post("/api/checks/documents", { kind: doc.kind, name, config: cfg, ...(doc.duplicate_of ? { duplicate_of: doc.duplicate_of } : {}),
            ...(doc.kind === "ENVELOPE" ? { feature: doc.feature === undefined ? "PAYMENTS" : doc.feature } : {}) })
        : await api.put(`/api/checks/documents/${doc.id}`, { name, config: cfg });
      setDirty(false); setSaved(true); onSaved(isDraft ? { ...d, justCreated: true } : d);
    } catch (x) { setErr(x); }
  };
  const test = async () => {
    setErr(null);
    try {
      const blob = isDraft ? await api.postBlob("/api/checks/documents/draft/test-print", { kind: doc.kind, config: cfg, logo_from: doc.duplicate_of ?? null })
        : await api.postBlob(`/api/checks/documents/${doc.id}/test-print`, { config: cfg });
      setPdf(blob, `${doc.kind.toLowerCase()}-test.pdf`); setViewing(true);
    } catch (x) { setErr(x); }
  };
  return { isDraft, cfg, change, name, setName: (v: string) => { setName(v); setDirty(true); }, err, dirty, saved, save, test, pdf, viewing, setViewing, reset: () => { setCfg(clone(doc.config)); setName(doc.name); setDirty(false); } };
}

function EditorFrame({ title, e, onClose, children, singleFeed, backLabel = "Back to Payments Setup" }: { title: string; e: ReturnType<typeof useEditor>; onClose: () => void; children: React.ReactNode; singleFeed?: boolean; backLabel?: string }) {
  return (
    <div className="check-setup">
      <div className="row space-between">
        <h1>{title}</h1>
        <button onClick={() => {
          if (!e.dirty || window.confirm(e.isDraft ? "This new template is not saved yet. Leave without keeping it?" : "Leave without saving your changes?")) onClose();
        }}>{backLabel}</button>
      </div>
      {e.isDraft ? <div className="alert info" role="note" data-testid="draft-note"><b>Not saved yet.</b> Nothing is kept until you click <b>Save</b>;
        going back without saving leaves no template behind.</div> : null}
      <ErrorBox error={e.err} />
      {children}
      <div className="actions sticky-actions">
        {e.saved ? <span className="hint" role="status">Saved.</span> : null}
        <button onClick={e.test}>Test print (sample data)</button>
        <button onClick={e.reset} disabled={!e.dirty}>Undo changes</button>
        <button className="primary" onClick={e.save} disabled={!e.dirty && !e.isDraft}>Save</button>
      </div>
      {e.pdf && e.viewing ? <PdfViewer pdf={e.pdf} title="Test print" singleFeed={singleFeed} onClose={() => e.setViewing(false)} /> : null}
    </div>
  );
}

/** #186: the live preview at the top of a letter or envelope editor (sample data, unsaved settings). */
function PreviewSection({ doc, e, scope, version = "" }: { doc: any; e: ReturnType<typeof useEditor>; scope: string; version?: string }) {
  const pinKey = `${scope}-pin`;
  const [pin, setPin] = useState(() => viewState.get(pinKey) ?? false);
  useEffect(() => { viewState.set(pinKey, pin); }, [pin, pinKey]);
  const letter = doc.kind === "LETTER";
  const aspect = letter ? 8.5 / 11 : (Number(e.cfg.width) || 9.5) / (Number(e.cfg.height) || 4.125);
  return (
    <Section id="pv" scope={scope} title="Preview (drawn to scale, sample data)" className={`doc-preview ${letter ? "letter" : "envelope"} ${pin ? "pinned" : ""}`} extra={
      <label className="check"><input type="checkbox" checked={pin} onChange={(ev) => setPin(ev.target.checked)} /> Keep at the top</label>
    }>
      <LivePreview imageUrl={e.isDraft ? "/api/checks/documents/draft/preview-image" : `/api/checks/documents/${doc.id}/preview-image`}
                   pdfUrl={e.isDraft ? "/api/checks/documents/draft/preview" : `/api/checks/documents/${doc.id}/preview`}
                   body={e.isDraft ? { kind: doc.kind, config: e.cfg, logo_from: doc.duplicate_of ?? null } : { config: e.cfg }}
                   title={letter ? "Cover letter preview" : "Envelope preview"} aspect={aspect} deps={[e.cfg, version]} />
      <p className="hint">{letter ? "The letter as it prints, with a sample payee and two sample invoices. It updates as you type." :
        "The envelope as it prints, with a sample payee. It updates as you type; Test print shows it on the page as the printer is fed."}</p>
    </Section>
  );
}

function Lines({ label, lines, max, onChange, variables, idBase, addLabel = "+ Add line" }: { label: string; lines: string[]; max: number; onChange: (l: string[]) => void; variables: any[]; idBase: string; addLabel?: string }) {
  return (
    <fieldset className="lines">
      <legend>{label}</legend>
      {lines.map((l, i) => (
        <div key={i} className="row form-row">
          <PatternInput id={`${idBase}-${i}`} label={`${label} line ${i + 1}`} value={l} variables={variables} hint={false} onChange={(v) => onChange(lines.map((x, j) => (j === i ? v : x)))} />
          <button type="button" className="small" onClick={() => onChange(lines.filter((_, j) => j !== i))} aria-label={`Remove ${label.toLowerCase()} line ${i + 1}`}>Remove</button>
        </div>
      ))}
      {lines.length < max ? <button type="button" className="small" onClick={() => onChange([...lines, ""])}>{addLabel}</button> : null}
    </fieldset>
  );
}

function LetterEditor({ setup, doc, focus, onClose, onSaved }: EditorProps) {
  if (focus === "window") viewState.set("pw-letter-lwin", true);   // #217: arrive at an open Window envelope section
  const e = useEditor(doc, onSaved);
  const winRef = useRef<HTMLSelectElement>(null);
  useEffect(() => {
    if (focus === "window" && winRef.current) {
      winRef.current.scrollIntoView({ block: "center" });
      winRef.current.focus();
    }
  }, [focus]);
  const c = e.cfg;
  const vars = setup.letter_variables;
  const cols: any[] = c.columns;
  const allCols: any[] = setup.letter_columns;
  const unused = allCols.filter((x) => !cols.some((y) => y.key === x.key));
  const move = (i: number, d: number) => e.change((x) => { const [it] = x.columns.splice(i, 1); x.columns.splice(i + d, 0, it); });
  // #176: the logo is uploaded and removed at once (not part of Save); the preview redraws with it
  const [logo, setLogo] = useState<any>(doc.logo || null);
  const [logoErr, setLogoErr] = useState<unknown>(null);
  const logoAct = async (fn: () => Promise<any>) => {
    setLogoErr(null);
    try { const d = await fn(); setLogo(d.logo || null); } catch (x) { setLogoErr(x); }
  };
  const windowed = c.window !== "NONE";
  const off = (k: string) => (ev: any) => e.change((x) => { x[k] = Number(ev.target.value) || 0; });
  return (
    <EditorFrame title={`Cover letter: ${doc.name}`} e={e} onClose={onClose}>
      <PreviewSection doc={doc} e={e} scope="pw-letter" version={logo?.version || ""} />
      <Section id="lgen" scope="pw-letter" title="General">
        <div className="row form-row">
          <NameField e={e} focus={focus} />
          <Field label="Font"><select value={c.font} onChange={(ev) => e.change((x) => { x.font = ev.target.value; })}>{DOC_FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Size (pt)"><input type="number" min={8} max={14} step={0.5} value={c.size} onChange={(ev) => e.change((x) => { x.size = Number(ev.target.value) || 11; })} /></Field>
          <label className="check"><input type="checkbox" checked={c.include_by_default} onChange={(ev) => e.change((x) => { x.include_by_default = ev.target.checked; })} /> "Include cover letter" starts ticked on the print screen</label>
        </div>
      </Section>
      <Section id="llh" scope="pw-letter" title="Letterhead">
        <label className="check"><input type="checkbox" checked={c.preprinted} onChange={(ev) => e.change((x) => { x.preprinted = ev.target.checked; })} /> Pre-printed letterhead paper (print no letterhead or logo; keep the top of the page blank)</label>
        {c.preprinted ? (
          <Field label="Blank space at the top (in)"><input type="number" min={1} max={4} step={0.125} value={c.preprinted_margin} onChange={(ev) => e.change((x) => { x.preprinted_margin = Number(ev.target.value) || 2; })} /></Field>
        ) : null}
        <Lines label="Letterhead" idBase="lh" lines={c.letterhead} max={6} variables={vars} onChange={(l) => e.change((x) => { x.letterhead = l; })} />
        <p className="hint">The first line prints in bold. <code>{"{ORG}"}</code> is the organization's name. Typical lines: street, town, phone, email.
          {c.preprinted ? " On pre-printed paper these lines are used only as the return address in a window envelope." : ""}</p>
        <fieldset className="lines">
          <legend>Logo</legend>
          <ErrorBox error={logoErr} />
          {e.isDraft ? (
            logo?.from ? (
              <div className="row form-row">
                <img className="logo-thumb" src={`/api/checks/documents/${logo.from}/logo?v=${logo.version}`} alt="The letter's logo" />
                <Field label="Logo position"><select value={c.logo_position} onChange={(ev) => e.change((x) => { x.logo_position = ev.target.value; })}>
                  <option value="LEFT">Top left</option><option value="CENTER">Top center (the letterhead lines are centered too)</option></select></Field>
                <p className="hint">The copied letter's logo; it is copied when you save.</p>
              </div>
            ) : <p className="muted">No logo. Save the letter first, then add one here.</p>
          ) : logo ? (
            <div className="row form-row">
              <img className="logo-thumb" src={`/api/checks/documents/${doc.id}/logo?v=${logo.version}`} alt="The letter's logo" />
              <Field label="Logo position"><select value={c.logo_position} onChange={(ev) => e.change((x) => { x.logo_position = ev.target.value; })}>
                <option value="LEFT">Top left</option><option value="CENTER">Top center (the letterhead lines are centered too)</option></select></Field>
              <button type="button" className="small" onClick={() => logoAct(() => api.post(`/api/checks/documents/${doc.id}/logo/remove`, {}))}>Remove logo</button>
            </div>
          ) : <p className="muted">No logo.</p>}
          {e.isDraft ? null : <label className="button small">{logo ? "Replace logo…" : "Add a logo…"}
            <input type="file" accept="image/png,image/jpeg" hidden aria-label="Logo image" onChange={(ev) => {
              const f = ev.target.files?.[0];
              ev.target.value = "";
              if (f) logoAct(() => api.upload(`/api/checks/documents/${doc.id}/logo`, f));
            }} />
          </label>}
          <p className="hint">PNG or JPEG, at most 1 MB. It prints above the letterhead lines, scaled to fit 2.5 × 1 in. Adding or removing the logo takes effect at once.</p>
        </fieldset>
        <label className="check"><input type="checkbox" checked={c.show_date} onChange={(ev) => e.change((x) => { x.show_date = ev.target.checked; })} /> Print today's date under the letterhead</label>
      </Section>
      {/* 2.2.0 (#317): the addressee block, like the letterhead, from {PAYEE.*} */}
      <Section id="ladr" scope="pw-letter" title="Addressee">
        <Lines label="Addressee" idBase="adr" addLabel="+ Add addressee line" lines={c.addressee || []} max={6} variables={vars} onChange={(l) => e.change((x) => { x.addressee = l; })} />
        <p className="hint">The payee's block under the date (and in the lower window of a window-envelope letter). The default is the payee's name and mailing
          address: <code>{"{PAYEE.NAME}"}</code>, <code>{"{PAYEE.MAILING_ADDRESS}"}</code>. A several-line value prints as several lines; empty lines are left out.</p>
      </Section>
      <Section id="ltext" scope="pw-letter" title="Text">
        <p className="hint">The payee's name and address (from the payee's entity) print under "To:". Type <code>{"{"}</code> for the variables; a blank line starts a new paragraph.</p>
        <PatternInput id="subject" label="Subject" value={c.subject} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.subject = v; })} />
        <PatternInput id="salutation" label="Salutation" value={c.salutation} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.salutation = v; })} />
        <PatternInput id="opening" label="Opening paragraph" multiline maxLength={2000} value={c.opening} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.opening = v; })} />
        <h3>Invoice table</h3>
        <table className="table compact">
          <thead><tr><th>Column</th><th>Heading</th><th /></tr></thead>
          <tbody>
            {cols.map((col, i) => (
              <tr key={col.key}>
                <td>{allCols.find((x) => x.key === col.key)?.heading}</td>
                <td><input aria-label={`Heading for ${col.key}`} maxLength={40} value={col.heading} onChange={(ev) => e.change((x) => { x.columns[i].heading = ev.target.value; })} /></td>
                <td className="actions-cell">
                  <button className="small" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move left">↑</button>{" "}
                  <button className="small" disabled={i === cols.length - 1} onClick={() => move(i, 1)} aria-label="Move right">↓</button>{" "}
                  <button className="small" disabled={cols.length === 1} onClick={() => e.change((x) => { x.columns.splice(i, 1); })}>Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {unused.length ? (
          <div className="row form-row">
            {unused.map((u) => <button key={u.key} className="small" onClick={() => e.change((x) => { x.columns.push({ key: u.key, heading: u.heading }); })}>+ {u.heading}</button>)}
          </div>
        ) : null}
        <Field label="Total line label"><input maxLength={60} value={c.total_label} onChange={(ev) => e.change((x) => { x.total_label = ev.target.value; })} /></Field>
        <PatternInput id="closing" label="Closing paragraph(s)" multiline maxLength={2000} value={c.closing} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.closing = v; })} />
        <PatternInput id="signoff" label="Sign-off" value={c.signoff} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.signoff = v; })} />
      </Section>
      <Section id="lwin" scope="pw-letter" title="Window envelope (#10 double-window)">
        <p className="hint">For #10 double-window envelopes nothing is printed on the envelope: the addresses print on this letter and show through the
          windows. Leave this at <i>None</i> for a plain envelope (printed from an envelope template).</p>
        <Field label="Address for a window envelope">
          <select ref={winRef} value={c.window} onChange={(ev) => e.change((x) => {
            // 2.1.0 (#247): a new window-envelope letter starts with fold marks on the front
            if (e.isDraft && x.window === "NONE" && ev.target.value !== "NONE" && x.fold_marks === "NONE") x.fold_marks = "FRONT";
            x.window = ev.target.value;
          })}>
            <option value="NONE">None (the letter goes in a plain envelope)</option>
            <option value="LETTER">On the letter: addresses at the top, the letter starts below the first fold</option>
            <option value="ADDRESS_PAGE">On a separate address page in front of the letter</option>
          </select>
        </Field>
        {windowed ? (
          <>
            <label className="check"><input type="checkbox" checked={c.window_return} onChange={(ev) => e.change((x) => { x.window_return = ev.target.checked; })} /> Return address (the letterhead lines) in the upper window</label>
            <p className="hint">The page is folded in three with the addresses on the top panel facing the windows. Positions follow a standard #10 double-window
              envelope; if yours differs, move each address (inches; right and down are positive). Test print draws the windows as dashed boxes and marks the folds:
              print it on plain paper, fold it and hold it behind the envelope.</p>
            <div className="row form-row">
              <Field label="Return address – right (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={c.return_dx} onChange={off("return_dx")} /></Field>
              <Field label="Return address – down (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={c.return_dy} onChange={off("return_dy")} /></Field>
              <Field label="Payee address – right (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={c.payee_dx} onChange={off("payee_dx")} /></Field>
              <Field label="Payee address – down (in)"><input type="number" step={0.0625} min={-0.75} max={0.75} value={c.payee_dy} onChange={off("payee_dy")} /></Field>
            </div>
          </>
        ) : null}
      </Section>
      <Section id="lfold" scope="pw-letter" title="Fold marks">
        <p className="hint">Small ticks at the left and right edges where the letter is folded in even thirds for a #10 envelope — just enough to fold by,
          and barely noticeable to the recipient. On the first sheet only. Each user can choose their own default in <i>My letter printer
          settings</i> on the print screen, and change it for one letter.</p>
        <Field label="Print fold marks">
          <select aria-label="Print fold marks" value={c.fold_marks} onChange={(ev) => e.change((x) => { x.fold_marks = ev.target.value; })}>
            <option value="NONE">No</option>
            <option value="FRONT">On the front of the page</option>
            <option value="BACK">On the back of the page (needs two-sided printing)</option>
          </select>
        </Field>
        {c.fold_marks === "BACK" ? (
          <p className="hint" role="note">The letter's PDF gets a back page for every page (the marks behind page 1, the others blank), so print it
            two-sided (flip on long edge). Printed one-sided, the marks come out on a separate sheet.</p>
        ) : null}
        {c.fold_marks !== "NONE" ? (
          <div className="row form-row">
            <Field label="Tick length (in)"><input type="number" aria-label="Tick length" step={0.05} min={0.1} max={0.5} value={c.fold_length} onChange={off("fold_length")} /></Field>
            <Field label="From the paper edge (in)"><input type="number" aria-label="Tick distance from the edge" step={0.05} min={0.1} max={0.5} value={c.fold_edge} onChange={off("fold_edge")} /></Field>
            <Field label="Line weight">
              <select aria-label="Tick line weight" value={c.fold_weight} onChange={(ev) => e.change((x) => { x.fold_weight = ev.target.value; })}>
                <option value="HAIRLINE">Hairline</option><option value="THIN">Thin</option><option value="MEDIUM">Medium</option>
              </select>
            </Field>
            <Field label="Shade">
              <select aria-label="Tick shade" value={c.fold_shade} onChange={(ev) => e.change((x) => { x.fold_shade = ev.target.value; })}>
                <option value="LIGHT">Light gray</option><option value="MEDIUM">Medium gray</option><option value="DARK">Dark gray</option>
              </select>
            </Field>
          </div>
        ) : null}
      </Section>
      <Section id="lsign" scope="pw-letter" title="Signed by">
        <p className="hint">The letter is signed (by name — never the signature image) by the check's signer: name, title and organization. When the check prints
          without a signer, these are used instead:</p>
        <div className="row form-row">
          <PatternInput id="fbname" label="Name when there is no signer" value={c.fallback_name} variables={vars} hint={false} onChange={(v) => e.change((x) => { x.fallback_name = v; })} />
          <PatternInput id="fbrole" label="Role when there is no signer" value={c.fallback_role} variables={vars} hint={false} placeholder="e.g. Treasurer, {ORG}" onChange={(v) => e.change((x) => { x.fallback_role = v; })} />
        </div>
      </Section>
    </EditorFrame>
  );
}

function EnvelopeEditor({ setup, doc, focus, onClose, onSaved, onOpen, feature = "PAYMENTS", backLabel }: EditorProps) {
  const e = useEditor(doc, onSaved);
  const c = e.cfg;
  const letters = (setup.documents || []).filter((d: any) => d.kind === "LETTER" && d.active);
  const winLetter = letters.find((d: any) => d.config?.window !== "NONE") || letters.find((d: any) => d.is_default) || letters[0];
  const openWindow = () => { if (!e.dirty || window.confirm("Leave without saving your changes?")) onOpen(winLetter, "window"); };
  const n = (k: string) => (ev: any) => e.change((x) => { x[k] = Number(ev.target.value) || 0; });
  return (
    <EditorFrame title={`Envelope: ${doc.name}`} e={e} onClose={onClose} singleFeed backLabel={backLabel}>
      <SharedNotice doc={doc} feature={feature} onOpen={(d) => { if (!e.dirty || window.confirm("Leave without saving your changes?")) onOpen(d); }} />
      {feature === "PAYMENTS" ? (
        <div className="alert info" data-testid="window-pointer">
          <b>This is for plain envelopes printed with the payee's address.</b> For #10 double-window envelopes, set up the <i>Window envelope</i> section of a
          cover letter instead: the letter carries the addresses.{" "}
          {winLetter ? <button type="button" className="linklike" onClick={openWindow}>Open the window envelope settings of “{winLetter.name}”</button> : null}
        </div>
      ) : feature === "DONATIONS" ? (
        <p className="hint">This is for plain envelopes printed with the donor's address. For #10 double-window envelopes, choose <i>Address for a window
          envelope</i> in Donations Setup's receipt letter instead: the receipt carries the addresses.</p>
      ) : null}
      <PreviewSection doc={doc} e={e} scope="pw-envelope" />
      <Section id="egen" scope="pw-envelope" title="General">
        <div className="row form-row">
          <NameField e={e} focus={focus} />
          <Field label="Width (in)"><input type="number" step={0.125} value={c.width} onChange={n("width")} /></Field>
          <Field label="Height (in)"><input type="number" step={0.125} value={c.height} onChange={n("height")} /></Field>
          <Field label="Font"><select value={c.font} onChange={(ev) => e.change((x) => { x.font = ev.target.value; })}>{DOC_FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Size (pt)"><input type="number" min={8} max={14} step={0.5} value={c.size} onChange={n("size")} /></Field>
          <label className="check"><input type="checkbox" checked={c.upper} onChange={(ev) => e.change((x) => { x.upper = ev.target.checked; })} /> Capitals</label>
        </div>
        <p className="hint">#10 envelope: 9.5 × 4.125 in. The addressee's name and address come from the entity: the payee for a payment, the donor for a donation.</p>
      </Section>
      <Section id="eret" scope="pw-envelope" title="Return address">
        <label className="check"><input type="checkbox" checked={c.return_address} onChange={(ev) => e.change((x) => { x.return_address = ev.target.checked; })} /> Print the return address (turn off for envelopes with a pre-printed return address; it can be switched for one print)</label>
        <Lines label="Return address" idBase="ret" lines={c.return_lines} max={5} variables={setup.envelope_variables} onChange={(l) => e.change((x) => { x.return_lines = l; })} />
      </Section>
      <Section id="epos" scope="pw-envelope" title="Positions (inches from the envelope's top-left corner)">
        <div className="row form-row">
          <Field label="Return address – left"><input type="number" step={0.0625} value={c.return_x} onChange={n("return_x")} /></Field>
          <Field label="Return address – top"><input type="number" step={0.0625} value={c.return_y} onChange={n("return_y")} /></Field>
          <Field label="Payee address – left"><input type="number" step={0.0625} value={c.address_x} onChange={n("address_x")} /></Field>
          <Field label="Payee address – top"><input type="number" step={0.0625} value={c.address_y} onChange={n("address_y")} /></Field>
        </div>
      </Section>
      <Section id="efeed" scope="pw-envelope" title="Feeding">
        <div className="row form-row">
          <Field label="Which end goes in first"><select value={c.lead} onChange={(ev) => e.change((x) => { x.lead = ev.target.value; })}><option value="STAMP_END">Stamp end first</option><option value="OTHER_END">Return-address end first</option></select></Field>
          <Field label="Page size"><select value={c.page} onChange={(ev) => e.change((x) => { x.page = ev.target.value; })}><option value="LETTER">Letter page (no printer setup needed)</option><option value="ENVELOPE">Envelope-sized page</option></select></Field>
          {c.page === "LETTER" ? <Field label="Manual-feed guides"><select value={c.guide} onChange={(ev) => e.change((x) => { x.guide = ev.target.value; })}><option value="CENTER">Center the envelope</option><option value="LEFT">Against the left guide</option><option value="RIGHT">Against the right guide</option></select></Field> : null}
          <Field label="Offset right (in)"><input type="number" step={0.0625} min={-0.5} max={0.5} value={c.dx} onChange={n("dx")} /></Field>
          <Field label="Offset down (in)"><input type="number" step={0.0625} min={-0.5} max={0.5} value={c.dy} onChange={n("dy")} /></Field>
        </div>
        <Field label="Printer note (shown when printing)"><input maxLength={200} value={c.note || ""} onChange={(ev) => e.change((x) => { x.note = ev.target.value || null; })} /></Field>
      </Section>
    </EditorFrame>
  );
}

