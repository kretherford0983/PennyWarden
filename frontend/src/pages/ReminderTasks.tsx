// 2.4.0 (#551): reminder tasks - the checklist on a reminder (tick one at a time, the first open one is "Next"), each
// task's contact (a fixed entity or whoever holds a position) and app function (a report or a page, by the name users
// see), and the editor used by the reminder form and by "Edit tasks…" on a shown reminder.
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { EntityPicker, ErrorBox, Field, GuardedForm, Modal } from "../components";
import { Link } from "../router";
import { navFor, useMe } from "../App";
import { FUNCTIONS, functionFor } from "../functions";
import { GROUPS, REPORTS } from "./reports/registry";

export const MAX_TASKS = 25;

/** A task as the editor keeps it (the API's task fields). */
export type TaskDraft = { id?: number; title: string; done?: boolean; contact_kind: "" | "ENTITY" | "POSITION";
  contact_entity_id: string; contact_position: string; function_id: string; contact?: any;
  via_entity_id?: string };   // editor only: the person the position was taken from (to offer "This person" back)

export const draftsOf = (tasks: any[] | undefined): TaskDraft[] => (tasks || []).map((t) => ({
  id: t.id, title: t.title, done: !!t.done, contact_kind: t.contact_kind || "", function_id: t.function_id || "",
  contact_entity_id: t.contact_entity_id ? String(t.contact_entity_id) : "", contact_position: t.contact_position || "",
  contact: t.contact }));

export const tasksBody = (drafts: TaskDraft[]) => drafts.map((d) => ({
  id: d.id ?? null, title: d.title, contact_kind: d.contact_kind || null,
  contact_entity_id: d.contact_kind === "ENTITY" && d.contact_entity_id ? Number(d.contact_entity_id) : null,
  contact_position: d.contact_kind === "POSITION" ? d.contact_position || null : null, function_id: d.function_id || null }));

/** The optional modules, by the names the Administrator turns on under System/About → General. */
const MODULE_NAMES: Record<string, string> = { fundraisers: "Events & Fundraisers", checks: "Payments", donations: "Donations", invoices: "Invoices" };

/** The button that opens a task's app function, disabled (with the reason) when this user can't open it: a module
 * that is turned off is named; otherwise it is the user's access. */
function FunctionButton({ id }: { id: string }) {
  const { me, can } = useMe();
  const f = functionFor(id);
  if (!f) return null;
  const modules = me.modules || {};
  const usable = (mods: Record<string, boolean | undefined>) =>
    f.usable({ can, modules: mods }, new Set(navFor({ ...me, modules: mods }).map((n) => n[0])));
  if (usable(modules)) return <Link to={f.path} className="button small" data-testid="task-function">{f.name}</Link>;
  const off = Object.keys(MODULE_NAMES).find((k) => !modules[k as keyof typeof modules] && usable({ ...modules, [k]: true }));
  const why = off ? `The ${MODULE_NAMES[off]} module is turned off.` : `You don't have access to ${f.name}.`;
  return (
    <span className="task-function-off">
      <button type="button" className="small" disabled title={why} data-testid="task-function">{f.name}</button>
      <span className="muted" data-testid="task-function-why"> {why}</span>
    </span>
  );
}

/** A task's contact: the people with their email, phone and mailing address, or the name/position with a warning. */
function ContactLine({ c }: { c: any }) {
  if (!c) return null;
  const what = c.kind === "POSITION" ? c.label : (c.label || "A contact that was removed");
  if (c.missing) {
    return (
      <div className="task-contact warn" data-testid="task-contact">
        <b>{what}</b>{c.inactive ? " (inactive)" : ""} — {c.kind === "POSITION" ? "nobody active holds this position" : "no contact details"}.
        {" "}Find the contact and edit the task.
      </div>
    );
  }
  return (
    <div className="task-contact" data-testid="task-contact">
      {c.kind === "POSITION" ? <span className="muted">{c.label}: </span> : null}
      {c.several ? <span className="badge red">More than one active entity holds this position</span> : null}
      {c.people.map((p: any) => (
        <div key={p.id} className="task-person">
          <b>{p.name}</b>{p.position && c.kind !== "POSITION" ? <span className="muted"> · {p.position}</span> : null}
          {p.email ? <> · <a href={`mailto:${p.email}`}>{p.email}</a>{" "}
            <button type="button" className="small link" aria-label={`Copy ${p.email}`}
                    onClick={() => navigator.clipboard?.writeText(p.email).catch(() => undefined)}>Copy</button></> : null}
          {p.phone ? <> · {p.phone}</> : null}
          {p.address?.length ? <div className="muted">{p.address.join(", ")}</div> : null}
        </div>
      ))}
    </div>
  );
}

