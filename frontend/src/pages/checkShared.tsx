/** 2.0.0 (#157, #160, #162): pieces shared by the check setup screen and the print screen - the check preview drawn
 * to scale with the built-in fonts, the pattern input with variable autocomplete, and browser print instructions. */
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type PdfBlob } from "../api";
import { ErrorBox, Modal } from "../components";

export type FontInfo = { key: string; label: string; descent: number; descent_bold: number; cap_height: number };
export type Variable = { name: string; description: string };
export const FIELD_LABELS: Record<string, string> = {
  date: "Date", payee: "Pay to", amount_number: "Amount (number)", amount_words: "Amount (words)", memo: "Memo", signature: "Signature",
  signature2: "Second signature",
};
export const TEXT_FIELDS = ["date", "payee", "amount_number", "amount_words", "memo"];
const CLEAR_ZONE = 0.625;

/** Loads the built-in check fonts once, so the preview draws with exactly the fonts that print. */
const loaded = new Set<string>();
export function useCheckFonts(fonts: FontInfo[] | undefined) {
  const [, setN] = useState(0);
  useEffect(() => {
    if (!fonts || typeof FontFace === "undefined") return;
    for (const f of fonts) {
      for (const w of ["regular", "bold"]) {
        const id = `${f.key}-${w}`;
        if (loaded.has(id)) continue;
        loaded.add(id);
        const ff = new FontFace(`PW-${f.key}`, `url(/api/checks/fonts/${f.key}/${w})`, { weight: w === "bold" ? "700" : "400" });
        ff.load().then((x) => { (document as any).fonts.add(x); setN((n) => n + 1); }, () => undefined);
      }
    }
  }, [fonts]);
}

/** Width in inches of text in one of the built-in fonts (canvas measurement once the font has loaded). */
let ctx2d: CanvasRenderingContext2D | null = null;
export function measure(text: string, family: string, bold: boolean, sizePt: number): number {
  if (!ctx2d) ctx2d = document.createElement("canvas").getContext("2d");
  if (!ctx2d) return (text.length * 0.55 * sizePt) / 72;
  ctx2d.font = `${bold ? 700 : 400} 100px ${family}`;
  return (ctx2d.measureText(text).width / 100) * (sizePt / 72);
}

/** #186: the voucher stubs as the server draws them (sample data): text runs and lines in page inches. */
export type StubDrawing = {
  texts: { x: number; y: number; text: string; font: string; bold: boolean; size: number; anchor: "start" | "end" }[];
  lines: { x1: number; y1: number; x2: number; y2: number; dash: boolean }[];
  top?: number;       // 2.1.0 (#246): the highest stub (a stub can be above the check)
  bottom: number;
};

export type FieldText = { text: string; size: number; fits: boolean; shrunk?: boolean; suggestion?: string | null };

/** The check drawn to scale (inches): the stock outline (pre-printed lines, labels), the clear zone, field boxes and the
 * text as it will print. `highlight` outlines one field. */
