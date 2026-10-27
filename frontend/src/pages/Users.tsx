import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorBox, Field, Loading, Modal, GuardedForm, RowMenu } from "../components";
import { useMe } from "../App";
import { PasswordChecklist } from "../PasswordChecklist";

const ROLES: Record<string, [string, string][]> = {
  ADMINISTRATOR: [["ADMINISTRATOR", "Administrator"]],
  FINANCIAL: [["BUDGET_MANAGER", "Budget Manager"], ["BUDGET_USER", "Budget User"], ["REGISTER_USER", "Register User"],
              ["BUDGET_ADMIN", "Budget Admin (with Budget Manager: may delete budgets of a Fiscal Year that is not approved)"],
              ["REGISTER_ADMIN", "Register Admin (with Register User: may delete uncleared transactions)"]],
  AUDITOR: [["AUDITOR", "Auditor"]],
};

export default function Users() {
  const { me, can } = useMe();
  const [mode, setMode] = useState<string>("local");
  const [users, setUsers] = useState<any[] | null>(null);
  const [edit, setEdit] = useState<any | null>(null);
  const [reset, setReset] = useState<any | null>(null);
  const [mfaReset, setMfaReset] = useState<any | null>(null);
  const [qReset, setQReset] = useState<any | null>(null); // 1.8.0 (#113)
  const [err, setErr] = useState<unknown>(null);
  const [q, setQ] = useState("");                       // 2.0.0 (#134): search
  const [byName, setByName] = useState(false);          // sort by last name, then first name
  const load = () => api.get("/api/users").then(setUsers, setErr);
  useEffect(() => {
    load();
    api.get("/api/system/status").then((s) => setMode(s.mode), () => undefined);
  }, []);
  if (!users) return <><ErrorBox error={err} /><Loading /></>;
  const manage = can("users.manage");
  const needle = q.trim().toLowerCase();
  const shown = users
    .filter((u) => !needle || [u.first_name, u.last_name, u.username, u.display_name, u.email].some((v) => (v || "").toLowerCase().includes(needle)))
    .sort((a, b) => (byName ? `${a.last_name || "\uffff"} ${a.first_name || ""}`.localeCompare(`${b.last_name || "\uffff"} ${b.first_name || ""}`, undefined, { sensitivity: "base" }) : 0));
  return (
    <div>
      <div className="page-head">
        <h1>Users</h1>
        {manage ? <button className="primary" onClick={() => setEdit({})}>New user</button> : null}
      </div>
      <ErrorBox error={err} />
      <div className="row form-row">
        <Field label="Search users"><input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, username or email" /></Field>
        <label className="check"><input type="checkbox" checked={byName} onChange={(e) => setByName(e.target.checked)} /> Sort by last name</label>
      </div>
      <table className="table">
        <thead><tr><th>Last name</th><th>First name</th><th>Username</th><th>Display name</th><th>Email</th><th>Security domain</th><th>Roles</th><th>Status</th><th>Two-step</th><th>Security questions</th>{manage ? <th /> : null}</tr></thead>
        <tbody>
          {shown.map((u) => (
            <tr key={u.id}>
              <td>{u.last_name || (u.name_needed ? <span className="badge red" title="An Administrator must enter this account's first and last name">name needed</span> : null)}</td>
              <td>{u.first_name}</td>
              <td>{u.username}</td><td>{u.display_name}</td><td>{u.email}</td><td>{u.security_domain}{u.security_domain === "COMBINED" && mode === "server" ? <div className="badge red" title="Combined roles are for local installs. Choose roles of one security domain.">Local-only roles</div> : null}</td><td>{u.roles.join(", ")}</td>
              <td>
                {u.active ? "Active" : "Disabled"}
                {u.locked_until ? <div className="badge red" title="Too many failed attempts">Locked until {new Date(u.locked_until).toLocaleString()}</div> : null}
                {u.failed_attempts ? <div className="muted small-text">{u.failed_attempts} failed attempt{u.failed_attempts === 1 ? "" : "s"} in a row</div> : null}
              </td>
              <td>{u.mfa_enabled ? <span className="badge green">On</span> : <span className="badge grey">Not set up</span>}</td>
              <td>{u.security_questions_set ? <span className="badge green">Set</span> : <span className="badge grey">At next sign-in</span>}</td>
              {manage ? (
                <td className="actions-cell">
                  <button className="small" onClick={() => setEdit(u)}>Edit</button>
                  <RowMenu name={u.username} actions={[
                    { label: "Reset password", onClick: () => setReset(u) },
                    u.mfa_enabled && { label: "Reset two-step", onClick: () => setMfaReset(u) },
                    u.security_questions_set && { label: "Reset security questions", onClick: () => setQReset(u) },
                  ]} />
                </td>
              ) : null}
            </tr>
          ))}
        </tbody>
      </table>
      {edit ? <UserForm user={edit} local={mode === "local"} ownRolesLocked={mode === "server" && edit.id === me.id} isSelf={edit.id === me.id} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); load(); }} /> : null}
      {reset ? <ResetForm user={reset} onClose={() => setReset(null)} /> : null}
      {mfaReset ? <MfaResetForm user={mfaReset} onClose={() => { setMfaReset(null); load(); }} /> : null}
      {qReset ? <QuestionsResetForm user={qReset} onClose={() => { setQReset(null); load(); }} /> : null}
    </div>
  );
}

