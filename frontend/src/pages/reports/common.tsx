/** 2.3.0 (#375): what every report page shares - the one action row (Open · Download PDF · Download PPTX ·
 * Download CSV, as the report has them) and the hooks a report uses to be remembered (Recently run, last options). */
import type { ReactNode } from "react";

/** A report's options as remembered for the user (parameters only, never output), and its short Recently run label. */
export type RunFn = (params: Record<string, any>, label: string) => void;
export type Links = { open?: string | null; download?: string | null; pptx?: string | null; csv?: string | null; onRun: () => void; note?: ReactNode };
export type ActionsFn = (l: Links) => ReactNode;

export function currentFy(fys: any[]): any {
  const t = new Date().toISOString().slice(0, 10);
  return fys.find((f) => f.start_date <= t && f.end_date >= t) || fys[fys.length - 1];
}

/** The report page's action row: Open (primary, a new tab) and the downloads the report has. Each link records the run
 * (it doesn't wait for it: the browser goes on to open or download the file). Missing link = not ready (disabled). */
export function ReportActions({ open, download, pptx, csv, onRun, note }: Links) {
  const a = (href: string | null | undefined, label: string, primary = false, newTab = false) =>
    href ? <a className={`button${primary ? " primary" : ""}`} href={href} onClick={onRun} {...(newTab ? { target: "_blank", rel: "noopener" } : {})}>{label}</a>
      : <button type="button" className={primary ? "primary" : ""} disabled>{label}</button>;
  return (
    <div className="actions left report-actions" data-testid="report-actions">
      {open !== undefined ? a(open, "Open", true, true) : null}
      {download !== undefined ? a(download, "Download PDF") : null}
      {pptx !== undefined ? a(pptx, "Download PPTX") : null}
      {csv !== undefined ? a(csv, "Download CSV") : null}
      {note}
    </div>
  );
}
