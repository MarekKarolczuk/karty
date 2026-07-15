"""Etap C potoku eksportu: strategie WYJŚCIA — zapis struktur z Etapu B
do plików użytkownika (ZIP, folder PNG, PDF do druku, pojedyncze PNG).
"""
from __future__ import annotations

import io
import json
import zipfile
from abc import ABC, abstractmethod
from pathlib import Path

from PIL import Image

from app import config
from app.core.eksport.uklady import ProgressCb, WynikUkladu, _tick


class StrategiaWyjscia(ABC):
    """Strategia Etapu C — materializuje WynikUkladu na dysku."""

    @abstractmethod
    def zapisz(self, wynik: WynikUkladu, out_path: Path,
               progress: ProgressCb | None = None) -> Path:
        ...


def _png_bajty(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, "PNG", dpi=config.dpi_for_template(*img.size))
    return buffer.getvalue()


class WyjscieZIP(StrategiaWyjscia):
    """Pojedyncze PNG spakowane do ZIP-a + manifest.json z metadanych układu."""

    def zapisz(self, wynik: WynikUkladu, out_path: Path,
               progress: ProgressCb | None = None) -> Path:
        total = len(wynik.plotna)
        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for i, (nazwa, img) in enumerate(zip(wynik.nazwy, wynik.plotna)):
                archive.writestr(f"{nazwa}.png", _png_bajty(img))
                _tick(progress, i + 1, total)
            archive.writestr(
                "manifest.json",
                json.dumps(wynik.metadane, indent=2, ensure_ascii=False,
                           default=list))
        return out_path


class WyjscieFolder(StrategiaWyjscia):
    """Pojedyncze PNG 300 DPI do wskazanego folderu."""

    def zapisz(self, wynik: WynikUkladu, out_path: Path,
               progress: ProgressCb | None = None) -> Path:
        out_path.mkdir(parents=True, exist_ok=True)
        total = len(wynik.plotna)
        for i, (nazwa, img) in enumerate(zip(wynik.nazwy, wynik.plotna)):
            img.save(out_path / f"{nazwa}.png", "PNG",
                     dpi=config.dpi_for_template(*img.size))
            _tick(progress, i + 1, total)
        return out_path


class WyjsciePNG(StrategiaWyjscia):
    """Jedno płótno (atlas/sprite) do pojedynczego pliku PNG."""

    def zapisz(self, wynik: WynikUkladu, out_path: Path,
               progress: ProgressCb | None = None) -> Path:
        wynik.plotna[0].save(out_path, "PNG")
        _tick(progress, 1, 1)
        return out_path


class WyjsciePDF(StrategiaWyjscia):
    """Płótna A4 z Etapu B osadzane 1:1 na kolejnych stronach PDF-a
    gotowego do druku."""

    def zapisz(self, wynik: WynikUkladu, out_path: Path,
               progress: ProgressCb | None = None) -> Path:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas as pdf_canvas

        c = pdf_canvas.Canvas(str(out_path), pagesize=A4)
        c.setTitle("Atelier Kart — arkusz do druku "
                   f"{wynik.metadane.get('format', '')}".rstrip())
        total = len(wynik.plotna)
        for i, plotno in enumerate(wynik.plotna):
            # JPEG q92 zamiast bezstratnego osadzenia — przy 300 DPI różnica
            # w druku niewidoczna, a plik mniejszy o rząd wielkości
            strona = io.BytesIO()
            plotno.save(strona, "JPEG", quality=92)
            strona.seek(0)
            c.drawImage(ImageReader(strona), 0, 0,
                        width=A4[0], height=A4[1])
            c.showPage()
            _tick(progress, i + 1, total)
        c.save()
        return out_path
