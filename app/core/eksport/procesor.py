"""Etap A potoku eksportu: procesor POJEDYNCZEJ karty.

Operuje na oryginalnej rozdzielczości obrazu — spad liczony z RZECZYWISTEGO
DPI karty (piksele szerokości / mm formatu), nie ze sztywnych 300 DPI
(karty z output/ mają ~683 DPI; stary eksporter dawał im spad węższy niż 3 mm).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from app.core.eksport.formaty import FormatKarty


def wczytaj_karte(path: Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def wczytaj_rewers(path: Path) -> Image.Image:
    """Rewers do komórki pionowej — poziomy wzór (np. 88:63) obracany o 90°."""
    img = Image.open(path).convert("RGB")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    return img


def _dodaj_spad(img: Image.Image, spad_px: int) -> Image.Image:
    """Spad przez replikację skrajnych pikseli — grafika karty (w tym ramka)
    zostaje nienaruszona w linii cięcia, bez skalowania."""
    w, h = img.size
    out = Image.new("RGB", (w + 2 * spad_px, h + 2 * spad_px))
    out.paste(img, (spad_px, spad_px))
    # krawędzie
    out.paste(img.crop((0, 0, w, 1)).resize((w, spad_px)), (spad_px, 0))
    out.paste(img.crop((0, h - 1, w, h)).resize((w, spad_px)),
              (spad_px, h + spad_px))
    out.paste(img.crop((0, 0, 1, h)).resize((spad_px, h)), (0, spad_px))
    out.paste(img.crop((w - 1, 0, w, h)).resize((spad_px, h)),
              (w + spad_px, spad_px))
    # narożniki
    out.paste(img.crop((0, 0, 1, 1)).resize((spad_px, spad_px)), (0, 0))
    out.paste(img.crop((w - 1, 0, w, 1)).resize((spad_px, spad_px)),
              (w + spad_px, 0))
    out.paste(img.crop((0, h - 1, 1, h)).resize((spad_px, spad_px)),
              (0, h + spad_px))
    out.paste(img.crop((w - 1, h - 1, w, h)).resize((spad_px, spad_px)),
              (w + spad_px, h + spad_px))
    return out


def _rysuj_znaczniki(img: Image.Image, spad_px: int) -> Image.Image:
    """Znaczniki cięcia w polu spadu: krótkie kreski na przedłużeniach linii
    NETTO karty, dosunięte do zewnętrznych krawędzi obrazu (odstęp od linii
    cięcia, żeby nie dotykały grafiki)."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    dlugosc = max(2, round(spad_px * 0.6))
    grubosc = max(1, round(spad_px / 12))
    # linie cięcia: x = spad_px i w - spad_px; y = spad_px i h - spad_px
    for x in (spad_px, w - spad_px):
        draw.line([(x, 0), (x, dlugosc)], fill=(0, 0, 0), width=grubosc)
        draw.line([(x, h - dlugosc), (x, h)], fill=(0, 0, 0), width=grubosc)
    for y in (spad_px, h - spad_px):
        draw.line([(0, y), (dlugosc, y)], fill=(0, 0, 0), width=grubosc)
        draw.line([(w - dlugosc, y), (w, y)], fill=(0, 0, 0), width=grubosc)
    return img


@dataclass(frozen=True)
class ProcesorKarty:
    """Etap A: zależnie od flag nakłada ramkę spadu i rysuje znaczniki cięcia.
    Bez flag jest przezroczysty (ZIP/atlas dostają karty nietknięte)."""
    format: FormatKarty
    spad: bool = False
    znaczniki: bool = False

    def spad_px(self, img: Image.Image) -> int:
        """Szerokość spadu w pikselach TEGO obrazu (z jego realnego DPI)."""
        if not self.spad:
            return 0
        return max(1, round(self.format.spad_mm * img.width
                            / self.format.szerokosc_mm))

    def przetworz(self, img: Image.Image) -> Image.Image:
        spad_px = self.spad_px(img)
        if spad_px:
            img = _dodaj_spad(img, spad_px)
            if self.znaczniki:
                img = _rysuj_znaczniki(img, spad_px)
        return img