/** The checklist on a reminder. Ticking the last open task asks for an optional note, then resolves the reminder. */
export function TaskList({ r, onChanged }: { r: any; onChanged?: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [last, setLast] = useState<any>(null);
  const tasks: any[] = r.tasks || [];
  if (!tasks.length) return null;
  const next = r.state !== "RESOLVED" ? tasks.find((t) => !t.done) : undefined;
  const open = tasks.filter((t) => !t.done).length;
  const call = async (path: string, body?: any) => {
    setErr(null); setBusy(true);
    try { await api.post(path, body || {}); onChanged?.(); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const toggle = (t: any) => {
    if (t.done) { if (r.can_untick) call(`/api/reminders/${r.id}/tasks/${t.id}/untick`); return; }
    if (!r.can_tick) return;
    if (open === 1) setLast(t); else call(`/api/reminders/${r.id}/tasks/${t.id}/tick`);
  };
  return (
    <div className="reminder-tasks">
      <div className="muted" data-testid="task-progress">{r.tasks_done} of {tasks.length} task{tasks.length === 1 ? "" : "s"} done</div>
      <ErrorBox error={err} />
      <ol className="task-list">
        {tasks.map((t) => {
          const canToggle = t.done ? r.can_untick : r.can_tick;
          return (
            <li key={t.id} className={`task${t.done ? " task-done" : ""}`} data-testid="reminder-task">
              <label className="check">
                <input type="checkbox" checked={!!t.done} disabled={busy || !canToggle} onChange={() => toggle(t)}
                       aria-label={`${t.done ? "Untick" : "Tick"} ${t.title}`} />
                <span className="task-title">{t.title}</span>
              </label>
              {next && next.id === t.id ? <span className="pill pill-approved" data-testid="task-next">Next</span> : null}
              {!t.done && r.state === "RESOLVED" ? <span className="pill">Skipped</span> : null}
              {t.done && t.done_by ? <span className="muted"> · ticked by {t.done_by} on {String(t.done_at).slice(0, 10)}</span> : null}
              {t.function_id ? <> <FunctionButton id={t.function_id} /></> : null}
              <ContactLine c={t.contact} />
            </li>
          );
        })}
      </ol>
      {last ? <LastTaskDialog r={r} t={last} onClose={() => setLast(null)}
                              onDone={() => { setLast(null); onChanged?.(); }} /> : null}
    </div>
  );
}

function LastTaskDialog({ r, t, onClose, onDone }: { r: any; t: any; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post(`/api/reminders/${r.id}/tasks/${t.id}/tick`, { note: note || null }); onDone(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Last task" onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <p><b>{t.title}</b> is the last open task: ticking it resolves <b>{r.title}</b>.
          {r.repeat_label && r.next_due ? ` The next one will be due ${r.next_due}.` : ""}</p>
        <ErrorBox error={err} />
        <Field label="Note (optional)" hint="Kept with the reminder and in the audit log."><input maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Tick and resolve</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** The task editor (reminder form, "Edit tasks…"). */
export function TaskEditor({ value, onChange }: { value: TaskDraft[]; onChange: (v: TaskDraft[]) => void }) {
  const [entities, setEntities] = useState<any[]>([]);
  useEffect(() => { api.get("/api/entities?status=active&limit=2000").then((es) => setEntities(es.filter((e: any) => !e.is_system)), () => setEntities([])); }, []);
  const positions = Array.from(new Set(entities.filter((e) => e.entity_type === "INDIVIDUAL" && (e.position || "").trim())
    .map((e) => e.position.trim()))).sort((a, b) => a.localeCompare(b));
  const put = (i: number, p: Partial<TaskDraft>) => onChange(value.map((d, j) => (j === i ? { ...d, ...p } : d)));
  const move = (i: number, by: number) => {
    const v = [...value]; const [d] = v.splice(i, 1); v.splice(i + by, 0, d); onChange(v);
  };
  const reportsByGroup = GROUPS.map((g) => ({ g, list: REPORTS.filter((r) => r.group === g.id) })).filter((x) => x.list.length);
  return (
    <fieldset className="task-editor" data-testid="task-editor">
      <legend>Tasks (optional)</legend>
      <p className="hint">A checklist ticked one at a time; when every task is ticked the reminder is resolved.</p>
      {value.map((d, i) => {
        const ent = entities.find((e) => String(e.id) === d.contact_entity_id);
        const known = d.contact_kind === "ENTITY" && d.contact_entity_id && !ent && d.contact?.label
          ? { id: d.contact_entity_id, label: `${d.contact.label} (inactive)` } : null;
        return (
          <div key={d.id ?? `new-${i}`} className="task-edit" data-testid="task-edit">
            <div className="row fields">
              <Field label={`Task ${i + 1}`}><input required maxLength={200} value={d.title} aria-label={`Task ${i + 1} name`}
                                                    onChange={(e) => put(i, { title: e.target.value })} /></Field>
              <div className="row task-edit-actions">
                <button type="button" className="small" disabled={i === 0} aria-label={`Move task ${i + 1} up`} onClick={() => move(i, -1)}>↑</button>
                <button type="button" className="small" disabled={i === value.length - 1} aria-label={`Move task ${i + 1} down`} onClick={() => move(i, 1)}>↓</button>
                <button type="button" className="small danger" disabled={d.done} title={d.done ? "Untick it first." : undefined}
                        aria-label={`Remove task ${i + 1}`} onClick={() => onChange(value.filter((_x, j) => j !== i))}>Remove</button>
              </div>
            </div>
            <div className="row fields">
              <Field label="Contact">
                <select value={d.contact_kind} aria-label={`Task ${i + 1} contact`}
                        onChange={(e) => put(i, { contact_kind: e.target.value as TaskDraft["contact_kind"], contact_entity_id: "", contact_position: "", via_entity_id: undefined })}>
                  <option value="">— none —</option>
                  <option value="ENTITY">An organization or person</option>
                  <option value="POSITION">Whoever holds a position</option>
                </select>
              </Field>
              {d.contact_kind === "ENTITY" ? (
                <EntityPicker label="Organization or person" entities={entities} value={d.contact_entity_id} extraOption={known}
                              placeholder="Type a name or a position…" onChange={(id, byPosition) => {
                                // #551: a person found by their position defaults to "whoever holds" it
                                const e = entities.find((x) => String(x.id) === id);
                                const pos = (e?.position || "").trim();
                                if (byPosition && e?.entity_type === "INDIVIDUAL" && pos) put(i, { contact_kind: "POSITION", contact_position: pos, contact_entity_id: "", via_entity_id: id });
                                else put(i, { contact_entity_id: id, via_entity_id: undefined });
                              }} />
              ) : null}
              {d.contact_kind === "POSITION" ? (
                <Field label="Position" hint="The active individuals with this position when the reminder is shown.">
                  <input list={`positions-${i}`} required maxLength={60} value={d.contact_position} aria-label={`Task ${i + 1} position`}
                         onChange={(e) => put(i, { contact_position: e.target.value })} />
                  <datalist id={`positions-${i}`}>{positions.map((p) => <option key={p} value={p} />)}</datalist>
                </Field>
              ) : null}
              <Field label="Opens (optional)">
                <select value={d.function_id} aria-label={`Task ${i + 1} opens`} onChange={(e) => put(i, { function_id: e.target.value })}>
                  <option value="">— nothing —</option>
                  {reportsByGroup.map(({ g, list }) => (
                    <optgroup key={g.id} label={`Reports · ${g.short}`}>
                      {list.map((r) => <option key={r.id} value={`report:${r.id}`}>{r.name}</option>)}
                    </optgroup>
                  ))}
                  <optgroup label="Pages">
                    {FUNCTIONS.filter((f) => f.kind === "page").map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
                  </optgroup>
                </select>
              </Field>
            </div>
            {(() => {
              // "This person" or "Whoever is <position>" for a person with a position, either way round
              const p = d.contact_kind === "ENTITY" ? ent : d.contact_kind === "POSITION" && d.via_entity_id
                ? entities.find((e) => String(e.id) === d.via_entity_id) : undefined;
              const pos = (p?.position || "").trim();
              if (!p || p.entity_type !== "INDIVIDUAL" || !pos) return null;
              const byPos = d.contact_kind === "POSITION";
              return (
                <div className="row" role="radiogroup" aria-label={`Task ${i + 1} contact is`}>
                  <label className="check"><input type="radio" name={`who-${i}`} checked={!byPos}
                    onChange={() => put(i, { contact_kind: "ENTITY", contact_entity_id: String(p.id), contact_position: "", via_entity_id: undefined })} /> This person ({p.display_name})</label>
                  <label className="check"><input type="radio" name={`who-${i}`} checked={byPos}
                    onChange={() => put(i, { contact_kind: "POSITION", contact_position: pos, contact_entity_id: "", via_entity_id: String(p.id) })} /> Whoever is {pos}</label>
                </div>
              );
            })()}
          </div>
        );
      })}
      {value.length < MAX_TASKS ? (
        <button type="button" className="small" onClick={() => onChange([...value, { title: "", contact_kind: "", contact_entity_id: "", contact_position: "", function_id: "" }])}>Add a task</button>
      ) : <p className="hint">A reminder can have up to {MAX_TASKS} tasks.</p>}
    </fieldset>
  );
}

/** "Edit tasks…" on a shown reminder: only the checklist changes (BR-REM-TASK-005). */
export function TasksDialog({ r, onClose, onSaved }: { r: any; onClose: () => void; onSaved: () => void }) {
  const [drafts, setDrafts] = useState<TaskDraft[]>(draftsOf(r.tasks));
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.put(`/api/reminders/${r.id}/tasks`, { tasks: tasksBody(drafts) }); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Tasks — ${r.title}`} onClose={onClose} wide>
      <GuardedForm onSubmit={submit}>
        <p className="hint">The reminder is shown, so only its tasks can change. Ticked tasks keep their tick.</p>
        <ErrorBox error={err} />
        <TaskEditor value={drafts} onChange={setDrafts} />
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save tasks</button></div>
      </GuardedForm>
    </Modal>
  );
}
