// pennywarden.org/guide (2.4.0, #473; the book #488): the user guide as a book - contents, chapters, task pages and
// search - for every version from 2.4, and the single "what's new" document of each earlier release from 1.10. The
// Markdown and the pictures are this site's own (copied from docs/ by scripts/build_site.sh). Pages are built with
// createElement/textContent only - nothing is ever parsed as HTML - and only http(s) links, in-page anchors and the
// guide's own pages become links. Mirrors frontend/src/pages/Help.tsx.
//   #/2.4                 contents          #/2.4/register         a chapter
//   #/2.4/register/x      a page            #/2.4/search/<words>   search
//   #/doc/2.3             an earlier release's document
(function () {
  "use strict";
  var REPO = "https://github.com/kretherford0983/PennyWarden/blob/main/";
  var ANCHOR_LINE = /^<a id="([a-z0-9-]+)"><\/a>\s*$/;
  var LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;
  var info = { current: "", books: [], docs: [] };   // versions.json
  var books = {};                                    // version -> guide.json
  var route = { kind: "contents", v: "" };

  function el(tag, text) { var e = document.createElement(tag); if (text != null) e.textContent = text; return e; }
  function slug(t) { return t.toLowerCase().replace(/[*`_]/g, "").replace(/[^a-z0-9 -]/g, "").trim().replace(/ /g, "-"); }
  function link(text, href) { var a = el("a", text); a.href = href; return a; }
  function join(from, href) {
    var path = from.split("/").slice(0, -1);
    href.split("/").forEach(function (p) { if (p === "..") path.pop(); else if (p && p !== ".") path.push(p); });
    return path.join("/");
  }
  function book(v) { return books[v]; }
  function findPage(v, c, p) {
    var b = book(v); if (!b) return null;
    for (var i = 0; i < b.chapters.length; i++) {
      var ch = b.chapters[i];
      if (ch.id !== c) continue;
      for (var j = 0; j < ch.pages.length; j++) if (ch.pages[j].id === p) return { chapter: ch, page: ch.pages[j], index: j };
    }
    return null;
  }
  function sourcePage(v, name) {
    var b = book(v); if (!b) return null;
    for (var i = 0; i < b.chapters.length; i++)
      for (var j = 0; j < b.chapters[i].pages.length; j++)
        if (b.chapters[i].pages[j].source === "../" + name + ".md") return [b.chapters[i].id, b.chapters[i].pages[j].id];
    return null;
  }

  // Where a Markdown link in file `from` (a path such as 2.4/register/x.md or 2.4/ref/check-printing.md) points.
  function resolve(href, from) {
    if (href.charAt(0) === "#") return /^#[A-Za-z0-9_-]+$/.test(href) ? href : null;
    if (/^https?:\/\//i.test(href)) return href;
    if (/^[a-z]+:/i.test(href) || href.indexOf("//") === 0 || href.indexOf("\\") >= 0) return null;
    var v = from.split("/")[0];
    var parts = href.split("#"), frag = parts[1] ? "#" + parts[1] : "";
    var full = join(from, parts[0]);
    var m = /^[0-9.]+\/([a-z0-9-]+)\/([a-z0-9-]+)\.md$/.exec(full);
    if (m && m[1] !== "ref" && findPage(v, m[1], m[2])) return "#/" + v + "/" + m[1] + "/" + m[2];
    var r = /^[0-9.]+\/(?:ref\/)?([a-z0-9-]+)\.md$/.exec(full);
    if (r && r[1] === "user-guide") return "#/" + v;
    var sp = r ? sourcePage(v, r[1]) : null;
    if (sp) return "#/" + v + "/" + sp[0] + "/" + sp[1];
    return REPO + "docs/" + full.split("/").slice(1).join("/").replace(/^ref\//, "") + frag;
  }
  function picture(href, from) {
    var full = join(from, href);
    return /^[0-9.]+\/img\/[a-z0-9-]+\.png$/.test(full) ? full : null;
  }

  function inline(parent, text, from) {
    var re = /\\([\\`*_{}[\]()#+\-.!|>])|`([^`]+)`|\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*|!\[([^\]]*)\]\(([^)\s]+)\)|\[([^\]]+)\]\(([^)\s]+)\)/g;
    var last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) parent.appendChild(document.createTextNode(m[1]));
      else if (m[2] !== undefined) parent.appendChild(el("code", m[2]));
      else if (m[3] !== undefined) { var b = el("strong"); inline(b, m[3], from); parent.appendChild(b); }
      else if (m[4] !== undefined) { var i = el("em"); inline(i, m[4], from); parent.appendChild(i); }
      else if (m[6] !== undefined) {
        var src = picture(m[6], from);
        if (src) { var img = el("img"); img.src = src; img.alt = m[5]; img.className = "guide-img"; img.loading = "lazy"; parent.appendChild(img); }
        else parent.appendChild(document.createTextNode(m[5]));
      }
      else {
        var target = resolve(m[8], from);
        var a = el(target ? "a" : "span");
        if (target) { a.href = target; if (/^https?:/.test(target)) a.rel = "noopener"; }
        inline(a, m[7], from);
        parent.appendChild(a);
      }
      last = re.lastIndex;
    }
    if (last < text.length) parent.appendChild(document.createTextNode(text.slice(last)));
    return parent;
  }

  function render(md, from) {
    var out = document.createDocumentFragment();
    var lines = md.replace(/\r\n/g, "\n").split("\n"), i = 0, pending = null;
    function startsBlock(s) { return /^(#{1,6} |```|>|\|)/.test(s) || LIST_ITEM.test(s) || ANCHOR_LINE.test(s); }
    function cells(s) { return s.trim().replace(/^\|/, "").replace(/\|$/, "").split(/\|/).map(function (c) { return c.trim(); }); }
    while (i < lines.length) {
      var line = lines[i], m;
      if (!line.trim()) { i++; continue; }
      if ((m = ANCHOR_LINE.exec(line))) { pending = m[1]; i++; continue; }
      if (line.indexOf("```") === 0) {
        var code = []; i++;
        while (i < lines.length && lines[i].indexOf("```") !== 0) code.push(lines[i++]);
        i++;
        var pre = el("pre"); pre.appendChild(el("code", code.join("\n"))); out.appendChild(pre);
        continue;
      }
      if ((m = /^(#{1,6}) (.*)$/.exec(line))) {
        var h = el("h" + Math.min(m[1].length, 4)); h.id = pending || slug(m[2]); pending = null;
        out.appendChild(inline(h, m[2], from)); i++;
        continue;
      }
      if (pending) { var s = el("span"); s.id = pending; out.appendChild(s); pending = null; }
      if (line.charAt(0) === "|" && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
        var wrap = el("div"); wrap.className = "guide-table";
        var table = el("table"), thead = el("thead"), tr = el("tr"), tbody = el("tbody");
        cells(line).forEach(function (c) { tr.appendChild(inline(el("th"), c, from)); });
        thead.appendChild(tr); table.appendChild(thead); i += 2;
        while (i < lines.length && lines[i].charAt(0) === "|") {
          var r = el("tr"); cells(lines[i++]).forEach(function (c) { r.appendChild(inline(el("td"), c, from)); }); tbody.appendChild(r);
        }
        table.appendChild(tbody); wrap.appendChild(table); out.appendChild(wrap);
        continue;
      }
      if (line.charAt(0) === ">") {
        var q = [];
        while (i < lines.length && lines[i].charAt(0) === ">") q.push(lines[i++].replace(/^>\s?/, ""));
        var bq = el("blockquote"); bq.appendChild(render(q.join("\n"), from)); out.appendChild(bq);
        continue;
      }
      if ((m = LIST_ITEM.exec(line))) {
        var top = m[1].length, items = [];
        while (i < lines.length) {
          var t = lines[i];
          if (!t.trim()) { var nm = LIST_ITEM.exec(lines[i + 1] || ""); if (nm && nm[1].length >= top) { i++; continue; } break; }
          var lm = LIST_ITEM.exec(t);
          if (lm && lm[1].length <= top + 1) items.push({ text: lm[3], ordered: /\d/.test(lm[2]), children: [] });
          else if (lm && items.length) items[items.length - 1].children.push({ text: lm[3], ordered: /\d/.test(lm[2]), children: [] });
          else if (/^\s/.test(t) && items.length) {
            var last = items[items.length - 1];
            var tgt = last.children.length && t.match(/^\s*/)[0].length > top + 2 ? last.children[last.children.length - 1] : last;
            tgt.text += " " + t.trim();
          } else break;
          i++;
        }
        out.appendChild(list(items, from));
        continue;
      }
      var para = [];
      while (i < lines.length && lines[i].trim() && !(para.length && startsBlock(lines[i]))) para.push(lines[i++].trim());
      out.appendChild(inline(el("p"), para.join(" "), from));
    }
    return out;
  }

  function list(items, from) {
    var l = el(items[0] && items[0].ordered ? "ol" : "ul");
    items.forEach(function (it) {
      var li = inline(el("li"), it.text, from);
      if (it.children.length) li.appendChild(list(it.children, from));
      l.appendChild(li);
    });
    return l;
  }

  function getText(url) { return fetch(url, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(url); return r.text(); }); }
  function getJson(url) { return getText(url).then(JSON.parse); }
  function loadBook(v) {
    if (books[v]) return Promise.resolve(books[v]);
    return getJson(v + "/guide.json").then(function (b) { books[v] = b; return b; });
  }

  function parse() {
    var h = decodeURIComponent(location.hash.replace(/^#\/?/, "")).split("/");
    if (h[0] === "doc" && h[1]) return { kind: "doc", v: h[1] };
    var v = /^[0-9]+\.[0-9]+$/.test(h[0]) ? h[0] : info.current;
    if (h[1] === "search") return { kind: "search", v: v, q: h.slice(2).join("/") };
    if (h[1] && h[2]) return { kind: "page", v: v, c: h[1], p: h[2] };
    if (h[1]) return { kind: "chapter", v: v, c: h[1] };
    return { kind: "contents", v: v };
  }

  // the version picker: the books that have this page (or chapter), then the earlier releases' documents
  function picker() {
    var sel = document.getElementById("guide-version");
    sel.textContent = "";
    info.books.forEach(function (b) {
      var has = route.kind !== "page" || !books[b.version] || findPage(b.version, route.c, route.p);
      if (has) sel.appendChild(el("option", b.version + (b.version === info.current ? " (current)" : ""))).value = "b:" + b.version;
    });
    info.docs.forEach(function (d) { sel.appendChild(el("option", d.version + " — what's new")).value = "d:" + d.version; });
    sel.value = route.kind === "doc" ? "d:" + route.v : "b:" + route.v;
  }

  function searchBox(v, q) {
    var f = el("form"); f.className = "guide-search"; f.setAttribute("role", "search");
    var i = el("input"); i.type = "search"; i.value = q || ""; i.placeholder = "Search the guide"; i.setAttribute("aria-label", "Search the guide");
    var b = el("button", "Search"); b.type = "submit";
    f.appendChild(i); f.appendChild(b);
    f.addEventListener("submit", function (e) { e.preventDefault(); if (i.value.trim()) location.hash = "#/" + v + "/search/" + encodeURIComponent(i.value.trim()); });
    return f;
  }
  function crumbs(v, ch) {
    var n = el("nav"); n.className = "small guide-crumbs"; n.setAttribute("aria-label", "Breadcrumb");
    n.appendChild(link("Contents", "#/" + v));
    if (ch) { n.appendChild(document.createTextNode(" › ")); n.appendChild(link(ch.title, "#/" + v + "/" + ch.id)); }
    return n;
  }
  function applies(v) { var p = el("p", "Applies to PennyWarden " + v); p.className = "small guide-applies"; return p; }

  function show() {
    route = parse();
    var box = document.getElementById("guide-doc");
    var done = function (nodes, title) {
      box.textContent = "";
      nodes.forEach(function (n) { box.appendChild(n); });
      document.title = (title ? title + " · " : "") + "PennyWarden user guide";
      picker();
      window.scrollTo(0, 0);
    };
    var fail = function () { done([el("p", "This page could not be loaded. The guide is also in the PennyWarden app (Help).")], ""); };
    if (route.kind === "doc") {
      var d = info.docs.filter(function (x) { return x.version === route.v; })[0];
      if (!d) return fail();
      return getText(d.file).then(function (md) {
        var note = el("p", "PennyWarden " + d.version + " — what was new in that release. "); note.className = "small";
        note.appendChild(link("The current guide", "#/" + info.current));
        done([note, render(md, "archive/x.md")], d.version);
      }).catch(fail);
    }
    var v = route.v;
    loadBook(v).then(function (b) {
      var top = searchBox(v, route.q);
      if (route.kind === "contents") {
        var grid = el("div"); grid.className = "guide-chapters";
        b.chapters.forEach(function (c) {
          var s = el("section"); s.className = "guide-card";
          var h = el("h2"); h.appendChild(link(c.title, "#/" + v + "/" + c.id)); s.appendChild(h);
          var p = el("p", c.summary); p.className = "small"; s.appendChild(p);
          var ul = el("ul");
          c.pages.forEach(function (pg) { var li = el("li"); li.appendChild(link(pg.title, "#/" + v + "/" + c.id + "/" + pg.id)); ul.appendChild(li); });
          s.appendChild(ul); grid.appendChild(s);
        });
        return done([top, el("h1", b.title), applies(v), grid], "");
      }
      if (route.kind === "search") {
        return getJson(v + "/search.json").then(function (idx) {
          var words = route.q.toLowerCase().split(/\s+/).filter(function (w) { return w.length > 1; });
          var hits = idx.filter(function (x) { var hay = (x.title + " " + x.summary + " " + x.text).toLowerCase(); return words.length && words.every(function (w) { return hay.indexOf(w) >= 0; }); });
          hits.sort(function (a, b2) { var t = function (x) { return words.filter(function (w) { return (x.title + " " + x.summary).toLowerCase().indexOf(w) >= 0; }).length; }; return t(b2) - t(a); });
          var ol = el("ol");
          hits.slice(0, 25).forEach(function (x) {
            var li = el("li"); var a = link(x.title, "#/" + v + "/" + x.chapter + "/" + x.page); li.appendChild(a);
            li.appendChild(document.createTextNode(" — " + x.chapter_title)); li.appendChild(el("br"));
            var at = x.text.toLowerCase().indexOf(words[0]);
            li.appendChild(el("span", at < 0 ? x.summary : "…" + x.text.slice(Math.max(0, at - 60), at + 120) + "…"));
            ol.appendChild(li);
          });
          done([top, crumbs(v), el("h1", "Search: " + route.q), hits.length ? ol : el("p", "No page mentions all of these words.")], "Search");
        }).catch(fail);
      }
      var ch = b.chapters.filter(function (c) { return c.id === route.c; })[0];
      if (!ch) return fail();
      if (route.kind === "chapter") {
        var ul = el("ul"); ul.className = "guide-pages";
        ch.pages.forEach(function (pg) {
          var li = el("li"); li.appendChild(link(pg.title, "#/" + v + "/" + ch.id + "/" + pg.id)); li.appendChild(el("br")); li.appendChild(el("span", pg.summary)); ul.appendChild(li);
        });
        var lead = el("p", ch.summary); lead.className = "guide-lead";
        return done([top, crumbs(v), el("h1", ch.title), applies(v), lead, ul], ch.title);
      }
      var hit = findPage(v, ch.id, route.p);
      if (!hit) return fail();
      var file = hit.page.source ? v + "/ref/" + hit.page.source.replace(/^\.\.\//, "") : v + "/" + ch.id + "/" + hit.page.id + ".md";
      return getText(file).then(function (md) {
        if (hit.page.source) md = md.replace(/^# .*\n/, "");
        var lead = el("p", hit.page.summary); lead.className = "guide-lead";
        var pn = el("nav"); pn.className = "guide-prevnext";
        var prev = ch.pages[hit.index - 1], next = ch.pages[hit.index + 1];
        pn.appendChild(prev ? link("← " + prev.title, "#/" + v + "/" + ch.id + "/" + prev.id) : el("span"));
        pn.appendChild(next ? link(next.title + " →", "#/" + v + "/" + ch.id + "/" + next.id) : el("span"));
        done([top, crumbs(v, ch), el("h1", hit.page.title), applies(v), lead, render(md, file), pn], hit.page.title);
      }).catch(fail);
    }).catch(fail);
  }

  // the #473 addresses (?doc=check-printing, ?v=2.3) keep working
  function legacy() {
    var q = new URLSearchParams(location.search);
    if (q.get("v")) { history.replaceState(null, "", "./#/doc/" + q.get("v")); return; }
    if (q.get("doc")) {
      var sp = sourcePage(info.current, q.get("doc"));
      history.replaceState(null, "", "./#/" + info.current + (sp ? "/" + sp[0] + "/" + sp[1] : ""));
    }
  }

  document.getElementById("guide-version").addEventListener("change", function (e) {
    var val = e.target.value, v = val.slice(2);
    if (val.charAt(0) === "d") { location.hash = "#/doc/" + v; return; }
    location.hash = route.kind === "page" ? "#/" + v + "/" + route.c + "/" + route.p : route.kind === "chapter" ? "#/" + v + "/" + route.c : "#/" + v;
  });
  window.addEventListener("hashchange", show);
  getJson("versions.json").then(function (d) {
    info.current = /^[0-9]+\.[0-9]+$/.test(d.current || "") ? d.current : "";
    info.books = (d.books || []).filter(function (x) { return /^[0-9]+\.[0-9]+$/.test(x.version); });
    info.docs = (d.docs || []).filter(function (x) { return /^[0-9.]+$/.test(x.version) && /^archive\/user-guide-v[0-9.]+\.md$/.test(x.file); });
    return Promise.all(info.books.map(function (b) { return loadBook(b.version).catch(function () {}); }));
  }).then(function () { legacy(); show(); }).catch(function () {
    document.getElementById("guide-doc").textContent = "The guide could not be loaded.";
  });
})();
