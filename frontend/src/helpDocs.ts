/** 2.4.0 (#473, book #488): the bundled user guide (see help.ts). Imported only by pages/Help.tsx, which App loads
 * lazily, so the rest of the app doesn't carry it. The book is docs/guide: guide.json lists the chapters and their
 * pages (order, titles, summaries); each page is docs/guide/<chapter>/<page>.md; pictures are docs/guide/img/*.png.
 * The two long reference guides (check printing, backup and restore) are pages whose `source` is the document. */
import manifestText from "../../docs/guide/guide.json?raw";
import checkPrinting from "../../docs/check-printing.md?raw";
import backupRestore from "../../docs/backup-restore.md?raw";

export interface GuidePage { id: string; title: string; summary: string; source?: string }
export interface GuideChapter { id: string; title: string; summary: string; pages: GuidePage[] }
export interface Guide { version: string; title: string; chapters: GuideChapter[] }

export const GUIDE: Guide = JSON.parse(manifestText);

const PAGES = import.meta.glob("../../docs/guide/*/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;
const IMAGES = import.meta.glob("../../docs/guide/img/*.png", { query: "?url", import: "default", eager: true }) as Record<string, string>;
/** The reference documents a page can show whole, by its `source` (relative to docs/guide). */
const SOURCES: Record<string, string> = { "../check-printing.md": checkPrinting, "../backup-restore.md": backupRestore };

export function chapterOf(id: string): GuideChapter | undefined {
  return GUIDE.chapters.find((c) => c.id === id);
}

export function pageOf(chapter: string, page: string): { chapter: GuideChapter; page: GuidePage } | undefined {
  const c = chapterOf(chapter);
  const p = c?.pages.find((x) => x.id === page);
  return c && p ? { chapter: c, page: p } : undefined;
}

/** A page's Markdown (its own file, or the reference document it shows). */
export function pageText(chapter: string, page: string): string | undefined {
  const hit = pageOf(chapter, page);
  if (!hit) return undefined;
  if (hit.page.source) return SOURCES[hit.page.source];
  return PAGES[`../../docs/guide/${chapter}/${page}.md`];
}

/** The bundled address of a guide picture (`img/<name>.png`), or undefined. */
export function imageUrl(name: string): string | undefined {
  return IMAGES[`../../docs/guide/img/${name}`];
}

/** The page that shows a reference document whole (e.g. "check-printing" -> reference/check-printing). */
export function sourcePage(docName: string): { chapter: string; page: string } | undefined {
  for (const c of GUIDE.chapters) {
    for (const p of c.pages) if (p.source === `../${docName}.md`) return { chapter: c.id, page: p.id };
  }
  return undefined;
}

/** Plain-text search over titles, summaries and page text: every word must appear; title hits rank first. */
export function search(query: string): { chapter: GuideChapter; page: GuidePage; snippet: string }[] {
  const words = query.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  if (!words.length) return [];
  const out: { chapter: GuideChapter; page: GuidePage; snippet: string; score: number }[] = [];
  for (const c of GUIDE.chapters) {
    for (const p of c.pages) {
      const body = (pageText(c.id, p.id) || "").replace(/!\[[^\]]*\]\([^)]*\)/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
        .replace(/<a id="[^"]*"><\/a>/g, "").replace(/[*`#|>]/g, "");
      const hay = `${p.title} ${p.summary} ${c.title} ${body}`.toLowerCase();
      if (!words.every((w) => hay.includes(w))) continue;
      const title = `${p.title} ${p.summary}`.toLowerCase();
      const score = words.reduce((s, w) => s + (title.includes(w) ? 10 : 0) + (body.toLowerCase().split(w).length - 1), 0);
      const at = body.toLowerCase().indexOf(words[0]);
      const snippet = at < 0 ? p.summary : (at > 60 ? "…" : "") + body.slice(Math.max(0, at - 60), at + 120).replace(/\s+/g, " ").trim() + "…";
      out.push({ chapter: c, page: p, snippet, score });
    }
  }
  return out.sort((a, b) => b.score - a.score).slice(0, 25);
}
