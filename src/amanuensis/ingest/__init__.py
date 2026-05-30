"""PDF ingestion — the source-mirror pipeline (M3.1+).

M3.1 ships a Docling-based ingester (``docling_ingester.ingest_pdf``).
M3.2 adds the pdfplumber fallback ingester
(``pdfplumber_ingester.ingest_pdf_pdfplumber``) with the same output
shape and a distinct ``ingest_engine`` manifest tag. The CLI
``--engine`` flag and auto-fallback selection live in M4 / M3.3
respectively; this package only exposes the two library entrypoints.
M3.3 will codify the determinism boundary; M3.4 will add a legal-
pleading fixture.
"""

from __future__ import annotations

from .docling_ingester import ingest_pdf
from .pdfplumber_ingester import ingest_pdf_pdfplumber

__all__ = ["ingest_pdf", "ingest_pdf_pdfplumber"]
