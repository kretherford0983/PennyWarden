import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, preAuthCsrf } from "../api";
import { ErrorBox, Field, GuardedForm, LegalLinks } from "../components";
import { ForgotPassword } from "./Recovery";

import { MaintenanceNotice } from "./Maintenance";
import { TestingBanner } from "./Testing";
import { DemoBanner } from "./Demo";

export default function Login({ workspace, onLogin, legal }: { workspace: string; onLogin: () => void; legal?: { license?: string; source_url?: string; maintenance_mode?: any; testing_mode?: boolean; demo?: boolean } }) {
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const pwRef = useRef<HTMLInputElement>(null);
  const [refused, setRefused] = useState(0);   // 2.2.0 (#343): count of refused sign-ins, to refocus the password
  useEffect(() => {
    // after the form is enabled again (GuardedForm disables it while signing in)
    if (refused) { const t = setTimeout(() => pwRef.current?.focus(), 0); return () => clearTimeout(t); }
  }, [refused]);
  const [forgot, setForgot] = useState(false); // 1.8.0 (#113)
  // 2.0.0 (#130): the maintenance message, read fresh (the app's status may be older than this sign-in page)
  const [maint, setMaint] = useState<any>(legal?.maintenance_mode || null);
  useEffect(() => {
    preAuthCsrf();
    api.get("/api/system/status").then((st) => setMaint(st.maintenance_mode || null), () => undefined);
  }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await preAuthCsrf();
      await api.post("/api/auth/login", { username, password });
      setP("");
      onLogin();
    } catch (x) {
      setErr(x);
      // 2.2.0 (#343): a refused sign-in (wrong username or password, or too many attempts) clears the password and puts
      // the cursor back in it; the username is kept. A password field's text can't be read, so there is nothing to fix.
      setP("");
      setRefused((n) => n + 1);
    }
  };
  if (forgot) return <div className="center"><ForgotPassword onBack={() => setForgot(false)} /></div>;
  return (
    <div className="center">
      <GuardedForm className="card auth-card" onSubmit={submit}>
        <h1>Sign in</h1>
        <p className="muted">{workspace}</p>
        {/* 2.0.0 (#130): maintenance mode - signing in still works, changes are paused for everyone but Administrators */}
        {maint?.on ? <MaintenanceNotice m={maint} /> : null}
        {legal?.testing_mode ? <TestingBanner /> : null /* 2.2.0 (#231) */}
        {legal?.demo ? <DemoBanner signIn /> : null /* 2.2.0 (#243): Reset demo data works without signing in */}
        <ErrorBox error={err} />
        <Field label="Username"><input required autoComplete="username" value={username} onChange={(e) => setU(e.target.value)} /></Field>
        <Field label="Password"><input ref={pwRef} required type="password" autoComplete="current-password" value={password} onChange={(e) => setP(e.target.value)} /></Field>
        <button className="primary" type="submit">Sign in</button>
        <button type="button" className="linklike forgot-link" onClick={() => { setErr(null); setForgot(true); }}>Forgot password?</button>
      </GuardedForm>
      {legal?.license ? <p className="hint login-legal"><img className="logo" src="/favicon.svg" alt="" width={16} height={16} /> PennyWarden · <LegalLinks license={legal.license} sourceUrl={legal.source_url} /></p> : null}
    </div>
  );
}
