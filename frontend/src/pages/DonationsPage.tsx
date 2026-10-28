/** 2.2.0 (#325): the Donations page (navigation, when the module is on). Register Users create donations - money and
 * items, with or without a date - print receipts, and Create transaction once the money is deposited; the other
 * financial roles and Auditors see it read-only.
 * "Received" decides (Kyle, 2026-10-23): a money line once it is linked to a deposit, an item once ticked Received.
 * Until then the date is an estimate and the receipt prints "Date received" blank. */
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { api, money } from "../api";
import { useMe } from "../App";
import { EntityPicker, ErrorBox, Field, GuardedForm, Loading, Modal, useConfirmable } from "../components";
import { Link } from "../router";
import { PdfViewer, usePdf } from "./checkShared";
import { ReceiptEnvelopePanel } from "./Envelopes";
import { DonorReportTab, StatementsTab } from "./DonationStatements";
import { TxnForm } from "./Register";

const PUB_1771 = "https://www.irs.gov/pub/irs-pdf/p1771.pdf";
const KIND_LABEL: Record<string, string> = { ORIGINAL: "Original", DUPLICATE: "Duplicate", CORRECTED: "Corrected" };
const SHOW: [string, string][] = [["all", "All"], ["awaiting", "Awaiting deposit"], ["value_missing", "Value not entered"], ["cancelled", "Cancelled"]];

const toCents = (v: string) => (v.trim() === "" ? null : Math.round(Number(v.replace(/[$,\s]/g, "")) * 100));
const fromCents = (c: number | null | undefined) => (c == null ? "" : (c / 100).toFixed(2));

type Line = {
  id?: number; kind: "MONEY" | "ITEM"; amount: string; description: string; purpose: string; goods: string; goods_description: string;
  date_received: string; item_received: boolean; item_no_value: boolean; item_no_value_reason: string;
  linked?: boolean; received?: boolean; locked?: boolean; deposit_id?: number | null; date_is_estimate?: boolean;
};
const blank = (): Line => ({ kind: "MONEY", amount: "", description: "", purpose: "", goods: "", goods_description: "", date_received: "",
  item_received: false, item_no_value: false, item_no_value_reason: "" });

