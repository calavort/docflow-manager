from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from pypdf import PdfReader, PdfWriter, Transformation


class CancelledError(Exception):
    pass


def _check_cancel(cancel_event) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise CancelledError()


def _open_pdf(input_file: str) -> PdfReader:
    """Abre o PDF traduzindo falhas de leitura em uma mensagem clara."""
    try:
        return PdfReader(input_file)
    except Exception as exc:
        raise RuntimeError(
            f'Não foi possível ler o arquivo "{Path(input_file).name}". '
            "Verifique se ele é um PDF válido e se não está protegido ou danificado."
        ) from exc


def merge(input_files: list[str], output_path: str, cancel_event=None) -> None:
    if not input_files:
        raise ValueError("Nenhum PDF informado para uniao.")

    first_reader = _open_pdf(input_files[0])
    if not first_reader.pages:
        raise ValueError("O primeiro PDF nao possui paginas.")
    target_width = float(first_reader.pages[0].mediabox.width)
    target_height = float(first_reader.pages[0].mediabox.height)

    writer = PdfWriter()
    for input_file in input_files:
        _check_cancel(cancel_event)
        reader = _open_pdf(input_file)
        for source_page in reader.pages:
            _check_cancel(cancel_event)
            source_width = float(source_page.mediabox.width)
            source_height = float(source_page.mediabox.height)
            if source_width <= 0 or source_height <= 0:
                raise ValueError(f"Pagina PDF com dimensoes invalidas: {Path(input_file).name}")

            scale = min(target_width / source_width, target_height / source_height)
            draw_width = source_width * scale
            draw_height = source_height * scale
            x = (target_width - draw_width) / 2.0
            y = (target_height - draw_height) / 2.0

            page = writer.add_blank_page(width=target_width, height=target_height)
            transform = Transformation().scale(scale, scale).translate(tx=x, ty=y)
            page.merge_transformed_page(source_page, transform, expand=False)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as handle:
        writer.write(handle)


@dataclass(slots=True)
class PageInterval:
    start: int
    end: int


def parse_intervals(text: str, page_count: int) -> list[PageInterval]:
    if not (text or "").strip():
        return [PageInterval(page, page) for page in range(1, page_count + 1)]

    intervals: list[PageInterval] = []
    for raw_part in text.split(","):
        part = raw_part.strip()
        if not part:
            continue
        pieces = [piece.strip() for piece in part.split("-") if piece.strip()]
        if len(pieces) == 1 and pieces[0].isdigit():
            start = end = int(pieces[0])
        elif len(pieces) == 2 and pieces[0].isdigit() and pieces[1].isdigit():
            start, end = int(pieces[0]), int(pieces[1])
        else:
            raise ValueError(f"Intervalo invalido: {part}")
        if start < 1 or end < start or end > page_count:
            raise ValueError(f"Intervalo fora do limite do PDF: {start}-{end}. Total de paginas: {page_count}.")
        intervals.append(PageInterval(start, end))
    return intervals


def sanitize_file_name(value: str) -> str:
    invalid = '<>:"/\\|?*' if os.name == "nt" else "/\0"
    sanitized = (value or "").strip()
    for ch in invalid:
        sanitized = sanitized.replace(ch, "-")
    return Path(sanitized).stem if sanitized else "Documento"


def split(input_file: str, intervals_text: str, output_folder: str, overwrite: bool, cancel_event=None, output_base_name: str = "") -> list[str]:
    reader = _open_pdf(input_file)
    intervals = parse_intervals(intervals_text, len(reader.pages))
    base_name = sanitize_file_name(output_base_name) if output_base_name.strip() else Path(input_file).stem
    outputs: list[str] = []

    for interval in intervals:
        _check_cancel(cancel_event)
        writer = PdfWriter()
        for page_index in range(interval.start - 1, interval.end):
            _check_cancel(cancel_event)
            writer.add_page(reader.pages[page_index])
        suffix = f"pag_{interval.start}" if interval.start == interval.end else f"pag_{interval.start}-{interval.end}"
        output_path = str(Path(output_folder) / f"{base_name}_{suffix}.pdf")
        if os.path.exists(output_path) and not overwrite:
            raise FileExistsError(f"Arquivo ja existe: {output_path}")
        with open(output_path, "wb") as handle:
            writer.write(handle)
        outputs.append(output_path)
    return outputs
