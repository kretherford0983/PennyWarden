// v1.4.1 CR-018: two-step verification — sign-in step, setup (QR code + copyable key), recovery codes, and the
// Security section of My Account.
import { useEffect, useState, type FormEvent } from "react";
import { api, setCsrf } from "../api";
import { ErrorBox, Field, GuardedForm, Loading } from "../components";
import type { Me } from "../App";
import { NewPasswordStep, QuestionsStep } from "./Recovery";

/** Full-screen step shown after the password was accepted and before the application opens. */
export function MfaGate({ me, workspace, onDone, onLogout }: { me: Me; workspace: string; onDone: () => void; onLogout: () => void }) {
  const signOut = async () => {
    try { await api.post("/api/auth/logout"); } catch { /* the session may already be gone */ }
    onLogout();
  };
  return (
    <div className="center">
      <div className="card auth-card mfa-card">
        <p className="muted">{workspace}</p>
        {me.mfa_pending === "QUESTIONS" ? <QuestionsStep onDone={onDone} /> /* 1.8.0 (#113) */
        : me.mfa_pending === "PASSWORD" ? <NewPasswordStep onDone={onDone} username={me.username} />
        : me.mfa_pending === "ENROLL" ? (
          <>
            <h1>Set up two-step verification</h1>
            <p>This server requires a second step at sign-in. Set up an authenticator app (for example Microsoft Authenticator, Google Authenticator, 1Password or Authy) to continue.</p>
            <Enrollment onFinished={onDone} />
          </>
        ) : (
          <>
            <h1>Two-step verification</h1>
            <VerifyForm onDone={onDone} />
          </>
        )}
        <p className="hint">Signed in as <b>{me.username}</b>. <button type="button" className="linklike" onClick={signOut}>Sign out</button></p>
      </div>
    </div>
  );
}

function VerifyForm({ onDone }: { onDone: () => void }) {
  const [code, setCode] = useState("");
  const [recovery, setRecovery] = useState(false);
  const [trust, setTrust] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const me = await api.post("/api/auth/mfa/verify", { code, trust_browser: trust });
      setCsrf(me.csrf_token);
      onDone();
    } catch (x) {
      setErr(x);
      setCode("");
    }
  };
  return (
    <GuardedForm onSubmit={submit}>
      <ErrorBox error={err} />
      {recovery ? (
        <Field label="Recovery code" hint="One of the codes you saved when you set up two-step verification (XXXX-XXXX-XXXX). Each code works once.">
          <input required autoComplete="off" autoFocus maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} />
        </Field>
      ) : (
        <Field label="Authentication code" hint="The 6-digit code shown in your authenticator app.">
          <input required inputMode="numeric" autoComplete="one-time-code" autoFocus pattern="[0-9 ]{6,7}" maxLength={7} value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))} />
        </Field>
      )}
      <label className="check"><input type="checkbox" checked={trust} onChange={(e) => setTrust(e.target.checked)} /> Trust this browser for 30 days</label>
      <p className="hint">Only on a computer you alone use. You can remove trusted browsers under My account → Two-step verification.</p>
      <button className="primary" type="submit">Verify</button>
      <p><button type="button" className="linklike" onClick={() => { setRecovery(!recovery); setCode(""); setErr(null); }}>
        {recovery ? "Use the authenticator app instead" : "Lost your phone? Use a recovery code"}
      </button></p>
    </GuardedForm>
  );
}

