"""Eksport talii: arkusz PDF A4 do druku (63×88 mm, spad, znaczniki cięcia),
ZIP z PNG dla programów oraz atlas sprite (Tabletop Simulator 10×7, 13×4).

Wszystko działa wyłącznie na plikach z dysku (output/, tla_kart/rewers.png) —
zero wywołań API.
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from PIL import Image, ImageOps

from app import config

MM_PER_INCH = 25.4
DPI = 300
# UWAGA: wymiary karty czytamy z config.CARD_MM na żywo wewnątrz eksportów —
# preset rozmiaru talii (Ustawienia) zmienia config.CARD_MM w trakcie sesji.
# 63/25.4*300 = 744.09 → 744×1039 px, standard wysokiej jakości dla TTS
CELL = (744, 1039)
CELL_SMALL = (409, 584)   # arkusz ≤4096 px dla starszych GPU

ProgressCb = Callable[[int, int], None]


@dataclass
class ExportJob:
    kind: str                                   # "pdf" | "zip" | "atlas" | "sprite"
    out_path: Path
    fronts: list[tuple[str, Path | None]]       # (nazwa np. "A_kier", ścieżka|None)
    back: Path | None = None
    columns: int = 3                            # PDF: 3×3 albo 2×3 na stronę
    bleed: bool = True                          # PDF: spad 3 mm
    marks: bool = True                          # PDF: znaczniki cięcia
    backs: bool = True                          # PDF: strony rewersów (duplex)
    small_atlas: bool = False                   # atlas ≤4096 px
    extra: dict = field(default_factory=dict)


def run_export(job: ExportJob, progress: ProgressCb | None = None) -> Path:
    if job.kind == "pdf":
        return export_pdf_print(job, progress)
    if job.kind == "files":
        return export_single_files(job, progress)
    if job.kind == "zip":
        return export_zip_png(job, progress)
    if job.kind == "atlas":
        return export_tts_atlas(job, progress)
    if job.kind == "sprite":
        return export_sprite_sheet(job, progress)
    raise ValueError(f"Nieznany rodzaj eksportu: {job.kind}")


def _tick(progress: ProgressCb | None, done: int, total: int) -> None:
    if progress is not None:
        progress(done, total)


def _existing(fronts: list[tuple[str, Path | None]]) -> list[tuple[str, Path]]:
    return [(name, path) for name, path in fronts
            if path is not None and path.exists()]


def _mm_to_px(mm: float) -> int:
    return round(mm / MM_PER_INCH * DPI)


def _add_bleed(img: Image.Image, bleed_px: int) -> Image.Image:
    """Spad przez replikację skrajnych pikseli — grafika karty (w tym ramka)
    zostaje nienaruszona w linii cięcia, bez skalowania."""
    w, h = img.size
    out = Image.new("RGB", (w + 2 * bleed_px, h + 2 * bleed_px))
    out.paste(img, (bleed_px, bleed_px))
    # krawędzie
    out.paste(img.crop((0, 0, w, 1)).resize((w, bleed_px)), (bleed_px, 0))
    out.paste(img.crop((0, h - 1, w, h)).resize((w, bleed_px)),
              (bleed_px, h + bleed_px))
    out.paste(img.crop((0, 0, 1, h)).resize((bleed_px, h)), (0, bleed_px))
    out.paste(img.crop((w - 1, 0, w, h)).resize((bleed_px, h)),
              (w + bleed_px, bleed_px))
    # narożniki
    out.paste(img.crop((0, 0, 1, 1)).resize((bleed_px, bleed_px)), (0, 0))
    out.paste(img.crop((w - 1, 0, w, 1)).resize((bleed_px, bleed_px)),
              (w + bleed_px, 0))
    out.paste(img.crop((0, h - 1, 1, h)).resize((bleed_px, bleed_px)),
              (0, h + bleed_px))
    out.paste(img.crop((w - 1, h - 1, w, h)).resize((bleed_px, bleed_px)),
              (w + bleed_px, h + bleed_px))
    return out


def _load_card_image(path: Path, bleed_px: int) -> Image.Image:
    img = Image.open(path).convert("RGB")
    if bleed_px > 0:
        img = _add_bleed(img, bleed_px)
    return img


def _load_back_image(path: Path) -> Image.Image:
    """Rewers do komórki pionowej — poziomy wzór (88:63) jest obracany o 90°."""
    img = Image.open(path).convert("RGB")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    return img


# --------------------------------------------------------------------- PDF A4
def export_pdf_print(job: ExportJob, progress: ProgressCb | None = None) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    cards = _existing(job.fronts)
    if not cards:
        raise ValueError("Brak wygenerowanych kart do eksportu (output/ puste)")

    card_w_mm, card_h_mm = config.CARD_MM
    cols, rows = job.columns, 3
    bleed_mm = 3.0 if job.bleed else 0.0
    cell_w = card_w_mm + 2 * bleed_mm
    cell_h = card_h_mm + 2 * bleed_mm
    page_w_mm, page_h_mm = A4[0] / mm, A4[1] / mm
    block_w, block_h = cols * cell_w, rows * cell_h
    if block_w > page_w_mm or block_h > page_h_mm:
        raise ValueError(
            f"Siatka {cols}×{rows} ze spadem nie mieści się na A4 — "
            f"wybierz układ 2×3 albo wyłącz spad"
        )
    margin_x = (page_w_mm - block_w) / 2
    margin_y = (page_h_mm - block_h) / 2
    bleed_px = _mm_to_px(bleed_mm)

    c = pdf_canvas.Canvas(str(job.out_path), pagesize=A4)
    c.setTitle("Atelier Kart — arkusz do druku 63×88 mm")

    per_page = cols * rows
    pages = [cards[i:i + per_page] for i in range(0, len(cards), per_page)]
    back_img = None
    if job.backs and job.back is not None and job.back.exists():
        back_img = _load_back_image(job.back)
        if bleed_px > 0:
            back_img = _add_bleed(back_img, bleed_px)

    total = sum(len(p) for p in pages) * (2 if back_img is not None else 1)
    done = 0

    def cell_origin(col: int, row: int) -> tuple[float, float]:
        """Lewy-dolny róg komórki w mm (PDF liczy od dołu)."""
        x = margin_x + col * cell_w
        y = page_h_mm - margin_y - (row + 1) * cell_h
        return x, y

    def draw_marks(count: int) -> None:
        """Znaczniki cięcia na przedłużeniach linii NETTO siatki, poza blokiem."""
        if not job.marks:
            return
        c.setLineWidth(0.25)
        c.setStrokeColorRGB(0, 0, 0)
        mark = 3.0  # mm
        gap = 0.5   # odstęp od pola spadu
        xs, ys = set(), set()
        for i in range(count):
            col, row = i % cols, i // cols
            x0, y0 = cell_origin(col, row)
            xs.update((x0 + bleed_mm, x0 + bleed_mm + card_w_mm))
            ys.update((y0 + bleed_mm, y0 + bleed_mm + card_h_mm))
        top = page_h_mm - margin_y + gap
        bottom = margin_y - gap
        for x in xs:
            c.line(x * mm, top * mm, x * mm, (top + mark) * mm)
            c.line(x * mm, bottom * mm, x * mm, (bottom - mark) * mm)
        left = margin_x - gap
        right = page_w_mm - margin_x + gap
        for y in ys:
            c.line(left * mm, y * mm, (left - mark) * mm, y * mm)
            c.line(right * mm, y * mm, (right + mark) * mm, y * mm)

    for page_cards in pages:
        # strona frontów
        for i, (_name, path) in enumerate(page_cards):
            col, row = i % cols, i // cols
            x, y = cell_origin(col, row)
            img = _load_card_image(path, bleed_px)
            c.drawImage(ImageReader(img), x * mm, y * mm,
                        cell_w * mm, cell_h * mm)
            done += 1
            _tick(progress, done, total)
        draw_marks(len(page_cards))
        c.showPage()

        # strona rewersów (lustrzane kolumny — duplex po długiej krawędzi)
        if back_img is not None:
            for i in range(len(page_cards)):
                col, row = i % cols, i // cols
                mirrored = cols - 1 - col
                x, y = cell_origin(mirrored, row)
                c.drawImage(ImageReader(back_img), x * mm, y * mm,
                            cell_w * mm, cell_h * mm)
                done += 1
                _tick(progress, done, total)
            draw_marks(len(page_cards))
            c.showPage()

    c.save()
    return job.out_path


# -------------------------------------------------------- pojedyncze pliki PNG
def export_single_files(job: ExportJob, progress: ProgressCb | None = None) -> Path:
    """Zapis kart jako pojedyncze PNG 300 DPI do wskazanego folderu."""
    cards = _existing(job.fronts)
    if not cards:
        raise ValueError("Brak wygenerowanych kart do eksportu (output/ puste)")
    out_dir = job.out_path
    out_dir.mkdir(parents=True, exist_ok=True)

    total = len(cards) + (1 if job.back and job.back.exists() else 0)
    done = 0
    for name, path in cards:
        img = Image.open(path).convert("RGB")
        img.save(out_dir / f"{name}.png", "PNG",
                 dpi=config.dpi_for_template(*img.size))
        done += 1
        _tick(progress, done, total)
    if job.back is not None and job.back.exists():
        img = _load_back_image(job.back)
        img.save(out_dir / "rewers.png", "PNG",
                 dpi=config.dpi_for_template(*img.size))
        done += 1
        _tick(progress, done, total)
    return out_dir


# --------------------------------------------------------------------- ZIP PNG
def export_zip_png(job: ExportJob, progress: ProgressCb | None = None) -> Path:
    cards = _existing(job.fronts)
    if not cards:
        raise ValueError("Brak wygenerowanych kart do eksportu (output/ puste)")
    missing = [name for name, path in job.fronts
               if path is None or not path.exists()]

    total = len(cards) + (1 if job.back and job.back.exists() else 0)
    done = 0
    sizes: set[tuple[int, int]] = set()

    with zipfile.ZipFile(job.out_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in cards:
            img = Image.open(path).convert("RGB")
            sizes.add(img.size)
            buffer = io.BytesIO()
            img.save(buffer, "PNG", dpi=config.dpi_for_template(*img.size))
            archive.writestr(f"{name}.png", buffer.getvalue())
            done += 1
            _tick(progress, done, total)
        if job.back is not None and job.back.exists():
            img = _load_back_image(job.back)
            buffer = io.BytesIO()
            img.save(buffer, "PNG", dpi=config.dpi_for_template(*img.size))
            archive.writestr("rewers.png", buffer.getvalue())
            done += 1
            _tick(progress, done, total)
        manifest = {
            "format": f"{config.CARD_MM[0]:g}x{config.CARD_MM[1]:g} mm",
            "dpi_hint": DPI,
            "cards": [name for name, _ in cards],
            "missing": missing,
            "back": bool(job.back and job.back.exists()),
            "sizes_px": sorted(list(sizes)),
        }
        archive.writestr("manifest.json",
                         json.dumps(manifest, indent=2, ensure_ascii=False))
    return job.out_path


# ------------------------------------------------------------------- Atlas TTS
def export_tts_atlas(job: ExportJob, progress: ProgressCb | None = None) -> Path:
    """Atlas 10×7 dla Tabletop Simulator: pola 0-51 = karty,
    ostatnie pole (69) = rewers (TTS traktuje je jako 'hidden back')."""
    cell = CELL_SMALL if job.small_atlas else CELL
    cols, rows = 10, 7
    sheet = Image.new("RGB", (cols * cell[0], rows * cell[1]), config.CREAM_HEX)

    back_img = None
    if job.back is not None and job.back.exists():
        back_img = ImageOps.fit(_load_back_image(job.back), cell,
                                method=Image.Resampling.LANCZOS)

    filler = back_img if back_img is not None \
        else Image.new("RGB", cell, config.CREAM_HEX)

    total = cols * rows
    done = 0
    for i in range(total):
        col, row = i % cols, i // cols
        pos = (col * cell[0], row * cell[1])
        if i < len(job.fronts):
            _name, path = job.fronts[i]
            if path is not None and path.exists():
                img = ImageOps.fit(Image.open(path).convert("RGB"), cell,
                                   method=Image.Resampling.LANCZOS)
                sheet.paste(img, pos)
            else:
                sheet.paste(filler, pos)
        else:
            sheet.paste(filler, pos)
        done += 1
        _tick(progress, done, total)
    # ostatnie pole = rewers
    sheet.paste(filler, ((cols - 1) * cell[0], (rows - 1) * cell[1]))

    sheet.save(job.out_path, "PNG")
    return job.out_path


# --------------------------------------------------------------- Sprite 13×4
def export_sprite_sheet(job: ExportJob, progress: ProgressCb | None = None) -> Path:
    """Klasyczny sprite-sheet 13×4 (same fronty, wiersz = kolor)."""
    cell = CELL_SMALL if job.small_atlas else CELL
    cols, rows = 13, 4
    sheet = Image.new("RGB", (cols * cell[0], rows * cell[1]), config.CREAM_HEX)
    total = min(len(job.fronts), cols * rows)
    done = 0
    for i, (_name, path) in enumerate(job.fronts[:cols * rows]):
        col, row = i % cols, i // cols
        if path is not None and path.exists():
            img = ImageOps.fit(Image.open(path).convert("RGB"), cell,
                               method=Image.Resampling.LANCZOS)
            sheet.paste(img, (col * cell[0], row * cell[1]))
        done += 1
        _tick(progress, done, total)
    sheet.save(job.out_path, "PNG")
    return job.out_path
