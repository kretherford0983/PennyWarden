// 1.8.0 (#113): forgotten password - security questions (sign-in step and My account), the Forgot password flow on
// the sign-in page, the new-password step after the host `reset-password`, and the notices.
import { useEffect, useState, type FormEvent } from "react";
import { api, preAuthCsrf, setCsrf } from "../api";
import { ErrorBox, Field, GuardedForm, Loading } from "../components";
import { PasswordChecklist } from "../PasswordChecklist";

type Q = { code: string; text: string };
type Choice = { question: string; answer: string };
const EMPTY: Choice[] = [{ question: "", answer: "" }, { question: "", answer: "" }, { question: "", answer: "" }];

function useCatalog() {
  const [cat, setCat] = useState<Q[] | null>(null);
  useEffect(() => { api.get("/api/auth/security-questions").then(setCat, () => setCat([])); }, []);
  return cat;
}

/** Three different questions from the list, each with an answer. */
export function QuestionPicker({ value, onChange }: { value: Choice[]; onChange: (v: Choice[]) => void }) {
  const cat = useCatalog();
  if (!cat) return <Loading />;
  const set = (i: number, p: Partial<Choice>) => onChange(value.map((c, j) => (j === i ? { ...c, ...p } : c)));
  return (
    <div className="question-picker">
      {value.map((c, i) => (
        <fieldset key={i} className="question-row">
          <legend>Question {i + 1}</legend>
          <Field label={`Security question ${i + 1}`}>
            <select required value={c.question} onChange={(e) => set(i, { question: e.target.value })}>
              <option value="">Choose a question…</option>
              {cat.map((q) => (
                <option key={q.code} value={q.code} disabled={value.some((o, j) => j !== i && o.question === q.code)}>{q.text}</option>
              ))}
            </select>
          </Field>
          <Field label={`Answer ${i + 1}`}>
            <input required autoComplete="off" maxLength={200} value={c.answer} onChange={(e) => set(i, { answer: e.target.value })} />
          </Field>
        </fieldset>
      ))}
      <p className="hint">Upper and lower case, spaces and punctuation do not matter. Answers are stored like passwords:
        nobody can read them, not even an Administrator.</p>
    </div>
  );
}

const ready = (v: Choice[]) => v.every((c) => c.question && c.answer.trim()) && new Set(v.map((c) => c.question)).size === 3;

/** Sign-in step: the security questions (first sign-in, after the upgrade, or after an Administrator's reset). */
export function QuestionsStep({ onDone }: { onDone: () => void }) {
  const [v, setV] = useState<Choice[]>(EMPTY);
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const me = await api.post("/api/auth/setup/security-questions", { questions: v });
      setCsrf(me.csrf_token);
      onDone();
    } catch (x) { setErr(x); }
  };
  return (
    <GuardedForm onSubmit={submit}>
      <h1>Choose your security questions</h1>
      <p>If you forget your password, you can set a new one on the sign-in page with <b>Forgot password?</b> by answering
        one of these questions. Choose questions whose answers you will remember and that others cannot easily find out.</p>
      <ErrorBox error={err} />
      <QuestionPicker value={v} onChange={setV} />
      <button className="primary" type="submit" disabled={!ready(v)}>Save and continue</button>
    </GuardedForm>
  );
}

/** Sign-in step after the host `reset-password`: the temporary password is replaced first. */
export function NewPasswordStep({ onDone, username }: { onDone: () => void; username?: string }) {
  const [f, setF] = useState({ new_password: "", new_password_confirmation: "" });
  const [err, setErr] = useState<unknown>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      const me = await api.post("/api/auth/setup/password", f);
      setCsrf(me.csrf_token);
      onDone();
    } catch (x) { setErr(x); }
  };
  return (
    <GuardedForm onSubmit={submit}>
      <h1>Choose a new password</h1>
      <p>You signed in with a temporary password. Choose your own password to continue.</p>
      <ErrorBox error={err} />
      <Field label="New password"><input type="password" required autoComplete="new-password" aria-describedby="pw-req-temp" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
      <Field label="Confirm new password"><input type="password" required autoComplete="new-password" value={f.new_password_confirmation} onChange={(e) => setF({ ...f, new_password_confirmation: e.target.value })} /></Field>
      {/* 2.2.0 (#343): "different from the temporary password" can only be checked by the server, on save */}
      <PasswordChecklist id="pw-req-temp" password={f.new_password}
        context={{ username, confirm: f.new_password_confirmation, temporary: true }} />
      <button className="primary" type="submit">Save and continue</button>
    </GuardedForm>
  );
}

