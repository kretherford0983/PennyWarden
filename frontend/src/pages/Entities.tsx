import { useEffect, useState, type FormEvent } from "react";
import { api, qs } from "../api";
import { ErrorBox, Field, Loading, Modal, useConfirmable, GuardedForm, RowMenu } from "../components";
import { useMe } from "../App";
import { entityName, entitySortKey } from "../names";

const MAILING = ["mailing_address_line1", "mailing_address_line2", "mailing_city", "mailing_state_region", "mailing_postal_code", "mailing_country"];
// 2.2.0 (#315, #316): first and last name; the display name and mailing address are kept only when "same as" is unticked
const EMPTY: Record<string, any> = { entity_type: "ORGANIZATION", organization_name: "", first_name: "", last_name: "", position: "", address_line1: "", address_line2: "", city: "",
  state_region: "", postal_code: "", country: "", phone: "", email: "", notes: "", is_financial_institution: false,
  display_name_custom: "", ein: "", ...Object.fromEntries(MAILING.map((k) => [k, ""])) };

export default function Entities() {
  const { can } = useMe();
  const [list, setList] = useState<any[] | null>(null);
  const [filter, setFilter] = useState({ search: "", status: "active", fi: "" });
  const [edit, setEdit] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const load = () => api.get(`/api/entities${qs({ search: filter.search, status: filter.status, financial_institution: filter.fi })}`).then(setList, setErr);
  useEffect(() => { load(); }, [filter]);
  const manage = can("entity.manage");
  const canFi = can("entity.manage_financial_institution");
  const setActive = async (e: any, active: boolean) => {
    setErr(null);
    try { await api.post(`/api/entities/${e.id}/${active ? "restore" : "inactivate"}`, {}); load(); } catch (x) { setErr(x); }
  };
  return (
    <div>
      <div className="page-head">
        <h1>Entities</h1>
        {manage ? <button className="primary" onClick={() => setEdit({ ...EMPTY })}>New entity</button> : null}
      </div>
      <div className="filters">
        <Field label="Search"><input value={filter.search} onChange={(e) => setFilter({ ...filter, search: e.target.value })} placeholder="Name, number or email" /></Field>
        <Field label="Status"><select value={filter.status} onChange={(e) => setFilter({ ...filter, status: e.target.value })}><option value="active">Active</option><option value="inactive">Inactive</option><option value="all">All</option></select></Field>
        <Field label="Financial Institution"><select value={filter.fi} onChange={(e) => setFilter({ ...filter, fi: e.target.value })}><option value="">Any</option><option value="true">Financial Institutions</option><option value="false">Other entities</option></select></Field>
      </div>
      <ErrorBox error={err} />
      {!list ? <Loading /> : (
        <table className="table">
          <thead><tr><th>Entity #</th><th>Name</th><th>Type</th><th>Contact</th><th>Financial Institution</th><th>Status</th>{manage ? <th /> : null}</tr></thead>
          <tbody>
            {list.length === 0 ? <tr><td colSpan={7} className="muted">No entities.</td></tr> : null}
            {[...list].sort((a, b) => entitySortKey(a).localeCompare(entitySortKey(b))).map((e) => {
              const locked = e.is_financial_institution && !canFi;
              return (
                <tr key={e.id} className={e.active ? "" : "inactive"}>
                  <td>{e.entity_number}</td><td>{entityName(e)}{e.display_name !== e.name && e.name ? <span className="muted"> ({e.name})</span> : null}{e.is_organization ? <> <span className="badge green" data-testid="org-badge">Your organization</span></> : null}</td><td>{e.entity_type === "INDIVIDUAL" ? "Individual" : "Organization"}</td>
                  <td>{[e.email, e.phone_display || e.phone, e.city].filter(Boolean).join(" · ")}</td>
                  <td>{e.is_financial_institution ? "Yes" : "No"}</td><td>{e.active ? "Active" : "Inactive"}</td>
                  {manage ? (
                    <td className="actions-cell">
                      {e.is_organization ? <span className="muted" title="An Administrator changes it in System/About → Organization">System/About</span>
                        : locked ? <span className="muted" title="Only a Budget Manager can maintain Financial Institutions">Budget Manager only</span> : (
                        <>
                          <button className="small" onClick={() => setEdit(e)}>Edit</button>
                          <RowMenu name={e.display_name} actions={[
                            e.active ? { label: "Inactivate", onClick: () => setActive(e, false), danger: true } : { label: "Restore", onClick: () => setActive(e, true) },
                          ]} />
                        </>
                      )}
                    </td>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {can("entity.review_names") ? <NamesToReview onEdit={setEdit} reloadKey={list} /> : null}
      {edit ? <EntityForm entity={edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} /> : null}
    </div>
  );
}

/** 1.6.7: shows a 10-digit number as (nnn) nnn-nnnn as soon as the field is left; the server decides what is stored. */
export function formatPhone(typed: string): string {
  const m = typed.trim().match(/^(.*?)(?:\s*(?:ext\.?|x|#)\s*(\d{1,8}))?$/i);
  if (!m || /[^0-9+().\-\s]/.test(m[1])) return typed;
  let d = m[1].replace(/\D/g, "");
  if (d.length === 11 && d[0] === "1") d = d.slice(1);
  else if (m[1].trim().startsWith("+")) return typed;
  if (d.length !== 10) return typed;
  return `(${d.slice(0, 3)}) ${d.slice(3, 6)}-${d.slice(6)}${m[2] ? ` x${m[2]}` : ""}`;
}

export function EntityForm({ entity, onClose, onSaved, forceFi }: { entity: any; onClose: () => void; onSaved: (e: any) => void; forceFi?: boolean }) {
  const isNew = !entity.id;
  const [f, setF] = useState<any>({ ...EMPTY, ...Object.fromEntries(Object.entries(entity).map(([k, v]) => [k, v ?? (k in EMPTY ? EMPTY[k] : v)])),
    phone: entity.phone_display || entity.phone || "", ...(forceFi ? { is_financial_institution: true } : {}) });
  const [dnSame, setDnSame] = useState<boolean>(entity.display_name_same !== false);
  const [mailSame, setMailSame] = useState<boolean>(entity.mailing_same !== false);
  const [err, setErr] = useState<unknown>(null);
  const { run, dialog } = useConfirmable();
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const submit = async (ev: FormEvent) => {
    ev.preventDefault();
    setErr(null);
    const body: any = {};
    Object.keys(EMPTY).forEach((k) => { body[k] = typeof f[k] === "string" ? (f[k].trim() || null) : f[k]; });
    if (body.entity_type !== "INDIVIDUAL") body.position = null;   // 1.6.7: a position belongs to a person
    if (body.entity_type !== "ORGANIZATION") body.ein = null;
    if (dnSame) body.display_name_custom = null;                    // "same as": nothing extra is kept (#315)
    if (mailSame) MAILING.forEach((k) => { body[k] = null; });
    try {
      const saved = await run((confirmations) => isNew ? api.post("/api/entities", { ...body, confirmations }) : api.patch(`/api/entities/${entity.id}`, { ...body, confirmations }));
      if (saved) onSaved(saved);
    } catch (x) { setErr(x); }
  };
  return (
    <Modal title={isNew ? "New entity" : `Edit ${entity.entity_number}`} onClose={onClose} wide>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        <Field label="Type">
          <select value={f.entity_type} onChange={set("entity_type")}><option value="ORGANIZATION">Organization</option><option value="INDIVIDUAL">Individual</option></select>
        </Field>
        <div className="row">
          <Field label={`Organization Name${f.entity_type === "ORGANIZATION" ? " (required)" : ""}`}><input required={f.entity_type === "ORGANIZATION"} maxLength={200} value={f.organization_name || ""} onChange={set("organization_name")} /></Field>
        </div>
        {/* 2.2.0 (#316): the person - or an organization's contact person - as first and last name */}
        <div className="row">
          <Field label={f.entity_type === "INDIVIDUAL" ? "First name (required)" : "Contact first name"}><input required={f.entity_type === "INDIVIDUAL"} maxLength={100} value={f.first_name || ""} onChange={set("first_name")} /></Field>
          <Field label={f.entity_type === "INDIVIDUAL" ? "Last name" : "Contact last name"}><input maxLength={100} value={f.last_name || ""} onChange={set("last_name")} /></Field>
        </div>
        {/* 2.2.0 (#315): the name prints on checks, envelopes, letters and receipts; the display name shows everywhere else */}
        <label className="check"><input type="checkbox" checked={dnSame} onChange={(e) => setDnSame(e.target.checked)} /> Display name same as Name</label>
        {!dnSame ? <Field label="Display name" hint="Shown in the register, pickers, lists and reports. Checks, envelopes, letters and receipts print the name.">
          <input maxLength={200} value={f.display_name_custom || ""} onChange={set("display_name_custom")} /></Field> : null}
        {f.entity_type === "ORGANIZATION" ? <Field label="EIN (optional)" hint="Written as 12-3456789."><input maxLength={12} value={f.ein || ""} onChange={set("ein")} /></Field> : null}
        {f.entity_type === "INDIVIDUAL" ? (
          <Field label="Position in the organization (optional)" hint="Filled in as this person's title when they are chosen as a signer on the audit review signature page or the cash count sheet.">
            <input maxLength={60} value={f.position || ""} placeholder="e.g. Treasurer" onChange={set("position")} />
          </Field>
        ) : null}
        {/* 1.7.1 (#51): aligned at the top - the hint under Phone no longer pushes Email down; shorter hint */}
        <div className="row top">
          <Field label="Email"><input type="email" value={f.email || ""} onChange={set("email")} /></Field>
          <Field label="Phone" hint="Any format, e.g. 555-123-4567. Shown as (555) 123-4567.">
            <input type="tel" maxLength={40} value={f.phone || ""} onChange={set("phone")} onBlur={() => setF((p: any) => ({ ...p, phone: formatPhone(p.phone || "") }))} />
          </Field>
        </div>
        <Field label="Address line 1"><input value={f.address_line1 || ""} onChange={set("address_line1")} /></Field>
        <Field label="Address line 2"><input value={f.address_line2 || ""} onChange={set("address_line2")} /></Field>
        <div className="row">
          <Field label="City"><input value={f.city || ""} onChange={set("city")} /></Field>
          <Field label="State/Region"><input value={f.state_region || ""} onChange={set("state_region")} /></Field>
          <Field label="Postal code"><input value={f.postal_code || ""} onChange={set("postal_code")} /></Field>
          <Field label="Country"><input value={f.country || ""} onChange={set("country")} /></Field>
        </div>
        <label className="check"><input type="checkbox" checked={mailSame} onChange={(e) => setMailSame(e.target.checked)} /> Mailing address same as Address</label>
        {!mailSame ? (
          <fieldset className="plain" aria-label="Mailing address">
            <p className="hint">Letters, envelopes and receipts are mailed here (for example a P.O. Box).</p>
            <Field label="Mailing address line 1"><input value={f.mailing_address_line1 || ""} onChange={set("mailing_address_line1")} /></Field>
            <Field label="Mailing address line 2"><input value={f.mailing_address_line2 || ""} onChange={set("mailing_address_line2")} /></Field>
            <div className="row">
              <Field label="Mailing city"><input value={f.mailing_city || ""} onChange={set("mailing_city")} /></Field>
              <Field label="Mailing state/region"><input value={f.mailing_state_region || ""} onChange={set("mailing_state_region")} /></Field>
              <Field label="Mailing postal code"><input value={f.mailing_postal_code || ""} onChange={set("mailing_postal_code")} /></Field>
              <Field label="Mailing country"><input value={f.mailing_country || ""} onChange={set("mailing_country")} /></Field>
            </div>
          </fieldset>
        ) : null}
        <Field label="Notes"><textarea value={f.notes || ""} onChange={set("notes")} /></Field>
        <label className="check"><input type="checkbox" disabled={forceFi} checked={!!f.is_financial_institution} onChange={set("is_financial_institution")} /> Financial Institution</label>
        {f.is_financial_institution ? <p className="hint">Once saved, only a Budget Manager may edit or inactivate a Financial Institution.</p> : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
      {dialog}
    </Modal>
  );
}


/** 2.2.0 (#316): the names the upgrade split into first and last name, for a Budget Manager to check ("Mary Ann
 * Smith" or "John Smith Jr." may need fixing). Each stays here until it is edited or confirmed. */
function NamesToReview({ onEdit, reloadKey }: { onEdit: (e: any) => void; reloadKey: unknown }) {
  const [list, setList] = useState<any[] | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const load = () => api.get("/api/entities/names-to-review").then(setList, setErr);
  useEffect(() => { load(); }, [reloadKey]);
  if (!list || !list.length) return err ? <ErrorBox error={err} /> : null;
  const confirm = async (e: any) => { setErr(null); try { await api.post(`/api/entities/${e.id}/confirm-name`, {}); load(); } catch (x) { setErr(x); } };
  return (
    <section className="card" aria-labelledby="names-review-h" data-testid="names-to-review">
      <h2 id="names-review-h">Names to review ({list.length})</h2>
      <p className="hint">The upgrade split each Primary Contact into a first and a last name at the first space. Check these; Edit to fix one, or Confirm when it is right.</p>
      <ErrorBox error={err} />
      <table className="table compact">
        <thead><tr><th>Entity #</th><th>Entity</th><th>First name</th><th>Last name</th><th /></tr></thead>
        <tbody>
          {list.map((e) => (
            <tr key={e.id}>
              <td>{e.entity_number}</td><td>{e.display_name}</td><td>{e.first_name}</td><td>{e.last_name || <span className="muted">—</span>}</td>
              <td className="actions-cell"><button className="small" onClick={() => onEdit(e)}>Edit</button> <button className="small" onClick={() => confirm(e)}>Confirm</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
