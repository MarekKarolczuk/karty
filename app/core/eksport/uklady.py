"""Etap B potoku eksportu: strategie UKŁADANIA przetworzonych kart na płótnach.

Trzy strategie: UkladPojedynczy (karty bez zmian), UkladAtlas (jedna wielka
siatka — presety TTS 10×7 i sprite 13×4) oraz UkladA4 (arkusze do druku IRL:
siatka wyliczana DYNAMICZNIE z formatu karty, opcjonalny duplex ze stronami
rewersów odbitymi lustrzanie w kolumnach).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from math import floor
from typing import Callable

from PIL import Image, ImageOps

from app import config
from app.core.eksport.formaty import A4_MM, DPI_DRUKU, FormatKarty, mm_na_px

ProgressCb = Callable[[int, int], None]

# komórka atlasu przy 300 DPI dla karty pokerowej (63/25.4*300 = 744.09 →
# 744×1039 px, standard wysokiej jakości dla TTS) i wariant ≤4096 px dla
# starszych GPU
CELL = (744, 1039)
CELL_SMALL = (409, 584)

# karta = (nazwa, obraz | None) — None to karta niewygenerowana; strategie
# same decydują, czy brak pomijają (Single/A4), czy wypełniają (Atlas)
Karta = tuple[str, Image.Image | None]


def _tick(progress: ProgressCb | None, done: int, total: int) -> None:
    if progress is not None:
        progress(done, total)


@dataclass
class WynikUkladu:
    """Wyjście Etapu B: płótna z równoległymi nazwami + metadane dla Etapu C
    (np. manifest ZIP-a albo parametry siatki do tytułu PDF-a)."""
    plotna: list[Image.Image]
    nazwy: list[str]
    metadane: dict = field(default_factory=dict)


class StrategiaUkladu(ABC):
    """Strategia Etapu B — odbiera karty z Etapu A, zwraca płótna."""

    @abstractmethod
    def uloz(self, karty: list[Karta], rewers: Image.Image | None,
             progress: ProgressCb | None = None) -> WynikUkladu:
        ...


# ------------------------------------------------------------------ pojedyncze
class UkladPojedynczy(StrategiaUkladu):
    """Karty w postaci niezmienionej (tablica pojedynczych obrazów) + rewers
    jako osobna pozycja; metadane = manifest talii (dla ZIP-a)."""

    def __init__(self, format: FormatKarty):
        self.format = format

    def uloz(self, karty: list[Karta], rewers: Image.Image | None,
             progress: ProgressCb | None = None) -> WynikUkladu:
        obecne = [(n, img) for n, img in karty if img is not None]
        plotna = [img for _n, img in obecne]
        nazwy = [n for n, _img in obecne]
        if rewers is not None:
            plotna.append(rewers)
            nazwy.append("rewers")
        manifest = {
            "format": f"{self.format.szerokosc_mm:g}x"
                      f"{self.format.wysokosc_mm:g} mm",
            "dpi_hint": DPI_DRUKU,
            "cards": [n for n, _img in obecne],
            "missing": [n for n, img in karty if img is None],
            "back": rewers is not None,
            "sizes_px": sorted({img.size for _n, img in obecne}),
        }
        _tick(progress, len(plotna), len(plotna))
        return WynikUkladu(plotna, nazwy, manifest)


# ----------------------------------------------------------------------- atlas
class UkladAtlas(StrategiaUkladu):
    """Sprite sheet: wszystkie karty sklejone w jedną siatkę kolumny×wiersze.
    Brakująca karta = wypełniacz (rewers, jeśli wypelniaj_rewersem, inaczej
    krem); rewers_w_ostatnim_polu = konwencja TTS („hidden back")."""

    def __init__(self, kolumny: int, wiersze: int, komorka: tuple[int, int],
                 wypelniaj_rewersem: bool = True,
                 rewers_w_ostatnim_polu: bool = False):
        self.kolumny = kolumny
        self.wiersze = wiersze
        self.komorka = komorka
        self.wypelniaj_rewersem = wypelniaj_rewersem
        self.rewers_w_ostatnim_polu = rewers_w_ostatnim_polu

    def uloz(self, karty: list[Karta], rewers: Image.Image | None,
             progress: ProgressCb | None = None) -> WynikUkladu:
        cw, ch = self.komorka
        sheet = Image.new("RGB", (self.kolumny * cw, self.wiersze * ch),
                          config.CREAM_HEX)
        wypelniacz = None
        if self.wypelniaj_rewersem and rewers is not None:
            wypelniacz = ImageOps.fit(rewers, self.komorka,
                                      method=Image.Resampling.LANCZOS)

        total = self.kolumny * self.wiersze
        for i in range(total):
            pos = ((i % self.kolumny) * cw, (i // self.kolumny) * ch)
            img = karty[i][1] if i < len(karty) else None
            if img is not None:
                sheet.paste(ImageOps.fit(img, self.komorka,
                                         method=Image.Resampling.LANCZOS), pos)
            elif self.wypelniaj_rewersem and wypelniacz is not None:
                sheet.paste(wypelniacz, pos)
            _tick(progress, i + 1, total)
        if self.rewers_w_ostatnim_polu and wypelniacz is not None:
            sheet.paste(wypelniacz,
                        ((self.kolumny - 1) * cw, (self.wiersze - 1) * ch))
        return WynikUkladu([sheet], ["atlas"],
                           {"kolumny": self.kolumny, "wiersze": self.wiersze})


def atlas_tts(maly: bool = False) -> UkladAtlas:
    """Preset TTS 10×7: pola 0-51 = karty, brak/nadmiar = rewers,
    ostatnie pole (69) = rewers (TTS traktuje je jako 'hidden back')."""
    return UkladAtlas(10, 7, CELL_SMALL if maly else CELL,
                      wypelniaj_rewersem=True, rewers_w_ostatnim_polu=True)


def sprite_13x4(maly: bool = False) -> UkladAtlas:
    """Klasyczny sprite-sheet 13×4 (same fronty, wiersz = kolor)."""
    return UkladAtlas(13, 4, CELL_SMALL if maly else CELL,
                      wypelniaj_rewersem=False)


# -------------------------------------------------------------------- A4 druk
class UkladA4(StrategiaUkladu):
    """Arkusze A4 @300 DPI do druku IRL. Siatka wyliczana DYNAMICZNIE
    z wymiarów formatu (+spad): poker/bridge ze spadem → 3×3, tarot → 2×2,
    mini → 4×4. Duplex: po każdej stronie awersów strona rewersów
    z kolumnami odbitymi LUSTRZANIE (druk dwustronny po długiej krawędzi)."""

    def __init__(self, format: FormatKarty, spad: bool = True,
                 dwustronny: bool = True, max_kolumny: int | None = None):
        self.format = format
        self.dwustronny = dwustronny
        cell_w, cell_h = format.mm_ze_spadem if spad else format.mm
        self.cell_mm = (cell_w, cell_h)
        self.kolumny = floor(A4_MM[0] / cell_w)
        self.wiersze = floor(A4_MM[1] / cell_h)
        if max_kolumny is not None:
            self.kolumny = min(self.kolumny, max_kolumny)
        if self.kolumny < 1 or self.wiersze < 1:
            raise ValueError(
                f"Karta {format.etykieta} ze spadem nie mieści się na A4")
        # marginesy centrujące blok siatki na stronie
        self._margines_mm = (
            (A4_MM[0] - self.kolumny * cell_w) / 2,
            (A4_MM[1] - self.wiersze * cell_h) / 2,
        )
        self.komorka_px = (mm_na_px(cell_w), mm_na_px(cell_h))
        self.strona_px = (mm_na_px(A4_MM[0]), mm_na_px(A4_MM[1]))

    @property
    def na_strone(self) -> int:
        return self.kolumny * self.wiersze

    # --- czyste funkcje pozycjonowania (testowalne bez renderu) ---------------
    def pozycja_komorki(self, indeks: int) -> tuple[int, int]:
        """Strona A (awersy): wypełnianie wierszami od lewej do prawej.
        Zwraca piksel lewego-górnego rogu komórki na płótnie A4."""
        kol, rzad = indeks % self.kolumny, indeks // self.kolumny
        return self._px(kol, rzad)

    def pozycja_rewersu(self, indeks: int) -> tuple[int, int]:
        """Strona B (rewersy): ten sam rząd, kolumna odbita LUSTRZANIE
        (od prawej do lewej) — po druku dwustronnym rewers trafia dokładnie
        na plecy swojego awersu."""
        kol, rzad = indeks % self.kolumny, indeks // self.kolumny
        return self._px(self.kolumny - 1 - kol, rzad)

    def _px(self, kol: int, rzad: int) -> tuple[int, int]:
        x_mm = self._margines_mm[0] + kol * self.cell_mm[0]
        y_mm = self._margines_mm[1] + rzad * self.cell_mm[1]
        return (mm_na_px(x_mm), mm_na_px(y_mm))

    # --------------------------------------------------------------------------
    def uloz(self, karty: list[Karta], rewers: Image.Image | None,
             progress: ProgressCb | None = None) -> WynikUkladu:
        obecne = [(n, img) for n, img in karty if img is not None]
        strony = [obecne[i:i + self.na_strone]
                  for i in range(0, len(obecne), self.na_strone)]
        rewers_cell = (rewers.resize(self.komorka_px,
                                     Image.Resampling.LANCZOS)
                       if self.dwustronny and rewers is not None else None)

        total = sum(len(s) for s in strony) * (2 if rewers_cell is not None
                                               else 1)
        done = 0
        plotna: list[Image.Image] = []
        nazwy: list[str] = []
        for nr, strona in enumerate(strony, start=1):
            awersy = Image.new("RGB", self.strona_px, "white")
            for i, (_n, img) in enumerate(strona):
                awersy.paste(img.resize(self.komorka_px,
                                        Image.Resampling.LANCZOS),
                             self.pozycja_komorki(i))
                done += 1
                _tick(progress, done, total)
            plotna.append(awersy)
            nazwy.append(f"strona_{nr:02d}_awersy")

            if rewers_cell is not None:
                rewersy = Image.new("RGB", self.strona_px, "white")
                for i in range(len(strona)):
                    rewersy.paste(rewers_cell, self.pozycja_rewersu(i))
                    done += 1
                    _tick(progress, done, total)
                plotna.append(rewersy)
                nazwy.append(f"strona_{nr:02d}_rewersy")

        return WynikUkladu(plotna, nazwy, {
            "format": self.format.etykieta,
            "kolumny": self.kolumny,
            "wiersze": self.wiersze,
        })
