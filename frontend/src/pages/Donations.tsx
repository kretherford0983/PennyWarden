/** 2.1.0 (#312): the Donations module, part 1 - donation receipt letters.
 * - DonationSetup (Administrators): the receipt template and signer (the EIN and address: System/About, #314), a live
 *   preview and a test print with sample data only.
 * - DonationReceiptDialog (from a deposit in the register): Register Users mark lines as donations and print one receipt
 *   per donor; Budget Managers, Budget Users and Auditors see the donation lines and receipts. */
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading, Modal, useConfirmable } from "../components";
import { useMe } from "../App";
import { Link } from "../router";
import { LivePreview, PatternInput, PdfViewer, Section, usePdf } from "./checkShared";
import { DocFocus, DocumentEditor } from "./CheckDocuments";
import { EnvelopeLibrary, ReceiptEnvelopePanel } from "./Envelopes";

const FONTS: [string, string][] = [["CARLITO", "Carlito (Calibri-compatible)"], ["SANS", "Liberation Sans (Arial-compatible)"], ["SERIF", "Liberation Serif (Times-compatible)"]];
const KIND_LABEL: Record<string, string> = { ORIGINAL: "Original", DUPLICATE: "Duplicate", CORRECTED: "Corrected" };

// ------------------------------------------------------------------ setup (Administrator)
export default function DonationSetup() {
  const [s, setS] = useState<any>(null);
  const [cfg, setCfg] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState(false);
  // 2.2.0 (#325): the envelopes used for Donations (the shared library) and their editor, in place of the page
  const [stmtPreview, setStmtPreview] = useState(false);
  const [lib, setLib] = useState<any>(null);
  const [editingEnv, setEditingEnv] = useState<any>(null);
  const [envFocus, setEnvFocus] = useState<DocFocus>(undefined);
  const loadLib = () => api.get("/api/envelopes").then(setLib, setErr);
  const load = () => api.get("/api/donations/setup").then((d) => { setS(d); setCfg(d.config); }, setErr);
  useEffect(() => { load(); loadLib(); }, []);
  if (editingEnv && lib) {
    const edit = (d: any, f?: DocFocus) => { setEditingEnv(d); setEnvFocus(f); };
    return <DocumentEditor setup={{ ...lib, documents: lib.envelopes }} doc={editingEnv} focus={envFocus} feature="DONATIONS" backLabel="Back to Donations Setup"
                           onOpen={edit} onClose={() => { edit(null); loadLib(); }} onSaved={(d) => { setEditingEnv(d); setEnvFocus(undefined); loadLib(); }} />;
  }
  if (!s || !cfg) return err ? <ErrorBox error={err} /> : <Loading />;
  const set = (k: string, v: unknown) => { setSaved(false); setCfg({ ...cfg, [k]: v }); };
  const dirty = JSON.stringify(cfg) !== JSON.stringify(s.config);
  const save = async () => {
    setErr(null);
    const sent = cfg;
    try {
      const d = await api.put("/api/donations/setup", { config: sent });
      setS(d);
      // a change typed while the save was on its way is kept (the page then shows "Unsaved changes")
      setCfg((cur: any) => (cur === sent ? d.config : cur));
      setSaved(true);
    } catch (x) { setErr(x); }
  };
  const statementTest = async () => {
    setErr(null);
    try { setPdf(await api.postBlob("/api/donations/setup/statement-test-print", { config: cfg }), "statement-test-print.pdf"); setViewing(true); } catch (x) { setErr(x); }
  };
  const testPrint = async () => {
    setErr(null);
    try { setPdf(await api.postBlob("/api/donations/setup/test-print", { config: cfg }), "receipt-test-print.pdf"); setViewing(true); } catch (x) { setErr(x); }
  };
  const vars = s.variables;
  return (
    <div className="page donation-setup">
      <h1>Donations Setup</h1>
      <p className="hint">Donation receipts are printed by Register Users from a deposit in the register (<b>Donation receipt…</b>). Here you set what every
        receipt carries. The preview and the test print use sample data only.</p>
      <ErrorBox error={err} />
      {s.missing.length ? <div className="alert warn" role="alert" data-testid="setup-missing">Receipts can't be printed until you enter {s.missing.join(" and ")} in{" "}
        <Link to="/about/general">System/About → Organization</Link>.</div> : null}
      <div className="setup-grid">
        <div>
          <Section id="org" scope="pw-donations" title="Organization">
            <dl className="dl" data-testid="donation-org">
              <dt>Name</dt><dd>{s.organization.name}</dd>
              <dt>Address</dt><dd>{s.organization.address.length ? s.organization.address.map((l: string, i: number) => <div key={i}>{l}</div>) : <span className="muted">Not entered</span>}</dd>
              <dt>EIN</dt><dd>{s.organization.ein || <span className="muted">Not entered</span>}</dd>
            </dl>
            <p className="hint">These come from <Link to="/about/general">System/About → Organization</Link>, where you change them. Every receipt prints the organization's name and EIN, the donor, the amount,
              the date received, the receipt number and the goods or services statement – these can't be removed.</p>
          </Section>
          <Section id="tpl" scope="pw-donations" title="Receipt letter">
            <div className="row form-row">
              <Field label="Font"><select value={cfg.font} onChange={(e) => set("font", e.target.value)}>{FONTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
              <Field label="Size"><input type="number" min={8} max={14} step={0.5} value={cfg.size} onChange={(e) => set("size", Number(e.target.value))} /></Field>
              <Field label="Date format"><select value={cfg.date_format} onChange={(e) => set("date_format", e.target.value)}>{s.date_formats.map((f: string) => <option key={f}>{f}</option>)}</select></Field>
            </div>
            <PatternInput id="rc-title" label="Title" value={cfg.title} variables={vars} hint={false} maxLength={120} onChange={(v) => set("title", v)} />
            <PatternInput id="rc-salutation" label="Salutation" value={cfg.salutation} variables={vars} hint={false} onChange={(v) => set("salutation", v)} />
            <PatternInput id="rc-body" label="Thank-you text" value={cfg.body} variables={vars} multiline maxLength={2000} onChange={(v) => set("body", v)} />
            <PatternInput id="rc-closing" label="Closing" value={cfg.closing} variables={vars} hint={false} onChange={(v) => set("closing", v)} />
            <div className="row form-row">
              <Field label="Signer's name"><input value={cfg.signer_name} maxLength={120} onChange={(e) => set("signer_name", e.target.value)} /></Field>
              <Field label="Signer's title"><input value={cfg.signer_title} maxLength={120} onChange={(e) => set("signer_title", e.target.value)} /></Field>
            </div>
            <p className="hint">The signer's name and title print under the closing, with room to sign by hand. Put <code>{"{DETAILS}"}</code> where a write-up for each donation should go
              (the Register User writes it when printing; a paragraph of only <code>{"{DETAILS}"}</code> is left out when there is none). Statement when no goods or services were given:
              <i> {s.no_goods_statement}</i> Confirm the receipt wording with your organization's own tax advisor.</p>
            {/* 2.2.0 (#325): the note printed whenever a receipt lists items (empty = the default wording) */}
            <PatternInput id="rc-items-note" label="Note when a receipt lists items" value={cfg.items_note || ""} variables={vars} multiline maxLength={1000}
                          placeholder={s.items_note_default} onChange={(v) => set("items_note", v)} />
            <div className="row">
              <button type="button" className="small" onClick={() => set("items_note", s.items_note_default)}>Default wording</button>
              <span className="hint">Empty prints the default wording shown in grey. Your own wording needs at least {s.items_note_min_words} words (a {"{VARIABLE}"} counts as one).
                Items are always listed by description only; the note can't be left off.</span>
            </div>
          </Section>
          {/* 2.2.0 (#317): the donor's addressee block on receipts and statements, from {DONOR.*} */}
          <Section id="adr" scope="pw-donations" title="Addressee">
            {(cfg.addressee || []).map((line: string, i: number) => (
              <div className="row" key={i}>
                <PatternInput id={`adr-${i}`} label={`Addressee line ${i + 1}`} value={line} variables={s.variables} hint={false} maxLength={200}
                              onChange={(v) => set("addressee", cfg.addressee.map((x: string, j: number) => (j === i ? v : x)))} />
                <button type="button" className="small" aria-label={`Remove addressee line ${i + 1}`} onClick={() => set("addressee", cfg.addressee.filter((_: string, j: number) => j !== i))}>Remove</button>
              </div>
            ))}
            {(cfg.addressee || []).length < 6 ? <button type="button" className="small" onClick={() => set("addressee", [...(cfg.addressee || []), ""])}>+ Add addressee line</button> : null}
            <p className="hint">The donor's block on receipts and year-end statements (and in the lower window of a window envelope). The default is the
              donor's name and mailing address: <code>{"{DONOR.NAME}"}</code>, <code>{"{DONOR.MAILING_ADDRESS}"}</code>.</p>
          </Section>
          {/* 2.2.0 (#256): the year-end giving statement's letter; layout, window and signer are the receipt's */}
          <Section id="stmt" scope="pw-donations" title="Year-end statement letter">
            <p className="hint">The letter printed with each donor's year-end giving statement (Donations page → <i>Year-end statements</i>). Put
              <code>{" {DONATION_TABLE} "}</code> in a paragraph of its own where the table of the year's donations goes (without it the table prints after
              the text). The organization, EIN, donor, year, total and the goods or services statement are always printed.</p>
            <PatternInput id="st-title" label="Title" value={cfg.statement_title} variables={s.statement_variables} hint={false} maxLength={120} onChange={(v) => set("statement_title", v)} />
            <PatternInput id="st-salutation" label="Salutation" value={cfg.statement_salutation} variables={s.statement_variables} hint={false} onChange={(v) => set("statement_salutation", v)} />
            <PatternInput id="st-body" label="Statement text" value={cfg.statement_body} variables={s.statement_variables} multiline maxLength={2000} onChange={(v) => set("statement_body", v)} />
            <PatternInput id="st-closing" label="Statement closing" value={cfg.statement_closing} variables={s.statement_variables} hint={false} onChange={(v) => set("statement_closing", v)} />
            <div className="row">
              <button type="button" onClick={statementTest}>Test print the statement (sample data)</button>
              <button type="button" className="small" onClick={() => setStmtPreview((v) => !v)}>{stmtPreview ? "Hide the statement preview" : "Show the statement preview"}</button>
            </div>
            {stmtPreview ? <LivePreview imageUrl="/api/donations/setup/statement-preview-image" pdfUrl="/api/donations/setup/statement-preview" body={{ config: cfg }}
                                        title="Year-end statement preview" aspect={8.5 / 11} deps={[JSON.stringify(cfg)]} /> : null}
          </Section>
          {/* 2.2.0 (#325): the cover letter's window-envelope options (#177) and fold marks (#247) */}
          <Section id="win" scope="pw-donations" title="Window envelope and fold marks">
            <div className="row form-row">
              <Field label="Address for a window envelope">
                <select value={cfg.window} onChange={(e) => set("window", e.target.value)} aria-label="Address for a window envelope">
                  <option value="NONE">None (a plain envelope can be printed)</option>
                  <option value="LETTER">On the receipt (#10 double-window envelope)</option>
                  <option value="ADDRESS_PAGE">On a separate address page</option>
                </select>
              </Field>
              {cfg.window !== "NONE" ? <label className="check"><input type="checkbox" checked={cfg.window_return} onChange={(e) => set("window_return", e.target.checked)} /> The organization's address in the upper window</label> : null}
              <Field label="Fold marks">
                <select value={cfg.fold_marks} onChange={(e) => set("fold_marks", e.target.value)} aria-label="Fold marks">
                  <option value="NONE">None</option>
                  <option value="FRONT">On the front</option>
                  <option value="BACK">On the back (two-sided)</option>
                </select>
              </Field>
            </div>
            <p className="hint">With a window envelope the donor's address prints where the lower window is and no envelope needs printing (the print screen
              offers <i>Print an envelope anyway</i>). Fold marks are small ticks at the edges to fold the receipt in even thirds; <i>On the back</i> needs a printer
              that prints two-sided.</p>
          </Section>
          <div className="actions left">
            <button className="primary" onClick={save} disabled={!dirty}>Save</button>
            <button onClick={testPrint}>Test print (sample data)</button>
            <button onClick={() => { setCfg({ ...s.defaults, signer_name: cfg.signer_name, signer_title: cfg.signer_title }); setSaved(false); }}>Default wording</button>
            {saved && !dirty ? <span className="hint" role="status">Saved.</span> : dirty ? <span className="hint">Unsaved changes</span> : null}
          </div>
        </div>
        <Section id="pv" scope="pw-donations" title="Preview (sample data)" className="doc-preview letter">
          <LivePreview imageUrl="/api/donations/setup/preview-image" pdfUrl="/api/donations/setup/preview" body={{ config: cfg }}
                       title="Donation receipt preview" aspect={8.5 / 11} deps={[JSON.stringify(cfg)]} />
        </Section>
      </div>
      {lib ? <EnvelopeLibrary feature="DONATIONS" docs={lib.envelopes} onChanged={loadLib} onEdit={(d, f) => { setEditingEnv(d); setEnvFocus(f); }} /> : null}
      {pdf && viewing ? (
        <PdfViewer pdf={pdf} title="Donation receipt test print" onClose={() => setViewing(false)}>
          <p className="hint">Sample data, marked SAMPLE – NOT A RECEIPT. It is not attached anywhere.</p>
        </PdfViewer>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ a deposit's donations (register)
type Line = { allocation_id: number; donor: string; donor_entity_id: number | null; donor_is_organization: boolean; description: string; amount: string; donation: boolean; purpose: string; goods: string; goods_description: string; date: string; amount_cents: number; linked_donation_id?: number | null; suggested?: boolean; fundraiser?: string | null };

const cents = (s: string): number | null => {
  const t = s.replace(/[$,\s]/g, "");
  if (!t) return null;
  if (!/^\d+(\.\d{1,2})?$/.test(t)) return NaN;
  return Math.round(Number(t) * 100);
};

export function DonationReceiptDialog({ txn, onClose, onChanged }: { txn: any; onClose: () => void; onChanged: () => void }) {
  const { can } = useMe();
  const canPrint = can("donation.print");
  const [d, setD] = useState<any>(null);
  const [lines, setLines] = useState<Line[]>([]);
  const [details, setDetails] = useState<Record<number, string>>({});   // {DETAILS} per donor (when the template has it)
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState<string | null>(null);
  const [envFor, setEnvFor] = useState<number | null>(null);   // 2.2.0 (#325): the donor whose envelope can be printed now
  const { run, dialog } = useConfirmable();
  const take = (x: any) => {
    setD(x);
    setLines(x.lines.map((l: any) => ({ allocation_id: l.allocation_id, donor: l.donor, donor_entity_id: l.donor_entity_id, donor_is_organization: !!l.donor_is_organization, description: l.description, amount: l.amount, amount_cents: l.amount_cents,
      // 2.2.0 (#256): a line in a fundraiser's donation bucket starts ticked as a suggestion; Save confirms it
      donation: l.donation || (!!l.suggested && canPrint && x.printable), suggested: !!l.suggested, fundraiser: l.fundraiser || null, purpose: l.purpose || "", goods: l.goods_cents ? (l.goods_cents / 100).toFixed(2) : "", goods_description: l.goods_description || "",
      date: l.date_received || x.date, linked_donation_id: l.linked_donation_id })));
    setDetails(Object.fromEntries(x.donors.map((o: any) => [o.entity_id, o.details || ""])));
  };
  // each load and save is numbered; a reply is shown only if nothing newer was started since, so a reload that comes
  // back late (after a print) can't overwrite lines saved or ticked in the meantime
  const seq = useRef(0);
  const latest = (fn: (x: any) => void) => { const n = ++seq.current; return (x: any) => { if (n === seq.current) fn(x); }; };
  const edits = useRef(0);       // a reload doesn't replace lines ticked or typed while it was on its way
  const load = () => {
    const e0 = edits.current;
    return api.get(`/api/donations/transactions/${txn.id}`).then(latest((x) => {
      if (edits.current === e0) take(x);
      else setD(x);              // receipts and donors refresh; the edited lines stay as typed
    }), setErr);
  };
  useEffect(() => { load(); }, [txn.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const editable = !!d && canPrint && d.printable;
  const original = d ? JSON.stringify([d.lines.map((l: any) => [l.donation, l.purpose || "", l.goods_cents ? (l.goods_cents / 100).toFixed(2) : "", l.goods_description || "", l.date_received || d.date]),
    d.donors.map((o: any) => o.details || "")]) : "";
  const dirty = d && JSON.stringify([lines.map((l) => [l.donation, l.purpose, l.goods, l.goods_description, l.date]),
    d.donors.map((o: any) => details[o.entity_id] || "")]) !== original;
  const setDetail = (id: number, v: string) => { edits.current++; setSaved(false); setDetails({ ...details, [id]: v }); };
  // the donors as on screen: ticking a line shows its donor straight away (no Save needed first)
  const savedDonors = new Map<number, any>((d?.donors || []).map((o: any) => [o.entity_id, o]));
  const groups: { entity_id: number; name: string; cents: number; goods: number; dates: string[]; saved: any }[] = [];
  for (const l of lines) {
    if (!l.donation || !l.donor_entity_id || l.linked_donation_id) continue;   // 2.2.0: Donations page ones print there
    let g = groups.find((x) => x.entity_id === l.donor_entity_id);
    if (!g) { g = { entity_id: l.donor_entity_id, name: l.donor, cents: 0, goods: 0, dates: [], saved: savedDonors.get(l.donor_entity_id) }; groups.push(g); }
    g.cents += l.amount_cents || 0;
    const gc = cents(l.goods);
    if (gc && !Number.isNaN(gc)) g.goods += gc;
    if (l.date && !g.dates.includes(l.date)) g.dates.push(l.date);
  }
  groups.forEach((g) => g.dates.sort());
  const usd = (c: number) => `$${(c / 100).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const printLabel = (g: any) => (!g.saved ? "Print receipt" : dirty ? (g.saved.current_receipt ? "Print" : "Print receipt")
    : g.saved.next_kind === "ORIGINAL" ? "Print receipt" : g.saved.next_kind === "DUPLICATE" ? "Print duplicate" : "Print corrected receipt");
  const canPrintNow = !!(canPrint && d?.printable && !d?.setup_missing.length);
  const setLine = (i: number, patch: Partial<Line>) => { edits.current++; setSaved(false); setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l))); };
  /** the lines and details on screen, as the API takes them (null: a goods value that isn't an amount) */
  const payload = () => {
    const body = lines.map((l) => {
      const g = l.donation ? cents(l.goods) : null;
      return { allocation_id: l.allocation_id, donation: l.donation, purpose: l.donation ? l.purpose || null : null,
        goods_cents: g && !Number.isNaN(g) ? g : g === null ? null : -1, goods_description: l.donation ? l.goods_description || null : null,
        date_received: l.donation && l.date && l.date !== d.date ? l.date : null };
    });
    if (body.some((b) => b.goods_cents === -1)) { setErr(new Error("Enter the goods or services value as an amount, e.g. 25.00.")); return null; }
    const donors = d.details_enabled ? groups.map((g) => ({ entity_id: g.entity_id, details: details[g.entity_id] || "" })) : [];
    return { lines: body, donors };
  };
  const save = async (): Promise<boolean> => {
    setErr(null);
    const p = payload();
    if (!p) return false;
    const apply = latest(take);
    try {
      apply(await api.put(`/api/donations/transactions/${txn.id}/lines`, p)); setSaved(true); onChanged(); return true;
    } catch (x) { setErr(x); return false; }
  };
  /** 2.1.0 (Kyle, 2026-10-23): the receipt as it would print, from what's on screen, watermarked; nothing is saved */
  const preview = async (donor: any) => {
    setErr(null);
    const p = payload();
    if (!p) return;
    try {
      const blob = await api.postBlob(`/api/donations/transactions/${txn.id}/receipts/preview`, { donor_entity_id: donor.entity_id, ...(dirty ? p : {}) });
      setPdf(blob, "receipt-preview.pdf"); setViewing(`Preview – ${donor.name}`);
    } catch (x) { setErr(x); }
  };
  /** Print saves first, so one click saves and prints */
  const print = async (donor: any) => {
    setErr(null);
    if (dirty && !(await save())) return;
    try {
      const blob = await run((c) => api.postBlob(`/api/donations/transactions/${txn.id}/receipts`, { donor_entity_id: donor.entity_id, confirmations: c }));
      if (!blob) return;
      setPdf(blob, "donation-receipt.pdf"); setViewing(`Donation receipt – ${donor.name}`); setEnvFor(donor.entity_id); onChanged(); load();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Donation receipt – deposit #${txn.id}`} onClose={onClose} wide>
      <ErrorBox error={err} />
      {!d ? <Loading /> : (
        <div className="donation-dialog">
          <p className="hint">Deposit of {d.total} received {d.date}. Mark the lines that are donations; each donor gets one receipt for
            their donation lines. The printed receipt is attached to the deposit.</p>
          {d.status !== "ACTIVE" ? <div className="alert warn" role="alert">This deposit is {d.status === "VOID" ? "void" : "deleted"}: its receipts are void and no receipt can be printed.</div>
            : d.closed ? <div className="alert info">This deposit belongs to a Closed Fiscal Year: its donations and receipts can be seen but not changed or printed.</div> : null}
          {d.setup_missing.length && canPrint && d.printable ? <div className="alert warn" data-testid="donation-setup-missing">An Administrator must enter {d.setup_missing.join(" and ")} in Donations Setup before receipts can be printed.</div> : null}
          {d.receipts.length ? (
            <details className="donation-printed">
              <summary>Printed receipts ({d.receipts.length})</summary>
              <table className="table compact" data-testid="donation-receipts">
                <thead><tr><th>Receipt</th><th>Kind</th><th>Donor</th><th className="num">Amount</th><th>Printed</th><th>Status</th></tr></thead>
                <tbody>
                  {d.receipts.map((r: any) => (
                    <tr key={r.id}>
                      <td>{r.number}</td>
                      <td>{KIND_LABEL[r.kind]}{r.replaces && r.kind === "CORRECTED" ? <span className="muted"> (replaces {r.replaces})</span> : null}</td>
                      <td>{r.donor}</td>
                      <td className="num">{r.amount}</td>
                      <td>{r.printed_at.slice(0, 10)}{r.printed_by ? ` · ${r.printed_by}` : ""}</td>
                      <td>{r.void ? <span className="badge red">Void</span> : r.superseded ? <span className="badge grey">Replaced</span> : <span className="badge green">In force</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="hint">The printed copies are in the deposit's attachments.</p>
            </details>
          ) : null}
          <div className="table-scroll">
          <table className="table compact donation-lines">
            <thead><tr><th>Donation</th><th>Donor</th><th>Description</th><th className="num">Amount</th><th>Date received</th><th>Purpose</th><th>Goods or services given (value, description)</th></tr></thead>
            <tbody>
              {lines.map((l, i) => (
                l.linked_donation_id ? (
                <tr key={l.allocation_id}>
                  <td><input type="checkbox" aria-label={`Donation: ${l.donor || "no donor"} ${l.amount}`} checked disabled /></td>
                  <td>{l.donor}</td><td>{l.description}</td><td className="num">{l.amount}</td>
                  <td colSpan={3}>Linked to <Link to="/donations">donation #{l.linked_donation_id}</Link> (Donations page): its receipt is printed and changed there.</td>
                </tr>
                ) : (
                <tr key={l.allocation_id}>
                  <td><input type="checkbox" aria-label={`Donation: ${l.donor || "no donor"} ${l.amount}`} checked={l.donation} disabled={!editable || ((!l.donor_entity_id || l.donor_is_organization) && !l.donation)}
                             title={l.donor_is_organization ? "Your own organization can't be the donor: record the donor as the line's entity" : undefined}
                             onChange={(e) => setLine(i, { donation: e.target.checked })} /></td>
                  <td>{l.donor || <span className="muted">No entity</span>}</td>
                  <td>{l.description}{l.suggested ? <span className="badge grey" data-testid="donation-suggested" title={`In a donation bucket of the fundraiser ${l.fundraiser}: ticked as a suggestion, saved only when you Save`}> Suggested ({l.fundraiser})</span> : null}</td>
                  <td className="num">{l.amount}</td>
                  <td>{l.donation ? <input type="date" aria-label={`Date received: ${l.donor} ${l.amount}`} value={l.date} max={d.date} disabled={!editable}
                                           title="When the donation was received, if before the deposit" onChange={(e) => setLine(i, { date: e.target.value || d.date })} /> : null}</td>
                  <td>{l.donation ? <input aria-label="Purpose" maxLength={200} value={l.purpose} disabled={!editable} placeholder="Optional" onChange={(e) => setLine(i, { purpose: e.target.value })} /> : null}</td>
                  <td>{l.donation ? (
                    <span className="row">
                      <input aria-label="Goods or services value" className="num narrow" inputMode="decimal" value={l.goods} disabled={!editable} placeholder="None" onChange={(e) => setLine(i, { goods: e.target.value })} />
                      {l.goods ? <input aria-label="Goods or services description" maxLength={200} value={l.goods_description} disabled={!editable} placeholder="e.g. Dinner for two" onChange={(e) => setLine(i, { goods_description: e.target.value })} /> : null}
                    </span>) : null}</td>
                </tr>
                )
              ))}
            </tbody>
          </table>
          </div>
          {groups.length ? (
            <section aria-labelledby="donors-h">
              <h3 id="donors-h">Receipts by donor</h3>
              <div data-testid="donation-donors" className="donation-donors">
                {groups.map((g) => (
                  <div key={g.entity_id} className="donation-donor" role="group" aria-label={`Donor ${g.name}`}>
                    <table className="table compact"><tbody>
                      <tr>
                        <td><b>{g.name}</b>{g.saved && !g.saved.has_address ? <span className="muted"> (no address)</span> : null}</td>
                        <td className="num">{usd(g.cents)}</td>
                        <td>Received {g.dates.join(", ")}</td>
                        <td>Goods or services: {g.goods ? usd(g.goods) : "None"}</td>
                        <td>{g.saved?.current_receipt || <span className="muted">Not printed</span>}</td>
                      </tr>
                    </tbody></table>
                    {d.details_enabled ? (editable ? (
                      <PatternInput id={`details-${g.entity_id}`} label={`Details for ${g.name} (optional)`} value={details[g.entity_id] || ""}
                                    variables={d.variables} multiline maxLength={2000} hint={false} onChange={(v) => setDetail(g.entity_id, v)} />
                    ) : g.saved?.details ? <p className="pre"><span className="muted">Details: </span>{g.saved.details}</p> : null) : null}
                    {groups.length > 1 && canPrintNow ? (
                      <div className="actions left">
                        <button onClick={() => preview(g)}>Preview</button>
                        <button onClick={() => print(g)}>{printLabel(g)}</button>
                      </div>
                    ) : null}
                    {envFor === g.entity_id && g.saved?.donation_id ? <ReceiptEnvelopePanel donationId={g.saved.donation_id} onChanged={onChanged} /> : null}
                  </div>
                ))}
              </div>
              {d.details_enabled && editable ? <p className="hint"><b>Details</b> print where the receipt letter has <code>{"{DETAILS}"}</code>, for example how
                the gift will be used; type <code>{"{"}</code> for variables such as <code>{"{AMOUNT}"}</code>. Left empty, that paragraph is left out.</p> : null}
            </section>
          ) : <p className="muted">No line is marked as a donation{canPrint && editable ? " yet" : ""}.</p>}
          <div className="actions donation-actions">
            {editable ? <button className={groups.length === 1 ? "" : "primary"} onClick={() => { void save(); }} disabled={!dirty}>Save</button> : null}
            {groups.length === 1 && canPrintNow ? <>
              <button onClick={() => preview(groups[0])}>Preview</button>
              <button className="primary" onClick={() => print(groups[0])}>{printLabel(groups[0])}</button>
            </> : null}
            {saved && !dirty ? <span className="hint" role="status">Saved.</span> : dirty && editable ? <span className="hint">Unsaved changes{canPrintNow && groups.length ? " (Print saves them first)" : ""}</span> : null}
            <span className="spacer" />
            <button onClick={onClose}>Close</button>
          </div>
        </div>
      )}
      {pdf && viewing ? (
        <PdfViewer pdf={pdf} title={viewing} onClose={() => setViewing(null)}>
          {viewing.startsWith("Preview") ? <p className="hint" data-testid="preview-note"><b>Preview only:</b> marked PREVIEW – NOT A RECEIPT, with what's on
            the screen. Nothing is saved, attached or numbered. Close it to make changes, then Print.</p> : null}
        </PdfViewer>
      ) : null}
      {dialog}
    </Modal>
  );
}
