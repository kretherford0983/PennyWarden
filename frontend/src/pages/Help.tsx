/** 2.4.0 (#473, book #488): Help - the bundled user guide, a book of chapters and task pages (docs/guide), shown inside
 * the app for every role: the contents, a chapter's pages, a page, and search. The Markdown is project-authored and
 * bundled at build time; this small renderer turns it into React elements, so all text is escaped and no raw HTML is
 * ever injected (BR-096). The only HTML it understands is a section marker line `<a id="name"></a>` (anchor ids). */
import { Fragment, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, type MouseEvent } from "react";
import { REPO_BLOB } from "../help";
import { GUIDE, chapterOf, imageUrl, pageOf, pageText, search, sourcePage, type GuideChapter } from "../helpDocs";
import { Link, useRouter } from "../router";

const ANCHOR_LINE = /^<a id="([a-z0-9-]+)"><\/a>\s*$/;

/** GitHub's heading ids, so links such as check-printing.md#cover-letters-and-envelopes keep working. */
export function slug(text: string): string {
  return text.toLowerCase().replace(/[*`_]/g, "").replace(/[^\p{L}\p{N} -]/gu, "").trim().replace(/ /g, "-");
}

type Target = { kind: "anchor"; id: string } | { kind: "app"; to: string } | { kind: "external"; href: string } | null;

/** The path of a relative Markdown href, from the file `from` (a repository path such as docs/guide/register/x.md). */
function joinPath(from: string, href: string): string {
  const parts = from.split("/").slice(0, -1);
  for (const p of href.split("/")) {
    if (p === "..") parts.pop();
    else if (p && p !== ".") parts.push(p);
  }
  return parts.join("/");
}

/** Where a Markdown link in file `from` points. Anything that isn't a plain web address, an in-page anchor or a
 * repository file becomes plain text (a "javascript:" link can never be produced). Guide pages and the reference
 * documents stay in the app; other repository files open on GitHub. */
export function resolveLink(href: string, from: string): Target {
  if (href.startsWith("#")) return /^#[A-Za-z0-9_-]+$/.test(href) ? { kind: "anchor", id: href.slice(1) } : null;
  if (/^https?:\/\//i.test(href)) return { kind: "external", href };
  if (/^[a-z]+:/i.test(href) || href.startsWith("//") || href.includes("\\")) return null;
  const [file, frag = ""] = href.split("#");
  const path = joinPath(from, file);
  const tail = frag ? `#${frag}` : "";
  const g = /^docs\/guide\/([a-z0-9-]+)\/([a-z0-9-]+)\.md$/.exec(path);
  if (g && pageOf(g[1], g[2])) return { kind: "app", to: `/help/${g[1]}/${g[2]}${tail}` };
  const d = /^docs\/([a-z0-9-]+)\.md$/.exec(path);
  if (d && d[1] === "user-guide") return { kind: "app", to: "/help" };
  const ref = d ? sourcePage(d[1]) : undefined;
  if (ref) {
    const to = `/help/${ref.chapter}/${ref.page}`;
    return path === from && frag ? { kind: "anchor", id: frag } : { kind: "app", to: to + tail };
  }
  return { kind: "external", href: REPO_BLOB + path + tail };
}

/** A guide picture: only docs/guide/img/<name>.png, bundled with the app; anything else shows its text. */
function image(alt: string, href: string, from: string, key: string): ReactNode {
  const m = /^docs\/guide\/img\/([a-z0-9-]+\.png)$/.exec(joinPath(from, href));
  const url = m ? imageUrl(m[1]) : undefined;
  return url ? <img key={key} className="help-img" src={url} alt={alt} loading="lazy" /> : <Fragment key={key}>{alt}</Fragment>;
}

function scrollToId(id: string) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ block: "start" });
}

