from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(slots=True)
class DetectedName:
    code: str
    sheet: int
    total_sheets: int
    revision: str
    recognized: bool
    pattern: str


EXISTING_STANDARD_RE = re.compile(r"^(?P<code>.+?)\s+FL\.?\s*(?P<sheet>\d+)\s*-\s*(?P<total>\d+)\s+(?P<revision>Rev\.\s*[A-Za-z0-9]+)$", re.I)
DRAWING_RE = re.compile(r"\bDESENHO\s*(?P<sheet>\d+)\b", re.I)
DRAWING_PREFIX_RE = re.compile(r"^\s*DESENHO\s*\d+\s*-?\s*", re.I)
FOLHA_RE = re.compile(r"\bFL\.?\s*(?P<sheet>\d+)\s*-\s*(?P<total>\d+)\b", re.I)
SPLIT_SHEET_RE = re.compile(r"(?:^|[\s_-])SPL\s*[-_ ]?(?P<sheet>\d{1,4})(?=\b|[\s_-]|$)", re.I)
REVISION_RE = re.compile(r"\b(?P<revision>Rev\.\s*[A-Za-z0-9]+)\b", re.I)
TRAILING_SHEET_RE = re.compile(r"(?:^|[\s_-])(?P<sheet>\d{1,4})\s*$", re.I)
CODE_RE = re.compile(r"\b[A-Z0-9]{2,}(?:-[A-Z0-9]+){2,}\b", re.I)


def normalize_revision(revision: str) -> str:
    value = (revision or "0").strip() or "0"
    return value if value.lower().startswith("rev.") else f"Rev.{value}"


def detect(file_name: str, fallback_sheet: int) -> DetectedName:
    name = Path(file_name).stem.strip()
    drawing = DRAWING_RE.search(name)
    folha = FOLHA_RE.search(name)
    split = SPLIT_SHEET_RE.search(name)
    revision = REVISION_RE.search(name)

    if drawing:
        sheet = int(drawing.group("sheet"))
    elif folha:
        sheet = int(folha.group("sheet"))
    elif split:
        sheet = int(split.group("sheet"))
    else:
        trailing = TRAILING_SHEET_RE.search(name)
        sheet = int(trailing.group("sheet")) if trailing else fallback_sheet

    total_sheets = int(folha.group("total")) if folha else 0
    revision_text = normalize_revision(revision.group("revision")) if revision else "Rev.0"

    existing = EXISTING_STANDARD_RE.match(name)
    if existing:
        return DetectedName(
            existing.group("code").strip(),
            int(existing.group("sheet")),
            int(existing.group("total")),
            normalize_revision(existing.group("revision")),
            True,
            "Padrao DocFlow existente",
        )

    cleaned = DRAWING_PREFIX_RE.sub("", name).strip()
    cleaned = FOLHA_RE.sub("", cleaned).strip()
    cleaned = SPLIT_SHEET_RE.sub("", cleaned).strip("-_ ")
    cleaned = REVISION_RE.sub("", cleaned).strip()

    code_match = CODE_RE.search(cleaned)
    if code_match:
        return DetectedName(
            code_match.group(0).strip(),
            sheet,
            total_sheets,
            revision_text,
            True,
            "Folha + codigo tecnico" if drawing or folha else "Codigo tecnico",
        )

    fallback_code = re.sub(r"\s+", "-", cleaned).strip("- ")
    return DetectedName(fallback_code, sheet, total_sheets, revision_text, False, "Ajuste manual recomendado")
