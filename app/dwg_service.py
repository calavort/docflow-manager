from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import os
import time

from .log_writer import LogWriter
from .pdf_service import CancelledError

DEFAULT_GAP = 1000.0
RELATIVE_GAP_FACTOR = 0.02


def _check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError()


def _import_com():
    try:
        import pythoncom  # type: ignore
        import win32com.client  # type: ignore
        import pywintypes  # type: ignore
        return pythoncom, win32com.client, pywintypes
    except Exception as exc:
        raise RuntimeError("Automacao DWG requer pywin32. Execute instalar_bibliotecas.bat e tente novamente.") from exc


_POINT_FACTORY = None


def _point(x: float, y: float, z: float):
    """Ponto 3D no formato que o AutoCAD aceita.

    A partir do AutoCAD 2027 uma tupla comum e recusada com E_INVALIDARG
    (-2147024809): a API exige um array tipado de doubles. O VARIANT abaixo
    funciona tambem nas versoes anteriores.
    """
    global _POINT_FACTORY
    if _POINT_FACTORY is None:
        try:
            import pythoncom  # type: ignore
            from win32com.client import VARIANT  # type: ignore

            tipo = pythoncom.VT_ARRAY | pythoncom.VT_R8
            _POINT_FACTORY = lambda values: VARIANT(tipo, values)  # noqa: E731
        except Exception:
            _POINT_FACTORY = tuple
    return _POINT_FACTORY((float(x), float(y), float(z)))


def _is_busy_error(exc: Exception) -> bool:
    # Com o AutoCAD ocupado o pywin32 as vezes nao encontra o metodo e levanta
    # AttributeError no lugar do com_error de "chamada rejeitada".
    if isinstance(exc, AttributeError):
        return True
    hresult = getattr(exc, "hresult", None)
    if hresult is None and getattr(exc, "args", None):
        try:
            hresult = int(exc.args[0])
        except Exception:
            hresult = None
    return hresult in (-2147417846, -2147418111)  # 0x8001010A, 0x80010001


def _retry_com(action, cancel_event, attempts: int = 40):
    last_exc = None
    for attempt in range(1, attempts + 1):
        _check_cancel(cancel_event)
        try:
            return action()
        except Exception as exc:
            last_exc = exc
            if not _is_busy_error(exc) or attempt >= attempts:
                raise
            time.sleep(min(0.25 + attempt * 0.05, 1.5))
    if last_exc:
        raise last_exc
    return action()


@dataclass(slots=True)
class Bounds:
    min_x: float = 0.0
    min_y: float = 0.0
    min_z: float = 0.0
    max_x: float = 0.0
    max_y: float = 0.0
    max_z: float = 0.0

    @property
    def is_valid(self) -> bool:
        return self.max_x > self.min_x or self.max_y > self.min_y or self.max_z > self.min_z

    @property
    def width(self) -> float:
        return abs(self.max_x - self.min_x)

    def shift_to(self, min_x: float, min_y: float, min_z: float) -> "Bounds":
        return Bounds(
            min_x,
            min_y,
            min_z,
            min_x + abs(self.max_x - self.min_x),
            min_y + abs(self.max_y - self.min_y),
            min_z + abs(self.max_z - self.min_z),
        )


def _point3(value) -> tuple[float, float, float] | None:
    try:
        if len(value) < 3:
            return None
        return float(value[0]), float(value[1]), float(value[2])
    except Exception:
        return None


def _get_bounds(block_reference) -> Bounds:
    try:
        min_point, max_point = block_reference.GetBoundingBox()
        minimum = _point3(min_point)
        maximum = _point3(max_point)
        if minimum is None or maximum is None:
            return Bounds()
        return Bounds(*minimum, *maximum)
    except Exception:
        return Bounds()


def _move_block(block_reference, dx: float, dy: float, dz: float, cancel_event) -> None:
    _retry_com(lambda: block_reference.Move(_point(0.0, 0.0, 0.0), _point(dx, dy, dz)), cancel_event)


def _regen(document, cancel_event) -> None:
    _retry_com(lambda: document.Regen(1), cancel_event, 8)


def _try_set_variable(document, name: str, value, log: LogWriter, cancel_event) -> None:
    try:
        _retry_com(lambda: document.SetVariable(name, value), cancel_event, 4)
    except Exception as exc:
        # Sao apenas otimizacoes: algumas variaveis sao somente leitura conforme
        # a versao do AutoCAD e a uniao funciona do mesmo jeito.
        log.info(f"Variavel {name} nao pode ser ajustada nesta versao do AutoCAD: {exc}")


def _configure_fast_batch_mode(document, log: LogWriter, cancel_event) -> None:
    _try_set_variable(document, "FILEDIA", 0, log, cancel_event)
    _try_set_variable(document, "CMDDIA", 0, log, cancel_event)
    _try_set_variable(document, "REGENAUTO", 0, log, cancel_event)
    _try_set_variable(document, "BACKGROUNDPLOT", 0, log, cancel_event)


def _get_or_create_autocad(client, log: LogWriter, cancel_event):
    try:
        acad = client.GetActiveObject("AutoCAD.Application")
        log.info("AutoCAD ja aberto detectado; usando a instancia existente.")
        return acad
    except Exception:
        pass

    acad = _retry_com(lambda: client.Dispatch("AutoCAD.Application"), cancel_event)
    if acad is None:
        raise RuntimeError("AutoCAD.Application nao retornou uma instancia valida.")
    log.info("Nenhum AutoCAD aberto foi detectado; uma nova instancia foi iniciada.")
    return acad


