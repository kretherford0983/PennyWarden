#!/usr/bin/env python3
"""2.4.0 (#488): writes docs/guide/README.md - the guide's contents for reading on GitHub - from docs/guide/guide.json.

    python scripts/guide_contents.py          (test_v240_user_guide.py checks it is up to date)
"""
import json
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[1] / "docs" / "guide"


def contents() -> str:
    m = json.loads((GUIDE / "guide.json").read_text("utf-8"))
    out = [f"# {m['title']}", "", f"Applies to PennyWarden {m['version']}. In the app, **Help** opens this guide; it is also on "
           "[pennywarden.org](https://pennywarden.org/guide/), where earlier versions can be chosen. The pages are written "
           "in `<chapter>/<page>.md`; the order, titles and summaries are in `guide.json`; pictures are made by "
           "`scripts/docs_screenshots.mjs`.", ""]
    for c in m["chapters"]:
        out += [f"## {c['title']}", "", c["summary"], ""]
        for p in c["pages"]:
            target = p["source"] if p.get("source") else f"{c['id']}/{p['id']}.md"
            out.append(f"- [{p['title']}]({target}) — {p['summary']}")
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    (GUIDE / "README.md").write_text(contents(), encoding="utf-8")
    print("wrote docs/guide/README.md")
