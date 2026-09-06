from __future__ import annotations

from pathlib import Path
import ctypes
import os
import sys

ROOT = Path(__file__).resolve().parent
LAUNCHER = ROOT / "DocFlow_Manager.pyw"
ICON = ROOT / "assets" / "docflow_manager_icon.ico"


def msg(text: str, flags: int = 0x40) -> None:
    ctypes.windll.user32.MessageBoxW(None, text, "DocFlow Manager", flags)


try:
    import win32com.client  # type: ignore

    exe = Path(sys.executable)
    pythonw = exe if exe.name.lower() == "pythonw.exe" else exe.with_name("pythonw.exe")
    if not pythonw.exists():
        raise FileNotFoundError(f"pythonw.exe nao encontrado em: {pythonw}")

    appdata = Path(os.environ["APPDATA"])
    programs = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    programs.mkdir(parents=True, exist_ok=True)
    shortcut_path = programs / "DocFlow Manager.lnk"

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(pythonw)
    shortcut.Arguments = f'"{LAUNCHER}"'
    shortcut.WorkingDirectory = str(ROOT)
    if ICON.exists():
        shortcut.IconLocation = f"{ICON},0"
    shortcut.Description = "DocFlow Manager"
    shortcut.save()

    msg(
        "Atalho criado no Menu Iniciar.\n\n"
        "Ele aponta DIRETAMENTE para pythonw.exe e chama DocFlow_Manager.pyw.\n"
        "Nao existe .bat/cmd no caminho de abertura, portanto nao ha flash do console."
    )
except Exception as exc:
    msg(
        "Nao foi possivel criar o atalho.\n\n"
        "Execute instalar_bibliotecas.bat primeiro e tente novamente.\n\n"
        f"Detalhe: {exc}",
        0x10,
    )
