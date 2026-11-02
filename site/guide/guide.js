// pennywarden.org/guide (2.4.0, #473): the current user guide and the archived release notes, with a version list.
// The Markdown files are this site's own (copied from docs/ by scripts/build_site.sh). They are turned into page
// elements with createElement/textContent only - nothing is ever parsed as HTML - and only http(s) links, in-page
// anchors and the guide's own documents become links. Mirrors frontend/src/pages/Help.tsx.
(function () {
  "use strict";
  var REPO = "https://github.com/kretherford0983/PennyWarden/blob/main/";
  var BUNDLED = { "user-guide": "user-guide.md", "check-printing": "check-printing.md", "backup-restore": "backup-restore.md" };
  var ANCHOR_LINE = /^<a id="([a-z0-9-]+)"><\/a>\s*$/;
  var LIST_ITEM = /^(\s*)([-*]|\d+\.)\s+(.*)$/;
  var versions = [];   // [{ version: "2.3", file: "archive/user-guide-v2.3.md" }]

  function el(tag, text) { var e = document.createElement(tag); if (text != null) e.textContent = text; return e; }
  function slug(t) { return t.toLowerCase().replace(/[*`_]/g, "").replace(/[^a-z0-9 -]/g, "").trim().replace(/ /g, "-"); }
  function params() { var q = new URLSearchParams(location.search); return { doc: q.get("doc") || "user-guide", v: q.get("v") || "" }; }
  function pageUrl(doc, v, frag) {
    var q = [];
    if (doc && doc !== "user-guide") q.push("doc=" + encodeURIComponent(doc));
    if (v) q.push("v=" + encodeURIComponent(v));
    return "./" + (q.length ? "?" + q.join("&") : "") + (frag ? "#" + frag : "");
  }

  // Where a Markdown link in file `from` (a path under docs/) points; null = plain text.
  function resolve(href, from) {
    if (href.charAt(0) === "#") return /^#[A-Za-z0-9_-]+$/.test(href) ? href : null;
    if (/^https?:\/\//i.test(href)) return href;
    if (/^[a-z]+:/i.test(href) || href.indexOf("//") === 0 || href.indexOf("\\") >= 0) return null;
    var parts = href.split("#"), frag = parts[1] || "";
    var path = from.split("/").slice(0, -1);
    parts[0].split("/").forEach(function (p) { if (p === "..") path.pop(); else if (p && p !== ".") path.push(p); });
    var full = path.join("/");
    var m = /^docs\/([a-z0-9-]+)\.md$/.exec(full);
    if (m && BUNDLED[m[1]]) return pageUrl(m[1], "", frag);
    var a = /^docs\/archive\/user-guide-v([0-9.]+)\.md$/.exec(full);
    if (a && versions.some(function (x) { return x.version === a[1]; })) return pageUrl("", a[1], frag);
    return REPO + full + (frag ? "#" + frag : "");
  }

  function inline(parent, text, from) {
    var re = /\\([\\`*_{}[\]()#+\-.!|>])|`([^`]+)`|\*\*(.+?)\*\*|\*([^*\s][^*]*?)\*|\[([^\]]+)\]\(([^)\s]+)\)/g;
    var last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1] !== undefined) parent.appendChild(document.createTextNode(m[1]));
      else if (m[2] !== undefined) parent.appendChild(el("code", m[2]));
      else if (m[3] !== undefined) { var b = el("strong"); inline(b, m[3], from); parent.appendChild(b); }
      else if (m[4] !== undefined) { var i = el("em"); inline(i, m[4], from); parent.appendChild(i); }
      else {
        var target = resolve(m[6], from);
        var a = el(target ? "a" : "span");
        if (target) { a.href = target; if (/^https?:/.test(target)) a.rel = "noopener"; }
        inline(a, m[5], from);
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

  function show() {
    var p = params(), box = document.getElementById("guide-doc");
    var known = versions.some(function (x) { return x.version === p.v; });
    var file = p.v && known ? versions.filter(function (x) { return x.version === p.v; })[0].file
      : (BUNDLED[p.doc] || BUNDLED["user-guide"]);
    document.getElementById("guide-version").value = p.v && known ? p.v : "";
    fetch(file, { cache: "no-cache" }).then(function (r) { if (!r.ok) throw new Error(); return r.text(); }).then(function (md) {
      box.textContent = "";
      if (p.doc !== "user-guide" && !p.v) {
        var back = el("p"); back.className = "small"; var a = el("a", "← User guide"); a.href = "./"; back.appendChild(a); box.appendChild(back);
      }
      box.appendChild(render(md, "docs/" + file));
      var h1 = box.querySelector("h1");
      document.title = (h1 ? h1.textContent + " · " : "") + "PennyWarden";
      if (location.hash) { var t = document.getElementById(decodeURIComponent(location.hash.slice(1))); if (t) t.scrollIntoView({ behavior: "instant" }); }
    }).catch(function () {
      box.textContent = "";
      box.appendChild(el("p", "The guide could not be loaded. It is also in the PennyWarden app (Help) and on GitHub."));
    });
  }

  var select = document.getElementById("guide-version");
  select.appendChild(el("option", "Current release")).value = "";
  select.addEventListener("change", function () { location.href = pageUrl("", select.value, ""); });
  fetch("versions.json", { cache: "no-cache" }).then(function (r) { return r.ok ? r.json() : { versions: [] }; }).then(function (d) {
    versions = (d.versions || []).filter(function (x) { return /^[0-9.]+$/.test(x.version) && /^archive\/user-guide-v[0-9.]+\.md$/.test(x.file); });
    versions.forEach(function (x) { select.appendChild(el("option", x.version + " — what's new")).value = x.version; });
  }).catch(function () {}).then(show);
})();
