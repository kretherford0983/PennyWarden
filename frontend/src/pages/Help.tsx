/** 2.4.0 (#473): Help - the bundled user guide (and the check-printing and backup guides it links to), shown inside
 * the app for every role. The Markdown is project-authored and bundled at build time; this small renderer turns it into
 * React elements, so all text is escaped and no raw HTML is ever injected (BR-096). The only HTML it understands is the
 * guide's own section marker line `<a id="name"></a>`, which becomes an anchor id. */
import { Fragment, useEffect, useMemo, useRef, type ReactNode, type MouseEvent } from "react";
import { REPO_BLOB } from "../help";
import { HELP_DOCS } from "../helpDocs";
import { Link, useRouter } from "../router";

const ANCHOR_LINE = /^<a id="([a-z0-9-]+)"><\/a>\s*$/;

/** GitHub's heading ids, so links such as check-printing.md#cover-letters-and-envelopes keep working. */
export function slug(text: string): string {
  return text.toLowerCase().replace(/[*`_]/g, "").replace(/[^\p{L}\p{N} -]/gu, "").trim().replace(/ /g, "-");
}

type Target = { kind: "anchor"; id: string } | { kind: "app"; to: string } | { kind: "external"; href: string } | null;

/** Where a Markdown link in document `doc` points. Anything that isn't a plain web address, an in-page anchor or a
 * repository file becomes plain text (a "javascript:" link can never be produced). */
export function resolveLink(href: string, doc: string): Target {
  if (href.startsWith("#")) return /^#[A-Za-z0-9_-]+$/.test(href) ? { kind: "anchor", id: href.slice(1) } : null;
  if (/^https?:\/\//i.test(href)) return { kind: "external", href };
  if (/^[a-z]+:/i.test(href) || href.startsWith("//") || href.includes("\\")) return null;
  const [file, frag = ""] = href.split("#");
  const parts: string[] = ["docs"];
  for (const p of file.split("/")) {
    if (p === "..") parts.pop();
    else if (p && p !== ".") parts.push(p);
  }
  const path = parts.join("/");
  const m = /^docs\/([a-z0-9-]+)\.md$/.exec(path);
  if (m && HELP_DOCS[m[1]]) {
    const base = m[1] === "user-guide" ? "/help" : `/help/${m[1]}`;
    if (m[1] === doc && frag) return { kind: "anchor", id: frag };
    return { kind: "app", to: frag ? `${base}#${frag}` : base };
  }
  return { kind: "external", href: REPO_BLOB + path + (frag ? `#${frag}` : "") };
}

function scrollToId(id: string) {
  const el = document.getElementById(id);
  if (el) el.scrollIntoView({ block: "start" });
}

/** Inline Markdown: `code`, **bold**, *italic*, [text](link) and backslash escapes. */
function inline(text: string, doc: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\\([\\`*_{}[\]()#+\-.!|>])|`([^`]+)`|\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
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
    else {
      const label = inline(m[5], doc, k);
      const t = resolveLink(m[6], doc);
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

export default function Help({ doc = "user-guide" }: { doc?: string }) {
  const { path } = useRouter();
  const ref = useRef<HTMLDivElement>(null);
  const entry = HELP_DOCS[doc];
  const content = useMemo(() => (entry ? renderMarkdown(entry.text, doc) : null), [entry, doc]);
  useEffect(() => {
    const id = decodeURIComponent(window.location.hash.slice(1));
    if (id) scrollToId(id);
    else ref.current?.scrollIntoView({ block: "start" });
  }, [path, doc]);
  if (!entry) return <p>Page not found.</p>;
  return (
    <div className="help-doc" ref={ref} data-testid="help-doc">
      {doc !== "user-guide" ? <p className="muted"><Link to="/help">← User guide</Link></p> : null}
      {content}
    </div>
  );
}
