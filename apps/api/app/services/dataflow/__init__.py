"""Dataflow layer: spreadsheet import and report export.

The package is split in three modules:

``mapping``
    Header detection and the alias table that maps spreadsheet columns onto
    the canonical field set.
``importer``
    The import engine: it builds a *plan* (one action per data row) from the
    spreadsheet **and** the current database state and applies it.
``exporter``
    The reporting engine: XLSX / CSV reports with one sheet per operational
    view.
"""

from __future__ import annotations

from app.services.dataflow.exporter import generate_report
from app.services.dataflow.importer import commit_import, preview_import
from app.services.dataflow.mapping import (
    CANONICAL_FIELDS,
    REQUIRED_FIELDS,
    detect_mapping,
)

__all__ = [
    "CANONICAL_FIELDS",
    "REQUIRED_FIELDS",
    "commit_import",
    "detect_mapping",
    "generate_report",
    "preview_import",
]