def _ensure_insertable_dwg(acad, input_file: str, log: LogWriter, cancel_event) -> str:
    if Path(input_file).suffix.lower() != ".dxf":
        return input_file

    source_document = None
    converted_path = str(Path(input_file).with_suffix(".dwg"))
    try:
        if os.path.exists(converted_path):
            os.remove(converted_path)
        source_document = _retry_com(lambda: acad.Documents.Open(input_file, False), cancel_event, 12)
        _retry_com(lambda: source_document.SaveAs(converted_path), cancel_event, 12)
        log.info(f"DXF temporario convertido para DWG antes da uniao: {Path(input_file).name}")
        return converted_path
    except Exception as exc:
        raise RuntimeError(f"O AutoCAD nao conseguiu converter o desenho temporario {Path(input_file).name} para DWG: {exc}") from exc
    finally:
        if source_document is not None:
            try:
                _retry_com(lambda: source_document.Close(False), None, 3)
            except Exception:
                log.warning(f"Nao foi possivel fechar o desenho temporario convertido: {Path(input_file).name}")


def _insert_dwg_as_block(document, input_file: str, x: float, y: float, z: float, cancel_event):
    try:
        return _retry_com(
            lambda: document.ModelSpace.InsertBlock(_point(x, y, z), input_file, 1.0, 1.0, 1.0, 0.0),
            cancel_event,
        )
    except Exception as exc:
        raise RuntimeError(f"O AutoCAD nao conseguiu inserir {Path(input_file).name}: {exc}") from exc


def merge_with_autocad(input_files: list[str], output_path: str, log: LogWriter, preserve_layouts: bool, cancel_event=None) -> None:
    pythoncom, client, pywintypes = _import_com()
    pythoncom.CoInitialize()
    target_document = None
    try:
        _check_cancel(cancel_event)
        acad = _get_or_create_autocad(client, log, cancel_event)
        _retry_com(lambda: setattr(acad, "Visible", True), cancel_event)
        target_document = _retry_com(lambda: acad.Documents.Add(), cancel_event)
        _configure_fast_batch_mode(target_document, log, cancel_event)
        log.info("AutoCAD pronto para uniao de DWG em thread STA.")
        log.info("Chamadas COM com retry ativado para reduzir falhas de aplicativo ocupado.")
        log.info("Modo rapido ativado: o DocFlow insere os DWGs direto no Model Space e evita abrir cada arquivo apenas para medicao.")
        if preserve_layouts:
            log.warning("A importacao de layouts foi ignorada no modo rapido para evitar lentidao e abas auxiliares no AutoCAD. O arquivo final mantem os desenhos unidos no Model Space.")

        next_min_x = 0.0
        baseline_y = 0.0
        inserted_count = 0
        for input_file in input_files:
            _check_cancel(cancel_event)
            if not os.path.exists(input_file):
                log.warning(f"DWG ignorado porque nao foi encontrado: {input_file}")
                continue

            insert_file = _ensure_insertable_dwg(acad, input_file, log, cancel_event)
            planned_x = next_min_x
            block_reference = _insert_dwg_as_block(target_document, insert_file, 0.0, 0.0, 0.0, cancel_event)
            inserted_count += 1

            bounds = _get_bounds(block_reference)
            if not bounds.is_valid:
                _regen(target_document, cancel_event)
                bounds = _get_bounds(block_reference)

            if bounds.is_valid:
                _move_block(block_reference, planned_x - bounds.min_x, baseline_y - bounds.min_y, -bounds.min_z, cancel_event)
                bounds = bounds.shift_to(planned_x, baseline_y, 0.0)
            else:
                log.warning(f"Nao foi possivel medir limites de {Path(input_file).name}; usando espaçamento conservador.")

            gap = max(bounds.width * RELATIVE_GAP_FACTOR, DEFAULT_GAP) if bounds.is_valid else DEFAULT_GAP
            next_min_x = (bounds.max_x if bounds.is_valid else planned_x + DEFAULT_GAP) + gap
            log.info(f"DWG inserido no Model Space: {Path(input_file).name}")
            log.info(f"Alinhamento aplicado: menor X = {planned_x:.3f}; menor Y = {baseline_y:.3f}.")
            log.info(f"Espacamento automatico reduzido aplicado: proximo X = {next_min_x:.3f}.")

        if inserted_count == 0:
            raise RuntimeError("Nenhum DWG foi inserido no arquivo final.")

        _check_cancel(cancel_event)
        _regen(target_document, cancel_event)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        _retry_com(lambda: target_document.SaveAs(output_path), cancel_event)
        log.info(f"Arquivo DWG final salvo: {output_path}")
    except Exception as exc:
        if isinstance(exc, CancelledError):
            raise
        hresult = getattr(exc, "hresult", None)
        busy_hint = ""
        if hresult == -2147417846:
            busy_hint = " O AutoCAD recusou chamadas COM por estar ocupado. Feche caixas de dialogo abertas no AutoCAD e tente novamente; normalmente nao precisa reiniciar o PC."
        if exc.__class__.__module__.startswith("pywintypes") or "COM" in exc.__class__.__name__.upper():
            raise RuntimeError("Falha na automacao do AutoCAD: " + str(exc) + busy_hint) from exc
        raise
    finally:
        if target_document is not None:
            try:
                _retry_com(lambda: target_document.Close(False), None, 3)
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
