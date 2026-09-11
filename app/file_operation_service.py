from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import os
import re
import shutil
import tempfile
import time

from pypdf import PdfReader

from . import file_name_recognizer
from .dwg_service import GridLayout, merge_with_autocad
from .log_writer import LogWriter
from .models import (
    NamingSuggestion,
    OperationOptions,
    OperationResult,
    RenamePreviewItem,
    SelectedFile,
)
from .pdf_service import (
    CancelledError,
    merge as merge_pdf_files,
    parse_intervals,
    sanitize_file_name as sanitize_split_name,
    split as split_pdf_file,
)
from .utils import desktop_directory, natural_key, notify_folder_change


class FileOperationService:
    def __init__(self) -> None:
        self.files: list[SelectedFile] = []
        self.last_output_files: list[str] = []
        self.last_output_folder: str | None = None
        self.output_folder: str | None = None

    def add_files(self, paths) -> int:
        paths = [str(path) for path in paths]
        added = 0
        incoming_paths = [
            self._clean_path(path)
            for path in paths
            if self._is_valid_supported_file(self._clean_path(path))
        ]

        if incoming_paths:
            self.last_output_files.clear()
            self.last_output_folder = None

        if self.files and incoming_paths:
            current_folder = os.path.dirname(self.files[0].full_path)
            incoming_folder = os.path.dirname(incoming_paths[0])
            if not self._same_path(current_folder, incoming_folder):
                # Arquivos de outra pasta comecam um lote novo: a numeracao
                # de folhas do lote anterior nao vale para eles.
                self.files.clear()
                self.output_folder = None

        for raw_path in paths:
            path = self._clean_path(raw_path)
            if not self._is_valid_supported_file(path):
                continue
            if any(self._same_path(file.full_path, path) for file in self.files):
                continue
            extension = Path(path).suffix.lower()

            stat = os.stat(path)
            self.files.append(
                SelectedFile(
                    uuid4().hex,
                    Path(path).name,
                    os.path.abspath(path),
                    extension.lstrip(".").upper(),
                    stat.st_size,
                    "Aguardando processamento",
                )
            )
            added += 1

        return added

    def clear(self) -> None:
        self.files.clear()
        self.last_output_files.clear()
        self.last_output_folder = None

    def clear_after_successful_operation(self) -> None:
        self.files.clear()

    def set_output_folder(self, folder: str) -> None:
        if not (folder or "").strip():
            return
        os.makedirs(folder, exist_ok=True)
        self.output_folder = folder
        self.last_output_files.clear()
        self.last_output_folder = None

    def get_current_output_folder(self) -> str:
        if self.files or self.output_folder:
            return self._get_output_folder()
        for latest in reversed(self.last_output_files):
            if os.path.isfile(latest):
                return os.path.dirname(latest) or self._get_output_folder()
        if self.last_output_folder:
            return self.last_output_folder
        return self._get_output_folder()

    def get_naming_suggestion(self) -> NamingSuggestion:
        if not self.files:
            return NamingSuggestion("IME-MC-1-43293", 1, 1, "Rev.0", False)

        detected = [file_name_recognizer.detect(file.name, index + 1) for index, file in enumerate(self.files)]
        first_recognized = next((item for item in detected if item.recognized), detected[0])
        sheets = [item.sheet for item in detected if item.sheet > 0]
        sheet_start = min(sheets, default=1)
        totals = [item.total_sheets for item in detected if item.total_sheets > 0]
        total_sheets = max(totals, default=0)
        if total_sheets <= 0:
            total_sheets = max(sheets, default=len(self.files))
        revision = next((item.revision for item in detected if item.revision), "Rev.0")
        return NamingSuggestion(first_recognized.code, sheet_start, max(total_sheets, sheet_start), revision, first_recognized.recognized)

    def rename_targets(self) -> list[SelectedFile]:
        """Arquivos que a renomeacao vai processar.

        Com formatos misturados na lista, so o formato mais numeroso e
        renomeado: o arquivo avulso normalmente entrou por engano na selecao e
        nao deve receber um numero da sequencia de folhas.
        """
        if not self.files:
            return []
        counts: dict[str, int] = {}
        for file in self.files:
            key = file.extension.upper()
            counts[key] = counts.get(key, 0) + 1
        if len(counts) <= 1:
            return list(self.files)
        first = self.files[0].extension.upper()
        main = max(counts.items(), key=lambda item: (item[1], item[0] == first))[0]
        return [file for file in self.files if file.extension.upper() == main]

    def generate_rename_preview(self, options: OperationOptions) -> list[RenamePreviewItem]:
        targets = self.rename_targets()
        detected = [file_name_recognizer.detect(file.name, index + 1) for index, file in enumerate(targets)]
        detected_total = max((item.total_sheets for item in detected if item.total_sheets > 0), default=0)
        detected_max_sheet = max((item.sheet for item in detected if item.sheet > 0), default=0)
        total_sheets = options.total_sheets if options.total_sheets > 0 else max(detected_total, detected_max_sheet, max(1, len(targets)))
        preview: list[RenamePreviewItem] = []
        for index, file in enumerate(targets):
            item = detected[index]
            sheet = options.sheet_start + index
            extension = Path(file.name).suffix
            new_name = self._build_output_name(options.output_pattern, item.code, sheet, total_sheets, options.revision, extension)
            output_path = str(Path(self._get_output_folder()) / new_name)
            preview.append(
                RenamePreviewItem(
                    file.id,
                    file.name,
                    new_name,
                    file.full_path,
                    output_path,
                    item.code,
                    sheet,
                    total_sheets,
                    options.revision,
                    item.recognized,
                    item.pattern,
                )
            )
        return preview

    def start(self, options: OperationOptions, cancel_event=None) -> OperationResult:
        log = LogWriter()
        output_folder = self._get_output_folder()
        os.makedirs(output_folder, exist_ok=True)
        self.last_output_files.clear()
        self.last_output_folder = output_folder
        source_folders = {os.path.dirname(file.full_path) for file in self.files}
        try:
            conflict = self._detect_conflicts(options, output_folder)
            if conflict is not None:
                return conflict
            if options.operation == "rename":
                self._rename_files(options, log, cancel_event)
            elif options.operation == "mergePdf":
                self._merge_pdf(output_folder, options, log, cancel_event)
            elif options.operation == "splitPdf":
                self._split_pdf(output_folder, options, log, cancel_event)
            elif options.operation == "mergeDwg":
                self._merge_dwg(output_folder, options, log, cancel_event)
            else:
                raise RuntimeError("Operacao nao suportada: " + options.operation)

            self._wait_for_output_files_ready(self.last_output_files, cancel_event)
            for folder in source_folders | {output_folder}:
                notify_folder_change(folder)
            return OperationResult(True, output_folder=output_folder, output_files=list(self.last_output_files), logs=list(log.entries))
        except CancelledError:
            log.warning("Operacao cancelada pelo usuario.")
            return OperationResult(False, cancelled=True, output_folder=output_folder, output_files=list(self.last_output_files), logs=list(log.entries))
        except Exception as exc:
            log.error(str(exc))
            return OperationResult(False, output_folder=output_folder, output_files=list(self.last_output_files), logs=list(log.entries))

    def _check_cancel(self, cancel_event) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise CancelledError()

    def _wait_for_output_files_ready(self, paths: list[str], cancel_event) -> None:
        pending = [path for path in paths if path]
        if not pending:
            return

        deadline = time.monotonic() + 12.0
        last_state: dict[str, tuple[int, int]] = {}
        stable_since: dict[str, float] = {}

        while pending:
            self._check_cancel(cancel_event)
            now = time.monotonic()
            listings: dict[str, set[str]] = {}
            for path in list(pending):
                folder = os.path.dirname(path) or "."
                if folder not in listings:
                    try:
                        listings[folder] = {entry.name.lower() for entry in os.scandir(folder)}
                    except OSError:
                        listings[folder] = set()
                if os.path.basename(path).lower() not in listings[folder]:
                    # o arquivo ainda nao aparece na listagem da pasta
                    last_state.pop(path, None)
                    stable_since.pop(path, None)
                    continue
                try:
                    stat = os.stat(path)
                    if stat.st_size <= 0:
                        raise OSError("Arquivo de saida vazio.")
                    with open(path, "rb") as handle:
                        handle.read(1)
                except OSError:
                    last_state.pop(path, None)
                    stable_since.pop(path, None)
                    continue

                state = (stat.st_size, stat.st_mtime_ns)
                if state != last_state.get(path):
                    last_state[path] = state
                    stable_since[path] = now
                    continue

                if now - stable_since.get(path, now) >= 0.75:
                    pending.remove(path)

            if not pending:
                return
            if now >= deadline:
                names = ", ".join(Path(path).name for path in pending)
                raise RuntimeError("A operacao terminou, mas o Windows ainda nao liberou os arquivos de saida: " + names)
            time.sleep(0.15)

    def _detect_conflicts(self, options: OperationOptions, output_folder: str) -> OperationResult | None:
        if options.overwrite_confirmed:
            return None
        if options.operation == "rename":
            conflicts = self._get_rename_conflicts(options)
        elif options.operation == "splitPdf":
            conflicts = self._get_pdf_split_conflict_paths(output_folder, options)
        elif options.operation in {"mergePdf", "mergeDwg"}:
            conflicts = self._get_merge_conflicts(options, output_folder)
        else:
            conflicts = []
        if not conflicts:
            return None
        return OperationResult(False, requires_overwrite_confirmation=True, output_folder=output_folder, conflicts=conflicts)

    def _rename_files(self, options: OperationOptions, log: LogWriter, cancel_event) -> None:
        preview = self.generate_rename_preview(options)
        if not preview:
            raise RuntimeError("Nenhum arquivo selecionado para renomear.")
        skipped = len(self.files) - len(preview)
        if skipped > 0:
            log.warning(f"{skipped} arquivo(s) de outro formato mantidos sem alteracao.")
        normalized_outputs = [os.path.normcase(os.path.abspath(item.output_path)) for item in preview]
        if len(normalized_outputs) != len(set(normalized_outputs)):
            raise RuntimeError("O padrao gerou nomes duplicados. Ajuste codigo, folha ou revisao antes de renomear.")

        staged: list[tuple[RenamePreviewItem, str]] = []
        try:
            for item in preview:
                self._check_cancel(cancel_event)
                if self._same_path(item.source_path, item.output_path):
                    self.last_output_files.append(item.output_path)
                    log.info(f"Nome mantido: {item.original_name}")
                    continue
                if not os.path.isfile(item.source_path):
                    raise FileNotFoundError(f"Arquivo de origem nao encontrado para renomear: {item.source_path}")
                temp_path = self._get_unique_temp_path(item.source_path)
                os.replace(item.source_path, temp_path)
                staged.append((item, temp_path))

            for item, temp_path in staged:
                self._check_cancel(cancel_event)
                Path(item.output_path).parent.mkdir(parents=True, exist_ok=True)
                if os.path.exists(item.output_path):
                    if not options.overwrite_confirmed:
                        raise FileExistsError(f"Arquivo ja existe: {item.output_path}")
                    os.remove(item.output_path)
                os.replace(temp_path, item.output_path)
                self.last_output_files.append(item.output_path)
                log.info(f"Renomeado: {item.original_name} -> {item.new_name}")
        except Exception:
            for item, temp_path in staged:
                try:
                    if os.path.isfile(temp_path) and not os.path.exists(item.source_path):
                        os.replace(temp_path, item.source_path)
                except Exception:
                    log.warning(f"Nao foi possivel restaurar arquivo temporario: {temp_path}")
            raise

    def _merge_pdf(self, output_folder: str, options: OperationOptions, log: LogWriter, cancel_event) -> None:
        pdfs = [file.full_path for file in self.files if file.extension.upper() == "PDF"]
        if len(pdfs) < 2:
            raise RuntimeError("Selecione ao menos dois PDFs para unir.")
        output_path = self._merge_pdf_output_path(output_folder, options, pdfs)
        # Gera primeiro em arquivo temporario. Assim o nome final pode ser
        # exatamente o mostrado na previa, mesmo quando ele coincide com um
        # dos PDFs de origem, sem truncar a origem durante a leitura.
        temp_output = os.path.join(output_folder, f".docflow_pdf_merge_{uuid4().hex}.pdf")
        try:
            self._check_cancel(cancel_event)
            merge_pdf_files(pdfs, temp_output, cancel_event)
            self._check_cancel(cancel_event)
            if not os.path.isfile(temp_output) or os.path.getsize(temp_output) == 0:
                raise RuntimeError("A uniao terminou sem gerar um PDF final valido.")
            os.replace(temp_output, output_path)
            self.last_output_files.append(output_path)
            log.info(f"PDF unido gerado: {output_path}")
            for pdf in pdfs:
                log.info(f"PDF incluido: {Path(pdf).name}")
        finally:
            try:
                if os.path.isfile(temp_output):
                    os.remove(temp_output)
            except Exception:
                log.warning("Nao foi possivel remover arquivo temporario: " + temp_output)

    def _split_pdf(self, output_folder: str, options: OperationOptions, log: LogWriter, cancel_event) -> None:
        pdfs = [file.full_path for file in self.files if file.extension.upper() == "PDF"]
        if not pdfs:
            has_dwg = any(file.extension.upper() == "DWG" for file in self.files)
            raise RuntimeError(
                "Separar PDF nao separa arquivos DWG. Selecione um arquivo PDF para separar paginas; para DWG, use a operacao Unir DWG."
                if has_dwg else "Selecione ao menos um PDF para separar."
            )
        for pdf in pdfs:
            self._check_cancel(cancel_event)
            base_name = self._split_output_base_name(options, len(pdfs))
            outputs = split_pdf_file(pdf, options.split_intervals, output_folder, options.overwrite_confirmed, cancel_event, base_name)
            for output in outputs:
                self.last_output_files.append(output)
                log.info(f"PDF separado gerado: {output}")

    def _merge_dwg(self, output_folder: str, options: OperationOptions, log: LogWriter, cancel_event) -> None:
        dwgs = [file.full_path for file in self.files if file.extension.upper() == "DWG"]
        if len(dwgs) < 2:
            raise RuntimeError("Selecione ao menos dois DWGs para unir.")
        source_folders = {os.path.normcase(os.path.abspath(os.path.dirname(path))) for path in dwgs}
        if len(source_folders) > 1:
            raise RuntimeError("A lista contem DWGs de pastas diferentes. Limpe a lista e selecione apenas os arquivos do mesmo lote antes de unir DWG.")

        ordered = self._order_dwg_inputs(dwgs)
        stage_folder = os.path.join(tempfile.gettempdir(), "DocFlow Manager", "DwgStage", uuid4().hex)
        temp_output = os.path.join(stage_folder, f"DocFlow_Work_{uuid4().hex}.dwg")
        output_path = self._get_exact_output_path(output_folder, "DWG_Unificado", ".dwg", options.output_file_name)
        started = time.monotonic()
        try:
            prepared = self._prepare_dwg_inputs_for_autocad(ordered, stage_folder, log, cancel_event)
            if len(prepared) < 2:
                raise RuntimeError("A uniao de DWG precisa de pelo menos dois desenhos validos. Verifique se os arquivos estao baixados do OneDrive e se abrem no AutoCAD.")
            log.info(f"Iniciando uniao otimizada de {len(prepared)} DWG(s). Arquivos temporarios locais: {stage_folder}")
            merge_with_autocad(prepared, temp_output, log, cancel_event, self._build_grid_layout(options))
            self._check_cancel(cancel_event)
            if not os.path.isfile(temp_output) or os.path.getsize(temp_output) == 0:
                raise RuntimeError("O AutoCAD terminou sem gerar um DWG final valido.")
            if os.path.isfile(output_path):
                os.remove(output_path)
            shutil.move(temp_output, output_path)
            self.last_output_files.append(output_path)
            elapsed = int(time.monotonic() - started)
            log.info(f"Tempo total da uniao de DWG: {elapsed // 60:02d}:{elapsed % 60:02d}.")
        finally:
            try:
                if os.path.isfile(temp_output):
                    os.remove(temp_output)
            except Exception:
                log.warning("Nao foi possivel remover arquivo temporario: " + temp_output)
            try:
                if os.path.isdir(stage_folder):
                    shutil.rmtree(stage_folder)
            except Exception:
                log.warning("Nao foi possivel remover pasta temporaria de DWG: " + stage_folder)
        log.info(f"DWG unido gerado: {output_path}")

    def _merge_pdf_output_path(self, output_folder: str, options: OperationOptions, pdfs: list[str]) -> str:
        """Caminho final da uniao de PDF.

        Protecao adicional: a uniao nunca deve sobrescrever silenciosamente um
        dos PDFs usados como origem. A interface ja mostra "Unificado" nesses
        casos; este calculo garante a mesma seguranca no backend.
        """
        output_path = self._get_exact_output_path(output_folder, "PDF_Unificado", ".pdf", options.output_file_name)
        if any(self._same_path(output_path, pdf) for pdf in pdfs):
            stem = Path(output_path).stem
            if not stem.lower().endswith(" unificado"):
                output_path = str(Path(output_folder) / f"{stem} Unificado.pdf")
        return output_path

    def _get_merge_conflicts(self, options: OperationOptions, output_folder: str) -> list[str]:
        """Uniao com nome exato nao pode apagar um arquivo pronto sem avisar.

        Renomear e separar ja pedem confirmacao; antes do nome exato a uniao
        desviava para "_02" sozinha e nunca chegava a sobrescrever nada.
        """
        try:
            if options.operation == "mergePdf":
                pdfs = [file.full_path for file in self.files if file.extension.upper() == "PDF"]
                if len(pdfs) < 2:
                    return []
                output_path = self._merge_pdf_output_path(output_folder, options, pdfs)
            else:
                if len([file for file in self.files if file.extension.upper() == "DWG"]) < 2:
                    return []
                output_path = self._get_exact_output_path(output_folder, "DWG_Unificado", ".dwg", options.output_file_name)
            return [output_path] if os.path.isfile(output_path) else []
        except Exception:
            return []

    @staticmethod
    def _build_grid_layout(options: OperationOptions) -> GridLayout:
        layout = options.dwg_layout
        return GridLayout(
            columns=layout.columns,
            rows=layout.rows,
            gap_x=layout.gap_x,
            gap_y=layout.gap_y,
            order=layout.order,
            uniform=layout.uniform,
        )

    def _order_dwg_inputs(self, dwgs: list[str]) -> list[str]:
        decorated = []
        for index, path in enumerate(dwgs):
            detected = file_name_recognizer.detect(Path(path).name, index + 1)
            sheet_key = detected.sheet if detected.sheet > 0 else 2**31 - 1
            decorated.append((sheet_key, natural_key(Path(path).name), index, path))
        decorated.sort(key=lambda x: (x[0], x[1], x[2]))
        return [item[3] for item in decorated]

    def _prepare_dwg_inputs_for_autocad(self, dwgs: list[str], stage_folder: str, log: LogWriter, cancel_event) -> list[str]:
        os.makedirs(stage_folder, exist_ok=True)
        prepared: list[str] = []
        for source_path in dwgs:
            self._check_cancel(cancel_event)
            kind = self._detect_drawing_file_kind(source_path)
            if kind == "invalid":
                log.warning(f"DWG ignorado porque o conteudo nao parece ser um desenho AutoCAD valido: {Path(source_path).name}")
                continue
            staged_extension = ".dxf" if kind == "dxf" else ".dwg"
            staged_name = self._sanitize_file_name(Path(source_path).stem)[:80]
            staged_path = os.path.join(stage_folder, f"{len(prepared) + 1:03d}-{staged_name}{staged_extension}")
            shutil.copy2(source_path, staged_path)
            prepared.append(staged_path)
            log.info(f"DWG preparado para AutoCAD [{len(prepared):03d}]: {Path(source_path).name}")
            if kind == "dxf":
                log.warning(f"O arquivo {Path(source_path).name} tem extensao .dwg, mas conteudo de DXF. O DocFlow tentara converter temporariamente antes de unir.")
        return prepared

    @staticmethod
    def _detect_drawing_file_kind(path: str) -> str:
        try:
            if not os.path.isfile(path) or os.path.getsize(path) < 16:
                return "invalid"
            with open(path, "rb") as handle:
                data = handle.read(512)
            header = data.decode("ascii", errors="ignore").replace("\r\n", "\n").lstrip("\x00\ufeff \t\r\n")
            if header.lower().startswith("ac10"):
                return "dwg"
            if header.lower().startswith("0\nsection") or "\nsection" in header.lower():
                return "dxf"
            return "invalid"
        except Exception:
            return "invalid"

    @staticmethod
    def _split_output_base_name(options: OperationOptions, pdf_count: int) -> str:
        """Nome base das paginas separadas.

        Com mais de um PDF na lista o nome vindo do padrao se repetiria em todos
        eles e as paginas colidiriam entre si; nesse caso cada arquivo usa o
        proprio nome como base.
        """
        return options.output_file_name if pdf_count == 1 else ""

    def _get_pdf_split_conflict_paths(self, output_folder: str, options: OperationOptions) -> list[str]:
        conflicts: list[str] = []
        try:
            pdfs = [file for file in self.files if file.extension.upper() == "PDF"]
            for pdf in pdfs:
                if not os.path.isfile(pdf.full_path):
                    continue
                reader = PdfReader(pdf.full_path)
                intervals = parse_intervals(options.split_intervals, len(reader.pages))
                requested = self._split_output_base_name(options, len(pdfs))
                base_name = sanitize_split_name(requested) if requested.strip() else Path(pdf.full_path).stem
                for interval in intervals:
                    suffix = f"pag_{interval.start}" if interval.start == interval.end else f"pag_{interval.start}-{interval.end}"
                    candidate = os.path.join(output_folder, f"{base_name}_{suffix}.pdf")
                    if os.path.isfile(candidate):
                        conflicts.append(candidate)
            return conflicts
        except Exception:
            return []

    def _get_rename_conflicts(self, options: OperationOptions) -> list[str]:
        preview = self.generate_rename_preview(options)
        source_paths = {os.path.normcase(os.path.abspath(item.source_path)) for item in preview}
        conflicts = []
        for item in preview:
            if self._same_path(item.source_path, item.output_path):
                continue
            normalized_output = os.path.normcase(os.path.abspath(item.output_path))
            if os.path.isfile(item.output_path) and normalized_output not in source_paths:
                conflicts.append(item.output_path)
        return conflicts

    def _get_output_folder(self) -> str:
        base_folder = os.path.dirname(self.files[0].full_path) if self.files else desktop_directory()
        return self.output_folder or base_folder

    def _get_exact_output_path(self, output_folder: str, default_base_name: str, extension: str, requested_name: str | None) -> str:
        # O arquivo gerado deve ter exatamente o nome mostrado na previa.
        # Nao use Path(...).stem aqui: nomes como "Rev.3" ou "Rev.A"
        # seriam interpretados como se ".3"/".A" fosse uma extensao e a revisao
        # desapareceria do nome final. Remove apenas a extensao real da operacao.
        if (requested_name or "").strip():
            requested = self._sanitize_file_name(requested_name)
            base_name = requested[:-len(extension)] if requested.lower().endswith(extension.lower()) else requested
        else:
            base_name = default_base_name
        base_name = base_name or default_base_name
        return os.path.join(output_folder, base_name + extension)

    def _get_unique_temp_path(self, source_path: str) -> str:
        folder = os.path.dirname(source_path) or desktop_directory()
        extension = Path(source_path).suffix
        for _ in range(1000):
            candidate = os.path.join(folder, f".docflow_rename_{uuid4().hex}{extension}")
            if not os.path.exists(candidate):
                return candidate
        return os.path.join(folder, f".docflow_rename_{time.strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:4]}{extension}")

    @staticmethod
    def _sanitize_file_name(value: str | None) -> str:
        sanitized = (value or "").strip()
        for invalid in '<>:"/\\|?*':
            sanitized = sanitized.replace(invalid, "-")
        return sanitized or "Documento"

    @classmethod
    def _build_output_name(cls, pattern: str, code: str, sheet: int, total: int, revision: str, extension: str) -> str:
        name = pattern
        replacements = {
            "{codigo}": code,
            "{code}": code,
            "{folha}": str(sheet),
            "{sheet}": str(sheet),
            "{total}": str(total),
            "{rev}": revision,
            "{revisao}": revision,
        }
        for token, value in replacements.items():
            name = re.sub(re.escape(token), lambda _: value, name, flags=re.I)
        sanitized = cls._sanitize_file_name(name)
        if sanitized.lower().endswith(extension.lower()):
            sanitized = sanitized[:-len(extension)]
        return sanitized + extension

    @staticmethod
    def _clean_path(path: str) -> str:
        return str(path or "").strip('" ')

    @staticmethod
    def _is_valid_supported_file(path: str) -> bool:
        return os.path.isabs(path) and os.path.isfile(path) and Path(path).suffix.lower() in {".pdf", ".dwg"}

    @staticmethod
    def _same_path(first: str, second: str) -> bool:
        try:
            return os.path.normcase(os.path.abspath(first)) == os.path.normcase(os.path.abspath(second))
        except Exception:
            return first.lower() == second.lower()
