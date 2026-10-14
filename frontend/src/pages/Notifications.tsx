// v1.6.3 CR-036: reminders and notifications. Personal reminders are private; organization reminders are shared.
import { useEffect, useState, type FormEvent } from "react";
import { api, todayIso } from "../api";
import { ErrorBox, Field, GuardedForm, Loading, Modal, RowMenu } from "../components";
import { Link } from "../router";
import { useMe } from "../App";

type View = "due" | "upcoming" | "resolved";
export const REMINDERS_CHANGED = "fm:reminders-changed"; // the bell in the top bar listens for this

export function ReminderItem({ r, onResolve, onReopen, onEdit, onDelete }: {
  r: any; onResolve?: (r: any) => void; onReopen?: (r: any) => void; onEdit?: (r: any) => void; onDelete?: (r: any) => void;
}) {
  return (
    <li className={`reminder reminder-${r.state.toLowerCase()}`} data-testid="reminder">
      <div className="reminder-main">
        <div className="reminder-title">
          <b>{r.title}</b>{" "}
          <span className={`pill ${r.scope === "ORGANIZATION" ? "pill-approved" : ""}`}>{r.scope === "ORGANIZATION" ? "Organization" : "Personal"}</span>
          {r.overdue_days > 0 ? <span className="badge red">{r.overdue_days} day{r.overdue_days === 1 ? "" : "s"} overdue</span> : null}
        </div>
        <div className="muted">
          Due {r.due_date}{r.state === "UPCOMING" && r.show_date !== r.due_date ? ` · shown from ${r.show_date}` : ""}
          {r.scope === "ORGANIZATION" && r.owner ? ` · set by ${r.owner}` : ""}
          {r.link ? <> · <Link to={r.link.url}>{r.link.label}</Link></> : null}
          {r.repeat_label ? <> · <span data-testid="reminder-repeat">{r.repeat_label}</span></> : null}
        </div>
        {r.details ? <div className="pre-wrap">{r.details}</div> : null}
        {r.state === "RESOLVED" ? <div className="muted">Resolved {String(r.resolved_at).slice(0, 10)} by {r.resolved_by || "?"}{r.resolution_note ? ` — ${r.resolution_note}` : ""}</div> : null}
      </div>
      <div className="row-actions">
        {/* #215: Edit stays visible, the other actions are in the ⋯ menu */}
        {r.can_edit && onEdit ? <button className="small" aria-label={`Edit ${r.title}`} onClick={() => onEdit(r)}>Edit</button> : null}
        <RowMenu name={r.title} actions={[
          r.can_resolve && onResolve && { label: "Resolve…", onClick: () => onResolve(r) },
          r.can_reopen && onReopen && { label: "Reopen", onClick: () => onReopen(r) },
          r.can_edit && onDelete && { label: "Delete", onClick: () => onDelete(r), danger: true },
        ]} />
      </div>
    </li>
  );
}

export default function Notifications() {
  const { can } = useMe();
  const [view, setView] = useState<View>("due");
  const [items, setItems] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [edit, setEdit] = useState<any>(null);
  const [resolving, setResolving] = useState<any>(null);
  const canCreate = can("reminder.personal") || can("reminder.org_manage");
  const load = () => api.get(`/api/reminders?view=${view}`).then(setItems, setErr);
  useEffect(() => { setItems(null); load(); }, [view]); // eslint-disable-line react-hooks/exhaustive-deps
  const changed = () => { load(); window.dispatchEvent(new Event(REMINDERS_CHANGED)); };
  const act = async (fn: () => Promise<any>) => {
    setErr(null);
    try { await fn(); changed(); } catch (x) { setErr(x); }
  };
  const empty: Record<View, string> = { due: "Nothing needs your attention.", upcoming: "No upcoming reminders.", resolved: "No resolved reminders." };
  return (
    <div>
      <div className="page-head">
        <h1>Notifications</h1>
        {canCreate ? <button className="primary" onClick={() => setEdit({})}>New reminder</button> : null}
      </div>
      <div role="tablist" className="row">
        {(["due", "upcoming", "resolved"] as View[]).map((v) => (
          <button key={v} role="tab" aria-selected={view === v} className={view === v ? "primary" : ""} onClick={() => setView(v)}>
            {v === "due" ? "Due" : v === "upcoming" ? "Upcoming" : "Resolved"}
          </button>
        ))}
      </div>
      <ErrorBox error={err} />
      {!items ? <Loading /> : !items.length ? <p className="muted">{empty[view]}</p> : (
        <ul className="reminders">
          {items.map((r) => (
            <ReminderItem key={r.id} r={r} onResolve={setResolving} onEdit={setEdit}
              onReopen={(x) => act(() => api.post(`/api/reminders/${x.id}/reopen`))}
              onDelete={(x) => window.confirm(`Delete the reminder “${x.title}”?`) && act(() => api.delete(`/api/reminders/${x.id}`))} />
          ))}
        </ul>
      )}
      {edit ? <ReminderForm current={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); changed(); }} /> : null}
      {resolving ? <ResolveDialog r={resolving} onClose={() => setResolving(null)} onDone={() => { setResolving(null); changed(); }} /> : null}
    </div>
  );
}

