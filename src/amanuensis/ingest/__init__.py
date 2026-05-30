"""PDF ingestion — the source-mirror pipeline (M3.1+).

M3.1 ships a Docling-based ingester (``docling_ingester.ingest_pdf``).
M3.2 will add a pdfplumber fallback and a public engine selector;
M3.3 will codify the determinism boundary; M3.4 will add a legal-
pleading fixture. The library-level function is the only surface
M3.1 exposes — no CLI subcommand yet.
"""

from __future__ import annotations

from .docling_ingester import ingest_pdf

__all__ = ["ingest_pdf"]
