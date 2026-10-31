import React, { useEffect, useRef, useState, type FormEvent, type FormHTMLAttributes, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, ApiError, type ApiWarning, money, qs } from "./api";
import { entityName } from "./names";

/** v1.3 CR-011: a form that ignores further submits while one is being saved. All controls in the form are
 *  disabled until the save (including any confirmation dialog it opens) finishes; the submit button reads "Saving…". */
export function GuardedForm({ onSubmit, children, ...rest }: Omit<FormHTMLAttributes<HTMLFormElement>, "onSubmit"> & {
  onSubmit: (e: FormEvent<HTMLFormElement>) => unknown;
}) {
  const busyRef = useRef(false);
  const mounted = useRef(true);
  const [busy, setBusy] = useState(false);
  useEffect(() => () => { mounted.current = false; }, []);
  const handle = async (e: FormEvent<HTMLFormElement>) => {
    if (busyRef.current) { e.preventDefault(); return; }
    busyRef.current = true;
    setBusy(true);
    try {
      await onSubmit(e);
    } finally {
      busyRef.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <form {...rest} onSubmit={handle} aria-busy={busy || undefined}>
      <fieldset className="form-guard" disabled={busy}>{children}</fieldset>
    </form>
  );
}

const openModals: object[] = [];

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  // 1.10.0 (#139): the focus moves into the dialog once, when it opens. A parent that re-renders while the user types
  // (e.g. the dialog's text lives in the same component) passes a new onClose each time; that must not run this again
  // and pull the focus away from the field. The latest onClose is kept in a ref for the Escape key.
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    // 2.0.0 (#174): dialogs can open on top of each other (a PDF viewer over the print screen) - Escape closes only the
    // top one
    const me = {};
    openModals.push(me);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && openModals[openModals.length - 1] === me && closeRef.current();
    window.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      const i = openModals.indexOf(me);
      if (i >= 0) openModals.splice(i, 1);
    };
  }, []);
  // Portal: nested dialogs (e.g. "new institution" inside the account form) must not nest <form> elements.
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">×</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const e = error as ApiError;
  const msg = e?.message || String(error);
  return (
    <div className="alert error" role="alert">
      <strong>{msg}</strong>
      {e?.fieldErrors?.length ? (
        <ul>
          {e.fieldErrors.map((f, i) => (
            <li key={i}>
              {f.field ? <code>{f.field}</code> : null} {f.message}
            </li>
          ))}
        </ul>
      ) : null}
      {e?.body?.blockers?.length ? (
        <ul>
          {e.body.blockers.map((b: any) => (
            <li key={b.code}>{b.message}</li>
          ))}
        </ul>
      ) : null}
      {e?.body?.candidates?.length ? (
        <p>Candidates: {e.body.candidates.map((c: any) => c.label).join(", ")}</p>
      ) : null}
    </div>
  );
}

