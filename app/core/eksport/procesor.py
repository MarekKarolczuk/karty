"""Etap A potoku eksportu: procesor POJEDYNCZEJ karty.

Operuje na oryginalnej rozdzielczości obrazu — spad liczony z RZECZYWISTEGO
DPI karty (piksele szerokości / mm formatu), nie ze sztywnych 300 DPI
(karty z output/ mają ~683 DPI; stary eksporter dawał im spad węższy niż 3 mm).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
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
    # narożniki: średni kolor małego bloku karty przy rogu (nie pojedynczy
    # skrajny piksel — bywa białawym artefaktem krawędzi i psuł kolor rogów)
    c = max(2, spad_px)

    def _rog(box: tuple[int, int, int, int]) -> Image.Image:
        piksel = img.crop(box).convert("RGB").resize((1, 1)).getpixel((0, 0))
        assert isinstance(piksel, tuple)                # RGB → (R, G, B)
        return Image.new("RGB", (spad_px, spad_px),
                         (int(piksel[0]), int(piksel[1]), int(piksel[2])))

    out.paste(_rog((0, 0, c, c)), (0, 0))
    out.paste(_rog((w - c, 0, w, c)), (w + spad_px, 0))
    out.paste(_rog((0, h - c, c, h)), (0, h + spad_px))
    out.paste(_rog((w - c, h - c, w, h)), (w + spad_px, h + spad_px))
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


# ------------------------------------------------------------------- druk KRM
# Udział krótszego boku karty pobierany jako obwódka do wyliczenia koloru tła.
_KRM_RING = 0.02
# Zaokrąglone narożniki: bok narożnego okna (udział krótszego boku) i próg
# jasności, powyżej którego piksel uznajemy za „papier" (biel poza konturem
# karty), a nie za grafikę.
_KRM_ROG_UDZIAL = 0.06
_KRM_ROG_PROG = 235


def zalej_rogi(img: Image.Image, kolor: tuple[int, int, int]) -> Image.Image:
    """Białe zaokrąglenia narożników zalane kolorem tła.

    Pliki kart mają zwykle wycięte, białe rogi. Drukarnia zabrania ich wprost
    (żadnych białych rogów ani masek zaokrąglających), a po wklejeniu na płótno
    zostałyby jasnymi trójkącikami przy krawędzi.

    Zaokrąglenie to ćwiartka koła, więc w każdym wierszu narożnego okna białe
    piksele tworzą CIĄGŁY prefiks od brzegu — wystarczy go zmierzyć i zamalować
    (żadnego flood-fillu, czyste numpy). Ruszamy tylko wtedy, gdy sam róg jest
    jasny jak papier: karta z grafiką idącą do samego rogu zostaje nietknięta."""
    arr = np.asarray(img.convert("RGB")).copy()
    h, w = arr.shape[:2]
    bok = max(4, round(min(w, h) * _KRM_ROG_UDZIAL))
    jasne = arr.min(axis=2) >= _KRM_ROG_PROG
    for sy, sx in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        # widok z rogiem w [0, 0] — ujemny krok odbija okno, zapis idzie do arr
        ys = slice(None, bok) if sy > 0 else slice(None, -bok - 1, -1)
        xs = slice(None, bok) if sx > 0 else slice(None, -bok - 1, -1)
        okno_jasne, okno = jasne[ys, xs], arr[ys, xs]
        if not okno_jasne[0, 0]:
            continue                      # róg to grafika — nic nie zalewamy
        for y in range(bok):
            niejasne = np.flatnonzero(~okno_jasne[y])
            dlugosc = int(niejasne[0]) if niejasne.size else bok
            if dlugosc:
                # +1 piksel na antyaliasowaną krawędź zaokrąglenia
                okno[y, :min(bok, dlugosc + 1)] = kolor
    return Image.fromarray(arr)


def kolor_krawedzi(img: Image.Image) -> tuple[int, int, int]:
    """Jednolity kolor tła pobrany z KRAWĘDZI karty: mediana pikseli obwódki
    (odporna na pojedyncze artefakty krawędzi, w odróżnieniu od średniej)."""
    arr = np.asarray(img.convert("RGB"))
    h, w = arr.shape[:2]
    ring = max(1, round(min(w, h) * _KRM_RING))
    piksele = np.concatenate([
        arr[:ring].reshape(-1, 3), arr[-ring:].reshape(-1, 3),
        arr[:, :ring].reshape(-1, 3), arr[:, -ring:].reshape(-1, 3),
    ])
    mediana = np.median(piksele, axis=0)
    return (int(mediana[0]), int(mediana[1]), int(mediana[2]))


@dataclass(frozen=True)
class ProcesorKRM:
    """Etap A dla druku w KRM: karta przeskalowana w głąb marginesu
    bezpieczeństwa i wyśrodkowana na płótnie BRUTTO (netto + spad), którego
    całą powierzchnię wypełnia jednolite tło z krawędzi karty.

    Skalowanie jest JEDNOLITE (proporcja karty zachowana), więc grafika mieści
    się w prostokącie `format.mm_ramki`, nigdy go nie przekraczając. Płótno jest
    w trybie RGB — żadnej alfy, żadnych masek zaokrąglających, żadnych białych
    rogów. Znaczników cięcia celowo brak: cały obwód to spad + margines
    bezpieczeństwa, kreski wpadłyby w obszar drukowany.
    """
    format: FormatKarty

    def przetworz(self, img: Image.Image) -> Image.Image:
        img = img.convert("RGB")
        tlo = kolor_krawedzi(img)
        img = zalej_rogi(img, tlo)        # białe zaokrąglenia → kolor tła
        plotno_px = self.format.px_300dpi_ze_spadem
        ramka_px = self.format.px_ramki_300dpi
        skala = min(ramka_px[0] / img.width, ramka_px[1] / img.height)
        cel = (max(1, round(img.width * skala)), max(1, round(img.height * skala)))
        karta = img.resize(cel, Image.Resampling.LANCZOS)

        out = Image.new("RGB", plotno_px, tlo)
        out.paste(karta, (round((plotno_px[0] - cel[0]) / 2),
                          round((plotno_px[1] - cel[1]) / 2)))
        return out


# Etapy A są wymienne — manager woła wyłącznie `.przetworz()`.
Procesor = ProcesorKarty | ProcesorKRM