/** Setup / change of authenticator. `currentCode` is required by the server when replacing an existing one. */
export function Enrollment({ currentCode, onFinished, onCancel }: { currentCode?: string; onFinished: () => void; onCancel?: () => void }) {
  const [setup, setSetup] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [copied, setCopied] = useState(false);
  // 2.2.0 (#327): the user's own key (Base32 or an otpauth://totp link) instead of the generated one
  const [ownKey, setOwnKey] = useState("");
  const [own, setOwn] = useState<any>(null);
  const [ownErr, setOwnErr] = useState<unknown>(null);
  useEffect(() => {
    api.post("/api/auth/mfa/enroll/start", { current_code: currentCode || null }).then(setSetup, setErr);
  }, [currentCode]);
  const useOwnKey = async () => {
    setOwnErr(null);
    try {
      setOwn(await api.post("/api/auth/mfa/enroll/own-key", { own_key: ownKey }));
      setOwnKey("");   // the key is not kept on the page once the server has it
      setCode("");
    } catch (x) { setOwnErr(x); }
  };
  const useGenerated = async () => {
    setOwnErr(null);
    try {
      setSetup(await api.post("/api/auth/mfa/enroll/own-key", { own_key: null }));
      setOwn(null);
      setCode("");
    } catch (x) { setOwnErr(x); }
  };
  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const r = await api.post("/api/auth/mfa/enroll/confirm", { code });
      setCsrf(r.me.csrf_token);
      setCodes(r.recovery_codes);
    } catch (x) {
      setErr(x);
      setCode("");
    }
  };
  if (codes) return <RecoveryCodes codes={codes} onContinue={onFinished} />;
  if (!setup) return err ? <><ErrorBox error={err} />{onCancel ? <button type="button" onClick={onCancel}>Back</button> : null}</> : <Loading />;
  const copyKey = async () => {
    try { await navigator.clipboard.writeText(setup.secret.replace(/ /g, "")); setCopied(true); } catch { setCopied(false); }
  };
  const ownKeyBox = setup.own_key_allowed === false ? (
    <div className="alert warn own-key" data-testid="own-key-blocked">
      <b>Use my own key instead</b> is not available: your two-step verification was reset after a possible security
      problem, so set it up with the new key above.
    </div>
  ) : (
    <details className="own-key">
      <summary>Use my own key instead</summary>
      <p className="hint">
        Already have PennyWarden in your authenticator app (for example after your two-step verification was reset)?
        Enter the key from that entry, or paste an <code>otpauth://totp/…</code> link exported from the app, and keep
        using it. <b>Reuse a key only if it was never exposed; after any security problem use the new key above.</b>
      </p>
      <ErrorBox error={ownErr} />
      <Field label="Your authenticator key or otpauth link">
        <input autoComplete="off" spellCheck={false} maxLength={2000} value={ownKey} onChange={(e) => setOwnKey(e.target.value)} />
      </Field>
      <button type="button" disabled={!ownKey.trim()} onClick={useOwnKey}>Use this key</button>
    </details>
  );
  const confirmStep = (
    <li>
      <b>Enter the 6-digit code</b> the app now shows{own ? " for that entry" : ""}.
      <GuardedForm onSubmit={confirm}>
        <ErrorBox error={err} />
        <Field label="Code from the app">
          <input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,7}" maxLength={7} value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9 ]/g, ""))} />
        </Field>
        <div className="actions left">
          <button className="primary" type="submit">Turn on two-step verification</button>
          {onCancel ? <button type="button" onClick={onCancel}>Cancel</button> : null}
        </div>
      </GuardedForm>
    </li>
  );
  if (own)
    return (
      <div className="mfa-setup">
        <ol className="steps">
          <li>
            <b>Using your own key.</b> Nothing is saved until the code below matches it.
            {own.short_key ? <p className="hint" data-testid="own-key-short">Your key is {own.key_length} characters, shorter than PennyWarden's own keys ({own.own_key_length} characters). It works, but a longer key is stronger.</p> : null}
            <ErrorBox error={ownErr} />
            <p><button type="button" className="small" onClick={useGenerated}>Use a new generated key instead</button></p>
          </li>
          {confirmStep}
        </ol>
      </div>
    );
  return (
    <div className="mfa-setup">
      <ol className="steps">
        <li>
          <b>Scan this QR code</b> with your authenticator app.
          <div className="qr"><img src={setup.qr_svg} alt="QR code for your authenticator app" width={220} height={220} /></div>
        </li>
        <li>
          <b>Can't scan it?</b> Add an account manually and enter this key (time-based):
          <div className="secret-row">
            <code className="secret" data-testid="mfa-secret">{setup.secret}</code>
            <button type="button" className="small" onClick={copyKey}>{copied ? "Copied" : "Copy key"}</button>
          </div>
          <p className="hint">Account: {setup.account} · Issuer: {setup.issuer}</p>
          {ownKeyBox}
        </li>
        {confirmStep}
      </ol>
    </div>
  );
}

function RecoveryCodes({ codes, onContinue }: { codes: string[]; onContinue: () => void }) {
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const text = `PennyWarden recovery codes (each works once)\n\n${codes.join("\n")}\n`;
  const copy = async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setCopied(false); }
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "pennywarden-recovery-codes.txt";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return (
    <div className="recovery">
      <div className="alert ok" role="status">Two-step verification is on.</div>
      <h2>Save your recovery codes</h2>
      <p>If you lose your phone, each of these codes lets you sign in <b>once</b>. Store them somewhere safe (a password manager or printed copy). <b>They will not be shown again</b> — to get new codes you must set up two-step verification again.</p>
      <ul className="codes" aria-label="Recovery codes">{codes.map((c) => <li key={c}><code>{c}</code></li>)}</ul>
      <div className="row">
        <button type="button" onClick={copy}>{copied ? "Copied" : "Copy codes"}</button>
        <button type="button" onClick={download}>Download as text file</button>
        <button type="button" onClick={() => window.print()}>Print</button>
      </div>
      <label className="check"><input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} /> I have saved my recovery codes</label>
      <div className="actions left"><button className="primary" disabled={!saved} onClick={onContinue}>Continue</button></div>
    </div>
  );
}

