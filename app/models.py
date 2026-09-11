from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import math


@dataclass(slots=True)
class SelectedFile:
    id: str
    name: str
    full_path: str
    extension: str
    size: int
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "fullPath": self.full_path,
            "extension": self.extension,
            "size": self.size,
            "status": self.status,
        }


@dataclass(slots=True)
class AddFilesResult:
    added_count: int
    messages: list[str] = field(default_factory=list)


@dataclass(slots=True)
class NamingSuggestion:
    code: str
    sheet_start: int
    total_sheets: int
    revision: str
    has_suggestion: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "sheetStart": self.sheet_start,
            "totalSheets": self.total_sheets,
            "revision": self.revision,
            "hasSuggestion": self.has_suggestion,
        }


@dataclass(slots=True)
class RenamePreviewItem:
    id: str
    original_name: str
    new_name: str
    source_path: str
    output_path: str
    code: str
    sheet: int
    total_sheets: int
    revision: str
    is_recognized: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "originalName": self.original_name,
            "newName": self.new_name,
            "sourcePath": self.source_path,
            "outputPath": self.output_path,
            "code": self.code,
            "sheet": self.sheet,
            "totalSheets": self.total_sheets,
            "revision": self.revision,
            "isRecognized": self.is_recognized,
            "message": self.message,
        }


@dataclass(slots=True)
class BatchStatus:
    file_count: int
    error_count: int
    validation_percent: int
    active_operation: str
    output_folder: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "fileCount": self.file_count,
            "errorCount": self.error_count,
            "validationPercent": self.validation_percent,
            "activeOperation": self.active_operation,
            "outputFolder": self.output_folder,
        }


@dataclass(slots=True)
class OperationLogEntry:
    level: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"level": self.level, "message": self.message}


@dataclass(slots=True)
class OperationResult:
    success: bool = False
    cancelled: bool = False
    requires_overwrite_confirmation: bool = False
    output_folder: str = ""
    log_file: str = ""
    output_files: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    logs: list[OperationLogEntry] = field(default_factory=list)


@dataclass(slots=True)
class DwgLayoutOptions:
    """Disposicao dos desenhos na uniao de DWG.

    Zero significa automatico: colunas/linhas sao deduzidas da quantidade de
    arquivos e o espacamento e calculado pelo tamanho dos desenhos.
    """

    columns: int = 0
    rows: int = 0
    gap_x: float = 0.0
    gap_y: float = 0.0
    order: str = "row"
    uniform: bool = True

    @classmethod
    def from_dict(cls, raw: Any) -> "DwgLayoutOptions":
        data = raw if isinstance(raw, dict) else {}
        order = str(data.get("order", "row") or "row").strip().lower()
        return cls(
            columns=max(0, OperationOptions._int(data.get("columns", 0), 0)),
            rows=max(0, OperationOptions._int(data.get("rows", 0), 0)),
            gap_x=max(0.0, OperationOptions._float(data.get("gapX", 0.0), 0.0)),
            gap_y=max(0.0, OperationOptions._float(data.get("gapY", 0.0), 0.0)),
            order="column" if order in {"column", "coluna", "vertical"} else "row",
            uniform=OperationOptions._bool(data.get("uniform", True), True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "gapX": self.gap_x,
            "gapY": self.gap_y,
            "order": self.order,
            "uniform": self.uniform,
        }


@dataclass(slots=True)
class OperationOptions:
    operation: str = "rename"
    revision: str = "Rev.0"
    sheet_start: int = 1
    total_sheets: int = 0
    split_intervals: str = ""
    output_pattern: str = "{codigo} FL{folha}-{total} {rev}"
    output_file_name: str = ""
    generate_log: bool = False
    preserve_layouts: bool = False
    overwrite_confirmed: bool = False
    dwg_layout: DwgLayoutOptions = field(default_factory=lambda: DwgLayoutOptions())

    @staticmethod
    def _text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        return str(value)

    @staticmethod
    def _bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes", "sim"}
        if isinstance(value, (int, float)):
            return bool(value)
        return default

    @staticmethod
    def _int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
            if not value:
                return default
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        return number if math.isfinite(number) else default

    @classmethod
    def from_message(cls, root: dict[str, Any]) -> "OperationOptions":
        nested = root.get("options")
        options = nested if isinstance(nested, dict) else root
        operation = cls.normalize_operation(root.get("operation", options.get("operation", "rename")))
        revision = cls.normalize_revision(cls._text(options.get("revision", "Rev.0"), "Rev.0"))
        output_pattern = cls._text(options.get("outputPattern", "{codigo} FL{folha}-{total} {rev}"), "").strip()
        if not output_pattern:
            output_pattern = "{codigo} FL{folha}-{total} {rev}"
        return cls(
            operation=operation,
            revision=revision,
            sheet_start=max(1, cls._int(options.get("sheetStart", 1), 1)),
            total_sheets=cls._int(options.get("totalSheets", 0), 0),
            split_intervals=cls._text(options.get("splitIntervals", ""), "").strip(),
            output_pattern=output_pattern,
            output_file_name=cls._text(options.get("outputFileName", ""), "").strip(),
            generate_log=cls._bool(options.get("generateLog", False)),
            preserve_layouts=cls._bool(options.get("preserveLayouts", False)),
            dwg_layout=DwgLayoutOptions.from_dict(options.get("dwgLayout")),
            overwrite_confirmed=cls._bool(options.get("overwriteConfirmed", False)) or cls._bool(root.get("overwriteConfirmed", False)),
        )

    @staticmethod
    def normalize_operation(operation: Any) -> str:
        key = str(operation or "rename").strip().lower()
        return {
            "renamepdf": "rename",
            "renamedwg": "rename",
            "rename": "rename",
            "mergepdf": "mergePdf",
            "unirpdf": "mergePdf",
            "splitpdf": "splitPdf",
            "separarpdf": "splitPdf",
            "mergedwg": "mergeDwg",
            "unirdwg": "mergeDwg",
        }.get(key, "rename")

    @staticmethod
    def normalize_revision(revision: str) -> str:
        value = (revision or "0").strip() or "0"
        return value if value.lower().startswith("rev.") else f"Rev.{value}"
