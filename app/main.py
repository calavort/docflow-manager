from __future__ import annotations

from pathlib import Path
import ctypes
import os

from .backend import DocFlowBackend
from .http_bridge import BackendHttpBridge
from .update_service import AppInstance
from .utils import close_stale_webview_processes, hide_console_window


def _message_box(text: str) -> None:
    if os.name == "nt":
        try:
            ctypes.windll.user32.MessageBoxW(None, text, "DocFlow Manager", 0x40)
        except Exception:
            pass


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

    # A reserva impede que uma janela abra no meio de uma instalacao e
    # recupera a atualizacao anterior se ela tiver sido interrompida.
    instance = AppInstance(root)
    try:
        if not instance.acquire():
            _message_box("Uma atualizacao esta em andamento. Aguarde a conclusao para abrir o programa.")
            return
    except Exception as exc:
        instance.release()
        _message_box(f"Nao foi possivel recuperar a atualizacao anterior: {exc}")
        return

    backend = DocFlowBackend()
    backend.attach_update_instance(instance)
    bridge = BackendHttpBridge(backend, interface)
    url = bridge.start()

    # O programa so abre a janela depois que o mesmo canal usado pelos botoes
    # foi testado. Assim nao existe mais a situacao "interface abriu, backend nao".
    bridge.health_check()
    bridge.api_self_test()

    window = webview.create_window(
        "DocFlow Manager",
        url=url,
        # +2px em cada eixo para o contorno de 1px da interface nao comer
        # area util e trazer a barra de rolagem de volta.
        width=562,
        height=942,
        min_size=(562, 942),
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

    def _page_is_up(bound_window) -> bool:
        """Confirma que a interface desenhou antes de ligar o resto.

        Sobras de ``msedgewebview2.exe`` de uma finalizacao a forca seguram a
        pasta de dados e o WebView2 nao inicia ("Recurso solicitado em uso").
        A janela abria vazia sem explicar nada; agora o programa limpa a sobra
        e diz o que fazer.
        """
        try:
            if bound_window.events.loaded.wait(15):
                backend.apply_square_corners()
                backend._window_set_topmost(True)
                return True
        except Exception:
            pass

        encerrados = close_stale_webview_processes(str(storage))
        if encerrados:
            _message_box(
                "A interface nao carregou porque um processo do WebView2 tinha ficado preso "
                "de uma execucao anterior.\n\n"
                f"Ja encerrei {encerrados} processo(s). Abra o DocFlow Manager novamente."
            )
        else:
            _message_box(
                "A interface nao carregou. Feche o DocFlow Manager pelo Gerenciador de Tarefas, "
                "se ele ainda aparecer la, e abra o programa novamente."
            )
        try:
            bound_window.destroy()
        except Exception:
            pass
        return False

    def bind_drop(bound_window) -> None:
        """Liga o drag-and-drop assim que a pagina estiver pronta.

        Este e o fluxo recomendado pelo proprio pywebview para que o WebView2
        habilite a captura nativa de arquivos e entregue ``pywebviewFullPath``.
        """
        if not _page_is_up(bound_window):
            return

        try:
            def _on_drag(_event) -> None:
                return None

            # O drop nativo fica ligado apenas ao documento inteiro. Esta é a
            # configuração usada pelo exemplo oficial do pywebview e evita
            # duplicidade/competição entre o documento e a faixa #dropZone.
            document = bound_window.dom.document
            document.events.dragenter += DOMEventHandler(_on_drag, True, True)
            document.events.dragstart += DOMEventHandler(_on_drag, True, True)
            document.events.dragover += DOMEventHandler(
                _on_drag, True, True, debounce=250
            )
            document.events.drop += DOMEventHandler(backend.on_dom_drop, True, True)
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
        instance.release()


if __name__ == "__main__":
    main()
