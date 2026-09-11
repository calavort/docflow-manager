"""Cliente de GitHub Releases e instalador transacional (so biblioteca padrao).

Este arquivo tambem e o instalador: antes de atualizar, uma copia dele e
colocada em ``.atualizacoes/instalador.py`` e executada de fora do programa.
Por isso ele nao pode importar nada do pacote ``app``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

APP_ID = "calavort.docflow-manager"
APP_NAME = "DocFlow Manager"
PACKAGE_PREFIX = "DocFlowManager"
LAUNCHER = "DocFlow_Manager.pyw"
STATE_DIR = ".atualizacoes"
MANIFEST = "manifesto-release.json"
MAX_PACKAGE = 40 * 1024 * 1024
MAX_EXPANDED = 80 * 1024 * 1024
# A lista explicita impede que dados pessoais sejam empacotados ou sobrescritos.
APP_FILES = (
    "DocFlow_Manager.pyw",
    "atualizador.py",
    "versao.json",
    "requirements.txt",
    "README.md",
    "instalar_bibliotecas.bat",
    "criar_atalho_menu_iniciar.pyw",
    "criar_atalho_menu_iniciar.ps1",
    "app/__init__.py",
    "app/backend.py",
    "app/dwg_service.py",
    "app/file_name_recognizer.py",
    "app/file_operation_service.py",
    "app/http_bridge.py",
    "app/log_writer.py",
    "app/main.py",
    "app/models.py",
    "app/pdf_service.py",
    "app/update_service.py",
    "app/utils.py",
    "assets/interface.html",
    "assets/docflow_app_icon.png",
    "assets/docflow_manager_icon.ico",
    "assets/Icone para exe e menu iniciar.ico",
    "assets/icons/docflow_icon_28.png",
    "assets/icons/docflow_icon_32.png",
    "assets/icons/docflow_icon_44.png",
    "assets/icons/docflow_icon_64.png",
    "assets/icons/docflow_icon_128.png",
    "assets/icons/docflow_icon_256.png",
    "assets/icons/docflow_icon_512.png",
    "assets/icons/docflow_icon_1024.png",
)


class UpdateError(Exception):
    pass


def version_tuple(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"v?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", str(value))
    if not match:
        raise UpdateError("Versao invalida. Use o formato 8.0.0.")
    return tuple(int(part) for part in match.groups())


def read_version(root: Path) -> dict:
    try:
        info = json.loads((root / "versao.json").read_text(encoding="utf-8"))
        if info["app_id"] != APP_ID:
            raise ValueError("app_id")
        version_tuple(info["version"])
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", info["repository"]):
            raise ValueError("repository")
        return info
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise UpdateError("Nao foi possivel ler versao.json.") from exc


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=True, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def safe_target(root: Path, relative: str) -> Path:
    if relative not in APP_FILES:
        raise UpdateError(f"Arquivo nao permitido no pacote: {relative}")
    root = root.resolve()
    target = root / relative
    for part in (target, *target.parents):
        if part == root:
            break
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise UpdateError("A pasta de instalacao contem um link de arquivos.")
    if not target.resolve().is_relative_to(root):
        raise UpdateError("Arquivo fora da pasta de instalacao.")
    return target


def state_path(root: Path) -> Path:
    target = root / STATE_DIR
    if target.is_symlink() or (hasattr(target, "is_junction") and target.is_junction()):
        raise UpdateError("A pasta de atualizacoes nao pode ser um link.")
    target.mkdir(parents=True, exist_ok=True)
    return target


class _FileLock:
    """Trava do proprio sistema: fechar ou derrubar o processo ja a libera."""

    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self, timeout: float = 0) -> bool:
        import msvcrt
        if self.stream:
            return True
        deadline = time.monotonic() + timeout
        stream = self.path.open("a+b")
        if not self.path.stat().st_size:
            stream.write(b"0")
            stream.flush()
        while True:
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                self.stream = stream
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    stream.close()
                    return False
                time.sleep(0.2)

    def release(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None


def running_instances(root: Path, exclude: Path | None = None) -> int:
    directory = state_path(root) / "instancias"
    if not directory.exists():
        return 0
    count = 0
    for path in directory.glob("*.lock"):
        if path == exclude:
            continue
        probe = _FileLock(path)
        try:
            if probe.acquire():
                probe.release()  # Arquivo orfao de um processo ja encerrado.
            else:
                count += 1
        except OSError:
            if path.exists():
                count += 1  # Nao instala se nao der para inspecionar uma janela viva.
    return count


class InstanceLock(_FileLock):
    """Trava exclusiva do instalador: barra aberturas novas e espera as janelas."""

    def __init__(self, root: Path):
        super().__init__(state_path(root) / "instancia.lock")
        self.root = root

    def acquire(self, timeout: float = 0) -> bool:
        deadline = time.monotonic() + timeout
        if not super().acquire(timeout):
            return False
        while running_instances(self.root):
            if time.monotonic() >= deadline:
                self.release()
                return False
            time.sleep(.1)
        return True


class AppInstance:
    """Uma reserva por janela aberta, com uma trava curta na abertura."""

    def __init__(self, root: Path):
        self.root = root
        self.gate = _FileLock(state_path(root) / "instancia.lock")
        directory = state_path(root) / "instancias"
        directory.mkdir(exist_ok=True)
        self.lease = _FileLock(directory / (uuid.uuid4().hex + ".lock"))

    def acquire(self) -> bool:
        if not self.gate.acquire(timeout=.5):
            return False
        try:
            if (state_path(self.root) / "transacao.json").exists():
                if running_instances(self.root):
                    return False
                recover_transaction(self.root)
            return self.lease.acquire()
        finally:
            self.gate.release()

    def reserve_update(self) -> bool:
        if not self.lease.stream or not self.gate.acquire():
            return False
        if running_instances(self.root, exclude=self.lease.path):
            self.gate.release()
            return False
        # A trava fica ate esta janela sair ou a instalacao ser cancelada, para
        # que nenhuma abertura nova nem um segundo instalador entre no meio.
        return True

    def cancel_update(self) -> None:
        self.gate.release()

    def release(self) -> None:
        self.lease.release()
        self.gate.release()


class _HttpsRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise UpdateError("Redirecionamento de download sem HTTPS.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def open_url(url: str):
    if urllib.parse.urlparse(url).scheme != "https":
        raise UpdateError("A atualizacao exige uma conexao HTTPS.")
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json" if url.startswith("https://api.github.com/") else "application/octet-stream",
        "User-Agent": "DocFlowManager-Updater",
        "X-GitHub-Api-Version": "2026-03-10",
    })
    return urllib.request.build_opener(_HttpsRedirect()).open(request, timeout=20)


def get_bytes(url: str, limit: int) -> bytes:
    with open_url(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Resposta de atualizacao maior que o permitido.")
    return data


@dataclass(frozen=True)
class Release:
    version: str
    repository: str
    url: str
    digest: str
    size: int


def release_from_json(data: dict, current: dict) -> Release | None:
    if not isinstance(data, dict):
        raise UpdateError("Resposta de release invalida.")
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = data.get("tag_name", "")
    if version_tuple(tag) <= version_tuple(current["version"]):
        return None
    version = tag.removeprefix("v")
    name = f"{PACKAGE_PREFIX}-{version}.zip"
    asset = next((item for item in data.get("assets", []) if item.get("name") == name), None)
    if not asset:
        raise UpdateError(f"O release ainda nao possui o pacote {name}.")
    expected_url = f"https://github.com/{current['repository']}/releases/download/{tag}/{name}"
    if asset.get("browser_download_url") != expected_url:
        raise UpdateError("O pacote nao pertence ao repositorio configurado.")
    digest = asset.get("digest") or ""
    if not re.fullmatch(r"sha256:[a-fA-F0-9]{64}", digest):
        checksum = next((item for item in data.get("assets", []) if item.get("name") == name + ".sha256"), None)
        if not checksum or checksum.get("browser_download_url") != expected_url + ".sha256":
            raise UpdateError("O release nao possui uma verificacao SHA-256 valida.")
        checksum_text = get_bytes(expected_url + ".sha256", 256).decode("ascii").strip()
        match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?" + re.escape(name), checksum_text)
        if not match:
            raise UpdateError("Arquivo SHA-256 invalido.")
        digest = "sha256:" + match.group(1)
    size = asset.get("size", 0)
    if not isinstance(size, int) or not 0 < size <= MAX_PACKAGE:
        raise UpdateError("Tamanho de download invalido.")
    return Release(version, current["repository"], expected_url, digest[7:].lower(), size)


def check_release(current: dict) -> Release | None:
    try:
        data = json.loads(get_bytes(f"https://api.github.com/repos/{current['repository']}/releases/latest", 2 * 1024 * 1024))
        return release_from_json(data, current)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError("Repositorio ou primeira versao ainda nao publicado no GitHub.") from exc
        if exc.code in (403, 429):
            raise UpdateError("GitHub indisponivel ou limite de consultas atingido. Tente mais tarde.") from exc
        raise UpdateError(f"GitHub retornou erro {exc.code}. Tente mais tarde.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError("Sem conexao com o GitHub. O programa continua funcionando normalmente.") from exc
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise UpdateError("O GitHub retornou dados de atualizacao invalidos.") from exc


def download_release(release: Release, root: Path, progress=lambda percent: None) -> Path:
    destination = state_path(root) / ("download-" + uuid.uuid4().hex + ".zip")
    try:
        received = 0
        digest = hashlib.sha256()
        with open_url(release.url) as response, destination.open("xb") as output:
            while chunk := response.read(128 * 1024):
                received += len(chunk)
                if received > release.size or received > MAX_PACKAGE:
                    raise UpdateError("O tamanho do pacote difere do informado no GitHub.")
                output.write(chunk)
                digest.update(chunk)
                progress(min(100, int(received * 100 / release.size)))
        if received != release.size or digest.hexdigest() != release.digest:
            raise UpdateError("Falha na verificacao do download. Nenhum arquivo foi atualizado.")
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def unpack_package(archive: Path, destination: Path, version: str, repository: str) -> dict:
    try:
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(name.casefold() for name in names)):
                raise UpdateError("O pacote possui arquivos duplicados.")
            if set(names) != set(APP_FILES) | {MANIFEST}:
                raise UpdateError("O pacote contem arquivos inesperados ou esta incompleto.")
            if sum(entry.file_size for entry in entries) > MAX_EXPANDED:
                raise UpdateError("Pacote descompactado maior que o permitido.")
            for entry in entries:
                if stat.S_ISLNK(entry.external_attr >> 16) or entry.is_dir():
                    raise UpdateError("O pacote contem links ou diretorios invalidos.")
            if package.getinfo(MANIFEST).file_size > 65536:
                raise UpdateError("Manifesto maior que o permitido.")
            manifest = json.loads(package.read(MANIFEST))
            if (manifest["app_id"] != APP_ID or manifest["version"] != version
                    or manifest["repository"] != repository or manifest["schema"] != 1
                    or set(manifest["files"]) != set(APP_FILES)):
                raise UpdateError("O manifesto nao corresponde a esta atualizacao.")
            minimum = tuple(manifest["python_min"])
            if minimum != (3, 11) or sys.version_info[:2] < minimum:
                raise UpdateError("Esta versao exige Python 3.11 ou superior.")
            for name in APP_FILES:
                data = package.read(name)
                if hashlib.sha256(data).hexdigest() != manifest["files"][name]:
                    raise UpdateError(f"Arquivo corrompido: {name}")
                if name.endswith((".py", ".pyw")):
                    compile(data, name, "exec")
                target = safe_target(destination, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            info = read_version(destination)
            if info["version"] != version or info["repository"] != repository:
                raise UpdateError("A versao interna do pacote esta incorreta.")
            return manifest
    except (zipfile.BadZipFile, ValueError, KeyError, TypeError, SyntaxError) as exc:
        raise UpdateError("Pacote de atualizacao invalido ou corrompido.") from exc


def install_package(archive: Path, root: Path, version: str, repository: str) -> Path:
    """Chame so com o InstanceLock na mao. Deixa um registro recuperavel."""
    current = read_version(root)
    if current["repository"] != repository or version_tuple(version) <= version_tuple(current["version"]):
        raise UpdateError("Atualizacao de outro repositorio ou versao antiga recusada.")
    state = state_path(root)
    backup = state / ("backup-" + current["version"] + "-" + uuid.uuid4().hex[:10])
    with tempfile.TemporaryDirectory(prefix="stage-", dir=state) as temporary:
        staged = Path(temporary)
        unpack_package(archive, staged, version, repository)
        # Atualizacao de codigo nunca roda pip sem o usuario saber.
        if (staged / "requirements.txt").read_bytes() != (root / "requirements.txt").read_bytes():
            raise UpdateError("Esta versao altera as bibliotecas. Faca a instalacao manual do pacote.")
        targets = {name: safe_target(root, name) for name in APP_FILES}
        backup.mkdir()
        existing = []
        for name, target in targets.items():
            if target.exists():
                if not target.is_file():
                    raise UpdateError(f"O destino nao e um arquivo: {name}")
                saved = safe_target(backup, name)
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                existing.append(name)
        journal = {"backup": backup.name, "existing": existing, "files": list(APP_FILES), "version": version}
        write_json(state / "transacao.json", journal)
        try:
            # A marca de versao muda por ultimo, depois de todo o programa.
            for name in sorted(APP_FILES, key=lambda item: item == "versao.json"):
                target = targets[name]
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staged / name, target)
        except Exception:
            recover_transaction(root)
            raise
        (state / "transacao.json").unlink()
    return backup


def recover_transaction(root: Path) -> bool:
    journal_path = state_path(root) / "transacao.json"
    if not journal_path.exists():
        return False
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if not re.fullmatch(r"backup-[0-9.]+-[a-f0-9]{10}", journal["backup"]):
        raise UpdateError("Registro de recuperacao invalido.")
    if set(journal["files"]) != set(APP_FILES) or not set(journal["existing"]).issubset(APP_FILES):
        raise UpdateError("Lista de recuperacao invalida.")
    backup = state_path(root) / journal["backup"]
    for name in journal["files"]:
        target = safe_target(root, name)
        if name in journal["existing"]:
            saved = safe_target(backup, name)
            if target.is_file() and sha256(target) == sha256(saved):
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(saved, target)
        else:
            target.unlink(missing_ok=True)
    journal_path.unlink()
    return True


def prepare_installer(archive: Path, root: Path, release: Release) -> Path:
    state = state_path(root)
    helper = state / "instalador.py"
    shutil.copy2(root / "atualizador.py", helper)
    plan = state / "plano.json"
    write_json(plan, {"root": str(root.resolve()), "archive": str(archive.resolve()),
                      "version": release.version, "repository": release.repository,
                      "sha256": release.digest, "python": sys.executable})
    return plan


def start_installer(plan: Path):
    ready = plan.parent / "instalador-pronto"
    ready.unlink(missing_ok=True)
    return subprocess.Popen(
        [sys.executable, str(plan.parent / "instalador.py"), "--install", str(plan)],
        cwd=plan.parent, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def installer_is_ready(root: Path) -> bool:
    return (state_path(root) / "instalador-pronto").exists()


def run_installer(plan_path: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    root = Path(plan["root"]).resolve()
    state = state_path(root)
    lock = InstanceLock(root)
    # O aperto de mao deixa o programa aberto se este ajudante nao subir.
    (state / "instalador-pronto").touch()
    if not lock.acquire(timeout=90):
        write_json(state / "resultado.json", {"ok": False, "message": "O programa nao foi encerrado. Tente atualizar novamente."})
        return 1
    try:
        archive = Path(plan["archive"])
        if archive.parent.resolve() != state.resolve() or sha256(archive) != plan["sha256"]:
            raise UpdateError("O pacote foi alterado depois do download.")
        recover_transaction(root)
        backup = install_package(archive, root, plan["version"], plan["repository"])
        write_json(state / "resultado.json", {"ok": True, "message": f"Atualizado para {plan['version']}.", "backup": backup.name})
        archive.unlink(missing_ok=True)
    except Exception as exc:
        write_json(state / "resultado.json", {"ok": False, "message": f"Atualizacao nao concluida: {exc}"})
    finally:
        lock.release()
    if (state / "transacao.json").exists():
        return 1
    subprocess.Popen([plan["python"], str(root / LAUNCHER)], cwd=root,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", type=Path, required=True)
    sys.exit(run_installer(parser.parse_args().install))
