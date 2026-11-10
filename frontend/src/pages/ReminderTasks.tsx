// 2.4.0 (#551): reminder tasks - the steps of a reminder (ticked one at a time, the first open one is "Next") and its
// objective (the reminder itself, always last: its tick completes the reminder), each
// task's contact (a fixed entity or whoever holds a position) and app function (a report or a page, by the name users
// see), and the editor used by the reminder form and by "Edit tasks…" on a shown reminder.
import { useEffect, useRef, useState, type FormEvent } from "react";
import { api } from "../api";
import { entityName } from "../names";
import { EntityPicker, ErrorBox, Field, GuardedForm, Modal, SuggestInput } from "../components";
import { Link } from "../router";
import { navFor, useMe } from "../App";
import { FUNCTIONS, functionFor } from "../functions";
import { GROUPS, REPORTS } from "./reports/registry";

export const MAX_TASKS = 25;   // the steps and the objective

/** A task as the editor keeps it (the API's task fields). The objective is the last draft (``objective``). */
export type TaskDraft = { id?: number; title: string; done?: boolean; objective?: boolean;
  contact_kind: "" | "ENTITY" | "POSITION"; contact_entity_id: string; contact_position: string; function_id: string;
  contact?: any; via_entity_id?: string; key?: string };   // editor only: via_entity_id, the person a position was
                                                           // taken from; key, a new step's React key (stable when moved)

let newKey = 0;
const blank = (objective = false): TaskDraft => ({ title: "", objective, contact_kind: "", contact_entity_id: "",
  contact_position: "", function_id: "", key: `new-${++newKey}` });

/** Drafts from the API's tasks: the steps, then the objective (a new reminder gets an empty objective). */
export const draftsOf = (tasks: any[] | undefined): TaskDraft[] => {
  const d: TaskDraft[] = (tasks || []).map((t) => ({
    id: t.id, title: t.title, done: !!t.done, objective: !!t.objective, contact_kind: t.contact_kind || "",
    function_id: t.function_id || "", contact_entity_id: t.contact_entity_id ? String(t.contact_entity_id) : "",
    contact_position: t.contact_position || "", contact: t.contact }));
  return d.some((x) => x.objective) ? [...d.filter((x) => !x.objective), d.find((x) => x.objective)!] : [...d, blank(true)];
};

const fields = (d: TaskDraft) => ({
  contact_kind: d.contact_kind || null,
  contact_entity_id: d.contact_kind === "ENTITY" && d.contact_entity_id ? Number(d.contact_entity_id) : null,
  contact_position: d.contact_kind === "POSITION" ? d.contact_position || null : null, function_id: d.function_id || null });

/** The API body: ``tasks`` (the steps) and ``objective`` (its contact and app function). */
export const tasksBody = (drafts: TaskDraft[]) => {
  const obj = drafts.find((d) => d.objective) || blank(true);
  return { tasks: drafts.filter((d) => !d.objective).map((d) => ({ id: d.id ?? null, title: d.title, ...fields(d) })),
           objective: fields(obj) };
};

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

