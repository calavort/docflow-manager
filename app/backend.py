from __future__ import annotations

import ctypes
import json
import re
import os
import subprocess
import tempfile
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Any

from .file_operation_service import FileOperationService
from .models import OperationOptions
from .utils import desktop_directory, natural_key, open_folder


class DocFlowBackend:
    """Backend chamado diretamente pelo Javascript do pywebview.

    A V3 evita depender de mensagens Python -> Javascript via ``run_js`` para as
    operações principais. Cada comando retorna seu resultado diretamente para a
    Promise do Javascript. Isso torna seleção de arquivos, pasta de saída e
    operações independentes do canal reverso do WebView2.
    """

    def __init__(self) -> None:
        self.window = None
        self.operations = FileOperationService()
        self.operation_running = False
        self.operation_cancel: threading.Event | None = None
        self._lock = threading.RLock()
        self._pending_drop_paths: list[str] = []

    def attach_window(self, window) -> None:
        self.window = window

    # ------------------------------------------------------------------
    # API única exposta ao Javascript
    # ------------------------------------------------------------------
    def post_message(self, message: dict[str, Any] | str) -> dict[str, Any]:
        try:
            root = json.loads(message) if isinstance(message, str) else dict(message or {})
            command = str(root.get("command", ""))

            if command == "ready":
                return self._state_response("ready")
            if command == "selectFiles":
                return self._select_files(root)
            if command == "chooseOutputFolder":
                return self._choose_output_folder()
            if command == "openOutputFolder":
                return self._open_output_folder()
            if command == "addDroppedFiles":
                return self._add_paths_from_drop(root.get("paths") or [])
            if command == "consumeDroppedFiles":
                with self._lock:
                    pending = list(self._pending_drop_paths)
                    self._pending_drop_paths.clear()
                return self._add_paths_from_drop(pending) if pending else {"type": "cancelled"}
            if command == "clearFiles":
                if self.operation_running:
                    return self._notice("warning", "Operação em andamento", "Aguarde a operação atual terminar.")
                self.operations.clear()
                return self._state_response("filesChanged", toast="Lista limpa.")
            if command == "generatePreview":
                options = OperationOptions.from_message(root)
                preview = self.operations.generate_rename_preview(options)
                return {
                    "type": "previewReady",
                    "items": [item.to_dict() for item in preview],
                    "status": self.operations.get_status(preview).to_dict(),
                    "namingSuggestion": self.operations.get_naming_suggestion().to_dict(),
                }
            if command == "startOperation":
                return self._start_operation(root)
            if command == "cancelOperation":
                return self._cancel_operation()
            if command == "windowMoveTo":
                x = int(float(root.get("x", 0) or 0))
                y = int(float(root.get("y", 0) or 0))
                if not self._window_move_to(x, y):
                    return self._notice("error", "Mover janela", "Nao foi possivel mover a janela.")
                return {"type": "ok"}
            if command == "windowMinimize":
                self._window_minimize()
                return {"type": "ok"}
            if command == "windowClose":
                self._window_close()
                return {"type": "ok"}
            if command == "windowSetTopMost":
                enabled = bool(root.get("enabled", False))
                applied = self._window_set_topmost(enabled)
                if not applied:
                    return self._notice("error", "Manter na frente", "Nao foi possivel aplicar o modo manter na frente.")
                return {"type": "ok", "topMost": enabled}

            return self._notice("warning", "Comando não reconhecido", command or "Comando vazio.")
        except Exception as exc:
            return self._error_response(str(exc))


    def on_dom_drop(self, event: dict[str, Any]) -> None:
        """Captura caminhos completos fornecidos pelo DOM do pywebview.

        O Javascript consome esses caminhos em seguida com ``consumeDroppedFiles``;
        assim não dependemos de executar Javascript de volta a partir deste evento.
        """
        try:
            transfer = event.get("dataTransfer") or event.get("domTransfer") or {}
            files = transfer.get("files") or []
            paths: list[str] = []
            for item in files:
                path = item.get("pywebviewFullPath") or item.get("path")
                if path:
                    paths.append(str(path))
            if paths:
                with self._lock:
                    existing = {os.path.normcase(item) for item in self._pending_drop_paths}
                    for path in paths:
                        if os.path.normcase(path) not in existing:
                            self._pending_drop_paths.append(path)
                            existing.add(os.path.normcase(path))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Seleção de arquivos / pasta
    # ------------------------------------------------------------------
    def _select_files(self, root: dict[str, Any]) -> dict[str, Any]:
        if self.operation_running:
            return self._notice("warning", "Operação em andamento", "Aguarde a operação atual terminar.")

        operation = OperationOptions.from_message(root).operation
        paths = self._native_select_files(operation)
        if not paths:
            return {"type": "cancelled"}

        result = self.operations.add_files(paths)
        toast = result.messages[0] if result.messages else "Arquivos adicionados."
        return self._state_response("filesChanged", toast=toast, logs=result.messages)

    def _choose_output_folder(self) -> dict[str, Any]:
        initial = self.operations.get_current_output_folder()
        folder = self._native_select_folder(initial)
        if not folder:
            return {"type": "cancelled"}

        self.operations.set_output_folder(folder)
        return self._state_response(
            "statusChanged",
            toast="Pasta de saída definida.",
            outputFolder=folder,
        )

    def _open_output_folder(self) -> dict[str, Any]:
        folder = self.operations.get_current_output_folder()
        try:
            open_folder(folder)
            return {"type": "notice", "level": "info", "message": "Pasta de saída aberta.", "outputFolder": folder}
        except Exception as exc:
            return self._notice("error", "Não foi possível abrir a pasta", f"{folder}\n\n{exc}")

    def _add_paths_from_drop(self, paths) -> dict[str, Any]:
        if self.operation_running:
            return self._notice("warning", "Operação em andamento", "Aguarde a operação atual terminar.")

        original = [str(path) for path in paths]
        ordered = sorted(original, key=lambda p: (natural_key(str(Path(p).parent)), natural_key(Path(p).name)))
        result = self.operations.add_files(ordered)
        logs = list(result.messages)
        if result.added_count > 0 and [os.path.normcase(p) for p in original] != [os.path.normcase(p) for p in ordered]:
            logs.append("Arquivos arrastados ordenados por nome para manter a sequência das folhas.")
        return self._state_response(
            "filesChanged",
            toast=(result.messages[0] if result.messages else "Arquivos adicionados."),
            logs=logs,
        )

    # ------------------------------------------------------------------
    # Operações
    # ------------------------------------------------------------------
    def _start_operation(self, root: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self.operation_running:
                return self._notice("warning", "Operação em andamento", "Aguarde a operação atual terminar.")
            self.operation_running = True
            self.operation_cancel = threading.Event()

        options = OperationOptions.from_message(root)
        try:
            result = self.operations.start(options, self.operation_cancel)
        finally:
            with self._lock:
                self.operation_running = False
                self.operation_cancel = None

        if result.requires_overwrite_confirmation:
            return {
                "type": "confirmationRequired",
                "title": "Confirmar sobrescrita",
                "message": "Alguns arquivos já existem na pasta de saída. Deseja sobrescrever?",
                "conflicts": result.conflicts,
            }

        response: dict[str, Any] = {
            "type": "operationCompleted",
            "success": result.success,
            "cancelled": result.cancelled,
            "outputFolder": result.output_folder,
            "outputFiles": result.output_files,
            "logFile": result.log_file,
            "logs": [entry.to_dict() for entry in result.logs],
            "message": self._operation_message(options.operation, result.success, result.cancelled, result.logs),
        }


        if result.success:
            self.operations.clear_after_successful_operation()
            response["files"] = []
            response["status"] = self.operations.get_status([]).to_dict()
            response["namingSuggestion"] = self.operations.get_naming_suggestion().to_dict()
        else:
            response["files"] = [file.to_dict() for file in self.operations.files]
            response["status"] = self.operations.get_status([]).to_dict()

        return response

    def _cancel_operation(self) -> dict[str, Any]:
        if not self.operation_running or self.operation_cancel is None:
            return self._notice("warning", "Nenhuma operação em andamento", "Não há operação ativa para cancelar.")
        self.operation_cancel.set()
        return self._notice("warning", "Cancelamento solicitado", "A operação será encerrada no próximo ponto seguro.")

    @staticmethod
    def _clean_log_message(message: str) -> str:
        """Remove o horário do log: o card do programa mostra só a mensagem."""
        text = str(message or "").strip()
        if text.startswith("[") and "]" in text[:12]:
            text = text.split("]", 1)[1].strip()
        if text and not text.endswith((".", "!", "?")):
            text += "."
        return text

    @classmethod
    def _operation_message(cls, operation: str, success: bool, cancelled: bool, logs) -> str:
        if success:
            return {
                "rename": "Renomeação concluída com sucesso.",
                "mergePdf": "União de PDF concluída com sucesso.",
                "splitPdf": "Separação de PDF concluída com sucesso.",
                "mergeDwg": "União de DWG concluída com sucesso.",
            }.get(operation, "Operação realizada com sucesso.")
        if cancelled:
            return "Operação cancelada pelo usuário."

        lead = {
            "rename": "Não foi possível renomear os arquivos.",
            "mergePdf": "Não foi possível unir os PDFs.",
            "splitPdf": "Não foi possível separar o PDF.",
            "mergeDwg": "Não foi possível unir os DWGs.",
        }.get(operation, "A operação não foi concluída.")
        errors = [entry.message for entry in logs if getattr(entry, "level", "") == "error"]
        detail = cls._clean_log_message(errors[-1]) if errors else ""
        if not cls._is_short_detail(detail):
            return lead
        # O detalhe ja pode ser uma frase completa; evita "Nao foi possivel" repetido.
        if detail.lower().startswith(("não foi possível", "nao foi possivel")):
            return detail
        return f"{lead} {detail}"

    @staticmethod
    def _is_short_detail(detail: str) -> bool:
        """Detalhes tecnicos (codigos COM, textos longos) ficam so no log."""
        if not detail or len(detail) > 110:
            return False
        return re.search(r"-?\d{7,}", detail) is None

    # ------------------------------------------------------------------
    # Respostas de estado
    # ------------------------------------------------------------------
    def _state_response(self, response_type: str, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "type": response_type,
            "files": [file.to_dict() for file in self.operations.files],
            "status": self.operations.get_status([]).to_dict(),
            "namingSuggestion": self.operations.get_naming_suggestion().to_dict(),
        }
        payload.update(extra)
        return payload

    @staticmethod
    def _notice(level: str, title: str, message: str) -> dict[str, Any]:
        return {"type": "notice", "level": level, "title": title, "message": message}

    def _error_response(self, message: str) -> dict[str, Any]:
        return {
            "type": "backendError",
            "message": message,
            "files": [file.to_dict() for file in self.operations.files],
            "status": self.operations.get_status([]).to_dict(),
        }

    # ------------------------------------------------------------------
    # Diálogos nativos do Windows sem console/flash
    # ------------------------------------------------------------------
    def _native_select_files(self, operation: str) -> list[str]:
        if os.name == "nt":
            try:
                return self._powershell_file_dialog(operation)
            except Exception:
                pass

        # Fallback do próprio pywebview.
        if self.window is None:
            return []
        try:
            import webview
            dialog_open = getattr(webview.FileDialog, "OPEN", getattr(webview.FileDialog, "LOAD", 10))
            if operation == "mergeDwg":
                file_types = ("DWG (*.dwg)",)
            elif operation in {"mergePdf", "splitPdf"}:
                file_types = ("PDF (*.pdf)",)
            else:
                file_types = ("Documentos técnicos (*.pdf;*.dwg)", "PDF (*.pdf)", "DWG (*.dwg)")
            selected = self.window.create_file_dialog(dialog_open, allow_multiple=True, file_types=file_types)
            return [str(item) for item in (selected or [])]
        except Exception:
            return []

    def _native_select_folder(self, initial: str) -> str:
        if os.name == "nt":
            try:
                return self._powershell_folder_dialog(initial)
            except Exception:
                pass

        if self.window is None:
            return ""
        try:
            import webview
            selected = self.window.create_file_dialog(webview.FileDialog.FOLDER, directory=initial or "")
            if not selected:
                return ""
            return str(selected[0] if isinstance(selected, (list, tuple)) else selected)
        except Exception:
            return ""

    @staticmethod
    def _powershell_exe() -> str:
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        candidate = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        return candidate if os.path.isfile(candidate) else "powershell.exe"

    @staticmethod
    def _hidden_creation_flags() -> int:
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if os.name == "nt" else 0

    def _powershell_file_dialog(self, operation: str) -> list[str]:
        if operation == "mergeDwg":
            filter_text = "DWG (*.dwg)|*.dwg"
        elif operation in {"mergePdf", "splitPdf"}:
            filter_text = "PDF (*.pdf)|*.pdf"
        else:
            filter_text = "Documentos técnicos (*.pdf;*.dwg)|*.pdf;*.dwg|PDF (*.pdf)|*.pdf|DWG (*.dwg)|*.dwg"

        initial = desktop_directory()
        if self.operations.files:
            initial = os.path.dirname(self.operations.files[0].full_path) or initial

        with tempfile.TemporaryDirectory(prefix="docflow_dialog_") as tmp:
            result_file = os.path.join(tmp, "selection.txt")
            env = os.environ.copy()
            env["DOCFLOW_RESULT"] = result_file
            env["DOCFLOW_INITIAL"] = initial
            env["DOCFLOW_FILTER"] = filter_text
            script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dlg = New-Object System.Windows.Forms.OpenFileDialog
$dlg.Multiselect = $true
$dlg.CheckFileExists = $true
$dlg.CheckPathExists = $true
$dlg.RestoreDirectory = $true
$dlg.Filter = $env:DOCFLOW_FILTER
if (Test-Path -LiteralPath $env:DOCFLOW_INITIAL) { $dlg.InitialDirectory = $env:DOCFLOW_INITIAL }
if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [System.IO.File]::WriteAllLines($env:DOCFLOW_RESULT, $dlg.FileNames, [System.Text.UTF8Encoding]::new($false))
}
"""
            completed = subprocess.run(
                [self._powershell_exe(), "-NoLogo", "-NoProfile", "-STA", "-Command", script],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=self._hidden_creation_flags(),
                timeout=3600,
                check=False,
            )
            if completed.returncode != 0 or not os.path.isfile(result_file):
                return []
            with open(result_file, "r", encoding="utf-8-sig") as handle:
                return [line.strip() for line in handle if line.strip()]

    def _powershell_folder_dialog(self, initial: str) -> str:
        initial = initial if initial and os.path.isdir(initial) else desktop_directory()
        with tempfile.TemporaryDirectory(prefix="docflow_dialog_") as tmp:
            result_file = os.path.join(tmp, "selection.txt")
            env = os.environ.copy()
            env["DOCFLOW_RESULT"] = result_file
            env["DOCFLOW_INITIAL"] = initial
            script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dlg = New-Object System.Windows.Forms.FolderBrowserDialog
$dlg.Description = 'Selecione a pasta de saída'
$dlg.ShowNewFolderButton = $true
if (Test-Path -LiteralPath $env:DOCFLOW_INITIAL) { $dlg.SelectedPath = $env:DOCFLOW_INITIAL }
if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [System.IO.File]::WriteAllText($env:DOCFLOW_RESULT, $dlg.SelectedPath, [System.Text.UTF8Encoding]::new($false))
}
"""
            completed = subprocess.run(
                [self._powershell_exe(), "-NoLogo", "-NoProfile", "-STA", "-Command", script],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=self._hidden_creation_flags(),
                timeout=3600,
                check=False,
            )
            if completed.returncode != 0 or not os.path.isfile(result_file):
                return ""
            return Path(result_file).read_text(encoding="utf-8-sig").strip()

    # ------------------------------------------------------------------
    # Janela
    # ------------------------------------------------------------------
    @staticmethod
    def _handle_to_int(handle) -> int:
        if handle is None:
            return 0
        for method_name in ("ToInt64", "ToInt32"):
            method = getattr(handle, method_name, None)
            if callable(method):
                try:
                    return int(method())
                except Exception:
                    pass
        try:
            return int(handle)
        except Exception:
            return 0

    def _is_valid_hwnd(self, hwnd: int) -> bool:
        if os.name != "nt" or not hwnd:
            return False
        try:
            return bool(ctypes.windll.user32.IsWindow(wintypes.HWND(hwnd)))
        except Exception:
            return False

    def _find_hwnd_by_process_and_title(self) -> int:
        if os.name != "nt":
            return 0
        title = str(getattr(self.window, "title", "") or "DocFlow Manager")
        current_pid = os.getpid()
        user32 = ctypes.windll.user32
        hwnds: list[int] = []

        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        user32.GetWindowTextLengthW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL

        def callback(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) != current_pid:
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value == title:
                hwnds.append(self._handle_to_int(hwnd))
            return True

        user32.EnumWindows(enum_proc(callback), 0)
        return hwnds[0] if hwnds else 0

    def _hwnd(self) -> int:
        try:
            native = getattr(self.window, "native", None)
            hwnd = self._handle_to_int(getattr(native, "Handle", None))
            if self._is_valid_hwnd(hwnd):
                return hwnd
        except Exception:
            pass
        return self._find_hwnd_by_process_and_title()

    def _window_minimize(self) -> None:
        hwnd = self._hwnd()
        if os.name == "nt" and hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 6)
        elif self.window:
            self.window.minimize()

    def _window_close(self) -> None:
        hwnd = self._hwnd()
        if os.name == "nt" and hwnd:
            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
        elif self.window:
            self.window.destroy()

    def _window_move_to(self, x: int, y: int) -> bool:
        hwnd = self._hwnd()
        if os.name == "nt" and hwnd:
            try:
                user32 = ctypes.windll.user32
                user32.SetWindowPos.argtypes = [
                    wintypes.HWND,
                    wintypes.HWND,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_uint,
                ]
                user32.SetWindowPos.restype = wintypes.BOOL
                flags = 0x0001 | 0x0004 | 0x0040
                if user32.SetWindowPos(wintypes.HWND(hwnd), None, int(x), int(y), 0, 0, flags):
                    return True
            except Exception:
                pass

        if self.window:
            try:
                self.window.move(int(x), int(y))
                return True
            except Exception:
                pass

        return False

    def _set_native_topmost_property(self, enabled: bool) -> bool:
        native = getattr(self.window, "native", None)
        if native is None or not hasattr(native, "TopMost"):
            return False
        try:
            if bool(getattr(native, "InvokeRequired", False)):
                from System import Action

                native.Invoke(Action(lambda: setattr(native, "TopMost", enabled)))
            else:
                native.TopMost = enabled
            return bool(native.TopMost) == enabled
        except Exception:
            return False

    def _apply_hwnd_topmost(self, hwnd: int, enabled: bool) -> bool:
        if os.name != "nt" or not self._is_valid_hwnd(hwnd):
            return False
        try:
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            user32.SetWindowPos.restype = wintypes.BOOL
            insert_after = wintypes.HWND(-1 if enabled else -2)
            flags = 0x0001 | 0x0002 | 0x0040
            if not enabled:
                flags |= 0x0010
            if not user32.SetWindowPos(wintypes.HWND(hwnd), insert_after, 0, 0, 0, 0, flags):
                return False
            if enabled:
                user32.SetForegroundWindow(wintypes.HWND(hwnd))
            return True
        except Exception:
            return False

    def _window_set_topmost(self, enabled: bool) -> bool:
        applied = False
        if self.window:
            try:
                self.window.on_top = enabled
                applied = True
            except Exception:
                pass
            applied = self._set_native_topmost_property(enabled) or applied
        hwnd = self._hwnd()
        applied = self._apply_hwnd_topmost(hwnd, enabled) or applied
        return applied

    def apply_square_corners(self) -> bool:
        """Forca cantos retos no host nativo quando o Windows oferece DWM."""
        hwnd = self._hwnd()
        if os.name != "nt" or not hwnd:
            return False
        try:
            preference = ctypes.c_int(1)  # DWMWCP_DONOTROUND
            result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(hwnd),
                33,  # DWMWA_WINDOW_CORNER_PREFERENCE
                ctypes.byref(preference),
                ctypes.sizeof(preference),
            )
            return int(result) == 0
        except Exception:
            return False
