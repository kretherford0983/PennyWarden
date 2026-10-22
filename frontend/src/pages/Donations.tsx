/** 2.1.0 (#312): the Donations module, part 1 - donation receipt letters.
 * - DonationSetup (Administrators): the receipt template and signer (the EIN and address: System/About, #314), a live
 *   preview and a test print with sample data only.
 * - DonationReceiptDialog (from a deposit in the register): Register Users mark lines as donations and print one receipt
 *   per donor; Budget Managers, Budget Users and Auditors see the donation lines and receipts. */
import { useEffect, useState } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading, Modal, useConfirmable } from "../components";
import { useMe } from "../App";
import { Link } from "../router";
import { LivePreview, PatternInput, PdfViewer, Section, usePdf } from "./checkShared";

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
  const load = () => api.get("/api/donations/setup").then((d) => { setS(d); setCfg(d.config); }, setErr);
  useEffect(() => { load(); }, []);
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
            <p className="hint">The signer's name and title print under the closing, with room to sign by hand. Statement when no goods or services were given:
              <i> {s.no_goods_statement}</i> Confirm the receipt wording with your organization's own tax advisor.</p>
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
      {pdf && viewing ? (
        <PdfViewer pdf={pdf} title="Donation receipt test print" onClose={() => setViewing(false)}>
          <p className="hint">Sample data, marked SAMPLE – NOT A RECEIPT. It is not attached anywhere.</p>
        </PdfViewer>
      ) : null}
    </div>
  );
}

// ------------------------------------------------------------------ a deposit's donations (register)
type Line = { allocation_id: number; donor: string; donor_entity_id: number | null; donor_is_organization: boolean; description: string; amount: string; donation: boolean; purpose: string; goods: string; goods_description: string };

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
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState<string | null>(null);
  const { run, dialog } = useConfirmable();
  const take = (x: any) => {
    setD(x);
    setLines(x.lines.map((l: any) => ({ allocation_id: l.allocation_id, donor: l.donor, donor_entity_id: l.donor_entity_id, donor_is_organization: !!l.donor_is_organization, description: l.description, amount: l.amount,
      donation: l.donation, purpose: l.purpose || "", goods: l.goods_cents ? (l.goods_cents / 100).toFixed(2) : "", goods_description: l.goods_description || "" })));
  };
  const load = () => api.get(`/api/donations/transactions/${txn.id}`).then(take, setErr);
  useEffect(() => { load(); }, [txn.id]); // eslint-disable-line react-hooks/exhaustive-deps
  const editable = !!d && canPrint && d.printable;
  const original = d ? JSON.stringify(d.lines.map((l: any) => [l.donation, l.purpose || "", l.goods_cents ? (l.goods_cents / 100).toFixed(2) : "", l.goods_description || ""])) : "";
  const dirty = d && JSON.stringify(lines.map((l) => [l.donation, l.purpose, l.goods, l.goods_description])) !== original;
  const setLine = (i: number, patch: Partial<Line>) => { setSaved(false); setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l))); };
  const save = async () => {
    setErr(null);
    const body = lines.map((l) => {
      const g = l.donation ? cents(l.goods) : null;
      return { allocation_id: l.allocation_id, donation: l.donation, purpose: l.donation ? l.purpose || null : null,
        goods_cents: g && !Number.isNaN(g) ? g : g === null ? null : -1, goods_description: l.donation ? l.goods_description || null : null };
    });
    if (body.some((b) => b.goods_cents === -1)) { setErr(new Error("Enter the goods or services value as an amount, e.g. 25.00.")); return; }
    try { take(await api.put(`/api/donations/transactions/${txn.id}/lines`, { lines: body })); setSaved(true); onChanged(); } catch (x) { setErr(x); }
  };
  const print = async (donor: any) => {
    setErr(null);
    try {
      const blob = await run((c) => api.postBlob(`/api/donations/transactions/${txn.id}/receipts`, { donor_entity_id: donor.entity_id, confirmations: c }));
      if (!blob) return;
      setPdf(blob, "donation-receipt.pdf"); setViewing(donor.name); onChanged(); load();
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
          <table className="table compact">
            <thead><tr><th>Donation</th><th>Donor</th><th>Description</th><th className="num">Amount</th><th>Purpose</th><th>Goods or services given (value, description)</th></tr></thead>
            <tbody>
              {lines.map((l, i) => (
                <tr key={l.allocation_id}>
                  <td><input type="checkbox" aria-label={`Donation: ${l.donor || "no donor"} ${l.amount}`} checked={l.donation} disabled={!editable || ((!l.donor_entity_id || l.donor_is_organization) && !l.donation)}
                             title={l.donor_is_organization ? "Your own organization can't be the donor: record the donor as the line's entity" : undefined}
                             onChange={(e) => setLine(i, { donation: e.target.checked })} /></td>
                  <td>{l.donor || <span className="muted">No entity</span>}</td>
                  <td>{l.description}</td>
                  <td className="num">{l.amount}</td>
                  <td>{l.donation ? <input aria-label="Purpose" maxLength={200} value={l.purpose} disabled={!editable} placeholder="Optional" onChange={(e) => setLine(i, { purpose: e.target.value })} /> : null}</td>
                  <td>{l.donation ? (
                    <span className="row">
                      <input aria-label="Goods or services value" className="num narrow" inputMode="decimal" value={l.goods} disabled={!editable} placeholder="None" onChange={(e) => setLine(i, { goods: e.target.value })} />
                      {l.goods ? <input aria-label="Goods or services description" maxLength={200} value={l.goods_description} disabled={!editable} placeholder="e.g. Dinner for two" onChange={(e) => setLine(i, { goods_description: e.target.value })} /> : null}
                    </span>) : null}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {editable ? (
            <div className="actions left">
              <button className="primary" onClick={save} disabled={!dirty}>Save donation lines</button>
              {saved && !dirty ? <span className="hint" role="status">Saved.</span> : null}
            </div>
          ) : null}
          {d.donors.length ? (
            <>
              <h3>Receipts by donor</h3>
              <table className="table compact" data-testid="donation-donors">
                <thead><tr><th>Donor</th><th className="num">Donation</th><th>Goods or services</th><th>Receipt</th><th></th></tr></thead>
                <tbody>
                  {d.donors.map((x: any) => (
                    <tr key={x.entity_id}>
                      <td>{x.name}{!x.has_address ? <span className="muted"> (no address)</span> : null}</td>
                      <td className="num">{x.amount}</td>
                      <td>{x.goods_cents ? `$${(x.goods_cents / 100).toFixed(2)}` : "None"}</td>
                      <td>{x.current_receipt || <span className="muted">Not printed</span>}</td>
                      <td>{canPrint && d.printable && !d.setup_missing.length ? (
                        <button disabled={!!dirty} onClick={() => print(x)}>
                          {x.next_kind === "ORIGINAL" ? "Print receipt" : x.next_kind === "DUPLICATE" ? "Print duplicate" : "Print corrected receipt"}
                        </button>) : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {dirty && canPrint ? <p className="hint">Save the donation lines before printing.</p> : null}
            </>
          ) : <p className="muted">No line is marked as a donation{canPrint && editable ? " yet" : ""}.</p>}
          {d.receipts.length ? (
            <>
              <h3>Printed receipts</h3>
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
            </>
          ) : null}
          <div className="actions"><button onClick={onClose}>Close</button></div>
        </div>
      )}
      {pdf && viewing ? <PdfViewer pdf={pdf} title={`Donation receipt – ${viewing}`} onClose={() => setViewing(null)} /> : null}
      {dialog}
    </Modal>
  );
}
