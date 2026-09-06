from __future__ import annotations

from pathlib import Path
from datetime import datetime
import ctypes
import os
import sys
import traceback

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def message_box(text: str, title: str = "DocFlow Manager", error: bool = True) -> None:
    if os.name == "nt":
        try:
            flags = 0x10 if error else 0x40
            ctypes.windll.user32.MessageBoxW(None, text, title, flags)
            return
        except Exception:
            pass


def save_crash_log(exc: BaseException) -> str:
    base = Path(os.environ.get("LOCALAPPDATA", str(ROOT))) / "DocFlow Manager"
    base.mkdir(parents=True, exist_ok=True)
    path = base / "DocFlow_crash.log"
    with path.open("a", encoding="utf-8-sig") as handle:
        handle.write("\n" + "=" * 72 + "\n")
        handle.write(f"Data: {datetime.now():%Y-%m-%d %H:%M:%S}\n")
        handle.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    return str(path)


try:
    import webview  # noqa: F401
    import pypdf  # noqa: F401
except Exception as exc:
    message_box(
        "As bibliotecas do DocFlow Manager ainda nao estao instaladas.\n\n"
        "Execute o arquivo 'instalar_bibliotecas.bat' uma vez e depois abra o programa novamente.\n\n"
        f"Detalhe: {exc}"
    )
    raise SystemExit(1)

try:
    from app.main import main
    main()
except SystemExit:
    raise
except BaseException as exc:
    log_file = save_crash_log(exc)
    message_box(
        "O DocFlow Manager encontrou um erro inesperado e foi fechado.\n\n"
        f"Um log foi salvo em:\n{log_file}\n\n"
        f"Erro: {exc}"
    )