export function CheckPreview({ cfg, fonts, texts, highlight, showBoxes = true, signature, signature2, stubs }: {
  cfg: any; fonts: FontInfo[]; texts: Record<string, FieldText> | null; highlight?: string | null; showBoxes?: boolean;
  signature?: string | null; signature2?: string | null; stubs?: StubDrawing | null;
}) {
  const cw = cfg.stock.check_width, ch = cfg.stock.check_height;
  // #186: voucher stubs are drawn in page inches; the check sits at the sheet's first check top, centred across it
  const sx = (cw - (cfg.stock.paper_width ?? cw)) / 2, sy = -(cfg.stock.check_tops?.[0] ?? 0);
  const vx = stubs ? Math.min(0, sx) : 0;
  const vw = stubs ? Math.max(cw, (cfg.stock.paper_width ?? cw)) : cw;
  const vy = stubs ? Math.min(0, (stubs.top ?? 0) + sy) : 0;   // #246: stubs above the check
  const vh = (stubs ? Math.max(ch, stubs.bottom + sy) : ch) - vy;
  const fi = (k: string) => fonts.find((f) => f.key === k) || fonts[0];
  const font = (name: string) => {
    const f = cfg.fields[name];
    return { key: f.font || cfg.defaults.font, size: f.size || cfg.defaults.size, bold: !!f.bold };
  };
  const baseline = (name: string, size: number) => {
    const f = cfg.fields[name];
    const ft = font(name);
    const d = ft.bold ? fi(ft.key).descent_bold : fi(ft.key).descent;
    return f.y + f.h - (d * size) / 72;
  };
  const T = (name: string) => texts?.[name];
  const textEl = (name: string) => {
    const t = T(name);
    if (!t || name === "amount_words") return null;
    const f = cfg.fields[name];
    const ft = font(name);
    const anchor = f.align === "RIGHT" ? "end" : f.align === "CENTER" ? "middle" : "start";
    const x = f.align === "RIGHT" ? f.x + f.w : f.align === "CENTER" ? f.x + f.w / 2 : f.x;
    return (
      <text key={name} x={x} y={baseline(name, t.size)} fontFamily={`PW-${ft.key}`} fontWeight={ft.bold ? 700 : 400}
            fontSize={t.size / 72} textAnchor={anchor} fill={t.fits ? "currentColor" : "var(--red-fg, #b00)"}>{t.text}</text>
    );
  };
  const words = () => {
    const t = T("amount_words");
    if (!t) return null;
    const f = cfg.fields.amount_words;
    const ft = font("amount_words");
    const y = baseline("amount_words", t.size);
    const m = t.text.match(/^(.*) (\S+\/100)( .*)?$/);
    const w = m ? m[1] : t.text, cents = m ? m[2] + (m[3] || "") : "";
    const mid = y - (fi(ft.key).cap_height * t.size) / 72 / 2;
    const family = `PW-${ft.key}`;
    const gap = 0.06;
    const x0 = f.x + measure(w, family, ft.bold, t.size) + gap;
    const x1 = f.x + f.w - measure(cents, family, ft.bold, t.size) - gap;
    const style = cfg.amount_words.fill;
    return (
      <g fill={t.fits ? "currentColor" : "var(--red-fg, #b00)"} fontFamily={family} fontWeight={ft.bold ? 700 : 400} fontSize={t.size / 72}>
        <text x={f.x} y={y}>{w}</text>
        {x1 > x0 ? (
          <line x1={x0} x2={x1} y1={mid} y2={mid} stroke="currentColor" strokeWidth={style === "LINE" ? 0.01 : 0.012}
                strokeLinecap="round" strokeDasharray={style === "LINE" ? undefined : style === "DASHES" ? "0.055 0.02" : "0.001 0.03"} opacity={0.8} />
        ) : null}
        <text x={f.x + f.w} y={y} textAnchor="end">{cents}</text>
      </g>
    );
  };
  const sigs: [any, string][] = [[cfg.fields.signature, signature ?? (cfg.stock.signature_lines === 2 ? "SIGNATURE 1" : "SIGNATURE")]];
  if (cfg.stock.signature_lines === 2 && cfg.fields.signature2) sigs.push([cfg.fields.signature2, signature2 ?? "SIGNATURE 2"]);
  const boxes = [...TEXT_FIELDS, "signature", ...(cfg.stock.signature_lines === 2 && cfg.fields.signature2 ? ["signature2"] : [])];
  return (
    <svg className="check-preview" viewBox={`${vx - 0.05} ${vy - 0.05} ${vw + 0.1} ${vh + 0.1}`} role="img" aria-label="Check preview drawn to scale"
         style={{ width: "100%", maxWidth: 900, display: "block", background: "var(--surface-2, #f7f5ee)" }}>
      <rect x={0} y={0} width={cw} height={ch} fill="none" stroke="currentColor" strokeWidth={0.01} opacity={0.5} />
      <rect x={0} y={ch - CLEAR_ZONE} width={cw} height={CLEAR_ZONE} fill="currentColor" opacity={0.08} />
      <text x={0.12} y={ch - CLEAR_ZONE + 0.14} fontSize={0.09} fontFamily="PW-SANS" opacity={0.6}>BANK NUMBER ZONE – NOTHING PRINTS HERE</text>
      {(cfg.stock.outline || []).map((o: any, i: number) => o.kind === "LINE" ? (
        <line key={i} x1={o.x} y1={o.y} x2={o.x2} y2={o.y2} stroke="currentColor" strokeWidth={0.008} opacity={0.45} />
      ) : o.kind === "BOX" ? (
        <rect key={i} x={o.x} y={o.y} width={o.x2 - o.x} height={o.y2 - o.y} fill="none" stroke="#b8963c" strokeWidth={0.015} opacity={0.6} />
      ) : (
        <text key={i} x={o.x} y={o.y} fontSize={(o.size || 8) / 72} fontFamily="PW-SANS" opacity={0.45}>{o.text}</text>
      ))}
      {showBoxes ? boxes.map((n) => {
        const f = cfg.fields[n];
        const bad = texts?.[n] && !texts[n].fits;
        return <rect key={n} x={f.x} y={f.y} width={f.w} height={f.h} fill={n === highlight ? "rgba(60,120,220,0.12)" : "none"}
                     stroke={bad ? "#c00" : n === highlight ? "#2b6cd4" : "#6a8"} strokeWidth={n === highlight ? 0.015 : 0.008}
                     strokeDasharray="0.03 0.02"><title>{FIELD_LABELS[n]}</title></rect>;
      }) : null}
      {TEXT_FIELDS.map(textEl)}
      {words()}
      {sigs.map(([b, label], i) => (
        <text key={i} x={b.x + b.w / 2} y={b.y + b.h / 2 + 0.04} textAnchor="middle" fontSize={0.1} fontFamily="PW-SANS" fontWeight={700} opacity={0.7}>
          {label}
        </text>
      ))}
      {stubs ? (
        <g data-testid="stub-preview" transform={`translate(${sx} ${sy})`}>
          {stubs.lines.map((l, i) => (
            <line key={i} x1={l.x1} y1={l.y1} x2={l.x2} y2={l.y2} stroke="currentColor" strokeWidth={l.dash ? 0.008 : 0.007}
                  strokeDasharray={l.dash ? "0.055 0.04" : undefined} opacity={l.dash ? 0.45 : 0.8} />
          ))}
          {stubs.texts.map((t, i) => (
            <text key={i} x={t.x} y={t.y} textAnchor={t.anchor} fontFamily={`PW-${t.font}`} fontWeight={t.bold ? 700 : 400}
                  fontSize={t.size / 72} fill="currentColor">{t.text}</text>
          ))}
        </g>
      ) : null}
    </svg>
  );
}

