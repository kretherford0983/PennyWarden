// Same-origin API client. Authentication is an HttpOnly server-side session cookie; the CSRF token is kept
// only in memory (never in localStorage/sessionStorage) and sent as X-CSRF-Token on state-changing requests.

let csrfToken: string | null = null;

/** v1.5.0: the server names the page build it serves. If this tab runs an older build (the server was upgraded while
 * the page was open), reload once so the current code is used. The `_b` query marker prevents a reload loop. */
const OWN_BUILD = (() => {
  try {
    return new URL(import.meta.url).pathname.split("/").pop() || "";
  } catch {
    return "";
  }
})();
let reloading = false;
function checkFrontendBuild(server: string | null) {
  if (!server || !OWN_BUILD.endsWith(".js") || reloading) return;
  const u = new URL(window.location.href);
  if (server === OWN_BUILD) {
    if (u.searchParams.has("_b")) {  // up to date again: drop the marker
      u.searchParams.delete("_b");
      window.history.replaceState(window.history.state, "", u.pathname + u.search + u.hash);
    }
    return;
  }
  if (u.searchParams.get("_b") === server) return; // already reloaded once for this build - never loop
  reloading = true;
  u.searchParams.set("_b", server);
  window.location.replace(u.toString());
}

export function getCsrf(): string | null {
  return csrfToken;
}

// HF-001 (1.5.0): a pre-auth token fetched while signed out must never overwrite a session token that was set
// meanwhile (a slow /api/auth/csrf answer used to replace the session token right after sign-in -> 403 CSRF_FAILED).
let csrfGen = 0;

export function setCsrf(token: string | null) {
  csrfGen += 1;
  csrfToken = token;
}

export interface ApiWarning {
  code: string;
  message: string;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  status: number;
  code: string;
  body: any;
  constructor(status: number, body: any) {
    super(body?.error?.message || `Request failed (${status})`);
    this.status = status;
    this.code = body?.error?.code || "ERROR";
    this.body = body?.error || {};
  }
  get warnings(): ApiWarning[] {
    return this.body?.warnings || [];
  }
  get fieldErrors(): { field: string | null; message: string }[] {
    return this.body?.errors || [];
  }
}

async function request<T>(method: string, url: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (method !== "GET" && csrfToken) headers["X-CSRF-Token"] = csrfToken;
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    if (isForm) payload = body as FormData;
    else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }
  const res = await fetch(url, { method, headers, body: payload, credentials: "same-origin" });
  checkFrontendBuild(res.headers.get("X-Frontend-Build"));
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = new ApiError(res.status, data);
    // build 13: maintenance mode came on while this page was open - the screens hide their change actions
    if (res.status === 503 && data?.error?.code === "MAINTENANCE") window.dispatchEvent(new CustomEvent("pw:maintenance-changed"));
    if (res.status === 401 && !url.startsWith("/api/auth/login")) {
      // v1.5.0: MFA_REQUIRED means "signed in, second step outstanding" - the app shows the two-step screen
      window.dispatchEvent(new CustomEvent("fm:unauthenticated", { detail: { code: data?.error?.code } }));
    }
    throw err;
  }
  return data as T;
}

/** 1.8.0 (#106): a POST that returns a file (e.g. a PDF made from a reviewed form); errors are thrown like api.post. */
async function requestBlob(url: string, body: unknown): Promise<Blob> {
  const headers: Record<string, string> = { Accept: "application/pdf, application/json", "Content-Type": "application/json" };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  const res = await fetch(url, { method: "POST", headers, body: JSON.stringify(body), credentials: "same-origin" });
  checkFrontendBuild(res.headers.get("X-Frontend-Build"));
  if (!res.ok) {
    let data: any = null;
    try { data = await res.json(); } catch { data = null; }
    if (res.status === 401) window.dispatchEvent(new CustomEvent("fm:unauthenticated", { detail: { code: data?.error?.code } }));
    throw new ApiError(res.status, data);
  }
  return res.blob();
}

export const api = {
  postBlob: (url: string, body: unknown) => requestBlob(url, body),
  get: <T = any>(url: string) => request<T>("GET", url),
  post: <T = any>(url: string, body?: unknown) => request<T>("POST", url, body ?? {}),
  patch: <T = any>(url: string, body?: unknown) => request<T>("PATCH", url, body ?? {}),
  put: <T = any>(url: string, body?: unknown) => request<T>("PUT", url, body ?? {}),
  delete: <T = any>(url: string) => request<T>("DELETE", url),
  postForm: <T = any>(url: string, fd: FormData) => request<T>("POST", url, fd, true), // 2.0.0 (#159)
  upload: <T = any>(url: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return request<T>("POST", url, fd, true);
  },
};

// 1.6.8 (#68): never two of these requests at once. The sign-in page asks when it opens and again when Sign in is
// pressed; two overlapping requests (neither carrying the cookie yet) each got their own token, the browser kept one
// as the cookie, the page sent the other -> 403 "Missing or invalid CSRF token." A caller that arrives while a
// request is under way waits for that one; a later request carries the cookie and gets the same token back.
let preAuthInFlight: Promise<void> | null = null;

export function preAuthCsrf(): Promise<void> {
  if (!preAuthInFlight) {
    const gen = csrfGen;
    preAuthInFlight = api
      .get<{ csrf_token: string }>("/api/auth/csrf")
      .then((r) => {
        if (gen === csrfGen) setCsrf(r.csrf_token); // someone set a (session) token meanwhile: keep it
      })
      .finally(() => {
        preAuthInFlight = null;
      });
  }
  return preAuthInFlight;
}

export function qs(params: Record<string, string | number | boolean | null | undefined>) {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function money(v: string | null | undefined) {
  if (v === null || v === undefined) return "";
  const n = Number(v);
  const neg = n < 0;
  const [i, d] = Math.abs(n).toFixed(2).split(".");
  return `${neg ? "-" : ""}$${i.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${d}`;
}

export function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** v1.3 CR-011: one-time key for a create form (works on plain-HTTP LAN addresses, unlike crypto.randomUUID). */
export function newRequestKey() {
  const b = new Uint8Array(16);
  crypto.getRandomValues(b);
  return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
}