export function ResolveDialog({ r, onClose, onDone }: { r: any; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [stop, setStop] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post(`/api/reminders/${r.id}/resolve`, { note: note || null, stop_repeating: stop }); onDone(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Resolve reminder" onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <p><b>{r.title}</b> — due {r.due_date}</p>
        <ErrorBox error={err} />
        <Field label="Note (optional)" hint="Kept with the reminder and in the audit log."><input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        {r.repeat_label ? (
          r.next_due ? (
            <>
              <p className="hint">{r.repeat_label}. {stop ? "No further reminder will be created." : `The next one will be due ${r.next_due}.`}</p>
              <label className="check"><input type="checkbox" checked={stop} onChange={(e) => setStop(e.target.checked)} /> Stop repeating after this one</label>
            </>
          ) : <p className="hint">{r.repeat_label}. This is the last one.</p>
        ) : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Mark as resolved</button></div>
      </GuardedForm>
    </Modal>
  );
}

function ReminderForm({ current, onClose, onSaved }: { current: any; onClose: () => void; onSaved: () => void }) {
  const { can } = useMe();
  const org = can("reminder.org_manage");
  const personal = can("reminder.personal");
  const [v, setV] = useState({
    scope: current.scope || (personal ? "PERSONAL" : "ORGANIZATION"), title: current.title || "", details: current.details || "",
    due_date: current.due_date || todayIso(), notify_days_before: String(current.notify_days_before ?? 0),
    link_type: current.link_type || "", link_id: current.link_id ? String(current.link_id) : "",
    repeat: current.repeat_every ? "yes" : "no", repeat_every: String(current.repeat_every ?? 1),
    repeat_unit: current.repeat_unit || "MONTH", repeat_until: current.repeat_until || "",
  });
  const [opts, setOpts] = useState<{ value: string; label: string }[]>([]);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => {
    setOpts([]);
    if (v.link_type === "FISCAL_YEAR") api.get("/api/fiscal-years").then((y) => setOpts(y.map((f: any) => ({ value: String(f.id), label: f.label }))), setErr);
    else if (v.link_type === "BANK_ACCOUNT") api.get("/api/bank-accounts").then((a) => setOpts(a.map((x: any) => ({ value: String(x.id), label: x.label }))), setErr);
    else if (v.link_type === "BUDGET") {
      api.get("/api/fiscal-years").then(async (ys) => {
        const out: { value: string; label: string }[] = [];
        for (const y of ys) {
          const t = await api.get(`/api/budgets?fiscal_year_id=${y.id}`);
          for (const p of [...t.income, ...t.expense]) {
            out.push({ value: String(p.id), label: `${y.display_name} · ${p.label}` });
            for (const c of p.children || []) out.push({ value: String(c.id), label: `${y.display_name} · ${c.label}` });
          }
        }
        setOpts(out);
      }, setErr);
    }
  }, [v.link_type]);
  const set = (k: string) => (e: any) => setV({ ...v, [k]: e.target.value });
  const repeats = v.scope === "ORGANIZATION" && v.repeat === "yes";
  const many = Number(v.repeat_every || 1) !== 1;
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = { scope: v.scope, title: v.title, details: v.details || null, due_date: v.due_date,
                   notify_days_before: Number(v.notify_days_before || 0),
                   link_type: v.link_type || null, link_id: v.link_type && v.link_id ? Number(v.link_id) : null,
                   repeat_every: repeats ? Number(v.repeat_every || 1) : null, repeat_unit: repeats ? v.repeat_unit : null,
                   repeat_until: repeats && v.repeat_until ? v.repeat_until : null };
    try {
      if (current.id) await api.put(`/api/reminders/${current.id}`, body); else await api.post("/api/reminders", body);
      onSaved();
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={current.id ? "Edit reminder" : "New reminder"} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {!current.id && org && personal ? (
          <Field label="For" hint="Organization reminders are shown to every financial user and to Auditors.">
            <select value={v.scope} onChange={set("scope")}><option value="PERSONAL">Just me (personal)</option><option value="ORGANIZATION">The whole organization</option></select>
          </Field>
        ) : <p className="muted">{v.scope === "ORGANIZATION" ? "Organization reminder" : "Personal reminder (only you see it)"}</p>}
        <Field label="Reminder"><input required maxLength={200} value={v.title} onChange={set("title")} /></Field>
        <Field label="Details (optional)"><textarea rows={2} maxLength={2000} value={v.details} onChange={set("details")} /></Field>
        <div className="row fields">
          <Field label="Due date"><input type="date" required value={v.due_date} onChange={set("due_date")} /></Field>
          <Field label="Show days before" hint="0 = on the due date."><input type="number" min={0} max={365} value={v.notify_days_before} onChange={set("notify_days_before")} /></Field>
        </div>
        {v.scope === "ORGANIZATION" ? (
          <div className="row fields">
            <Field label="Repeat">
              <select value={v.repeat} onChange={set("repeat")}><option value="no">Does not repeat</option><option value="yes">Repeats every…</option></select>
            </Field>
            {repeats ? (
              <>
                <Field label="Every"><input type="number" required min={1} max={365} value={v.repeat_every} onChange={set("repeat_every")} /></Field>
                <Field label="Period">
                  <select value={v.repeat_unit} onChange={set("repeat_unit")}>
                    <option value="DAY">{many ? "days" : "day"}</option><option value="WEEK">{many ? "weeks" : "week"}</option>
                    <option value="MONTH">{many ? "months" : "month"}</option><option value="YEAR">{many ? "years" : "year"}</option>
                  </select>
                </Field>
                <Field label="Until (optional)" hint="Empty = no end."><input type="date" min={v.due_date} value={v.repeat_until} onChange={set("repeat_until")} /></Field>
              </>
            ) : null}
          </div>
        ) : null}
        {repeats ? <p className="hint">Each time it is resolved, the next one is created, counted from the due date above (not from the day it was resolved).</p> : null}
        <div className="row fields">
          <Field label="Link to (optional)">
            <select value={v.link_type} onChange={(e) => setV({ ...v, link_type: e.target.value, link_id: "" })}>
              <option value="">— nothing —</option><option value="FISCAL_YEAR">A Fiscal Year</option><option value="BUDGET">A budget</option><option value="BANK_ACCOUNT">A bank account</option>
            </select>
          </Field>
          {v.link_type ? (
            <Field label="Item">
              <select required value={v.link_id} onChange={set("link_id")}>
                <option value="">— choose —</option>
                {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Field>
          ) : null}
        </div>
        <p className="hint">Once it is shown, a reminder stays in everyone's notifications until it is resolved. It can be edited or deleted only before that.</p>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** Dashboard section: due reminders (rendered only when there are any). */
export function DashboardNotifications() {
  const [items, setItems] = useState<any[]>([]);
  const [resolving, setResolving] = useState<any>(null);
  const load = () => api.get("/api/reminders?view=due").then(setItems, () => undefined);
  useEffect(() => { load(); }, []);
  if (!items.length) return null;
  return (
    <section className="card" aria-labelledby="dash-notif-h">
      <div className="charts-head"><h2 id="dash-notif-h">Notifications ({items.length})</h2><Link to="/notifications">All reminders</Link></div>
      <ul className="reminders">{items.map((r) => <ReminderItem key={r.id} r={r} onResolve={setResolving} />)}</ul>
      {resolving ? <ResolveDialog r={resolving} onClose={() => setResolving(null)} onDone={() => { setResolving(null); load(); window.dispatchEvent(new Event(REMINDERS_CHANGED)); }} /> : null}
    </section>
  );
}