/** Text with {VARIABLES}: autocomplete after "{" (case-insensitive), descriptions shown, Enter/Tab/click inserts. */
const ROLE_GROUPS: Record<string, string> = { ORG: "Organization", PAYEE: "Payee", DONOR: "Donor" };

export function PatternInput({ value, onChange, variables, label, id, placeholder, maxLength = 200, multiline = false, hint = true }: {
  value: string; onChange: (v: string) => void; variables: Variable[]; label: string; id: string; placeholder?: string; maxLength?: number;
  multiline?: boolean; hint?: boolean;
}) {
  const ref = useRef<any>(null);
  const [caret, setCaret] = useState(0);
  const [active, setActive] = useState(0);
  const [focus, setFocus] = useState(false);
  const open = useMemo(() => {
    const before = value.slice(0, caret);
    const i = before.lastIndexOf("{");
    if (i < 0 || before.slice(i).includes("}") || (i > 0 && before[i - 1] === "{")) return null; // "{{" is a literal brace
    const typed = before.slice(i + 1);
    if (!/^([A-Za-z_][A-Za-z0-9_]*\.?)?[A-Za-z0-9_]*$/.test(typed)) return null;   // 2.1.0 (#314): ORG.NAME
    // 2.2.0 (#317): plain names first, then the dotted ones grouped by role ({ORG.*}, {PAYEE.*}, {DONOR.*})
    const group = (n: string) => (n.includes(".") ? n.split(".")[0] : "");
    const list = variables.filter((v) => v.name.startsWith(typed.toUpperCase()))
      .map((v, k) => ({ v, k })).sort((a, b) => (group(a.v.name) === group(b.v.name) ? a.k - b.k
        : group(a.v.name) === "" ? -1 : group(b.v.name) === "" ? 1 : group(a.v.name).localeCompare(group(b.v.name)))).map((x) => x.v);
    return list.length ? { start: i, typed, list } : null;
  }, [value, caret, variables]);
  // The cursor goes right after an inserted variable in the same render that shows the new text (a layout effect),
  // before the next keystroke can arrive - moving it later (e.g. on the next animation frame) let fast typing land
  // in the wrong place.
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    const pos = pendingCaret.current;
    if (pos === null || !ref.current) return;
    pendingCaret.current = null;
    ref.current.setSelectionRange(pos, pos);
    setCaret(pos);
  }, [value]);
  const insert = (name: string) => {
    if (!open) return;
    const after = value.slice(caret);
    const next = value.slice(0, open.start) + `{${name}}` + (after.startsWith("}") ? after.slice(1) : after);
    pendingCaret.current = open.start + name.length + 2;
    onChange(next);
  };
  const onKey = (e: React.KeyboardEvent) => {
    if (!open || !focus) return;
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => (a + 1) % open.list.length); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => (a - 1 + open.list.length) % open.list.length); }
    else if (e.key === "Enter" || e.key === "Tab") { e.preventDefault(); insert(open.list[Math.min(active, open.list.length - 1)].name); }
    else if (e.key === "Escape") setFocus(false);
  };
  return (
    <div className="field pattern-input">
      <label htmlFor={id}>{label}</label>
      <div className="pi-wrap">
      {multiline ? (
        <textarea rows={4} id={id} ref={ref} value={value} maxLength={maxLength} placeholder={placeholder} autoComplete="off" spellCheck={false}
             aria-expanded={!!open && focus} aria-controls={`${id}-list`} aria-autocomplete="list"
             onChange={(e: any) => { onChange(e.target.value); setCaret(e.target.selectionStart || 0); setActive(0); }}
             onKeyUp={(e: any) => setCaret(e.target.selectionStart || 0)}
             onClick={(e: any) => setCaret(e.target.selectionStart || 0)}
             onKeyDown={onKey} onFocus={() => setFocus(true)} onBlur={() => setTimeout(() => setFocus(false), 150)} />
      ) : (
        <input id={id} ref={ref} value={value} maxLength={maxLength} placeholder={placeholder} autoComplete="off" spellCheck={false}
             role="combobox" aria-expanded={!!open && focus} aria-controls={`${id}-list`} aria-autocomplete="list"
             onChange={(e: any) => { onChange(e.target.value); setCaret(e.target.selectionStart || 0); setActive(0); }}
             onKeyUp={(e: any) => setCaret(e.target.selectionStart || 0)}
             onClick={(e: any) => setCaret(e.target.selectionStart || 0)}
             onKeyDown={onKey} onFocus={() => setFocus(true)} onBlur={() => setTimeout(() => setFocus(false), 150)} />
      )}
      {open && focus ? (
        <ul className="autocomplete" id={`${id}-list`} role="listbox">
          {open.list.map((v, i) => {
            const g = v.name.includes(".") ? v.name.split(".")[0] : "";
            const prev = i > 0 && open.list[i - 1].name.includes(".") ? open.list[i - 1].name.split(".")[0] : "";
            return (
              <Fragment key={v.name}>
                {g && g !== prev ? <li role="presentation" className="ac-group muted">{ROLE_GROUPS[g] || g}</li> : null}
                <li role="option" aria-selected={i === active} className={i === active ? "active" : ""}
                    onMouseDown={(e) => { e.preventDefault(); insert(v.name); }}>
                  <code>{`{${v.name}}`}</code> <span className="hint">{v.description}</span>
                </li>
              </Fragment>
            );
          })}
        </ul>
      ) : null}
      </div>
      {hint ? <span className="hint">Text prints as typed; <code>{"{VARIABLE}"}</code> fills in from the transaction (type <code>{"{"}</code> for the list). Use <code>{"{{"}</code> and <code>{"}}"}</code> to print a brace.</span> : null}
    </div>
  );
}

