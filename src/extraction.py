"""Document extraction: turns a corpus file into an ExtractedDocument with an
outline of citable section/sheet references, never just raw page numbers.

Three format-specific extractors (docx/xlsx/pdf) converge on the same
ExtractedDocument shape so downstream stages don't need to know what format a
document started as.
"""
from __future__ import annotations

import glob
import os
import re

from .manifest import DocFormat, ManifestEntry, get
from .models import ExtractedDocument, OutlineEntry, ReadStatus

_HEADING_STYLE_RE = re.compile(r"^heading", re.IGNORECASE)
# Matches lines like "Item 6 Financial Crime Remediation Programme",
# "Section 5 Statement on Remediation Activity", "1. Executive Summary"
_NUMBERED_LABEL_RE = re.compile(
    r"^(item|section|appendix)\s+\d+[:.\s]|^\d+(\.\d+)*[\.\)]\s+\S"
    , re.IGNORECASE,
)

# PDFs carry no paragraph-style metadata (unlike docx), so headings must be
# guessed from text shape alone. This corpus's PDF headings (e.g. "Priority
# Area One — Financial Crime Controls", "Regulatory Commentary") are short,
# title-cased lines with no trailing sentence punctuation — distinct from
# wrapped body-paragraph lines, which almost always contain a lowercase
# non-stopword and/or run past ~80 characters.
_TITLE_CASE_STOPWORDS = {
    "of", "the", "and", "for", "to", "in", "at", "a", "an", "on", "with", "this",
}


def _looks_title_case(line: str) -> bool:
    words = line.split()
    if not words or len(words) > 10:
        return False
    for word in words:
        core = word.strip("-:,;—")
        if not core:
            continue
        if core.lower() in _TITLE_CASE_STOPWORDS:
            continue
        if not core[0].isupper():
            return False
    return True


def resolve_path(entry: ManifestEntry, corpus_dir: str) -> str | None:
    matches = glob.glob(os.path.join(corpus_dir, entry.filename_glob))
    matches = [m for m in matches if os.path.isfile(m)]
    if len(matches) != 1:
        return None
    return matches[0]


def extract_document(doc_id: str, corpus_dir: str) -> ExtractedDocument:
    entry = get(doc_id)
    path = resolve_path(entry, corpus_dir)
    if path is None:
        return ExtractedDocument(
            doc_id=doc_id,
            status=ReadStatus.FAILED_TO_PROCESS,
            error=f"could not uniquely resolve a file for glob '{entry.filename_glob}' in {corpus_dir!r}",
        )
    try:
        if entry.fmt == DocFormat.DOCX:
            return _extract_docx(doc_id, path)
        if entry.fmt == DocFormat.XLSX:
            return _extract_xlsx(doc_id, path)
        if entry.fmt == DocFormat.PDF:
            return _extract_pdf(doc_id, path)
        raise ValueError(f"unknown format {entry.fmt}")
    except Exception as exc:  # noqa: BLE001 - deliberately broad: any parse failure routes to Coverage Gaps
        return ExtractedDocument(doc_id=doc_id, status=ReadStatus.FAILED_TO_PROCESS, error=str(exc))


def _finalize(doc_id: str, outline: list[OutlineEntry], text_parts: list[str]) -> ExtractedDocument:
    full_text = "\n".join(p for p in text_parts if p.strip())
    if not full_text.strip():
        return ExtractedDocument(doc_id=doc_id, status=ReadStatus.EMPTY, outline=[], full_text="")
    return ExtractedDocument(doc_id=doc_id, status=ReadStatus.OK, outline=outline, full_text=full_text)


def _extract_docx(doc_id: str, path: str) -> ExtractedDocument:
    import docx  # python-docx

    document = docx.Document(path)
    outline: list[OutlineEntry] = []
    text_parts: list[str] = []
    current_ref: str | None = None
    current_preview: list[str] = []

    def flush():
        if current_ref is not None:
            preview = " ".join(current_preview).strip()[:200]
            outline.append(OutlineEntry(ref=current_ref, preview=preview))

    for para in document.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        is_heading = bool(_HEADING_STYLE_RE.match(para.style.name or "")) or bool(
            _NUMBERED_LABEL_RE.match(text)
        )
        if is_heading:
            flush()
            current_ref = text
            current_preview = []
        else:
            text_parts.append(text)
            if current_ref is not None:
                current_preview.append(text)
    flush()

    # Also sweep tables (board minutes / org charts sometimes use them)
    for table in document.tables:
        for row in table.rows:
            row_text = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
            if row_text:
                text_parts.append(row_text)

    return _finalize(doc_id, outline, text_parts)


def _extract_xlsx(doc_id: str, path: str) -> ExtractedDocument:
    import openpyxl

    wb = openpyxl.load_workbook(path, data_only=True)
    outline: list[OutlineEntry] = []
    text_parts: list[str] = []
    for sheet in wb.worksheets:
        rows_text = []
        for row in sheet.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                rows_text.append(" | ".join(cells))
        sheet_text = "\n".join(rows_text)
        if sheet_text.strip():
            outline.append(OutlineEntry(ref=sheet.title, preview=sheet_text[:200]))
            text_parts.append(f"[sheet: {sheet.title}]\n{sheet_text}")

    return _finalize(doc_id, outline, text_parts)


def _extract_pdf(doc_id: str, path: str) -> ExtractedDocument:
    import pypdf

    reader = pypdf.PdfReader(path)
    outline: list[OutlineEntry] = []
    text_parts: list[str] = []
    current_ref: str | None = None
    current_preview: list[str] = []

    def flush():
        if current_ref is not None:
            preview = " ".join(current_preview).strip()[:200]
            outline.append(OutlineEntry(ref=current_ref, preview=preview))

    for page in reader.pages:
        page_text = page.extract_text() or ""
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            looks_like_heading = (
                bool(_NUMBERED_LABEL_RE.match(line))
                or (len(line) < 80 and line.isupper())
                or (
                    len(line) < 80
                    and not line.endswith((".", "?", "!", ",", ";", ":"))
                    and _looks_title_case(line)
                )
            )
            if looks_like_heading:
                flush()
                current_ref = line
                current_preview = []
            else:
                text_parts.append(line)
                if current_ref is not None:
                    current_preview.append(line)
    flush()

    return _finalize(doc_id, outline, text_parts)
