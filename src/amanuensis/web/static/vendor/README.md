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

## cytoscape.min.js

- Source: https://unpkg.com/cytoscape@3.30.0/dist/cytoscape.min.js
- Version: 3.30.0 (pinned)
- License: MIT (https://github.com/cytoscape/cytoscape.js/blob/master/LICENSE)
- Vendored on: 2026-05-30

Re-vendor with:

```
curl -fsSL -o src/amanuensis/web/static/vendor/cytoscape.min.js \
  https://unpkg.com/cytoscape@3.30.0/dist/cytoscape.min.js
```

## cose-base.js

- Source: https://unpkg.com/cose-base@2.2.0/cose-base.js
- Version: 2.2.0 (pinned)
- License: MIT (https://github.com/iVis-at-Bilkent/cose-base/blob/master/LICENSE)
- Vendored on: 2026-05-30

Re-vendor with:

```
curl -fsSL -o src/amanuensis/web/static/vendor/cose-base.js \
  https://unpkg.com/cose-base@2.2.0/cose-base.js
```

Dependency of ``cytoscape-cose-bilkent``; must load BEFORE it in the
browser. The UMD wrapper exposes ``window.coseBase`` which
``cytoscape-cose-bilkent`` reads at registration time.

## cytoscape-cose-bilkent.js

- Source: https://unpkg.com/cytoscape-cose-bilkent@4.1.0/cytoscape-cose-bilkent.js
- Version: 4.1.0 (pinned)
- License: MIT (https://github.com/cytoscape/cytoscape.js-cose-bilkent/blob/master/LICENSE)
- Vendored on: 2026-05-30

Re-vendor with:

```
curl -fsSL -o src/amanuensis/web/static/vendor/cytoscape-cose-bilkent.js \
  https://unpkg.com/cytoscape-cose-bilkent@4.1.0/cytoscape-cose-bilkent.js
```

The cose-bilkent layout for Cytoscape (M8.4 relation-graph view).
Load order in the browser: ``cose-base.js`` → ``cytoscape-cose-bilkent.js``
→ ``cytoscape.min.js`` → ``cytoscape.use(window.cytoscapeCoseBilkent)``.

## alpine.min.js

- Source: https://unpkg.com/alpinejs@3.14.1/dist/cdn.min.js
- Version: 3.14.1 (pinned)
- License: MIT (https://github.com/alpinejs/alpine/blob/main/LICENSE.md)
- Vendored on: 2026-05-30

Re-vendor with:

```
curl -fsSL -o src/amanuensis/web/static/vendor/alpine.min.js \
  https://unpkg.com/alpinejs@3.14.1/dist/cdn.min.js
```

Used by M8.4 (relation-graph view) for the ``htmx:afterSwap`` binding
that re-feeds elements into a stable Cytoscape instance without
rebuilding the canvas. Loaded only by ``relation_graph.html`` (not in
``base.html``) so other pages are unaffected.

## dagre.min.js

- Source: https://unpkg.com/dagre@0.8.5/dist/dagre.min.js
- Version: 0.8.5 (pinned)
- License: MIT (https://github.com/dagrejs/dagre/blob/master/LICENSE)
- Vendored on: 2026-06-01

Re-vendor with:

```
curl -fsSL -o src/amanuensis/web/static/vendor/dagre.min.js \
  https://unpkg.com/dagre@0.8.5/dist/dagre.min.js
```

Graph layout algorithm used by the M10 probandum tree page. Must load
BEFORE ``cytoscape-dagre.js`` because the latter reads ``window.dagre``
at registration time.

## cytoscape-dagre.js

- Source: https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js
- Version: 2.5.0 (pinned)
- License: MIT (https://github.com/cytoscape/cytoscape.js-dagre/blob/master/LICENSE)
- Vendored on: 2026-06-01

Re-vendor with:

```
curl -fsSL -o src/amanuensis/web/static/vendor/cytoscape-dagre.js \
  https://unpkg.com/cytoscape-dagre@2.5.0/cytoscape-dagre.js
```

Cytoscape adapter that wires the ``dagre`` layout into Cytoscape's
layout registry. Used by ``probandum_tree.html`` (M10 T10.4). Load
order in the browser: ``dagre.min.js`` → ``cytoscape.min.js`` →
``cytoscape-dagre.js`` → ``cytoscape.use(window.cytoscapeDagre)``.