export default function DonationsPage() {
  const { can } = useMe();
  const [show, setShow] = useState("all");
  const [q, setQ] = useState("");
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<number | "new" | null>(null);
  const [creating, setCreating] = useState(false);
  const [tab, setTab] = useState<"donations" | "statements" | "report">("donations");   // 2.2.0 (#256)
  const load = () => api.get(`/api/donations?show=${show}${q.trim() ? `&q=${encodeURIComponent(q.trim())}` : ""}`).then(setData, setErr);
  useEffect(() => { load(); }, [show]); // eslint-disable-line react-hooks/exhaustive-deps
  const printer = can("donation.print");
  return (
    <div className="page donations-page">
      <div className="page-head">
        <h1>Donations</h1>
        {printer ? (
          <div className="row">
            <button className="primary" onClick={() => setOpen("new")}>New donation</button>
            {can("transaction.manage") ? <button onClick={() => setCreating(true)}>Create transaction</button> : null}
          </div>
        ) : null}
      </div>
      <div role="tablist" className="row" aria-label="Donations views">
        <button role="tab" aria-selected={tab === "donations"} className={tab === "donations" ? "primary" : ""} onClick={() => setTab("donations")}>Donations</button>
        <button role="tab" aria-selected={tab === "statements"} className={tab === "statements" ? "primary" : ""} onClick={() => setTab("statements")}>Year-end statements</button>
        <button role="tab" aria-selected={tab === "report"} className={tab === "report" ? "primary" : ""} onClick={() => setTab("report")}>Donor report</button>
      </div>
      {tab === "statements" ? <StatementsTab /> : tab === "report" ? <DonorReportTab /> : <>
      <p className="hint">A donation is what a receipt is printed for: one donor, money and items. Record it here when the receipt is needed before the
        money arrives, or for items; when the money is deposited, <b>Create transaction</b> records the deposit and links it. Deposits already in the
        register can still be marked from the register (<b>Donation receipt…</b>).</p>
      <ErrorBox error={err} />
      <div className="row filters">
        <div role="radiogroup" aria-label="Show" className="row">
          {SHOW.map(([k, l]) => (
            <label key={k} className="check"><input type="radio" name="don-show" checked={show === k} onChange={() => setShow(k)} />
              {" "}{l}{data && k !== "all" && data.counts[k] ? ` (${data.counts[k]})` : ""}</label>
          ))}
        </div>
        <form className="row" onSubmit={(e) => { e.preventDefault(); load(); }}>
          <input type="search" aria-label="Search donations" placeholder="Donor, donation # or receipt number" value={q} onChange={(e) => setQ(e.target.value)} />
          <button type="submit" className="small">Search</button>
        </form>
      </div>
      {!data ? <Loading /> : !data.items.length ? <p className="muted">No donations{show !== "all" ? " in this view" : " yet"}.</p> : (
        <table className="table" aria-label="Donations">
          <thead><tr><th>#</th><th>Donor</th><th className="num">Money</th><th>Items</th><th>Status</th><th>Receipt</th><th>Deposit</th></tr></thead>
          <tbody>
            {data.items.map((d: any) => (
              <tr key={d.id} className="clickable" onClick={() => setOpen(d.id)}>
                <td><button type="button" className="link" onClick={(e) => { e.stopPropagation(); setOpen(d.id); }} aria-label={`Open donation ${d.id}`}>{d.id}</button></td>
                <td>{d.donor.name}{d.origin === "DEPOSIT" ? <span className="muted"> · marked on a deposit</span> : null}</td>
                <td className="num">{d.money_cents ? d.money : ""}</td>
                <td>{d.items ? `${d.items} item${d.items > 1 ? "s" : ""}` : ""}{d.value_missing ? <span className="badge warn" title="An item has no estimated value and no reason"> Value not entered</span> : null}</td>
                <td><span className={`badge${d.status === "CANCELLED" ? " grey" : d.status === "AWAITING_DEPOSIT" ? " warn" : ""}`}>{d.status_text}</span></td>
                <td>{d.current_receipt || <span className="muted">—</span>}</td>
                <td>{d.deposits.map((t: any) => `#${t.id}${t.status !== "ACTIVE" ? ` (${t.status.toLowerCase()})` : ""}`).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      </>}
      {open != null ? <DonationEditor id={open === "new" ? null : open} canPrint={printer} onClose={() => setOpen(null)} onChanged={load} onOpen={(id) => setOpen(id)} /> : null}
      {creating ? <CreateTransaction onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load(); }} /> : null}
    </div>
  );
}

// ------------------------------------------------------------------ one donation
function DonationEditor({ id, canPrint, onClose, onChanged, onOpen }: { id: number | null; canPrint: boolean; onClose: () => void; onChanged: () => void; onOpen: (id: number) => void }) {
  const [d, setD] = useState<any>(null);
  const [entities, setEntities] = useState<any[]>([]);
  const [donor, setDonor] = useState("");
  const [details, setDetails] = useState("");
  const [lines, setLines] = useState<Line[]>([blank()]);
  const [err, setErr] = useState<unknown>(null);
  const [saved, setSaved] = useState(false);
  const [cancelAsk, setCancelAsk] = useState<string | null>(null);
  const [pdf, setPdf] = usePdf();
  const [viewing, setViewing] = useState(false);
  const [printed, setPrinted] = useState(false);     // 2.2.0 (#325): after a receipt, its envelope can be printed
  const { run, dialog } = useConfirmable();
  const take = (x: any) => {
    setD(x); setDonor(String(x.donor.id)); setDetails(x.details || "");
    setLines(x.lines.map((l: any) => ({
      id: l.id, kind: l.kind, amount: fromCents(l.amount_cents), description: l.description || "", purpose: l.purpose || "",
      goods: fromCents(l.goods_cents), goods_description: l.goods_description || "", date_received: l.date_received || "",
      item_received: !!l.item_received, item_no_value: !!l.item_no_value, item_no_value_reason: l.item_no_value_reason || "",
      linked: l.linked, received: l.received, locked: l.locked, deposit_id: l.deposit_id, date_is_estimate: l.date_is_estimate,
    })));
  };
  useEffect(() => {
    if (id != null) api.get(`/api/donations/${id}`).then(take, setErr);
    if (canPrint) api.get("/api/entities?status=active").then((es) => setEntities(es.filter((e: any) => !e.is_system && !e.is_organization)));
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const editable = canPrint && (id == null || (d && d.editable));
  const set = (i: number, patch: Partial<Line>) => { setSaved(false); setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l))); };
  const body = () => ({
    donor_entity_id: Number(donor), details,
    lines: lines.map((l) => ({
      ...(l.id ? { id: l.id } : {}), kind: l.kind, amount_cents: toCents(l.amount), description: l.description || null, purpose: l.purpose || null,
      goods_cents: toCents(l.goods), goods_description: l.goods_description || null, date_received: l.date_received || null,
      item_received: l.kind === "ITEM" && l.item_received, item_no_value: l.kind === "ITEM" && l.item_no_value,
      item_no_value_reason: l.kind === "ITEM" && l.item_no_value ? l.item_no_value_reason || null : null,
    })),
  });
  const save = async (e?: FormEvent) => {
    e?.preventDefault();
    setErr(null);
    try {
      const x = id == null ? await api.post("/api/donations", body()) : await api.put(`/api/donations/${id}`, body());
      take(x); setSaved(true); onChanged();
      if (id == null) onOpen(x.id);
      return x;
    } catch (x) { setErr(x); return null; }
  };
  const preview = async () => {
    setErr(null);
    try { setPdf(await api.postBlob(`/api/donations/${id}/receipts/preview`, {}), "receipt-preview.pdf"); setViewing(true); } catch (x) { setErr(x); }
  };
  const print = async () => {
    setErr(null);
    try {
      const r = await run((confirmations) => api.postBlob(`/api/donations/${id}/receipts`, { confirmations }));
      if (!r) return;
      setPdf(r, "receipt.pdf"); setViewing(true); setPrinted(true);
      api.get(`/api/donations/${id}`).then(take); onChanged();
    } catch (x) { setErr(x); }
  };
  const cancel = async () => {
    setErr(null);
    try { take(await api.post(`/api/donations/${id}/cancel`, { reason: cancelAsk || "" })); setCancelAsk(null); onChanged(); } catch (x) { setErr(x); }
  };
  if (id != null && !d) return <Modal title="Donation" onClose={onClose}>{err ? <ErrorBox error={err} /> : <Loading />}</Modal>;
  const title = id == null ? "New donation" : `Donation #${id} – ${d.donor.name}`;
  return (
    <Modal title={title} onClose={onClose} wide>
      <GuardedForm onSubmit={save}>
        <ErrorBox error={err} />
        {d ? <p className="muted">{d.status_text}{d.origin === "DEPOSIT" ? " · marked on a deposit in the register (change it there)" : ""}{d.cancel_reason ? ` · ${d.cancel_reason}` : ""}</p> : null}
        <fieldset disabled={!editable} className="plain">
          {editable ? (
            <EntityPicker label="Donor (entity)" entities={entities} value={donor} onChange={(v) => { setDonor(v); setSaved(false); }}
              extraOption={d ? { id: String(d.donor.id), label: d.donor.name } : null} />
          ) : <p><b>Donor:</b> {d.donor.name}</p>}
          {lines.map((l, i) => (
            <fieldset key={l.id ?? `n${i}`} className="lines donation-line">
              <legend>Line {i + 1}{l.linked ? ` · deposit #${l.deposit_id}` : ""}{l.locked ? " · Closed Fiscal Year" : ""}</legend>
              <div className="row form-row">
                <Field label={l.kind === "ITEM" ? "Estimated value for our records (not printed)" : "Amount"}>
                  <input inputMode="decimal" aria-label={`Line ${i + 1} ${l.kind === "ITEM" ? "estimated value" : "amount"}`} value={l.amount}
                         disabled={!!l.linked} onChange={(e) => set(i, { amount: e.target.value })} />
                </Field>
                <Field label={l.kind === "ITEM" ? "Item description (printed)" : "Description"}>
                  <input maxLength={200} aria-label={`Line ${i + 1} description`} value={l.description} onChange={(e) => set(i, { description: e.target.value })} />
                </Field>
                <Field label={l.received ? "Received date" : "Est. received date (optional)"}>
                  <input type="date" aria-label={`Line ${i + 1} date`} value={l.date_received} onChange={(e) => set(i, { date_received: e.target.value })} />
                </Field>
              </div>
              <label className="check"><input type="checkbox" checked={l.kind === "ITEM"} disabled={!!l.linked || !!l.received}
                onChange={(e) => set(i, { kind: e.target.checked ? "ITEM" : "MONEY" })} /> Item (not money)</label>
              {l.kind === "ITEM" ? (
                <>
                  <p className="hint">The receipt describes the item; it never prints a value. Under IRS Publication 1771 the donor determines the value of donated
                    property (<a href={PUB_1771} target="_blank" rel="noopener noreferrer">Pub. 1771</a>). The estimate is for the organization's own records.</p>
                  <div className="row form-row">
                    <label className="check"><input type="checkbox" checked={l.item_received} onChange={(e) => set(i, { item_received: e.target.checked })} /> Received</label>
                    <label className="check"><input type="checkbox" checked={l.item_no_value} onChange={(e) => set(i, { item_no_value: e.target.checked, amount: e.target.checked ? "" : l.amount })} /> No value will be provided</label>
                    {l.item_no_value ? <Field label="Reason"><input maxLength={500} aria-label={`Line ${i + 1} no value reason`} value={l.item_no_value_reason} onChange={(e) => set(i, { item_no_value_reason: e.target.value })} /></Field> : null}
                  </div>
                  {!l.amount && !l.item_no_value ? <p className="hint warn">Value not entered: enter an estimate, or tick No value will be provided.</p> : null}
                </>
              ) : null}
              <div className="row form-row">
                <Field label="Purpose (optional)"><input maxLength={200} value={l.purpose} onChange={(e) => set(i, { purpose: e.target.value })} /></Field>
                <Field label="Goods or services given in exchange ($, optional)"><input inputMode="decimal" aria-label={`Line ${i + 1} goods value`} value={l.goods} onChange={(e) => set(i, { goods: e.target.value })} /></Field>
                {toCents(l.goods) ? <Field label="Describe them"><input maxLength={200} value={l.goods_description} onChange={(e) => set(i, { goods_description: e.target.value })} /></Field> : null}
              </div>
              {editable && lines.length > 1 && !l.linked ? <button type="button" className="small" onClick={() => setLines(lines.filter((_, j) => j !== i))}>Remove line</button> : null}
            </fieldset>
          ))}
          {editable ? <button type="button" className="small" onClick={() => setLines([...lines, blank()])}>+ Add line</button> : null}
          <Field label="Details for the receipt (optional)" hint="Printed where the receipt template has {DETAILS}.">
            <textarea maxLength={2000} value={details} onChange={(e) => { setDetails(e.target.value); setSaved(false); }} />
          </Field>
        </fieldset>
        <div className="actions left">
          {editable ? <button type="submit" className="primary">{id == null ? "Save donation" : "Save changes"}</button> : null}
          {saved ? <span className="hint" role="status">Saved.</span> : null}
          {d && canPrint && d.printable ? <>
            <button type="button" onClick={preview}>Preview receipt</button>
            <button type="button" onClick={print}>Print receipt{d.next_kind !== "ORIGINAL" ? ` (${KIND_LABEL[d.next_kind].toLowerCase()})` : ""}</button>
          </> : null}
          {d && canPrint && d.cancellable ? <button type="button" className="danger" onClick={() => setCancelAsk("")}>Cancel donation…</button> : null}
        </div>
      </GuardedForm>
      {printed && d && id != null && canPrint && d.printable ? <ReceiptEnvelopePanel donationId={id} onChanged={() => { api.get(`/api/donations/${id}`).then(take); onChanged(); }} /> : null}
      {d ? <ReceiptList d={d} /> : null}
      {cancelAsk != null ? (
        <Modal title="Cancel donation" onClose={() => setCancelAsk(null)}>
          <p>A donation that never happens is cancelled with a reason. Its receipts become void; nothing is deleted.</p>
          <Field label="Reason (required)"><input autoFocus maxLength={500} value={cancelAsk} onChange={(e) => setCancelAsk(e.target.value)} /></Field>
          <div className="actions"><button onClick={() => setCancelAsk(null)}>Back</button><button className="danger" disabled={!cancelAsk.trim()} onClick={cancel}>Cancel donation</button></div>
        </Modal>
      ) : null}
      {viewing && pdf ? <PdfViewer pdf={pdf} title="Donation receipt" onClose={() => setViewing(false)} /> : null}
      {dialog}
    </Modal>
  );
}

function ReceiptList({ d }: { d: any }) {
  if (!d.receipts.length) return <p className="muted">No receipt printed yet.</p>;
  return (
    <section aria-label="Receipts">
      <h3>Receipts</h3>
      <ul className="plain">
        {d.receipts.map((r: any) => (
          <li key={r.id}>
            <b>{r.number}</b> · {KIND_LABEL[r.kind]}{r.replaces ? ` (replaces ${r.replaces})` : ""} · {r.amount} · printed {new Date(r.printed_at).toLocaleDateString()} by {r.printed_by}
            {r.void ? <span className="badge grey"> Void</span> : r.superseded ? <span className="badge grey"> Superseded</span> : null}
            {!r.date_received ? <span className="muted"> · date received left blank</span> : null}
          </li>
        ))}
      </ul>
      {d.documents.length ? <p className="hint">Printed copies kept with this donation: {d.documents.map((x: any, i: number) => (
        <span key={x.id}>{i ? ", " : ""}<a href={`/api/donations/${d.id}/documents/${x.id}`} target="_blank" rel="noopener">{x.name}</a></span>))}.
        {d.deposits.length ? " Copies are also on the deposit." : ""}</p> : null}
      {d.deposits.length ? <p className="hint">Deposits: {d.deposits.map((t: any) => `#${t.id} (${t.date})`).join(", ")} – see the <Link to="/register">register</Link>.</p> : null}
    </section>
  );
}

// ------------------------------------------------------------------ Create transaction
function CreateTransaction({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [lines, setLines] = useState<any[] | null>(null);
  const [picked, setPicked] = useState<number[]>([]);
  const [accounts, setAccounts] = useState<any[]>([]);
  const [acct, setAcct] = useState("");
  const [fys, setFys] = useState<any[]>([]);
  const [err, setErr] = useState<unknown>(null);
  const [form, setForm] = useState(false);
  useEffect(() => {
    api.get("/api/donations/awaiting-lines").then((r) => setLines(r.items), setErr);
    api.get("/api/bank-accounts").then((a) => {
      const reg = a.filter((x: any) => x.register_enabled && x.status === "ACTIVE");
      setAccounts(reg);
      const prim = reg.find((x: any) => x.is_primary) || reg[0];
      if (prim) setAcct(String(prim.id));
    });
    api.get("/api/fiscal-years").then(setFys);
  }, []);
  const chosen = useMemo(() => (lines || []).filter((l) => picked.includes(l.id)), [lines, picked]);
  const account = accounts.find((a) => String(a.id) === acct);
  if (form && account) {
    return <TxnForm account={account} txn={null} fys={fys} fromDonations={{ lines: chosen }} onClose={() => setForm(false)} onSaved={() => onSaved()} />;
  }
  const total = chosen.reduce((s, l) => s + l.amount_cents, 0);
  return (
    <Modal title="Create transaction from donations" onClose={onClose} wide>
      <ErrorBox error={err} />
      <p className="hint">Tick the donations that were deposited. Only money not yet linked to a deposit is listed. Several donations make one split deposit,
        a line per donation; you choose the bank account, date and budgets next. Saving links them and attaches their printed receipts to the deposit.</p>
      {!lines ? <Loading /> : !lines.length ? <p className="muted">No donation is awaiting a deposit.</p> : (
        <table className="table" aria-label="Awaiting deposit">
          <thead><tr><th></th><th>Donation</th><th>Donor</th><th>Description</th><th>Est. received</th><th className="num">Amount</th></tr></thead>
          <tbody>
            {lines.map((l) => (
              <tr key={l.id}>
                <td><input type="checkbox" aria-label={`Include donation ${l.donation_id} ${l.donor} ${l.amount}`} checked={picked.includes(l.id)}
                           onChange={(e) => setPicked(e.target.checked ? [...picked, l.id] : picked.filter((x) => x !== l.id))} /></td>
                <td>#{l.donation_id}</td><td>{l.donor}</td><td>{l.description}</td><td>{l.date_received || ""}</td><td className="num">{l.amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="row form-row">
        <Field label="Bank account"><select value={acct} onChange={(e) => setAcct(e.target.value)}>{accounts.map((a) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></Field>
        <p className="hint">Total: <b>{money(fromCents(total))}</b></p>
      </div>
      <div className="actions"><button onClick={onClose}>Cancel</button><button className="primary" disabled={!chosen.length || !account} onClick={() => setForm(true)}>Continue</button></div>
    </Modal>
  );
}