export type Browser = "chromium" | "firefox" | "safari" | "other";
export function detectBrowser(): Browser {
  const ua = navigator.userAgent;
  if (/Firefox\//.test(ua)) return "firefox";
  if (/Edg\/|Chrome\/|Chromium\//.test(ua)) return "chromium";
  if (/Safari\//.test(ua)) return "safari";
  return "other";
}

/** The print settings that matter for the detected browser (#162). */
export function BrowserTips({ singleFeed }: { singleFeed?: boolean }) {
  const b = detectBrowser();
  return (
    <div className="alert info browser-tips" role="note">
      <strong>Print settings</strong>
      {b === "chromium" ? (
        <ul>
          <li>Chrome, Brave or Edge: set <b>Scale</b> to <b>Actual size</b> (or Custom 100) – not "Fit to printable area".</li>
          <li>Check the <b>Paper size</b> the dialog picked{singleFeed ? " and choose the manual-feed tray" : ""}.</li>
          <li>If you saved a printer profile in your printer driver, use <b>Print using system dialog</b> (Ctrl+Shift+P) to pick it.</li>
        </ul>
      ) : b === "firefox" ? (
        <ul>
          <li>Firefox: set <b>Scale</b> to <b>100%</b> and turn off <b>Fit to page width</b>.</li>
          <li>Check the paper size{singleFeed ? " and the manual-feed tray" : ""} in the print dialog.</li>
        </ul>
      ) : b === "safari" ? (
        <ul>
          <li>Safari: set <b>Scale</b> to <b>100%</b>, and turn off <b>Auto-rotate</b> and <b>Scale to fit</b>.</li>
          <li>Check the paper size{singleFeed ? " and the manual-feed tray" : ""}.</li>
        </ul>
      ) : (
        <ul><li>Print at <b>100% / Actual size</b>. If your browser can't, download the PDF and print it from a PDF app.</li></ul>
      )}
      <p className="hint">Every test page has a 5-inch line: if it isn't exactly 5 inches, the scale is wrong. If the browser can't print at actual size,
        download the PDF and print it from Adobe Reader, Preview or another PDF app.</p>
    </div>
  );
}

/** Links to open a generated PDF in a new tab and to download it. */
export function PdfLinks({ pdf, label = "Open in a new tab" }: { pdf: { url: string; name: string } | null; label?: string }) {
  if (!pdf) return null;
  return (
    <span className="pdf-links">
      <a className="button" href={pdf.url} target="_blank" rel="noopener">{label}</a>
      <a className="button" href={pdf.url} download={pdf.name}>Download PDF</a>
    </span>
  );
}

/** 2.0.0 (#174): a generated PDF shown in the page with a Print button that opens the browser's print dialog
 * directly - one click to see it, one to print. Download and a new tab remain for browsers that can't print a PDF
 * from the page. */
/** #174: which setup sections are collapsed and whether a preview is pinned - kept in memory while the app is open
 * (AC-SEC-006: the app keeps nothing in browser storage). */
export const viewState = new Map<string, boolean>();

/** #174 / #186: a collapsible section of a Payments Setup editor (check styles, cover letters, envelopes). */
export function Section({ id, title, children, extra, className = "", scope = "pw-check-setup" }: {
  id: string; title: string; children: React.ReactNode; extra?: React.ReactNode; className?: string; scope?: string;
}) {
  const key = `${scope}-${id}`;
  const [open, setOpen] = useState(() => viewState.get(key) ?? true);
  const toggle = () => {
    const next = !open;
    setOpen(next);
    viewState.set(key, next);
  };
  return (
    <section className={`card collapsible ${open ? "open" : "closed"} ${className}`} aria-labelledby={`${id}-h`}>
      <div className="collapsible-head">
        <h2 id={`${id}-h`}>
          <button type="button" className="collapse-btn" aria-expanded={open} aria-controls={`${id}-body`} onClick={toggle}>
            <span aria-hidden="true" className="chev">{open ? "▾" : "▸"}</span> {title}
          </button>
        </h2>
        {extra}
      </div>
      <div id={`${id}-body`} hidden={!open}>{children}</div>
    </section>
  );
}

/** 2.3.0 (#394): the one layout of every setup editor (Donations Setup, check styles, cover letters, envelopes; later
 * Invoices #218). Wide screens (1200px and up): the settings on the left and the preview on the right, always locked -
 * the preview column stays in the window while the settings scroll (capped at the window's height; a taller preview
 * scrolls inside its column). Narrow screens: the preview at the top of the page, with *Keep at the top* (PinToggle)
 * to lock it there. The settings come first in the page order (keyboard, screen readers); CSS places the preview. */
export function SetupLayout({ preview, children, className = "" }: { preview: React.ReactNode; children: React.ReactNode; className?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    const pane = el?.closest(".content") as HTMLElement | null;
    if (!el || !pane) return;
    // the height the locked preview may use: the scrolling pane less its padding and the sticky Save bar
    const fit = () => {
      const pad = parseFloat(getComputedStyle(pane).paddingTop || "0") + parseFloat(getComputedStyle(pane).paddingBottom || "0");
      el.style.setProperty("--pane-h", `${Math.max(240, pane.clientHeight - pad - 64)}px`);
    };
    fit();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(fit);
    ro.observe(pane);
    return () => ro.disconnect();
  }, []);
  return (
    <div className={`setup-layout ${className}`} ref={ref}>
      <div className="setup-settings">{children}</div>
      <div className="setup-preview" data-testid="setup-preview">{preview}</div>
    </div>
  );
}

/** 2.3.0 (#394): *Keep at the top* for a preview on narrow screens (hidden on wide ones, where it is always locked),
 * remembered per page while the app is open. */
export function usePin(key: string): [boolean, (v: boolean) => void] {
  const [pin, setPin] = useState(() => viewState.get(key) ?? false);
  useEffect(() => { viewState.set(key, pin); }, [pin, key]);
  return [pin, setPin];
}

export function PinToggle({ pin, setPin }: { pin: boolean; setPin: (v: boolean) => void }) {
  return <label className="check pin-toggle"><input type="checkbox" checked={pin} onChange={(e) => setPin(e.target.checked)} /> Keep at the top</label>;
}

/** #186 / build 11 (#217): the live preview of a letter or envelope template - the server draws the template with sample
 * data from the unsaved settings, shortly after each change; the previous picture stays until the new one is ready.
 * It is shown as a picture (PNG of the PDF that prints), because Safari shows a PDF in an inline frame blank. Where the
 * server can't draw pictures (PREVIEW_UNAVAILABLE) it falls back to the PDF in a frame plus an "Open preview" link. */
export function LivePreview({ imageUrl, pdfUrl, body, title, aspect, deps }: {
  imageUrl: string; pdfUrl: string; body: unknown; title: string; aspect: number; deps: unknown[];
}) {
  const [img, setImg] = useState<string | null>(null);
  const [pdf, setPdf] = usePdf();
  const [usePdfFallback, setFallback] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => () => { if (img) URL.revokeObjectURL(img); }, [img]);
  useEffect(() => {
    let live = true;
    const h = setTimeout(() => {
      const ok = () => { if (live) setErr(null); };
      const fail = (x: unknown) => { if (live) setErr(x); };
      if (usePdfFallback) {
        api.postBlob(pdfUrl, body).then((b) => { if (live) { setPdf(b, "preview.pdf"); ok(); } }, fail);
        return;
      }
      api.postBlob(imageUrl, body).then((b) => { if (live) { setImg(URL.createObjectURL(b)); ok(); } },
        (x) => { if (live && x instanceof ApiError && x.code === "PREVIEW_UNAVAILABLE") setFallback(true); else fail(x); });
    }, 600);
    return () => { live = false; clearTimeout(h); };
  }, [...deps, usePdfFallback]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="live-preview" data-testid="live-preview">
      <ErrorBox error={err} />
      {usePdfFallback ? (pdf ? (
        <>
          <iframe className="live-preview-frame" src={`${pdf.url}#toolbar=0&navpanes=0&view=Fit`} title={title}
                  style={{ aspectRatio: String(aspect) }} />
          <p className="hint"><a href={pdf.url} target="_blank" rel="noopener">Open preview</a> (if the preview above stays blank in this browser)</p>
        </>
      ) : <p className="muted">Drawing the preview…</p>) : img ? (
        <img className="live-preview-image" src={img} alt={title} data-testid="live-preview-image" />
      ) : <p className="muted">Drawing the preview…</p>}
    </div>
  );
}

/** A generated PDF to print. `preview` (build 13, #230): the server's token for a picture of it. */
export type PdfFile = { url: string; name: string; preview?: string };

/** Build 13 (#230): Safari draws a PDF in an inline frame blank - and printing that frame could waste a check - so in
 * Safari the viewer shows a picture of the very PDF (drawn by the server) and Print… opens the PDF in a new tab, where
 * Safari shows and prints it. Other browsers keep the PDF in the page. Without a picture (an older server, or a server
 * that can't draw one) Safari gets the frame with a pointer to the new tab. */
function usePdfPicture(pdf: PdfFile, wanted: boolean) {
  const [img, setImg] = useState<{ url: string; pages: number } | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!wanted || !pdf.preview) { setFailed(true); return; }
    let live = true;
    let made: string | null = null;
    setImg(null); setFailed(false);
    fetch(`/api/pdf-preview/${encodeURIComponent(pdf.preview)}`, { credentials: "same-origin" })
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        const b = await r.blob();
        if (!live) return;
        made = URL.createObjectURL(b);
        setImg({ url: made, pages: Number(r.headers.get("X-Page-Count") || "1") });
      })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; if (made) URL.revokeObjectURL(made); };
  }, [pdf.url, pdf.preview, wanted]);
  return { img, failed };
}

