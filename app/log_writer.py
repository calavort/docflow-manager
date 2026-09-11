from __future__ import annotations

from datetime import datetime

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
