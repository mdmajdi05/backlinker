"""Header detection and column mapping for spreadsheet imports.

Imported workbooks are produced by humans *and* by third party tools, so the
header row is matched against a table of aliases instead of requiring exact
column names.  Every column of the sheet is reported: columns that cannot be
mapped are returned with an empty ``target_field`` so the UI can show what was
ignored instead of silently dropping data.

The module is intentionally free of database access so it can be reused by the
exporter and by tests.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

__all__ = [
    "ALIASES",
    "CANONICAL_FIELDS",
    "FUZZY_THRESHOLD",
    "REQUIRED_FIELDS",
    "URL_FIELDS",
    "detect_mapping",
    "mapping_to_fields",
    "normalize_header",
    "required_fields_present",
]

#: Canonical field names understood by the import engine.
CANONICAL_FIELDS: tuple[str, ...] = (
    "project",
    "website_name",
    "target_url",
    "opportunity_url",
    "submission_url",
    "category",
    "anchor_text",
    "description",
    "email",
    "status",
    "published_url",
    "verified",
    "last_attempt",
    "notes",
    "error",
    "domain",
    "language",
    "region",
    "score",
    "adapter",
    "project_name",
)

#: Fields that must carry a value for a row to be importable.
REQUIRED_FIELDS: frozenset[str] = frozenset({"opportunity_url", "target_url"})

#: Canonical fields whose value is a URL.
URL_FIELDS: frozenset[str] = frozenset(
    {"target_url", "opportunity_url", "submission_url", "published_url"}
)

#: Minimum similarity ratio for a fuzzy header match.
FUZZY_THRESHOLD = 0.72

#: Alias table: human readable column title -> canonical field.
#:
#: The titles listed in the product specification ("Project", "Website",
#: "Target URL", "Backlink Website", ...) are present verbatim; the remaining
#: entries cover the common variations found in exported workbooks.
ALIASES: dict[str, str] = {
    # -- project ------------------------------------------------------
    "Project": "project",
    "Project Name": "project_name",
    "Project ID": "project",
    "Campaign": "project",
    "Campaign Name": "project_name",
    # -- source website ------------------------------------------------
    "Website": "website_name",
    "Website Name": "website_name",
    "Source Website": "website_name",
    "Site Name": "website_name",
    "Directory": "website_name",
    "Backlink Website": "opportunity_url",
    "Opportunity URL": "opportunity_url",
    "Opportunity": "opportunity_url",
    "Listing URL": "opportunity_url",
    "Source URL": "opportunity_url",
    "Directory URL": "opportunity_url",
    "Website URL": "opportunity_url",
    # -- target --------------------------------------------------------
    "Target URL": "target_url",
    "Target Website": "target_url",
    "Target Landing Page": "target_url",
    "Destination URL": "target_url",
    "Landing Page": "target_url",
    "Our URL": "target_url",
    "Submission URL": "submission_url",
    "Submission Page": "submission_url",
    "Form URL": "submission_url",
    # -- content -------------------------------------------------------
    "Category": "category",
    "Category Name": "category",
    "Anchor Text": "anchor_text",
    "Anchor": "anchor_text",
    "Anchor Text Used": "anchor_text",
    "Description": "description",
    "Business Description": "description",
    "Email": "email",
    "Contact Email": "email",
    "Email Address": "email",
    "Status": "status",
    "Submission Status": "status",
    "Backlink Status": "status",
    "Current Status": "status",
    "Backlink Published URL": "published_url",
    "Published URL": "published_url",
    "Published Page URL": "published_url",
    "Actual Published URL": "published_url",
    "Live URL": "published_url",
    "Verified": "verified",
    "Is Verified": "verified",
    "Verified (Live)": "verified",
    "Last Attempt": "last_attempt",
    "Last Attempt Date": "last_attempt",
    "Last Attempt At": "last_attempt",
    "Notes": "notes",
    "Internal Notes": "notes",
    "Error": "error",
    "Last Error": "error",
    "Error Message": "error",
    # -- enrichment ----------------------------------------------------
    "Domain": "domain",
    "Language": "language",
    "Region": "region",
    "Score": "score",
    "Quality Score": "score",
    "Adapter": "adapter",
    "Adapter ID": "adapter",
}

_HEADER_NOISE = re.compile(r"[\s:*]+")


def normalize_header(header: str) -> str:
    """Normalise a column title for alias lookups.

    ``"  Backlink Published URL: "`` becomes ``"backlink published url"``.
    """
    text = _HEADER_NOISE.sub(" ", str(header or "").strip())
    text = text.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip().lower()


def _alias_lookup() -> dict[str, str]:
    """Build the normalised alias table (computed once, at import time)."""
    lookup: dict[str, str] = {}
    for alias, field in ALIASES.items():
        lookup.setdefault(normalize_header(alias), field)
    for field in CANONICAL_FIELDS:
        lookup.setdefault(normalize_header(field), field)
    return lookup


_LOOKUP = _alias_lookup()


def _match_field(key: str) -> tuple[str, float]:
    """Return ``(target_field, confidence)`` for a normalised header."""
    if not key:
        return "", 0.0
    exact = _LOOKUP.get(key)
    if exact is not None:
        return exact, 1.0
    best_field = ""
    best_score = 0.0
    for alias, field in _LOOKUP.items():
        score = SequenceMatcher(None, key, alias).ratio()
        if score > best_score:
            best_field = field
            best_score = score
    if best_score >= FUZZY_THRESHOLD:
        return best_field, best_score
    return "", 0.0


def detect_mapping(headers: list[str]) -> list[dict]:
    """Map spreadsheet columns onto canonical fields.

    Returns one entry per input column::

        {"source_column": str, "target_field": str, "confidence": float, "required": bool}

    ``target_field`` is an empty string for columns that could not be mapped.
    When two columns map onto the same field the first (left-most) one wins
    and the other is reported as unmapped.
    """
    mapping: list[dict] = []
    taken: set[str] = set()
    for header in headers or []:
        target, confidence = _match_field(normalize_header(header))
        if target and target in taken:
            target, confidence = "", 0.0
        elif target:
            taken.add(target)
        mapping.append(
            {
                "source_column": str(header),
                "target_field": target,
                "confidence": round(float(confidence), 3),
                "required": target in REQUIRED_FIELDS,
            }
        )
    return mapping


def mapping_to_fields(mapping: list[dict]) -> dict[str, str]:
    """Convert a detected mapping into ``{source_column: target_field}``."""
    fields: dict[str, str] = {}
    for entry in mapping or []:
        source = str(entry.get("source_column", ""))
        target = str(entry.get("target_field", "") or "")
        if source and target:
            fields[source] = target
    return fields


def required_fields_present(mapping: list[dict]) -> list[str]:
    """Return the required canonical fields that are missing from a mapping."""
    mapped = {str(e.get("target_field", "") or "") for e in mapping or []}
    return sorted(field for field in REQUIRED_FIELDS if field not in mapped)
