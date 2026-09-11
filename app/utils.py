from __future__ import annotations

from pathlib import Path
import ctypes
import os
import re
import subprocess


def desktop_directory() -> str:
    if os.name == "nt":
        try:
            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY = 0x10
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                return buf.value
        except Exception:
            pass
    return str(Path.home() / "Desktop")


def natural_key(value: str):
    return [int(part) if part.isdigit() else part.casefold() for part in re.split(r"(\d+)", value)]


def open_folder(folder: str) -> None:
    path = os.path.abspath(folder)
    os.makedirs(path, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys_platform() == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def sys_platform() -> str:
    import sys
    return sys.platform


def notify_folder_change(folder: str) -> None:
    """Avisa o Windows Explorer para atualizar a pasta na hora.

    Sem isso a janela do Explorer pode continuar mostrando os nomes antigos por
    um ou dois segundos depois que a operacao ja terminou.
    """
    if os.name != "nt" or not folder:
        return
    try:
        path = os.path.abspath(folder)
        if not os.path.isdir(path):
            return
        shcne_updatedir = 0x00001000
        shcnf_pathw = 0x0005
        ctypes.windll.shell32.SHChangeNotify(shcne_updatedir, shcnf_pathw, ctypes.c_wchar_p(path), None)
    except Exception:
        pass


def hide_console_window() -> None:
    if os.name != "nt":
        return
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def close_stale_webview_processes(storage_path: str) -> int:
    """Encerra processos do WebView2 presos na pasta de dados do programa.

    Quando o DocFlow e finalizado a forca, os processos ``msedgewebview2.exe``
    filhos podem sobreviver segurando essa pasta. A abertura seguinte falha com
    "Recurso solicitado em uso" (0x800700AA) e a janela aparece em branco, sem
    dizer nada. So chame com a reserva de instancia na mao: sem outro DocFlow
    vivo, qualquer processo apontando para essa pasta e sobra de uma execucao
    anterior.
    """
    if os.name != "nt" or not storage_path:
        return 0
    script = (
        "$alvo = $env:DOCFLOW_STORAGE;"
        "$presos = Get-CimInstance Win32_Process -Filter \"Name='msedgewebview2.exe'\" |"
        " Where-Object { $_.CommandLine -and $_.CommandLine.Contains($alvo) };"
        "$presos | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue };"
        "($presos | Measure-Object).Count"
    )
    try:
        env = os.environ.copy()
        env["DOCFLOW_STORAGE"] = os.path.abspath(storage_path)
        completed = subprocess.run(
            [powershell_exe(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=20,
            check=False,
        )
        return int((completed.stdout or "0").strip() or 0)
    except Exception:
        return 0


def powershell_exe() -> str:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    candidate = os.path.join(system_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    return candidate if os.path.isfile(candidate) else "powershell.exe"