/** 2.4.0 polish: a read-only view of a contact's entity (for users who see entity details - register.view). */
function EntityViewDialog({ id, onClose }: { id: number; onClose: () => void }) {
  const [e, setE] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { api.get(`/api/entities/${id}`).then(setE, setErr); }, [id]);
  const lines = (pre: string) => [[`${pre}address_line1`, `${pre}address_line2`].map((k) => e[k]),
    [[e[`${pre}city`], e[`${pre}state_region`]].filter(Boolean).join(", "), e[`${pre}postal_code`]].filter(Boolean).join(" "),
    e[`${pre}country`]].flat().filter(Boolean);
  const row = (label: string, v: any) => (v ? <><dt>{label}</dt><dd>{v}</dd></> : null);
  const mailing = e && !e.mailing_same ? lines("mailing_") : [];
  return (
    <Modal title={e ? e.display_name : "Entity"} onClose={onClose}>
      <ErrorBox error={err} />
      {e ? (
        <dl className="dl" data-testid="entity-view">
          {row("Entity number", e.entity_number)}
          {row("Type", e.entity_type === "INDIVIDUAL" ? "Individual" : "Organization")}
          {row("Organization", e.organization_name)}
          {row("Name", [e.first_name, e.last_name].filter(Boolean).join(" "))}
          {row("Position", e.position)}
          {row("Email", e.email ? <><a href={`mailto:${e.email}`}>{e.email}</a>{" "}
            <button type="button" className="small link" aria-label={`Copy ${e.email}`}
                    onClick={() => navigator.clipboard?.writeText(e.email).catch(() => undefined)}>Copy</button></> : null)}
          {row("Phone", e.phone_display || e.phone)}
          {row("Address", lines("").length ? lines("").map((l: string) => <div key={l}>{l}</div>) : null)}
          {row("Mailing address", mailing.length ? mailing.map((l: string) => <div key={l}>{l}</div>) : null)}
          {row("EIN", e.ein)}
          {row("Tax exempt", e.tax_exempt ? `Yes${e.tax_exempt_certificate ? ` (certificate ${e.tax_exempt_certificate})` : ""}` : null)}
          {row("Financial institution", e.is_financial_institution ? "Yes" : null)}
          {row("Status", e.active ? null : "Inactive")}
          {row("Notes", e.notes ? <span className="pre-wrap">{e.notes}</span> : null)}
        </dl>
      ) : err ? null : <p className="muted">Loading…</p>}
      <div className="actions"><button type="button" onClick={onClose}>Close</button></div>
    </Modal>
  );
}

/** A task's contact: the people with their email, phone and mailing address, or the name/position with a warning.
 * 2.4.0 polish: each name opens a read-only view of the entity, for users who see contact details. */
function ContactLine({ c }: { c: any }) {
  const { can } = useMe();
  const [viewing, setViewing] = useState<number | null>(null);
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
          {can("register.view") ? (
            <button type="button" className="link entity-link" data-testid="task-contact-entity" title="View this entity"
                    aria-label={`View ${p.name}`} onClick={() => setViewing(p.id)}><b>{p.name}</b></button>
          ) : <b>{p.name}</b>}{p.position && c.kind !== "POSITION" ? <span className="muted"> · {p.position}</span> : null}
          {p.email ? <> · <a href={`mailto:${p.email}`}>{p.email}</a>{" "}
            <button type="button" className="small link" aria-label={`Copy ${p.email}`}
                    onClick={() => navigator.clipboard?.writeText(p.email).catch(() => undefined)}>Copy</button></> : null}
          {p.phone ? <> · {p.phone}</> : null}
          {p.address?.length ? <div className="muted">{p.address.join(", ")}</div> : null}
        </div>
      ))}
      {viewing !== null ? <EntityViewDialog id={viewing} onClose={() => setViewing(null)} /> : null}
    </div>
  );
}

/** The checklist on a reminder: its steps, then its objective, whose tick completes (resolves) the reminder. A reminder
 * with only its objective shows just the objective's contact and app function, if any (it is resolved as always). */