export function PdfViewer({ pdf, title, onClose, singleFeed, children }: {
  pdf: PdfFile; title: string; onClose: () => void; singleFeed?: boolean; children?: React.ReactNode;
}) {
  const frame = useRef<HTMLIFrameElement>(null);
  const [failed, setFailed] = useState(false);
  const safari = detectBrowser() === "safari";
  const picture = usePdfPicture(pdf, safari);
  const print = () => {
    if (safari) {   // Safari prints the PDF from its own viewer in a new tab
      const a = document.createElement("a");
      a.href = pdf.url; a.target = "_blank"; a.rel = "noopener";
      document.body.appendChild(a); a.click(); a.remove();
      return;
    }
    try {
      const w = frame.current?.contentWindow;
      if (!w) throw new Error("no frame");
      w.focus();
      w.print();
    } catch { setFailed(true); }
  };
  return (
    <Modal title={title} onClose={onClose} wide>
      <div className="pdf-viewer">
        <div className="row">
          <button className="primary" onClick={print} autoFocus>Print…</button>
          <PdfLinks pdf={pdf} />
          <button onClick={onClose}>Close</button>
        </div>
        {failed ? <div className="alert warn">This browser can't print from here: use <b>Open in a new tab</b> and print from there.</div> : null}
        {safari ? <p className="hint" data-testid="safari-print-note">Safari: <b>Print…</b> opens the PDF in a new tab – print it from there (⌘P), at <b>100%</b>.</p> : null}
        {children}
        {!safari ? <iframe ref={frame} className="pdf-frame" src={pdf.url} title={title} />
          : picture.img ? (
            <>
              <img className="pdf-picture" src={picture.img.url} alt={`${title} – picture of the PDF`} data-testid="pdf-picture" />
              {picture.img.pages > 4 ? <p className="hint">The picture shows the first 4 of {picture.img.pages} pages; the PDF has them all.</p> : null}
            </>
          ) : picture.failed ? (
            <>
              <iframe ref={frame} className="pdf-frame" src={pdf.url} title={title} />
              <p className="hint">If the preview above stays blank, use <b>Open in a new tab</b>.</p>
            </>
          ) : <p className="muted">Drawing the preview…</p>}
        <details className="browser-tips-wrap"><summary>Print settings for this browser</summary><BrowserTips singleFeed={singleFeed} /></details>
      </div>
    </Modal>
  );
}

export function usePdf() {
  const [pdf, setPdfState] = useState<PdfFile | null>(null);
  const set = (blob: PdfBlob | null, name = "check.pdf") => {
    setPdfState((old) => {
      if (old) URL.revokeObjectURL(old.url);
      return blob ? { url: URL.createObjectURL(blob), name, preview: blob.previewToken } : null;
    });
  };
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf.url); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return [pdf, set] as const;
}

export function inches(v: number) { return `${v.toFixed(3)}"`; }

/** 2.0.0 (#164): the check amount in numbers and words while a payment is entered, as the account's check style prints
 * them (calculated by the server, never typed). */
export function AmountPreview({ accountId, total }: { accountId: number; total: string }) {
  const [p, setP] = useState<{ number: string | null; words: string | null } | null>(null);
  useEffect(() => {
    const h = setTimeout(() => {
      api.post("/api/checks/payments/amount-preview", { bank_account_id: accountId, amount: total }).then(setP, () => setP(null));
    }, 250);
    return () => clearTimeout(h);
  }, [accountId, total]);
  if (!p?.words) return null;
  return (
    <div className="amount-preview" data-testid="amount-preview" aria-live="polite">
      <span className="hint">On the check:</span> <code>{p.number}</code> <span className="words">{p.words}</span>
    </div>
  );
}
