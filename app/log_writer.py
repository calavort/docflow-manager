from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import OperationLogEntry


class LogWriter:
    def __init__(self) -> None:
        self.entries: list[OperationLogEntry] = []

    def _add(self, level: str, message: str) -> None:
        self.entries.append(OperationLogEntry(level, f"[{datetime.now():%H:%M:%S}] {message}"))

    def info(self, message: str) -> None:
        self._add("info", message)

    def warning(self, message: str) -> None:
        self._add("warning", message)

    def error(self, message: str) -> None:
        self._add("error", message)

    def save(self, output_folder: str, operation: str) -> str:
        folder = Path(output_folder)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"DocFlow_Log_{datetime.now():%Y%m%d_%H%M%S}_{operation}.log"
        lines = [
            "DocFlow Manager - Log de Operacao",
            f"Operacao: {operation}",
            f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
        ]
        lines.extend(f"{entry.level.upper()} {entry.message}" for entry in self.entries)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
        return str(path)
