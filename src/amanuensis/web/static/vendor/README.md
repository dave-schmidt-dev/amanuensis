# Vendored third-party assets

These files are checked in verbatim so the wheel ships offline-reproducible.
Do NOT add a build step that re-fetches them at install time.

## htmx.min.js

- Source: https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
- Version: 1.9.12 (pinned)
- License: BSD 2-Clause (https://github.com/bigskysoftware/htmx/blob/master/LICENSE)
- Vendored on: 2026-05-30

Re-vendor with:

```
curl -fsSL -o src/amanuensis/web/static/vendor/htmx.min.js \
  https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js
```

Bumping the version requires re-running the Playwright suite (M8.9)
to catch any breaking attribute or extension changes.
