from __future__ import annotations

from pathlib import Path
import os

from .backend import DocFlowBackend
from .http_bridge import BackendHttpBridge
from .utils import hide_console_window


def main() -> None:
    hide_console_window()
    import webview
    from webview.dom import DOMEventHandler

    root = Path(__file__).resolve().parents[1]
    assets = root / "assets"
    interface = assets / "interface.html"
    icon = assets / "docflow_manager_icon.ico"
    storage = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DocFlow Manager" / "WebView2Data"
    storage.mkdir(parents=True, exist_ok=True)

    backend = DocFlowBackend()
    bridge = BackendHttpBridge(backend, interface)
    url = bridge.start()

    # O programa so abre a janela depois que o mesmo canal usado pelos botoes
    # foi testado. Assim nao existe mais a situacao "interface abriu, backend nao".
    bridge.health_check()
    bridge.api_self_test()

    window = webview.create_window(
        "DocFlow Manager",
        url=url,
        width=560,
        height=940,
        min_size=(560, 940),
        resizable=False,
        frameless=True,
        easy_drag=False,
        shadow=False,
        on_top=True,
        background_color="#f3f2f1",
        text_select=False,
        zoomable=False,
        draggable=True,
    )
    backend.attach_window(window)

    def bind_drop(bound_window) -> None:
        """Liga o drag-and-drop assim que a pagina estiver pronta.

        Este e o fluxo recomendado pelo proprio pywebview para que o WebView2
        habilite a captura nativa de arquivos e entregue ``pywebviewFullPath``.
        """
        try:
            bound_window.events.loaded.wait(10)
            backend.apply_square_corners()
            backend._window_set_topmost(True)

            def _on_drag(_event) -> None:
                return None

            drop_zone = bound_window.dom.get_element("#dropZone")
            drop_targets = [bound_window.dom.document]
            if drop_zone is not None:
                drop_targets.append(drop_zone)

            bound_window.dom.document.events.dragenter += DOMEventHandler(
                _on_drag, True, True
            )
            bound_window.dom.document.events.dragstart += DOMEventHandler(
                _on_drag, True, True
            )
            bound_window.dom.document.events.dragover += DOMEventHandler(
                _on_drag, True, True, debounce=250
            )
            for target in drop_targets:
                target.events.drop += DOMEventHandler(backend.on_dom_drop, True, True)
        except Exception as exc:
            # O seletor nativo permanece disponivel. Registra um diagnostico
            # sem abrir console para o usuario.
            try:
                log_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "DocFlow Manager"
                log_dir.mkdir(parents=True, exist_ok=True)
                (log_dir / "drag_drop_error.log").write_text(
                    f"Falha ao inicializar drag-and-drop: {type(exc).__name__}: {exc}\n",
                    encoding="utf-8",
                )
            except Exception:
                pass

    try:
        webview.start(
            bind_drop,
            window,
            debug=False,
            private_mode=False,
            storage_path=str(storage),
            icon=str(icon) if icon.exists() else None,
        )
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