export function TaskList({ r, onChanged, collapsed }: { r: any; onChanged?: () => void; collapsed?: boolean }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [completing, setCompleting] = useState(false);
  const tasks: any[] = r.tasks || [];
  const steps = tasks.filter((t) => !t.objective);
  const obj = tasks.find((t) => t.objective);
  if (!obj) return null;
  if (!steps.length) {
    if (!obj.function_id && !obj.contact) return null;
    return (
      <div className="reminder-tasks" data-testid="reminder-objective">
        {obj.function_id ? <div><FunctionButton id={obj.function_id} /></div> : null}
        <ContactLine c={obj.contact} />
      </div>
    );
  }
  const progress = <div className="muted" data-testid="task-progress">{r.steps_done} of {r.steps} step{r.steps === 1 ? "" : "s"} done</div>;
  // 2.4.0 polish: a collapsed dashboard card shows only the progress line
  if (collapsed) return <div className="reminder-tasks">{progress}</div>;
  const resolved = r.state === "RESOLVED";
  const next = resolved ? undefined : steps.find((t) => !t.done) || obj;
  const call = async (path: string) => {
    setErr(null); setBusy(true);
    try { await api.post(path, {}); onChanged?.(); } catch (x) { setErr(x); } finally { setBusy(false); }
  };
  const toggle = (t: any) => {
    if (t.done) { if (r.can_untick) call(`/api/reminders/${r.id}/tasks/${t.id}/untick`); return; }
    if (!r.can_tick) return;
    if (t.objective) setCompleting(true); else call(`/api/reminders/${r.id}/tasks/${t.id}/tick`);
  };
  const row = (t: any) => {
    const canToggle = t.done ? r.can_untick : r.can_tick;
    return (
      <li key={t.id} className={`task${t.done ? " task-done" : ""}${t.objective ? " task-objective" : ""}`}
          data-testid={t.objective ? "reminder-objective" : "reminder-task"}>
        <label className="check">
          <input type="checkbox" checked={!!t.done} disabled={busy || !canToggle} onChange={() => toggle(t)}
                 aria-label={t.done ? `Clear completion of ${t.title}` : `Mark ${t.title} completed`} />
          <span className="task-title">{t.objective ? <b>{t.title}</b> : t.title}</span>
        </label>
        {t.objective && !t.done ? <span className="muted"> — completes the reminder </span> : null}
        {next && next.id === t.id ? <span className="pill pill-approved" data-testid="task-next">Next</span> : null}
        {!t.done && resolved ? <span className="pill">Skipped</span> : null}
        {t.done && t.done_by ? <span className="muted"> · Marked completed by {t.done_by} on {String(t.done_at).slice(0, 10)}</span> : null}
        {t.function_id ? <> <FunctionButton id={t.function_id} /></> : null}
        <ContactLine c={t.contact} />
      </li>
    );
  };
  return (
    <div className="reminder-tasks">
      {progress}
      <ErrorBox error={err} />
      <ol className="task-list">{steps.map(row)}</ol>
      <ul className="task-list task-list-objective">{row(obj)}</ul>
      {completing ? <CompleteDialog r={r} t={obj} open={steps.filter((t) => !t.done)} onClose={() => setCompleting(false)}
                                    onDone={() => { setCompleting(false); onChanged?.(); }} /> : null}
    </div>
  );
}

