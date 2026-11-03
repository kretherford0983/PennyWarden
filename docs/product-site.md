# pennywarden.org — the product page (since 1.10.0)

The page at <https://pennywarden.org> is published from this repository by GitHub Pages.

## What is where

| | |
|---|---|
| `site/index.html`, `site.css`, `site.js` | The page itself, written by hand for people who are not technical (the README stays the technical overview). No external fonts, scripts or trackers; a strict Content-Security-Policy |
| `site/guide/index.html`, `guide.js` | The **User guide** (2.4.0, #473; a book since #488): for every release from 2.4 the book from `docs/guide` (Contents, chapters, task pages with pictures, search) in `guide/<version>/`, and the single archived "what's new" document of each release from 1.10 to 2.3. Hash addresses (`#/2.4/register/read-register`); the **Applies to** list offers the versions that have the page. Built by `scripts/build_site.sh` (`versions.json`, per-version `search.json`); pages are built with `textContent` only (no HTML parsing) |
| `docs/screenshots/readme/*.png` | A few of the README screenshots are copied in when the site is built |
| `scripts/release_data.py` | Builds `releases.json` (production releases) and `releases-test.json` (test builds and production releases) from the repository's GitHub releases |
| `scripts/build_site.sh` | Assembles everything into `_site/` |
| `.github/workflows/pages.yml` | Builds from **main** and deploys to GitHub Pages |

The download buttons are filled in from `releases.json`, so they always point at the current production release
(the Windows `.exe` and the Mac `.dmg` have the version in their names). The visitor's own system is highlighted.

## When it is published

- **After every release:** the `build` workflow's last job starts `pages.yml` once the GitHub release (production on
  `main`) or pre-release (test build on `test`) is published. A production release updates `releases.json`; a test
  build only `releases-test.json`, which the product page never reads.
- **When the page changes on main** (`site/`, the README screenshots, the two scripts or the workflow).
- **By hand:** Actions → *pages* → *Run workflow*.

The page is always built from `main`, so changes to it go live with a release, like everything else.

## Release data files

`https://pennywarden.org/releases.json` and `https://pennywarden.org/releases-test.json`:

```json
{ "schema": 1, "channel": "stable", "generated_at": "…", "latest": "1.10.0", "latest_tag": "v1.10.0",
  "releases": [ { "version": "1.10.0", "tag": "v1.10.0", "channel": "stable", "build": null, "date": "2026-10-10",
                  "url": "https://github.com/…/releases/tag/v1.10.0", "notes": "…the CHANGELOG section…",
                  "downloads": [ { "os": "windows", "kind": "installer", "name": "…", "url": "…", "size": 1, "sha256": "…" } ] } ] }
```

Newest first. `notes` is the release text without the install instructions at its end. The application's update
check reads these files (docs/configuration.md, *Update check*).

## One-time setup (done 2026-10-09)

1. Namecheap → Advanced DNS: the GitHub verification TXT record, four `A` and four `AAAA` records for `@`
   (GitHub Pages addresses) and `www` CNAME `kretherford0983.github.io`; the parking records removed.
2. GitHub → profile Settings → Pages: `pennywarden.org` verified.
3. Repository → Settings → Pages: source *GitHub Actions*, custom domain `pennywarden.org`; **Enforce HTTPS** once
   GitHub has issued the certificate.
4. After the first deployment: save the page in the Internet Archive (<https://web.archive.org/save>).