/** Sign-in page: Forgot password? */
export function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [username, setUsername] = useState("");
  const [q, setQ] = useState<{ question: Q; needs_code: boolean } | null>(null);
  const [f, setF] = useState({ answer: "", code: "", new_password: "", new_password_confirmation: "" });
  const [err, setErr] = useState<unknown>(null);
  const [done, setDone] = useState(false);
  const start = async (e?: FormEvent) => {
    e?.preventDefault();
    setErr(null);
    try {
      await preAuthCsrf();
      setQ(await api.post("/api/auth/forgot/start", { username }));
    } catch (x) { setErr(x); }
  };
  const complete = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await preAuthCsrf();
      await api.post("/api/auth/forgot/complete", { username, answer: f.answer, code: q?.needs_code ? f.code : null,
        new_password: f.new_password, new_password_confirmation: f.new_password_confirmation });
      setDone(true);
    } catch (x: any) {
      setErr(x);
      if (x?.status === 400 || x?.status === 409) {   // a new question after a failed attempt
        setF({ ...f, answer: "", code: "" });
        setQ(null);
      }
    }
  };
  if (done) {
    return (
      <div className="card auth-card">
        <h1>Password changed</h1>
        <div className="alert ok" role="status">Your password was changed. You were signed out everywhere; sign in with the new password.</div>
        <button className="primary" type="button" onClick={onBack}>Back to sign in</button>
      </div>
    );
  }
  return (
    <div className="card auth-card">
      <h1>Forgot password</h1>
      <ErrorBox error={err} />
      {!q ? (
        <GuardedForm onSubmit={start}>
          <p>Enter your username. You will be asked one of your security questions.</p>
          <Field label="Username"><input required autoComplete="username" maxLength={64} value={username} onChange={(e) => setUsername(e.target.value)} /></Field>
          <button className="primary" type="submit">Continue</button>
        </GuardedForm>
      ) : (
        <GuardedForm onSubmit={complete}>
          <p className="security-question" data-testid="security-question"><b>{q.question.text}</b></p>
          <Field label="Your answer"><input required autoComplete="off" maxLength={200} value={f.answer} onChange={(e) => setF({ ...f, answer: e.target.value })} /></Field>
          {q.needs_code ? (
            <Field label="Authenticator code or recovery code" hint="The 6-digit code from your authenticator app, or one of your recovery codes (it is used up).">
              <input required autoComplete="one-time-code" maxLength={20} value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} />
            </Field>
          ) : null}
          <Field label="New password"><input type="password" required autoComplete="new-password" aria-describedby="pw-req-forgot" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></Field>
          <Field label="Confirm new password"><input type="password" required autoComplete="new-password" value={f.new_password_confirmation} onChange={(e) => setF({ ...f, new_password_confirmation: e.target.value })} /></Field>
          <PasswordChecklist id="pw-req-forgot" password={f.new_password}
            context={{ username, confirm: f.new_password_confirmation }} />
          <button className="primary" type="submit">Set new password</button>
        </GuardedForm>
      )}
      <p className="hint">Forgot the answers too? Ask an Administrator to reset your password.</p>
      <button type="button" className="linklike" onClick={onBack}>Back to sign in</button>
    </div>
  );
}

/** My account: the questions chosen, and changing them (current password needed). */
export function SecurityQuestionsSection() {
  const [mine, setMine] = useState<any>(null);
  const [edit, setEdit] = useState(false);
  const [v, setV] = useState<Choice[]>(EMPTY);
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [ok, setOk] = useState(false);
  useEffect(() => { api.get("/api/me/security-questions").then(setMine, setErr); }, []);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      setMine(await api.put("/api/me/security-questions", { current_password: pw, questions: v }));
      setEdit(false); setPw(""); setV(EMPTY); setOk(true);
    } catch (x) { setErr(x); }
  };
  return (
    <section className="card" aria-labelledby="sq-h">
      <h2 id="sq-h">Security questions</h2>
      <p className="hint">Used by <b>Forgot password?</b> on the sign-in page.</p>
      {ok ? <div className="alert ok" role="status">Your security questions were changed.</div> : null}
      {!edit ? <ErrorBox error={err} /> : null}
      {mine ? (
        <ol data-testid="my-questions">{mine.questions.map((q: any) => <li key={q.slot}>{q.text}</li>)}</ol>
      ) : null}
      {!edit ? <button type="button" onClick={() => { setEdit(true); setOk(false); }}>Change security questions</button> : (
        <GuardedForm onSubmit={submit}>
          <ErrorBox error={err} />
          <QuestionPicker value={v} onChange={setV} />
          <Field label="Current password"><input type="password" required autoComplete="current-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
          <div className="actions left">
            <button className="primary" type="submit" disabled={!ready(v)}>Save questions</button>
            <button type="button" onClick={() => { setEdit(false); setErr(null); }}>Cancel</button>
          </div>
        </GuardedForm>
      )}
    </section>
  );
}

/** Shown once after signing in: a self-service reset, or failed attempts on the account. */
export function SignInNotices({ notices, onDismissed }: { notices: { kind: string; message: string }[]; onDismissed: () => void }) {
  if (!notices?.length) return null;
  const dismiss = async () => {
    try { await api.post("/api/me/sign-in-notices/dismiss"); } finally { onDismissed(); }
  };
  return (
    <div className="alert warn banner" role="alert" data-testid="sign-in-notices">
      {notices.map((n) => <p key={n.kind}>{n.message}</p>)}
      <button type="button" className="small" onClick={dismiss}>OK</button>
    </div>
  );
}

/** Administrators: accounts locked for an hour or more, disabled after failed attempts, self-service resets. */
export function AdminSecurityNotices({ path }: { path: string }) {
  const [list, setList] = useState<any[]>([]);
  useEffect(() => { api.get("/api/security-notices").then(setList, () => setList([])); }, [path]);
  if (!list.length) return null;
  return (
    <div className="alert warn banner" role="alert" data-testid="security-notices">
      <b>Security notices</b>
      <ul>
        {list.map((n) => (
          <li key={n.id}>{n.message}{" "}
            <button type="button" className="small" onClick={() => api.post(`/api/security-notices/${n.id}/dismiss`).then(setList, () => undefined)}>Dismiss</button>
          </li>
        ))}
      </ul>
    </div>
  );
}