/** Inline Markdown: `code`, **bold**, *italic*, [text](link) and backslash escapes. */
function inline(text: string, doc: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\\([\\`*_{}[\]()#+\-.!|>])|`([^`]+)`|\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*|!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let n = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const k = `${key}-${n++}`;
    if (m[1] !== undefined) out.push(m[1]);
    else if (m[2] !== undefined) out.push(<code key={k}>{m[2]}</code>);
    else if (m[3] !== undefined) out.push(<strong key={k}>{inline(m[3], doc, k)}</strong>);
    else if (m[4] !== undefined) out.push(<em key={k}>{inline(m[4], doc, k)}</em>);
    else if (m[6] !== undefined) out.push(image(m[5], m[6], doc, k));
    else {
      const label = inline(m[7], doc, k);
      const t = resolveLink(m[8], doc);
      if (!t) out.push(<Fragment key={k}>{label}</Fragment>);
      else if (t.kind === "anchor") {
        const onClick = (e: MouseEvent) => { e.preventDefault(); window.history.replaceState({}, "", `#${t.id}`); scrollToId(t.id); };
        out.push(<a key={k} href={`#${t.id}`} onClick={onClick}>{label}</a>);
      } else if (t.kind === "app") out.push(<Link key={k} to={t.to}>{label}</Link>);
      else out.push(<a key={k} href={t.href} target="_blank" rel="noopener noreferrer">{label}</a>);
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;

interface Item { text: string; children: Item[]; ordered: boolean }

function renderList(items: Item[], ordered: boolean, doc: string, key: string): ReactNode {
  const body = items.map((it, i) => (
    <li key={i}>
      {inline(it.text, doc, `${key}-${i}`)}
      {it.children.length ? renderList(it.children, it.children[0].ordered, doc, `${key}-${i}`) : null}
    </li>
  ));
  return ordered ? <ol key={key}>{body}</ol> : <ul key={key}>{body}</ul>;
}

/** Block-level Markdown -> React. Supports what the bundled guides use: headings, paragraphs, lists (one level of
 * nesting), tables, block quotes, fenced code and the section marker lines. */
export function renderMarkdown(md: string, doc: string): ReactNode[] {
  const lines = md.replace(/\r\n/g, "\n").split("\n");
  const out: ReactNode[] = [];
  let pendingId: string | null = null;
  let i = 0;
  const isTableSep = (s: string) => /^\s*\|?\s*:?-{2,}/.test(s) && s.includes("|");
  const startsBlock = (s: string) => /^(#{1,6} |```|>|\|)/.test(s) || LIST_ITEM.test(s) || ANCHOR_LINE.test(s);
  while (i < lines.length) {
    const line = lines[i];
    const key = `b${i}`;
    if (!line.trim()) { i++; continue; }
    const a = ANCHOR_LINE.exec(line);
    if (a) { pendingId = a[1]; i++; continue; }
    if (line.startsWith("```")) {
      const code: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) code.push(lines[i++]);
      i++;
      out.push(<pre key={key}><code>{code.join("\n")}</code></pre>);
      continue;
    }
    const h = /^(#{1,6}) (.*)$/.exec(line);
    if (h) {
      const level = Math.min(h[1].length, 4);
      const id = pendingId || slug(h[2]);
      pendingId = null;
      const Tag = (`h${level}`) as "h1" | "h2" | "h3" | "h4";
      out.push(<Tag key={key} id={id} className="help-heading">{inline(h[2], doc, key)}</Tag>);
      i++;
      continue;
    }
    if (pendingId) { out.push(<span key={`${key}a`} id={pendingId} />); pendingId = null; }
    if (line.startsWith("|") && i + 1 < lines.length && isTableSep(lines[i + 1])) {
      const cells = (s: string) => s.trim().replace(/^\|/, "").replace(/\|$/, "").split(/(?<!\\)\|/).map((c) => c.trim());
      const head = cells(line);
      i += 2;
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) rows.push(cells(lines[i++]));
      out.push(
        <div key={key} className="table-wrap">
          <table className="help-table">
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, doc, `${key}h${j}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, ri) => <tr key={ri}>{r.map((c, j) => <td key={j}>{inline(c, doc, `${key}r${ri}c${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      );
      continue;
    }
    if (line.startsWith(">")) {
      const quote: string[] = [];
      while (i < lines.length && lines[i].startsWith(">")) quote.push(lines[i++].replace(/^>\s?/, ""));
      out.push(<blockquote key={key}>{renderMarkdown(quote.join("\n"), doc)}</blockquote>);
      continue;
    }
    const li = LIST_ITEM.exec(line);
    if (li) {
      const top = li[1].length;
      const ordered = /\d/.test(li[2]);
      const items: Item[] = [];
      while (i < lines.length) {
        const s = lines[i];
        if (!s.trim()) {
          // a blank line ends the list unless the next line is another item of it
          const next = lines[i + 1] ?? "";
          const nm = LIST_ITEM.exec(next);
          if (nm && nm[1].length >= top) { i++; continue; }
          break;
        }
        const m = LIST_ITEM.exec(s);
        if (m && m[1].length <= top + 1) items.push({ text: m[3], children: [], ordered: /\d/.test(m[2]) });
        else if (m && items.length) items[items.length - 1].children.push({ text: m[3], children: [], ordered: /\d/.test(m[2]) });
        else if (/^\s/.test(s) && items.length) {
          const last = items[items.length - 1];
          const target = last.children.length && s.match(/^\s*/)![0].length > top + 2 ? last.children[last.children.length - 1] : last;
          target.text += " " + s.trim();
        } else break;
        i++;
      }
      out.push(renderList(items, ordered, doc, key));
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !(para.length && startsBlock(lines[i]))) para.push(lines[i++].trim());
    out.push(<p key={key}>{inline(para.join(" "), doc, key)}</p>);
  }
  return out;
}

function Applies() {
  return <p className="help-applies muted">Applies to PennyWarden {GUIDE.version}</p>;
}

function SearchBox({ initial = "" }: { initial?: string }) {
  const { navigate } = useRouter();
  const [q, setQ] = useState(initial);
  const submit = (e: FormEvent) => { e.preventDefault(); if (q.trim()) navigate(`/help/search?q=${encodeURIComponent(q.trim())}`); };
  return (
    <form className="help-search" role="search" onSubmit={submit}>
      <input type="search" aria-label="Search the guide" placeholder="Search the guide" value={q} onChange={(e) => setQ(e.target.value)} />
      <button type="submit">Search</button>
    </form>
  );
}

function Crumbs({ chapter }: { chapter?: GuideChapter }) {
  return (
    <nav className="help-crumbs small" aria-label="Breadcrumb">
      <Link to="/help">Contents</Link>{chapter ? <> › <Link to={`/help/${chapter.id}`}>{chapter.title}</Link></> : null}
    </nav>
  );
}

function Contents() {
  return (
    <>
      <h1>{GUIDE.title}</h1>
      <Applies />
      <p>How to use PennyWarden, one area at a time. Each chapter lists its pages; each page explains one task. The
        <b> ?</b> button at the top of every screen opens the page about that screen.</p>
      <div className="help-chapters">
        {GUIDE.chapters.map((c) => (
          <section key={c.id} className="help-chapter-card" aria-labelledby={`hc-${c.id}`}>
            <h2 id={`hc-${c.id}`}><Link to={`/help/${c.id}`}>{c.title}</Link></h2>
            <p className="muted small">{c.summary}</p>
            <ul>{c.pages.map((p) => <li key={p.id}><Link to={`/help/${c.id}/${p.id}`}>{p.title}</Link></li>)}</ul>
          </section>
        ))}
      </div>
    </>
  );
}

function Chapter({ chapter }: { chapter: GuideChapter }) {
  return (
    <>
      <Crumbs />
      <h1>{chapter.title}</h1>
      <Applies />
      <p className="help-lead">{chapter.summary}</p>
      <ul className="help-page-list">
        {chapter.pages.map((p) => <li key={p.id}><Link to={`/help/${chapter.id}/${p.id}`}><b>{p.title}</b></Link><br /><span className="muted">{p.summary}</span></li>)}
      </ul>
    </>
  );
}

function Page({ chapter, id }: { chapter: GuideChapter; id: string }) {
  const hit = pageOf(chapter.id, id)!;
  const text = pageText(chapter.id, id) || "";
  const from = hit.page.source ? `docs/${hit.page.source.replace(/^\.\.\//, "")}` : `docs/guide/${chapter.id}/${id}.md`;
  const content = useMemo(() => {
    // a reference document carries its own title: show it without repeating ours
    const md = hit.page.source ? text.replace(/^# .*\n/, "") : text;
    return renderMarkdown(md, from);
  }, [text, from, hit.page.source]);
  const k = chapter.pages.findIndex((p) => p.id === id);
  const prev = chapter.pages[k - 1];
  const next = chapter.pages[k + 1];
  return (
    <>
      <Crumbs chapter={chapter} />
      <h1>{hit.page.title}</h1>
      <Applies />
      <p className="help-lead">{hit.page.summary}</p>
      {content}
      <nav className="help-prevnext" aria-label="More in this chapter">
        {prev ? <Link to={`/help/${chapter.id}/${prev.id}`}>← {prev.title}</Link> : <span />}
        {next ? <Link to={`/help/${chapter.id}/${next.id}`}>{next.title} →</Link> : <span />}
      </nav>
    </>
  );
}

function Results({ q }: { q: string }) {
  const hits = useMemo(() => search(q), [q]);
  return (
    <>
      <Crumbs />
      <h1>Search: {q}</h1>
      {!hits.length ? <p>No page mentions all of these words. Try fewer or other words, or browse the <Link to="/help">contents</Link>.</p> : (
        <ol className="help-results" data-testid="help-results">
          {hits.map((h) => (
            <li key={`${h.chapter.id}/${h.page.id}`}>
              <Link to={`/help/${h.chapter.id}/${h.page.id}`}><b>{h.page.title}</b></Link> <span className="muted small">— {h.chapter.title}</span>
              <br /><span className="small">{h.snippet}</span>
            </li>
          ))}
        </ol>
      )}
    </>
  );
}

/** /help, /help/<chapter>, /help/<chapter>/<page>, /help/search?q=. The 2.4.0 #473 addresses /help/check-printing and
 * /help/backup-restore still open those documents. */
export default function Help({ chapter, page }: { chapter?: string; page?: string }) {
  const { path, search: qs } = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id) window.setTimeout(() => scrollToId(id), 0);
    else ref.current?.scrollIntoView({ block: "start" });
  }, [path]);
  const q = chapter === "search" ? new URLSearchParams(qs).get("q") || "" : "";
  let body: ReactNode;
  let title = "Help";
  const c = chapter ? chapterOf(chapter) : undefined;
  const legacy = chapter && !c && !page ? sourcePage(chapter) : undefined;
  if (!chapter || chapter === "user-guide") body = <Contents />;
  else if (chapter === "search") { body = <Results q={q} />; title = "Search"; }
  else if (legacy) { const lc = chapterOf(legacy.chapter)!; body = <Page chapter={lc} id={legacy.page} />; }
  else if (c && !page) { body = <Chapter chapter={c} />; title = c.title; }
  else if (c && page && pageOf(c.id, page)) { body = <Page chapter={c} id={page} />; title = pageOf(c.id, page)!.page.title; }
  else body = <><Crumbs /><p>Page not found. See the <Link to="/help">contents</Link>.</p></>;
  useEffect(() => { document.title = `${title} · PennyWarden`; }, [title]);
  return (
    <div className="help-doc" ref={ref} data-testid="help-doc">
      <SearchBox key={q} initial={q} />
      {body}
    </div>
  );
}
