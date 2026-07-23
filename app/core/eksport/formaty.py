"""Konfiguracja formatów kart potoku eksportu — JEDNO źródło prawdy.

Wymiary w mm żyją wyłącznie w config.CARD_PRESETS (poker 63×88, bridge 57×88,
tarot 70×120, mini 44×63); ten moduł opakowuje je w obiekty FormatKarty
z przelicznikami na piksele druku (300 DPI) i spadem — żadnych powielonych
magicznych liczb w dalszych etapach potoku.
"""
from __future__ import annotations

from dataclasses import dataclass

from app import config

MM_NA_CAL = 25.4
DPI_DRUKU = 300
SPAD_MM = 3.0          # domyślna szerokość spadu drukarskiego
# Margines bezpieczeństwa drukarni: grafika (ramka + wszystko w środku) musi
# zmieścić się tyle milimetrów W GŁĄB od linii cięcia (wymóg KRM).
MARGINES_BEZPIECZENSTWA_MM = 5.0
A4_MM = (210.0, 297.0)


def mm_na_px(mm: float, dpi: int = DPI_DRUKU) -> int:
    """Milimetry → piksele przy zadanym DPI (domyślnie 300 — druk)."""
    return round(mm / MM_NA_CAL * dpi)


@dataclass(frozen=True)
class FormatKarty:
    """Parametry jednego formatu karty (wymiary NETTO, bez spadu)."""
    klucz: str
    etykieta: str
    szerokosc_mm: float
    wysokosc_mm: float
    spad_mm: float = SPAD_MM
    margines_mm: float = MARGINES_BEZPIECZENSTWA_MM

    @property
    def mm(self) -> tuple[float, float]:
        return (self.szerokosc_mm, self.wysokosc_mm)

    @property
    def mm_ze_spadem(self) -> tuple[float, float]:
        return (self.szerokosc_mm + 2 * self.spad_mm,
                self.wysokosc_mm + 2 * self.spad_mm)

    @property
    def px_300dpi(self) -> tuple[int, int]:
        """Rozdzielczość karty netto przy 300 DPI (poker: 744×1039)."""
        return (mm_na_px(self.szerokosc_mm), mm_na_px(self.wysokosc_mm))

    @property
    def px_300dpi_ze_spadem(self) -> tuple[int, int]:
        w, h = self.mm_ze_spadem
        return (mm_na_px(w), mm_na_px(h))

    @property
    def mm_ramki(self) -> tuple[float, float]:
        """Maksymalny prostokąt GRAFIKI karty: netto pomniejszone o margines
        bezpieczeństwa z każdej strony (poker: 53 × 78 mm)."""
        return (self.szerokosc_mm - 2 * self.margines_mm,
                self.wysokosc_mm - 2 * self.margines_mm)

    @property
    def px_ramki_300dpi(self) -> tuple[int, int]:
        w, h = self.mm_ramki
        return (mm_na_px(w), mm_na_px(h))


def formaty() -> dict[str, FormatKarty]:
    """Wszystkie obsługiwane formaty, zbudowane z config.CARD_PRESETS."""
    return {
        klucz: FormatKarty(klucz, etykieta, mm[0], mm[1])
        for klucz, (etykieta, mm, _ratio) in config.CARD_PRESETS.items()
    }


def aktywny_format() -> FormatKarty:
    """Format wybrany w Ustawieniach — liczony NA ŻYWO (config.set_card_preset
    zmienia wybór w trakcie sesji)."""
    return formaty()[config.SELECTED_CARD_PRESET]