/** Ticking the objective: a note, required when steps are still open (they are shown as skipped). */
function CompleteDialog({ r, t, open, onClose, onDone }: { r: any; t: any; open: any[]; onClose: () => void; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.post(`/api/reminders/${r.id}/tasks/${t.id}/tick`, { note: note || null }); onDone(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title="Complete the reminder" onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <p>Marking <b>{t.title}</b> completed finishes the reminder.{r.repeat_label && r.next_due ? ` The next one will be due ${r.next_due}.` : ""}</p>
        {open.length ? (
          <div className="alert warn" role="note">
            {open.length} step{open.length === 1 ? " isn't" : "s aren't"} completed and will be shown as skipped: {open.map((x) => x.title).join(", ")}. Say why in the note.
          </div>
        ) : null}
        <ErrorBox error={err} />
        <Field label={open.length ? "Note" : "Note (optional)"} hint="Kept with the reminder and in the audit log.">
          <input required={open.length > 0} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Mark completed</button></div>
      </GuardedForm>
    </Modal>
  );
}

/** A task's contact and "Opens" fields (a step's or the objective's). */
function TaskFields({ d, label, entities, positions, put }: {
  d: TaskDraft; label: string; entities: any[]; positions: { value: string; hint?: string }[]; put: (p: Partial<TaskDraft>) => void;
}) {
  const ent = entities.find((e) => String(e.id) === d.contact_entity_id);
  const known = d.contact_kind === "ENTITY" && d.contact_entity_id && !ent && d.contact?.label
    ? { id: d.contact_entity_id, label: `${d.contact.label} (inactive)` } : null;
  const reportsByGroup = GROUPS.map((g) => ({ g, list: REPORTS.filter((r) => r.group === g.id) })).filter((x) => x.list.length);
  // "This person" or "Whoever is <position>" for a person with a position, either way round
  const p = d.contact_kind === "ENTITY" ? ent : d.contact_kind === "POSITION" && d.via_entity_id
    ? entities.find((e) => String(e.id) === d.via_entity_id) : undefined;
  const pos = (p?.position || "").trim();
  const byPos = d.contact_kind === "POSITION";
  return (
    <>
      <div className="row fields">
        <Field label="Contact (optional)">
          <select value={d.contact_kind} aria-label={`${label} contact`}
                  onChange={(e) => put({ contact_kind: e.target.value as TaskDraft["contact_kind"], contact_entity_id: "", contact_position: "", via_entity_id: undefined })}>
            <option value="">— none —</option>
            <option value="ENTITY">An organization or person</option>
            <option value="POSITION">Whoever holds a position</option>
          </select>
        </Field>
        {d.contact_kind === "ENTITY" ? (
          <EntityPicker label={`${label}: organization or person`} entities={entities} value={d.contact_entity_id} extraOption={known}
                        placeholder="Type a name or a position…" onChange={(id, byPosition) => {
                          // #551: a person found by their position defaults to "whoever holds" it
                          const e = entities.find((x) => String(x.id) === id);
                          const ep = (e?.position || "").trim();
                          if (byPosition && e?.entity_type === "INDIVIDUAL" && ep) put({ contact_kind: "POSITION", contact_position: ep, contact_entity_id: "", via_entity_id: id });
                          else put({ contact_entity_id: id, via_entity_id: undefined });
                        }} />
        ) : null}
        {d.contact_kind === "POSITION" ? (
          <Field label="Position" hint="The active individuals with this position when the reminder is shown.">
            <SuggestInput required maxLength={60} value={d.contact_position} ariaLabel={`${label} position`}
                          suggestions={positions} empty="No one has this position yet"
                          onChange={(v) => put({ contact_position: v })} />
          </Field>
        ) : null}
        <Field label="Opens (optional)">
          <select value={d.function_id} aria-label={`${label} opens`} onChange={(e) => put({ function_id: e.target.value })}>
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
      {p && p.entity_type === "INDIVIDUAL" && pos ? (
        <div className="row" role="radiogroup" aria-label={`${label} contact is`}>
          <label className="check"><input type="radio" name={`who-${label.replace(/\W+/g, "-")}`} checked={!byPos}
            onChange={() => put({ contact_kind: "ENTITY", contact_entity_id: String(p.id), contact_position: "", via_entity_id: undefined })} /> This person ({p.display_name})</label>
          <label className="check"><input type="radio" name={`who-${label.replace(/\W+/g, "-")}`} checked={byPos}
            onChange={() => put({ contact_kind: "POSITION", contact_position: pos, contact_entity_id: "", via_entity_id: String(p.id) })} /> Whoever is {pos}</label>
        </div>
      ) : null}
    </>
  );
}

/** The task editor (reminder form, "Edit tasks…"): the steps, reorderable among themselves, then the objective -
 * pinned last, named by the reminder's title. */
export function TaskEditor({ title, value, onChange }: { title: string; value: TaskDraft[]; onChange: (v: TaskDraft[]) => void }) {
  const [entities, setEntities] = useState<any[]>([]);
  useEffect(() => { api.get("/api/entities?status=active&limit=2000").then((es) => setEntities(es.filter((e: any) => !e.is_system)), () => setEntities([])); }, []);
  // 2.4.0 polish: each position with who holds it, so "city" finds "City Clerk" and "Mayor of the City of …", and a
  // holder's name finds their position (positions resolve case-insensitively, so case variants are listed once)
  const held = new Map<string, { value: string; names: string[] }>();
  entities.filter((e) => e.entity_type === "INDIVIDUAL" && (e.position || "").trim()).forEach((e) => {
    const k = e.position.trim().toLowerCase();
    if (!held.has(k)) held.set(k, { value: e.position.trim(), names: [] });
    held.get(k)!.names.push(entityName(e));
  });
  const positions = [...held.values()].sort((a, b) => a.value.localeCompare(b.value))
    .map((p) => ({ value: p.value, hint: p.names.sort((a, b) => a.localeCompare(b)).join(", ") }));
  const steps = value.filter((d) => !d.objective);
  const obj = value.find((d) => d.objective) || blank(true);
  const setSteps = (v: TaskDraft[]) => onChange([...v, obj]);
  const put = (i: number, p: Partial<TaskDraft>) => setSteps(steps.map((d, j) => (j === i ? { ...d, ...p } : d)));
  const moveTo = (from: number, to: number) => {
    if (from === to) return;
    const v = [...steps]; const [d] = v.splice(from, 1); v.splice(to, 0, d); setSteps(v);
  };
  const move = (i: number, by: number) => moveTo(i, i + by);
  // 2.4.0 polish: drag a step by its handle (⠿) to any place in the list; ↑/↓ stay for the keyboard
  const dragFrom = useRef<number | null>(null);
  const [dragging, setDragging] = useState<number | null>(null);
  const [over, setOver] = useState<number | null>(null);
  const endDrag = () => { dragFrom.current = null; setDragging(null); setOver(null); };
  return (
    <fieldset className="task-editor" data-testid="task-editor">
      <legend>Steps (optional)</legend>
      <p className="hint">Steps are marked completed one at a time, in any order; the reminder itself is the last task, and marking it completed finishes the reminder.
        {steps.length > 1 ? " Drag a step by ⠿, or use ↑ and ↓, to change the order." : ""}</p>
      {steps.map((d, i) => (
        <div key={d.id ?? d.key ?? `new-${i}`} data-testid="task-edit"
             className={`task-edit${dragging === i ? " dragging" : ""}${over === i && dragging !== null && dragging !== i ? (dragging < i ? " drop-after" : " drop-before") : ""}`}
             onDragOver={(e) => { if (dragFrom.current === null) return; e.preventDefault(); e.dataTransfer.dropEffect = "move"; if (over !== i) setOver(i); }}
             onDrop={(e) => { if (dragFrom.current === null) return; e.preventDefault(); moveTo(dragFrom.current, i); endDrag(); }}>
          <div className="row fields">
            <span className="drag-handle" title="Drag to move this step" aria-hidden="true" draggable data-testid="task-drag"
                  onDragStart={(e) => { dragFrom.current = i; setDragging(i); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(i)); }}
                  onDragEnd={endDrag}>⠿</span>
            <Field label={`Step ${i + 1}`}><input required maxLength={200} value={d.title} aria-label={`Step ${i + 1} name`}
                                                  onChange={(e) => put(i, { title: e.target.value })} /></Field>
            <div className="row task-edit-actions">
              <button type="button" className="small" disabled={i === 0} aria-label={`Move step ${i + 1} up`} onClick={() => move(i, -1)}>↑</button>
              <button type="button" className="small" disabled={i === steps.length - 1} aria-label={`Move step ${i + 1} down`} onClick={() => move(i, 1)}>↓</button>
              <button type="button" className="small danger" disabled={d.done} title={d.done ? "Clear its completion first." : undefined}
                      aria-label={`Remove step ${i + 1}`} onClick={() => setSteps(steps.filter((_x, j) => j !== i))}>Remove</button>
            </div>
          </div>
          <TaskFields d={d} label={`Step ${i + 1}`} entities={entities} positions={positions} put={(p) => put(i, p)} />
        </div>
      ))}
      {steps.length < MAX_TASKS - 1 ? (
        <button type="button" className="small" onClick={() => setSteps([...steps, blank()])}>Add a step</button>
      ) : <p className="hint">A reminder can have up to {MAX_TASKS} tasks (its steps and itself).</p>}
      <div className="task-edit task-edit-objective" data-testid="task-edit-objective">
        <div className="field-label">{steps.length ? `Last: ${title || "the reminder"}` : (title || "The reminder")} — completes the reminder</div>
        <TaskFields d={obj} label="Objective" entities={entities} positions={positions} put={(p) => onChange([...steps, { ...obj, ...p }])} />
      </div>
    </fieldset>
  );
}

/** "Edit tasks…" on a shown reminder: only the checklist changes (BR-REM-TASK-005). */
export function TasksDialog({ r, onClose, onSaved }: { r: any; onClose: () => void; onSaved: () => void }) {
  const [drafts, setDrafts] = useState<TaskDraft[]>(draftsOf(r.tasks));
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try { await api.put(`/api/reminders/${r.id}/tasks`, tasksBody(drafts)); onSaved(); } catch (x) { setErr(x); }
  };
  return (
    <Modal title={`Tasks — ${r.title}`} onClose={onClose} wide>
      <GuardedForm onSubmit={submit}>
        <p className="hint">The reminder is shown, so only its tasks can change. Completed tasks stay completed.</p>
        <ErrorBox error={err} />
        <TaskEditor title={r.title} value={drafts} onChange={setDrafts} />
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save tasks</button></div>
      </GuardedForm>
    </Modal>
  );
}