/** My Account → Two-step verification. */
export function SecuritySection() {
  const [st, setSt] = useState<any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [mode, setMode] = useState<"view" | "setup" | "change-code" | "change" | "disable">("view");
  const [code, setCode] = useState("");
  const [current, setCurrent] = useState("");
  const load = () => api.get("/api/me/mfa").then(setSt, setErr);
  useEffect(() => { load(); }, []);
  if (!st) return <section className="card"><h2>Two-step verification</h2><ErrorBox error={err} /><Loading /></section>;
  const done = () => { setMode("view"); setCode(""); setCurrent(""); load(); };
  const revoke = async (id?: number) => {
    try { setSt(await api.post(id ? `/api/me/mfa/trusted-browsers/${id}/revoke` : "/api/me/mfa/trusted-browsers/revoke-all")); } catch (x) { setErr(x); }
  };
  const disable = async (e: FormEvent) => {
    e.preventDefault();
    try { setSt(await api.post("/api/me/mfa/disable", { code })); done(); } catch (x) { setErr(x); }
  };
  const d = (v: string | null) => (v ? new Date(v).toLocaleString() : "—");
  return (
    <section className="card" aria-labelledby="mfa-h">
      <h2 id="mfa-h">Two-step verification</h2>
      <ErrorBox error={err} />
      {mode === "setup" ? <Enrollment onFinished={done} onCancel={done} /> : null}
      {mode === "change" ? <Enrollment currentCode={current} onFinished={done} onCancel={done} /> : null}
      {mode === "change-code" ? (
        <GuardedForm onSubmit={(e) => { e.preventDefault(); setMode("change"); }}>
          <p>To change your authenticator app, first confirm with a current code from the app you use now — or a recovery code if you no longer have it.</p>
          <Field label="Current code or recovery code"><input required autoComplete="off" maxLength={20} value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>
          <div className="actions left"><button className="primary" type="submit">Continue</button><button type="button" onClick={done}>Cancel</button></div>
        </GuardedForm>
      ) : null}
      {mode === "disable" ? (
        <GuardedForm onSubmit={disable}>
          <Field label="Current code or recovery code"><input required autoComplete="off" maxLength={20} value={code} onChange={(e) => setCode(e.target.value)} /></Field>
          <div className="actions left"><button className="primary" type="submit">Turn off</button><button type="button" onClick={done}>Cancel</button></div>
        </GuardedForm>
      ) : null}
      {mode === "view" ? (
        st.enabled ? (
          <>
            <p><span className="badge green">On</span> since {d(st.enabled_at)} · {st.recovery_codes_remaining} of 10 recovery codes unused</p>
            {st.recovery_codes_remaining <= 3 ? <div className="alert warn">Only {st.recovery_codes_remaining} recovery code(s) left. Use <b>Change authenticator</b> to get a new set.</div> : null}
            <div className="row">
              <button type="button" onClick={() => setMode("change-code")}>Change authenticator</button>
              {!st.required ? <button type="button" onClick={() => setMode("disable")}>Turn off</button> : null}
            </div>
            <p className="hint">Changing the authenticator also issues new recovery codes (the old ones stop working) and signs out trusted browsers.</p>
            <h3>Trusted browsers</h3>
            {st.trusted_browsers.length ? (
              <>
                <table className="table compact">
                  <thead><tr><th>Browser</th><th>Trusted since</th><th>Last used</th><th>Expires</th><th /></tr></thead>
                  <tbody>{st.trusted_browsers.map((b: any) => (
                    <tr key={b.id}><td className="ua">{b.label || "Unknown browser"}</td><td>{d(b.created_at)}</td><td>{d(b.last_used_at)}</td><td>{d(b.expires_at)}</td>
                      <td><button type="button" className="small" onClick={() => revoke(b.id)}>Remove</button></td></tr>
                  ))}</tbody>
                </table>
                <button type="button" className="small" onClick={() => revoke()}>Remove all</button>
              </>
            ) : <p className="muted">None. Tick "Trust this browser for 30 days" at sign-in to skip the code on a computer you alone use.</p>}
          </>
        ) : (
          <>
            <p><span className="badge grey">Off</span> {st.required ? "This server requires two-step verification; you will be asked to set it up at the next sign-in." : "Add a second step to your sign-in with an authenticator app (recommended)."}</p>
            <button type="button" className="primary" onClick={() => setMode("setup")}>Set up two-step verification</button>
          </>
        )
      ) : null}
    </section>
  );
}