function WarningDetails({ w }: { w: ApiWarning }) {
  const d: any = w.details || {};
  return (
    <div className="warning-details">
      {d.gaps?.map((g: any, i: number) => (
        <p key={i}>
          Uncovered dates: <b>{g.from}</b> to <b>{g.to}</b> (adjacent {g.adjacent?.label})
        </p>
      ))}
      {d.overlapping?.map((o: any) => (
        <div key={o.id}>
          <p>
            Overlaps <b>{o.label}</b> ({o.start_date} – {o.end_date}).
          </p>
          <p className="muted">
            Closure readiness: {o.readiness?.can_close ? "ready to close" : (o.readiness?.blockers || []).map((b: any) => b.message).join("; ")}
          </p>
        </div>
      ))}
      {d.matches?.length ? (
        <table className="table compact">
          <thead>
            <tr><th>Entity #</th><th>Name</th><th>Type</th><th>Status</th><th>Email</th></tr>
          </thead>
          <tbody>
            {d.matches.map((m: any) => (
              <tr key={m.id}>
                <td>{m.entity_number}</td><td>{m.display_name}</td><td>{m.entity_type}</td>
                <td>{m.active ? "Active" : "Inactive"}</td><td>{m.email}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {d.closest_fiscal_year ? <p>Closest configured Fiscal Year (reference only): <b>{d.closest_fiscal_year.label}</b></p> : null}
      {d.budget_fiscal_year && !d.closest_fiscal_year ? (
        <p>
          Budget Fiscal Year: <b>{d.budget_fiscal_year.label}</b>; natural Fiscal Year: {(d.natural_fiscal_years || []).map((f: any) => f.label).join(", ")}
        </p>
      ) : null}
    </div>
  );
}

/** Runs an action; if the server requires explicit confirmation, shows the warnings and re-submits with
 * the acknowledged codes. Confirmation is a blocking dialog with an explicit checkbox. */
export function useConfirmable() {
  const [pending, setPending] = useState<null | { warnings: ApiWarning[]; retry: (codes: string[]) => void; cancel: () => void }>(null);
  const [ack, setAck] = useState(false);
  async function run<T>(fn: (confirmations: string[]) => Promise<T>, acc: string[] = []): Promise<T | undefined> {
    try {
      return await fn(acc);
    } catch (e) {
      if (e instanceof ApiError && e.code === "CONFIRMATION_REQUIRED" && e.warnings.length) {
        return new Promise<T | undefined>((resolve, reject) => {
          setAck(false);
          let done = false; // a double click on "Confirm and continue" must not submit twice
          setPending({
            warnings: e.warnings,
            retry: (codes) => {
              if (done) return;
              done = true;
              setPending(null);
              run(fn, [...acc, ...codes]).then(resolve, reject);
            },
            cancel: () => {
              if (done) return;
              done = true;
              setPending(null);
              resolve(undefined);
            },
          });
        });
      }
      throw e;
    }
  }
  const dialog = pending ? (
    <Modal title="Confirmation required" onClose={pending.cancel}>
      {pending.warnings.map((w) => (
        <div key={w.code} className="alert warn" role="alert">
          <strong>{w.message}</strong>
          <WarningDetails w={w} />
        </div>
      ))}
      <label className="check">
        <input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} /> I have reviewed these warnings and explicitly confirm.
      </label>
      <div className="actions">
        <button onClick={pending.cancel}>Cancel</button>
        <button className="primary" disabled={!ack} onClick={() => pending.retry(pending.warnings.map((w) => w.code))}>
          Confirm and continue
        </button>
      </div>
    </Modal>
  ) : null;
  return { run, dialog };
}

export function Lock({ open }: { open: boolean }) {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" className="lock-icon">
      <rect x="4" y="11" width="16" height="10" rx="2" fill="currentColor" />
      {open ? (
        <path d="M8 11V7a4 4 0 0 1 7.5-2" stroke="currentColor" strokeWidth="2.2" fill="none" />
      ) : (
        <path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="currentColor" strokeWidth="2.2" fill="none" />
      )}
    </svg>
  );
}

export function BudgetState({ state }: { state: { code: string; icon: string; label: string } }) {
  const icon =
    state.icon === "lock-closed" ? <Lock open={false} /> : state.icon === "lock-open" ? <Lock open /> : <span className="glyph">{state.icon}</span>;
  return (
    <span className={`state state-${state.code.toLowerCase()}`} title={state.label}>
      <span role="img" aria-label={state.label}>{icon}</span> <span className="state-text">{state.label}</span>
    </span>
  );
}

export function FyStatus({ status }: { status: string }) {
  return <span className={`pill pill-${status.toLowerCase()}`}>{status.charAt(0) + status.slice(1).toLowerCase()}</span>;
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <div className="field">
      <label className="field-inner">
        <span className="field-label">{label}</span>
        {children}
      </label>
      {hint ? <span className="hint">{hint}</span> : null}
    </div>
  );
}

// ------------------------------------------------------------------ 2.3.0 (#371, BR-109): budgets are gross
/** The same sentence is GROSS_BUDGET_NOTE in backend/fmpoc/services/common.py (a test keeps the two identical). */
export const GROSS_BUDGET_NOTE =
  "Budget amounts are gross. Offsetting income or expense recorded in a budget of the opposite type, such as a reimbursement, is not subtracted.";

/** The disclaimer line shown with a budget table (Budgets, Fiscal Year, Budget Review). */
export function GrossBudgetNote() {
  return <p className="hint gross-note" data-testid="gross-budget-note">{GROSS_BUDGET_NOTE}</p>;
}

let infoTipSeq = 0;
/** A small ⓘ button that opens a popup with a short explanation (Escape, a click elsewhere or the button closes it). */
export function InfoTip({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  const [id] = useState(() => `info-tip-${++infoTipSeq}`);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <span className="info-tip" ref={box}>
      <button type="button" className="info-tip-btn" aria-label={label} title={label} aria-expanded={open}
              aria-controls={open ? id : undefined} onClick={() => setOpen(!open)}>ⓘ</button>
      {open ? <span id={id} role="note" className="info-tip-pop">{text}</span> : null}
    </span>
  );
}

export function Loading() {
  return <p className="muted" aria-live="polite">Loading…</p>;
}

// ------------------------------------------------------------------ attachments
export const FY_DOCUMENT_TYPES: [string, string][] = [["APPROVAL", "Approval document"], ["AUDIT_SIGNOFF", "Audit Signoff"], ["UNSPECIFIED", "Other document"]];

export function Attachments({ ownerType, ownerId, canUpload, canRemove, title = "Attachments", documentTypes, canRetype, reloadKey, onChanged, hint, canReorder }: {
  ownerType: "fiscal_year" | "transaction" | "allocation" | "fundraiser";
  ownerId: number;
  canUpload: boolean;
  canRemove: boolean;
  title?: string;
  /** v1.3 CR-007: Fiscal Year document types shown in this list; the first is used for uploads. */
  documentTypes?: string[];
  canRetype?: boolean;
  reloadKey?: number;
  onChanged?: () => void;
  hint?: ReactNode;
  /** 2.1.0 (#259): may set the order (used on screen, in the Audit/Close/fundraiser reports and downloads). */
  canReorder?: boolean;
}) {
  const [all, setAll] = useState<any[]>([]);
  const [order, setOrder] = useState<any[] | null>(null);   // #259: the list while reordering (null = not reordering)
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [viewIdx, setViewIdx] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const items = documentTypes ? all.filter((a) => documentTypes.includes(a.document_type || "UNSPECIFIED")) : all;
  const load = () => api.get(`/api/attachments${qs({ owner_type: ownerType, owner_id: ownerId })}`).then(setAll, setErr);
  useEffect(() => {
    load();
  }, [ownerType, ownerId, reloadKey]);
  const retype = async (id: number, t: string) => {
    setErr(null);
    try { await api.post(`/api/attachments/${id}/document-type`, { document_type: t }); await load(); onChanged?.(); } catch (e) { setErr(e); }
  };
  const onFile = async (f: File | undefined) => {
    if (!f) return;
    setErr(null);
    if (f.size > 5 * 1024 * 1024) {
      setErr(new Error("Attachments may not exceed 5 MB per file."));
      return;
    }
    setBusy(true);
    try {
      await api.upload(`/api/attachments${qs({ owner_type: ownerType, owner_id: ownerId, document_type: documentTypes?.[0] })}`, f);
      await load();
      onChanged?.();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const remove = async (id: number) => {
    if (!window.confirm("Remove this attachment? It is retained in history.")) return;
    try {
      await api.post(`/api/attachments/${id}/remove`);
      await load();
      onChanged?.();
    } catch (e) {
      setErr(e);
    }
  };
  const move = (from: number, to: number) => {
    if (!order || to < 0 || to >= order.length || from === to) return;
    const next = [...order];
    const [x] = next.splice(from, 1);
    next.splice(to, 0, x);
    setOrder(next);
  };
  const saveOrder = async () => {
    if (!order) return;
    setErr(null);
    setBusy(true);
    try {
      await api.put("/api/attachments/order", { owner_type: ownerType, owner_id: ownerId, attachment_ids: order.map((a) => a.id) });
      setOrder(null);
      await load();
      onChanged?.();
    } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  const cur = viewIdx !== null ? items[viewIdx] : null;
  if (order) {
    return (
      <section className="attachments">
        <h3>{title}: set the order</h3>
        <p className="hint">Drag a file by its handle, or use ▲ and ▼. This order is used on screen, in the reports and in downloads.</p>
        <ErrorBox error={err} />
        <ol className="att-list att-order" aria-label={`Order of ${title}`}>
          {order.map((a, i) => (
            <li key={a.id} draggable onDragStart={() => setDragIdx(i)} onDragEnd={() => setDragIdx(null)}
                onDragOver={(e) => { e.preventDefault(); if (dragIdx !== null && dragIdx !== i) { move(dragIdx, i); setDragIdx(i); } }}
                className={dragIdx === i ? "dragging" : undefined}>
              <span className="drag-handle" aria-hidden="true" title="Drag to move">⠿</span>
              <span className="att-name">{a.original_filename}</span>
              {a.system_generated ? <span className="badge grey">System generated</span> : null}
              <span className="att-move">
                <button type="button" className="small" aria-label={`Move ${a.original_filename} up`} disabled={i === 0} onClick={() => move(i, i - 1)}>▲</button>
                <button type="button" className="small" aria-label={`Move ${a.original_filename} down`} disabled={i === order.length - 1} onClick={() => move(i, i + 1)}>▼</button>
              </span>
            </li>
          ))}
        </ol>
        <div className="actions">
          <button type="button" onClick={() => { setOrder(null); setErr(null); }}>Cancel</button>
          <button type="button" className="primary" disabled={busy || order.every((a, i) => a.id === items[i]?.id)} onClick={saveOrder}>Save order</button>
        </div>
      </section>
    );
  }
  return (
    <section className="attachments">
      <h3>{title} ({items.length})
        {canReorder && items.length > 1 ? <button type="button" className="small att-reorder" onClick={() => setOrder(items)}>Reorder…</button> : null}
      </h3>
      {hint}
      <ErrorBox error={err} />
      {items.length ? (
        <ul className="att-list">
          {items.map((a, i) => (
            <li key={a.id}>
              <button className="link" onClick={() => setViewIdx(i)}>{a.original_filename}</button>{" "}
              <span className="muted">{a.mime_type} · {(a.size_bytes / 1024).toFixed(1)} KB</span>{" "}
              <a href={`${a.content_url}?download=true`}>Download</a>
              {a.system_generated ? <span className="badge grey">System generated</span> : null}
              {canRetype && !a.system_generated ? (
                <select className="small" aria-label={`Document type of ${a.original_filename}`} value={a.document_type || "UNSPECIFIED"} onChange={(e) => retype(a.id, e.target.value)}>
                  {FY_DOCUMENT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                </select>
              ) : null}
              {canRemove && !a.system_generated ? <button className="small danger" onClick={() => remove(a.id)}>Remove</button> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No attachments.</p>
      )}
      {canUpload ? (
        <label className="upload">
          <span>{documentTypes ? `Add ${(FY_DOCUMENT_TYPES.find(([v]) => v === documentTypes[0])?.[1] || "document").toLowerCase()}` : "Add attachment"} (PDF, JPG, PNG; max 5 MB)</span>
          <input type="file" accept={ATTACH_ACCEPT} disabled={busy}
                 onChange={(e) => { onFile(e.target.files?.[0]); e.target.value = ""; }} />
        </label>
      ) : null}
      {cur ? (
        <Modal title={`${cur.original_filename} (${(viewIdx ?? 0) + 1} of ${items.length})`} onClose={() => setViewIdx(null)} wide>
          <div className="viewer-nav">
            <button disabled={viewIdx === 0} onClick={() => setViewIdx((viewIdx ?? 0) - 1)}>◀ Previous</button>
            <span>{(viewIdx ?? 0) + 1} / {items.length}</span>
            <button disabled={viewIdx === items.length - 1} onClick={() => setViewIdx((viewIdx ?? 0) + 1)}>Next ▶</button>
          </div>
          {cur.mime_type === "application/pdf" ? (
            <iframe className="viewer" src={cur.content_url} title={cur.original_filename} />
          ) : (
            <img className="viewer-img" src={cur.content_url} alt={cur.original_filename} />
          )}
        </Modal>
      ) : null}
    </section>
  );
}

// ------------------------------------------------------------------ attachments chosen before saving (v1.3, CR-010)
export const ATTACH_ACCEPT = ".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png";

export function attachmentProblem(f: File): string | null {
  if (!/\.(pdf|jpe?g|png)$/i.test(f.name)) return `${f.name}: only PDF, JPG and PNG files are accepted.`;
  if (f.size > 5 * 1024 * 1024) return `${f.name}: attachments may not exceed 5 MB per file.`;
  if (f.size === 0) return `${f.name}: the file is empty.`;
  return null;
}

/** Files queued in a form; they are uploaded right after the record is saved. */
export function PendingFiles({ label, files, onChange }: { label: string; files: File[]; onChange: (f: File[]) => void }) {
  const [err, setErr] = useState<string | null>(null);
  const add = (list: FileList | null) => {
    const picked = Array.from(list || []);
    const bad = picked.map(attachmentProblem).filter(Boolean) as string[];
    setErr(bad.length ? bad.join(" ") : null);
    onChange([...files, ...picked.filter((f) => !attachmentProblem(f))]);
  };
  return (
    <div className="pending-files">
      <label className="upload">
        <span>{label} (PDF, JPG, PNG; max 5 MB each)</span>
        <input type="file" multiple accept={ATTACH_ACCEPT} aria-label={label} onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
      </label>
      {err ? <p className="warn-text" role="alert">{err}</p> : null}
      {files.length ? (
        <ul className="att-list">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              {f.name} <span className="muted">{(f.size / 1024).toFixed(1)} KB · uploads when saved</span>{" "}
              <button type="button" className="small" aria-label={`Remove ${f.name}`} onClick={() => onChange(files.filter((_, j) => j !== i))}>Remove</button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** v1.3 CR-009: "<Entity> - <Budget>" label for a split allocation (entity falls back to the transaction's). */
export function allocationLabel(t: any, a: any) {
  const ent = a.entity?.display_name || (t.entity && !t.entity.is_system ? t.entity.display_name : "");
  return ent ? `${ent} - ${a.budget.label}` : a.budget.label;
}

// ------------------------------------------------------------------ searchable entity picker (v1.2, CR-006)
/** Accessible combobox: type to filter entities by name or Entity Number; arrow keys + Enter to choose. */
export function EntityPicker({ label, entities, value, onChange, placeholder = "Type to search…", extraOption }: {
  label: string;
  entities: any[];
  value: string;
  onChange: (id: string) => void;
  placeholder?: string;
  extraOption?: { id: string; label: string } | null;
}) {
  const all = extraOption && !entities.some((e) => String(e.id) === extraOption.id)
    ? [...entities, { id: extraOption.id, display_name: extraOption.label, entity_number: "" }] : entities;
  // 2.2.0 (#316): Individuals follow the user's name order; searching also finds the other names
  const nm = (e: any) => entityName(e);
  const selected = all.find((e) => String(e.id) === value);
  const counts: Record<string, number> = {};
  all.forEach((e) => (counts[nm(e)] = (counts[nm(e)] || 0) + 1));
  const text = (e: any) => (counts[nm(e)] > 1 && e.entity_number ? `${nm(e)} (${e.entity_number})` : nm(e));
  const [query, setQuery] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const id = useRef(`ep-${Math.random().toString(36).slice(2)}`).current;
  const q = (query ?? "").trim().toLowerCase();
  const matches = all.filter((e) => !q || nm(e).toLowerCase().includes(q) || (e.display_name || "").toLowerCase().includes(q)
    || (e.name || "").toLowerCase().includes(q) || (e.entity_number || "").toLowerCase().includes(q)).slice(0, 50);
  const choose = (e: any | null) => {
    onChange(e ? String(e.id) : "");
    setQuery(null);
    setOpen(false);
  };
  const onKey = (ev: React.KeyboardEvent) => {
    if (ev.key === "ArrowDown") { ev.preventDefault(); setOpen(true); setActive((a) => Math.min(a + 1, matches.length)); }
    else if (ev.key === "ArrowUp") { ev.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (ev.key === "Enter" && open) { ev.preventDefault(); choose(active === 0 ? null : matches[active - 1]); }
    else if (ev.key === "Escape") { setOpen(false); setQuery(null); }
  };
  return (
    <div className="field entity-picker">
      <label className="field-inner" htmlFor={id}>
        <span className="field-label">{label}</span>
      </label>
      <input id={id} role="combobox" aria-expanded={open} aria-controls={`${id}-list`} aria-autocomplete="list"
             autoComplete="off" placeholder={placeholder}
             value={query ?? (selected ? text(selected) : "")}
             onChange={(e) => { setQuery(e.target.value); setOpen(true); setActive(1); }}
             onFocus={(e) => { setOpen(true); e.target.select(); }}
             onBlur={() => setTimeout(() => { setOpen(false); setQuery(null); }, 150)}
             onKeyDown={onKey} />
      {open ? (
        <ul className="picker-list" role="listbox" id={`${id}-list`}>
          <li role="option" aria-selected={active === 0} className={active === 0 ? "active" : ""}
              onMouseDown={(e) => { e.preventDefault(); choose(null); }}>— none —</li>
          {matches.map((e, i) => (
            <li key={e.id} role="option" aria-selected={active === i + 1} className={active === i + 1 ? "active" : ""}
                onMouseDown={(ev) => { ev.preventDefault(); choose(e); }}>
              {nm(e)} <span className="muted">{e.entity_number}</span>
            </li>
          ))}
          {matches.length === 0 ? <li className="muted" aria-disabled="true">No matching entities</li> : null}
        </ul>
      ) : null}
    </div>
  );
}

function utcText(iso: string): string {
  return iso.replace("T", " ").replace("Z", " UTC");
}

/** v1.4 CR-022: version + build details (no network details). */
export function BuildDetails({ info }: { info: { version: string; mode?: string; build?: Record<string, string> | null; license?: string; source_url?: string } }) {
  const b = info.build;
  return (
    <dl className="dl" data-testid="build-details">
      <dt>Version</dt><dd data-testid="app-version">{info.version}</dd>
      {b ? (
        <>
          <dt>Build</dt>
          <dd>{[b.branch ? `${b.branch} build` : "Build", b.run ? `#${b.run}` : null].filter(Boolean).join(" ")}{b.commit ? ` (${b.commit})` : ""}</dd>
          {b.built_at ? (
            <>
              <dt>Built</dt>
              {/* #185: the machine's local time (the computer in local mode, the server in server mode); UTC on hover */}
              <dd data-testid="built-at" title={`${utcText(b.built_at)}`}>{b.built_at_local || utcText(b.built_at)}</dd>
            </>
          ) : null}
        </>
      ) : (
        <><dt>Build</dt><dd>Development build</dd></>
      )}
      {info.mode ? <><dt>Mode</dt><dd>{info.mode === "server" ? "Server" : "Local"}</dd></> : null}
      {info.license ? <><dt>License</dt><dd data-testid="app-license"><LegalLinks license={info.license} sourceUrl={info.source_url} /></dd></> : null}
    </dl>
  );
}

/** v1.4 CR-019: Remaining amount; income received above budget shows as a green "+$X above budget". */
export function Remaining({ x }: { x: { remaining: string; above_budget?: string | null } }) {
  if (x.above_budget) return <span className="above">+{money(x.above_budget)} above budget</span>;
  return <span className={Number(x.remaining) < 0 ? "neg" : ""}>{money(x.remaining)}</span>;
}

/** v1.5.0: AGPL-3.0 - free software; the source code of this build is offered to every user (AGPL section 13). */
export function LegalLinks({ license, sourceUrl }: { license: string; sourceUrl?: string }) {
  return (
    <span className="legal-links">
      Free software under the {license.replace(/-only$/, "")} license ·{" "}
      {sourceUrl ? <><a href={sourceUrl} target="_blank" rel="noopener noreferrer">Source code</a> · </> : null}
      <a href="/api/system/legal/license" target="_blank" rel="noopener">License</a> ·{" "}
      <a href="/api/system/legal/notices" target="_blank" rel="noopener">Third-party notices</a>
    </span>
  );
}

/** 2.0.0 build 11 (#215, docs/ui-standards.md): a table row's actions. **Edit** stays a visible button next to it (the
 * caller renders it); every other action is an item of this menu, opened from a real <button> marked ⋯ ("Actions for
 * <row>"). Keyboard: Enter/Space or ↓ opens it on the first item, ↑ on the last; ↑/↓/Home/End move; Enter/Space
 * choose; Escape or Tab closes it, and the focus goes back to the button. Destructive items (danger) go last, after a
 * divider, and keep their own confirmations. The menu is drawn fixed to the viewport so a scrolling table can't clip
 * it; it follows its button when the page scrolls and closes when the button scrolls out of view. */
export type RowAction = { label: string; onClick: () => void; danger?: boolean; disabled?: boolean; title?: string };

let rowMenuSeq = 0;

export function RowMenu({ name, actions }: { name: string; actions: (RowAction | null | false | undefined)[] }) {
  const items = [...actions.filter((a): a is RowAction => !!a)].sort((a, b) => Number(!!a.danger) - Number(!!b.danger));
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ top: number; right: number; up: boolean }>({ top: 0, right: 0, up: false });
  const btn = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLUListElement>(null);
  const [id] = useState(() => `row-menu-${++rowMenuSeq}`);
  const focusItem = (i: number) => {
    const els = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not([aria-disabled=true])") || []);
    if (!els.length) return;
    els[(i + els.length) % els.length].focus();
  };
  const place = () => {
    const r = btn.current?.getBoundingClientRect();
    if (!r) return false;
    const up = r.bottom + 40 + items.length * 34 > window.innerHeight && r.top > window.innerHeight / 2;
    setPos({ top: up ? r.top : r.bottom, right: Math.max(8, window.innerWidth - r.right), up });
    return r.bottom > 0 && r.top < window.innerHeight;
  };
  const show = (first: "first" | "last") => {
    place();
    setOpen(true);
    requestAnimationFrame(() => focusItem(first === "first" ? 0 : -1));
  };
  const close = (refocus = true) => { setOpen(false); if (refocus) btn.current?.focus(); };
  useEffect(() => {
    if (!open) return;
    const away = (e: Event) => {
      const t = e.target as Node;
      if (!menu.current?.contains(t) && !btn.current?.contains(t)) setOpen(false);
    };
    // scrolling or resizing moves the menu with its button; it closes once the button leaves the window
    const gone = (e: Event) => { if (!menu.current?.contains(e.target as Node) && !place()) setOpen(false); };
    document.addEventListener("mousedown", away);
    window.addEventListener("scroll", gone, true);
    window.addEventListener("resize", gone);
    return () => { document.removeEventListener("mousedown", away); window.removeEventListener("scroll", gone, true); window.removeEventListener("resize", gone); };
  }, [open]);
  if (!items.length) return null;
  const onMenuKey = (e: React.KeyboardEvent) => {
    const els = Array.from(menu.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not([aria-disabled=true])") || []);
    const i = els.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown") { e.preventDefault(); focusItem(i + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); focusItem(i - 1); }
    else if (e.key === "Home") { e.preventDefault(); focusItem(0); }
    else if (e.key === "End") { e.preventDefault(); focusItem(-1); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }   // not the dialog around it
    else if (e.key === "Tab") { close(false); }
  };
  const label = `Actions for ${name}`;
  return (
    <>
      <button ref={btn} type="button" className="small row-menu-btn" aria-label={label} title={label} aria-haspopup="menu"
              aria-expanded={open} aria-controls={open ? id : undefined}
              onClick={() => (open ? close() : show("first"))}
              onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); show("first"); } else if (e.key === "ArrowUp") { e.preventDefault(); show("last"); } }}>
        <span aria-hidden="true">⋯</span>
      </button>
      {open ? createPortal(
        <ul ref={menu} id={id} role="menu" aria-label={label} className="row-menu" onKeyDown={onMenuKey}
            style={pos.up ? { bottom: window.innerHeight - pos.top + 2, right: pos.right } : { top: pos.top + 2, right: pos.right }}>
          {items.map((a, i) => (
            <li key={a.label} role="none" className={a.danger && i > 0 && !items[i - 1].danger ? "divider" : undefined}>
              <button type="button" role="menuitem" tabIndex={-1} className={`menu-item${a.danger ? " danger" : ""}`} title={a.title}
                      aria-disabled={a.disabled || undefined}
                      onClick={() => { if (a.disabled) return; close(); a.onClick(); }}>{a.label}</button>
            </li>
          ))}
        </ul>, document.body) : null}
    </>
  );
}
