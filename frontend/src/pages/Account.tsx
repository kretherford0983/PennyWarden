import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api";
import { BuildDetails, ErrorBox, Field, GuardedForm } from "../components";
import { ROLE_NAMES, useMe } from "../App";
import { SecuritySection } from "./Mfa";
import { SecurityQuestionsSection } from "./Recovery";
import { UpdateBanner, type UpdateStatus } from "./Updates";
import { PasswordChecklist, PasswordFieldsWithChecklist } from "../PasswordChecklist";

export default function Account({ updates = null }: { updates?: UpdateStatus | null }) {
  const { me, setTheme } = useMe();
  const [f, setF] = useState({ current_password: "", new_password: "", new_password_confirmation: "" });
  const [err, setErr] = useState<unknown>(null);
  const [ok, setOk] = useState(false);
  const [ver, setVer] = useState<any>(null);
  useEffect(() => {
    api.get("/api/system/version").then(setVer).catch(() => setVer(null));
  }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    setOk(false);
    try {
      await api.post("/api/auth/change-password", f);
      setF({ current_password: "", new_password: "", new_password_confirmation: "" });
      setOk(true);
    } catch (x) {
      setErr(x);
    }
  };
  const theme = async (t: "light" | "dark") => {
    await api.put("/api/me/preferences", { theme: t });
    setTheme(t);
  };
  return (
    <div>
      <h1>My account</h1>
      {/* 1.10.0 (#58): on a local install the update banner is shown here only */}
      <UpdateBanner s={updates} />
      <p>Signed in as <b>{me.display_name || me.username}</b></p>
      <dl className="dl" aria-label="Your account">
        <dt>Username</dt><dd>{me.username}</dd>
        <dt>Email</dt><dd>{me.email}</dd>
        <dt>{me.roles.length === 1 ? "Role" : "Roles"}</dt>
        <dd>{me.roles.length ? me.roles.map((r) => ROLE_NAMES[r] || r).join(", ") : "—"}</dd>
      </dl>
      <section className="card">
        <h2>Appearance</h2>
        <div role="radiogroup" aria-label="Theme" className="row">
          <label className="check"><input type="radio" name="theme" checked={me.theme === "light"} onChange={() => theme("light")} /> Light</label>
          <label className="check"><input type="radio" name="theme" checked={me.theme === "dark"} onChange={() => theme("dark")} /> Dark</label>
        </div>
        <p className="hint">Your preference is saved to your account and applies on every sign-in.</p>
      </section>
      <GuardedForm className="card" onSubmit={submit}>
        <h2>Change password</h2>
        <ErrorBox error={err} />
        {ok ? <div className="alert ok" role="status">Password changed. Your other sessions were signed out.</div> : null}
        {/* 2.2.0 (#343): the requirements beside the fields, ticked off while typing; a refused change keeps the fields */}
        <PasswordFieldsWithChecklist checklist={<PasswordChecklist id="pw-req-account" password={f.new_password}
          context={{ username: me.username, current: f.current_password, confirm: f.new_password_confirmation }} />}>
          <Field label="Current password"><input type="password" required autoComplete="current-password" value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></Field>
          <Field label="New password"><input type="password" required autoComplete="new-password" aria-describedby="pw-req-account" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
          <Field label="Confirm new password"><input type="password" required autoComplete="new-password" value={f.new_password_confirmation} onChange={(e) => setF({ ...f, new_password_confirmation: e.target.value })} /></Field>
        </PasswordFieldsWithChecklist>
        <button className="primary" type="submit">Change password</button>
      </GuardedForm>
      <SecuritySection />
      <SecurityQuestionsSection />
      <section className="card" aria-labelledby="about-h">
        <h2 id="about-h">About</h2>
        {ver ? <BuildDetails info={ver} /> : <p className="hint">Loading…</p>}
      </section>
    </div>
  );
}