// 1.9.0 (#54): on a local install roles of every domain can be combined; the domain follows from the roles
const ROLE_DOMAIN: Record<string, string> = Object.fromEntries(Object.entries(ROLES).flatMap(([d, rs]) => rs.map(([c]) => [c, d])));
export function domainOf(roles: string[]): string {
  const ds = Array.from(new Set(roles.map((r) => ROLE_DOMAIN[r]).filter(Boolean)));
  return ds.length === 1 ? ds[0] : ds.length ? "COMBINED" : "FINANCIAL";
}

function UserForm({ user, ownRolesLocked = false, isSelf = false, local = false, onClose, onSaved }: { user: any; ownRolesLocked?: boolean; isSelf?: boolean; local?: boolean; onClose: () => void; onSaved: () => void }) {
  const isNew = !user.id;
  const [f, setF] = useState({
    username: user.username || "", email: user.email || "", display_name: user.display_name || "", password: "",
    first_name: user.first_name || "", last_name: user.last_name || "",
    security_domain: user.security_domain || "FINANCIAL", roles: (user.roles || []) as string[], active: user.active ?? true,
  });
  const [err, setErr] = useState<unknown>(null);
  const toggle = (r: string) => {
    const roles = f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r];
    setF({ ...f, roles, security_domain: local ? domainOf(roles) : f.security_domain });
  };
  const setDomain = (d: string) => setF({ ...f, security_domain: d, roles: d === "FINANCIAL" ? [] : [ROLES[d][0][0]] });
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      if (isNew) {
        await api.post("/api/users", { username: f.username, email: f.email, display_name: f.display_name, password: f.password,
          first_name: f.first_name, last_name: f.last_name,
          security_domain: f.security_domain, roles: f.roles });
      } else {
        await api.patch(`/api/users/${user.id}`, { email: f.email, display_name: f.display_name,
          first_name: f.first_name, last_name: f.last_name,
          security_domain: f.security_domain, roles: f.roles, active: f.active });
      }
      onSaved();
    } catch (x) {
      setErr(x);
    }
  };
  return (
    <Modal title={isNew ? "New user" : `Edit ${user.label || user.username}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {isNew ? <Field label="Username"><input required value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></Field> : null}
        <div className="row fields">
          <Field label="First name"><input required maxLength={60} value={f.first_name} onChange={(e) => setF({ ...f, first_name: e.target.value })} /></Field>
          <Field label="Last name"><input required maxLength={60} value={f.last_name} onChange={(e) => setF({ ...f, last_name: e.target.value })} /></Field>
        </div>
        <Field label="Email"><input required type="email" value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Display name" hint="The name shown in the top bar for this user. At least 3 characters."><input value={f.display_name} onChange={(e) => setF({ ...f, display_name: e.target.value })} /></Field>
        {isNew ? <Field label="Initial password"><input required type="password" autoComplete="new-password" aria-describedby="pw-req-newuser" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></Field> : null}
        {isNew ? <PasswordChecklist id="pw-req-newuser" password={f.password} context={{ username: f.username }} /> : null /* 2.2.0 (#343) */}
        {/* 1.7.2 (#55): in server mode an Administrator cannot change their own roles (also refused by the server) */}
        {ownRolesLocked ? <p className="hint" id="own-roles-hint">You cannot change your own security domain or roles. Another Administrator can change them for you.</p> : null}
        {local ? (
          <fieldset aria-describedby="local-roles-hint">
            <legend>Roles</legend>
            <p className="hint" id="local-roles-hint">On a local install one person can hold roles of every security domain.</p>
            {Object.entries(ROLES).map(([d, rs]) => (
              <div key={d} className="role-group">
                <b>{d === "ADMINISTRATOR" ? "Administration" : d === "FINANCIAL" ? "Financial" : "Audit"}</b>
                {rs.map(([code, name]) => (
                  <label key={code} className="check"><input type="checkbox" checked={f.roles.includes(code)} onChange={() => toggle(code)} /> {name}</label>
                ))}
              </div>
            ))}
          </fieldset>
        ) : <>
        <fieldset disabled={ownRolesLocked} aria-describedby={ownRolesLocked ? "own-roles-hint" : undefined}>
          <legend>Security domain (exactly one)</legend>
          {Object.keys(ROLES).map((d) => (
            <label key={d} className="check"><input type="radio" name="domain" checked={f.security_domain === d} onChange={() => setDomain(d)} /> {d}</label>
          ))}
        </fieldset>
        {f.security_domain === "FINANCIAL" ? (
          <fieldset disabled={ownRolesLocked}>
            <legend>Financial roles</legend>
            {ROLES.FINANCIAL.map(([code, name]) => (
              <label key={code} className="check"><input type="checkbox" checked={f.roles.includes(code)} onChange={() => toggle(code)} /> {name}</label>
            ))}
          </fieldset>
        ) : null}
        </>}
        {!isNew ? (
          <>
            {/* 1.7.2 (#55 follow-up): your own account cannot be disabled by you (also refused by the server) */}
            <label className="check"><input type="checkbox" checked={f.active} disabled={isSelf} aria-describedby={isSelf ? "own-active-hint" : undefined}
              onChange={(e) => setF({ ...f, active: e.target.checked })} /> Active</label>
            {isSelf ? <p className="hint" id="own-active-hint">You cannot disable your own account.</p> : null}
          </>
        ) : null}
        <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Save</button></div>
      </GuardedForm>
    </Modal>
  );
}

function ResetForm({ user, onClose }: { user: any; onClose: () => void }) {
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post(`/api/users/${user.id}/reset-password`, { new_password: pw });
      setDone(true);
    } catch (x) {
      setErr(x);
    }
  };
  return (
    <Modal title={`Reset password for ${user.username}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {done ? <div className="alert ok">Password reset. The user's sessions were signed out.</div> : (
          <>
            <Field label="New password"><input type="password" required autoComplete="new-password" aria-describedby="pw-req-reset" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
            <PasswordChecklist id="pw-req-reset" password={pw} context={{ username: user.username }} />
            <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Reset</button></div>
          </>
        )}
      </GuardedForm>
    </Modal>
  );
}

