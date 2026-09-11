"""Ligacao entre o atualizador e a interface do DocFlow Manager.

A interface fala com este servico pelos comandos ``updateState``,
``checkUpdate``, ``downloadUpdate`` e ``installUpdate``. Nenhum deles bloqueia:
o trabalho pesado (rede, conferencia do pacote) roda em uma thread e a interface
le o andamento por ``updateState``.
"""

from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atualizador import (  # noqa: E402
    AppInstance,
    UpdateError,
    check_release,
    download_release,
    installer_is_ready,
    prepare_installer,
    read_version,
    start_installer,
    state_path,
    unpack_package,
)

IDLE_MESSAGE = "Aguardando verificação."


class UpdateService:
    """Verificacao, download e instalacao da proxima versao publicada."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else ROOT
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._release = None
        self._archive: Path | None = None
        self._busy = False
        self._stage = "idle"
        self._progress = 0
        self._message = IDLE_MESSAGE
        self._offered = False
        self._instance: AppInstance | None = None
        self._close_window = None
        try:
            self.version = read_version(self.root)["version"]
            self.available_for_install = True
        except UpdateError:
            # Sem versao.json o programa continua funcionando; so nao atualiza.
            self.version = ""
            self.available_for_install = False
            self._message = IDLE_MESSAGE

    # ------------------------------------------------------------------
    # Estado lido pela interface
    # ------------------------------------------------------------------
    def attach(self, instance: AppInstance | None, close_window) -> None:
        self._instance = instance
        self._close_window = close_window

    def state(self, **extra: Any) -> dict[str, Any]:
        with self._lock:
            payload = {
                "type": "updateState",
                "version": self.version,
                "message": self._message,
                "busy": self._busy,
                "stage": self._stage,
                "progress": self._progress,
                "supported": self.available_for_install,
                "latest": self._release.version if self._release else "",
                "available": self._release is not None,
                "ready": bool(self._archive and self._archive.exists()),
                "shouldOffer": self._should_offer(),
            }
            payload.update(extra)
            return payload

    def _should_offer(self) -> bool:
        """A interface so abre o card de oferta uma vez por versao encontrada."""
        return bool(self._release) and not self._offered

    def offer_shown(self) -> dict[str, Any]:
        with self._lock:
            self._offered = True
        return self.state()

    def _set(self, message: str, *, stage: str | None = None, busy: bool | None = None, progress: int | None = None) -> None:
        with self._lock:
            self._message = message
            if stage is not None:
                self._stage = stage
            if busy is not None:
                self._busy = busy
            if progress is not None:
                self._progress = progress

    def startup_result(self) -> str:
        """Mensagem deixada pelo instalador na execucao anterior, se houver."""
        result = state_path(self.root) / "resultado.json"
        if not result.exists():
            return ""
        try:
            data = json.loads(result.read_text(encoding="utf-8"))
            result.replace(result.with_name("ultimo-resultado.json"))
            return str(data.get("message") or "")
        except (OSError, ValueError):
            return ""

    # ------------------------------------------------------------------
    # Trabalho em segundo plano
    # ------------------------------------------------------------------
    def _run(self, name: str, work) -> bool:
        with self._lock:
            if self._busy or (self._worker and self._worker.is_alive()):
                return False
            self._busy = True
            self._worker = threading.Thread(target=work, name=f"DocFlow-{name}", daemon=True)
            thread = self._worker
        thread.start()
        return True

    def check(self) -> dict[str, Any]:
        if not self.available_for_install:
            return self.state()
        if not self._run("check", self._check_worker):
            return self.state()
        self._set("Verificando atualizações...", stage="checking", progress=0)
        return self.state()

    def _check_worker(self) -> None:
        try:
            release = check_release(read_version(self.root))
            with self._lock:
                if release != self._release and self._archive:
                    self._archive.unlink(missing_ok=True)
                    self._archive = None
                self._release = release
                self._offered = False
            if release:
                self._set(f"Versão {release.version} disponível.", stage="available", busy=False)
            else:
                self._set("Você está na versão mais recente.", stage="idle", busy=False)
        except Exception as exc:
            self._fail(str(exc))

    def download(self) -> dict[str, Any]:
        with self._lock:
            release = self._release
            archive = self._archive
        if release is None:
            return self.state()
        if archive and archive.exists():
            self._set("Download conferido. Pronto para instalar.", stage="ready", busy=False, progress=100)
            return self.state()
        if not self._run("download", lambda: self._download_worker(release)):
            return self.state()
        self._set("Baixando atualização: 0%", stage="downloading", progress=0)
        return self.state()

    def _download_worker(self, release) -> None:
        try:
            archive = download_release(release, self.root, self._on_progress)
            try:
                with tempfile.TemporaryDirectory(prefix="validacao-", dir=state_path(self.root)) as temporary:
                    stage = Path(temporary)
                    unpack_package(archive, stage, release.version, release.repository)
                    if (stage / "requirements.txt").read_bytes() != (self.root / "requirements.txt").read_bytes():
                        raise UpdateError("Esta versão altera as bibliotecas. Instale o pacote manualmente.")
            except Exception:
                archive.unlink(missing_ok=True)
                raise
            with self._lock:
                self._archive = archive
            self._set("Download conferido. Pronto para instalar.", stage="ready", busy=False, progress=100)
        except Exception as exc:
            self._fail(str(exc))

    def _on_progress(self, percent: int) -> None:
        self._set(f"Baixando atualização: {percent}%", stage="downloading", progress=int(percent))

    def _fail(self, message: str) -> None:
        with self._lock:
            stage = "available" if self._release else "idle"
        self._set(message, stage=stage, busy=False)

    # ------------------------------------------------------------------
    # Instalacao
    # ------------------------------------------------------------------
    def install(self) -> dict[str, Any]:
        with self._lock:
            release = self._release
            archive = self._archive
            if self._stage == "installing":
                return self.state()
        if release is None or not archive or not archive.exists():
            return self.state(error="Baixe a atualização antes de instalar.")

        # Uma pasta de desenvolvimento nao pode ser sobrescrita por um pacote
        # publicado: o trabalho em andamento seria perdido.
        if (self.root / ".git").exists():
            message = "Pasta de desenvolvimento: publique a versão em vez de instalar por cima."
            self._set(message, stage="ready", busy=False)
            return self.state(error=message)

        if self._instance is not None and not self._instance.reserve_update():
            message = "Feche as outras janelas do DocFlow Manager e tente instalar novamente."
            self._set(message, stage="ready", busy=False)
            return self.state(error=message)

        try:
            plan = prepare_installer(archive, self.root, release)
            helper = start_installer(plan)
        except Exception as exc:
            if self._instance is not None:
                self._instance.cancel_update()
            self._fail(str(exc))
            return self.state(error=self._message)

        self._set(f"Instalando a versão {release.version}...", stage="installing", busy=True)
        threading.Thread(target=self._wait_installer, args=(helper,), name="DocFlow-install", daemon=True).start()
        return self.state()

    def _wait_installer(self, helper) -> None:
        """Fecha a janela so depois que o instalador avisa que subiu."""
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if helper.poll() is not None:
                self._cancel_install("O instalador não iniciou. O programa foi mantido aberto.")
                return
            if installer_is_ready(self.root):
                time.sleep(0.4)  # Deixa a interface mostrar a mensagem antes de sair.
                if self._close_window is not None:
                    self._close_window()
                return
            time.sleep(0.1)
        try:
            helper.terminate()
        except Exception:
            pass
        self._cancel_install("O instalador não respondeu. Tente novamente.")

    def _cancel_install(self, message: str) -> None:
        if self._instance is not None:
            self._instance.cancel_update()
        self._set(message, stage="ready", busy=False)
