"""Amanuensis local web app (Phase 1, milestone M8).

A FastAPI + Jinja2 + HTMX + Tailwind app that surfaces the substrate
read-only to a human supervisor and accepts clarifications / iterations
through HTMX forms. Localhost-only by default (INV — supervisor in the
loop is *local* by design; the substrate is not multi-tenant).

M8.1 ships only the skeleton (lifespan, ``/healthz``, base template,
vendored HTMX, Tailwind build pipeline). Subsequent milestones add the
dashboard (M8.2), atom browser (M8.3), relation graph via Cytoscape
(M8.4), forms (M8.5), and Playwright coverage (M8.9).
"""

from __future__ import annotations