// v1.4.1 CR-018: the user sets two-step verification up again at the next sign-in.
function MfaResetForm({ user, onClose }: { user: any; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const [compromised, setCompromised] = useState(false);   // 2.2.0 (#327)
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post(`/api/users/${user.id}/reset-mfa`, { reason, compromised });
      setDone(true);
    } catch (x) {
      setErr(x);
    }
  };
  return (
    <Modal title={`Reset two-step verification for ${user.username}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {done ? <><div className="alert ok" role="status">Two-step verification was reset. {user.username} was signed out and will set it up again at the next sign-in.</div><div className="actions"><button type="button" className="primary" onClick={onClose}>Done</button></div></> : (
          <>
            <p>Use this when {user.username} has lost both the authenticator app and the recovery codes. Their authenticator, recovery codes and trusted browsers are removed and they are signed out everywhere.</p>
            <Field label="Reason (required)"><input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Lost phone" /></Field>
            {/* 2.2.0 (#327): after a possible compromise the user can't set up again with a key they already have */}
            <label className="check"><input type="checkbox" checked={compromised} onChange={(e) => setCompromised(e.target.checked)} aria-describedby="mfa-compromise-hint" /> Possible compromise</label>
            <p className="hint" id="mfa-compromise-hint">Tick this if the authenticator key may have been exposed (a stolen phone, a security problem). {user.username} then has to set up with a newly generated key; otherwise they may keep the key already in their authenticator app.</p>
            <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Reset two-step verification</button></div>
          </>
        )}
      </GuardedForm>
    </Modal>
  );
}

// 1.8.0 (#113): the user chooses new security questions at the next sign-in.
function QuestionsResetForm({ user, onClose }: { user: any; onClose: () => void }) {
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.post(`/api/users/${user.id}/reset-security-questions`, { reason });
      setDone(true);
    } catch (x) {
      setErr(x);
    }
  };
  return (
    <Modal title={`Reset security questions for ${user.username}`} onClose={onClose}>
      <GuardedForm onSubmit={submit}>
        <ErrorBox error={err} />
        {done ? <><div className="alert ok" role="status">The security questions were reset. {user.username} will choose new ones at the next sign-in.</div><div className="actions"><button type="button" className="primary" onClick={onClose}>Done</button></div></> : (
          <>
            <p>Use this when {user.username} no longer remembers the answers. Their questions and answers are removed; they choose new ones at the next sign-in. Until then, <i>Forgot password?</i> does not work for them.</p>
            <Field label="Reason (required)"><input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Forgot the answers" /></Field>
            <div className="actions"><button type="button" onClick={onClose}>Cancel</button><button className="primary" type="submit">Reset security questions</button></div>
          </>
        )}
      </GuardedForm>
    </Modal>
  );
}
