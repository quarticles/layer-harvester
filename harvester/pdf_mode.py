"""
PDF V2 extension for the layer harvester.

Loaded only when --usage pdf is passed. Provides:
  - active_columns()        column list with PDF V2 inserted
  - collect_pdf_data()      per-file PDF type counts
  - sort_key()              canonical ordering for PDF types in summaries
  - PDF_COLUMN_DESCRIPTION  for injection into the Legend sheet
"""

from harvester.core import BASE_COLUMNS, NO_PDF_LABEL, PDF_HAZARD_PREFIX

PDF_COLUMN    = ("pdf_v2", "PDF V2")
PDF_COL_ORDER = ["global:risk", "global:additional", "local"]

PDF_COLUMN_DESCRIPTION = (
    "PDF V2",
    f"Suffix extracted from the '{PDF_HAZARD_PREFIX}<keyword>' entry in the "
    f"keyword_list (e.g. 'local', 'global:risk', 'global:additional'). "
    f"Shows '{NO_PDF_LABEL}' when no such keyword is present.",
)


def active_columns() -> list:
    """Return BASE_COLUMNS with PDF V2 inserted after Is Global."""
    cols = list(BASE_COLUMNS)
    idx = next((i for i, (k, _) in enumerate(cols) if k == "is_global"), len(cols) - 1)
    cols.insert(idx + 1, PDF_COLUMN)
    return cols


def sort_key(t: str) -> tuple:
    """Canonical sort order: global:risk → global:additional → local → others → NO_PDF_LABEL.

    All tuples are (int, str) so comparisons never raise TypeError.
    Zero-padding the index preserves numeric order if PDF_COL_ORDER ever grows past 9 entries.
    """
    if t == NO_PDF_LABEL:
        return (2, "")
    try:
        return (0, f"{PDF_COL_ORDER.index(t):04d}")
    except ValueError:
        return (1, t)


def collect_pdf_data(rows: list) -> tuple[list, dict]:
    """
    Scan a list of extracted rows and return:
      - all_types: unique pdf_v2 values in insertion order (unsorted)
      - counts:    dict mapping pdf_v2 value → count
    """
    all_types: list[str] = []
    counts: dict[str, int] = {}
    for r in rows:
        tag = r.get("pdf_v2", NO_PDF_LABEL)
        counts[tag] = counts.get(tag, 0) + 1
        if tag not in all_types:
            all_types.append(tag)
    return all_types, counts
