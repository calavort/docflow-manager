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
