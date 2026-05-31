"""``amanuensis.export`` — static-HTML export of a single distillation.

Phase 1 ships a STUB (M9.1): one self-contained HTML file per source
containing the source-mirror paragraphs, the extracted atoms, and the
relations, plus a machine-readable JSON sidecar embedded as
``<script type="application/json">`` blocks. Phase 4 promotes this to a
full audit-HTML bundle (multi-page, Cytoscape graph, replay-log
viewer); the stub establishes the file-shape + CLI surface those later
milestones depend on.

The single public entry point is :func:`export_static_html`. The CLI
command (``amanuensis export <source-id>``) is a thin Typer wrapper
around it.
"""

from .static_html import export_static_html

__all__ = ["export_static_html"]
