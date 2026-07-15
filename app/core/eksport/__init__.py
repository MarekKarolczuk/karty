"""Potok eksportu talii (Pipeline + Strategy):

    Etap A `procesor.ProcesorKarty`  — spad + znaczniki cięcia na karcie,
    Etap B `uklady.StrategiaUkladu`  — Single / Atlas / A4 Grid (duplex),
    Etap C `wyjscia.StrategiaWyjscia` — ZIP / folder / PDF / PNG,

spinane przez `manager.ExportManager`. Formaty kart w `formaty.FormatKarty`
(zbudowane z config.CARD_PRESETS — jedno źródło prawdy wymiarów).
"""
from app.core.eksport.formaty import (
    A4_MM, DPI_DRUKU, FormatKarty, aktywny_format, formaty, mm_na_px,
)
from app.core.eksport.manager import ExportManager, manager_dla_joba
from app.core.eksport.procesor import ProcesorKarty
from app.core.eksport.uklady import (
    CELL, CELL_SMALL, StrategiaUkladu, UkladA4, UkladAtlas, UkladPojedynczy,
    WynikUkladu, atlas_tts, sprite_13x4,
)
from app.core.eksport.wyjscia import (
    StrategiaWyjscia, WyjscieFolder, WyjsciePDF, WyjsciePNG, WyjscieZIP,
)

__all__ = [
    "A4_MM", "DPI_DRUKU", "FormatKarty", "aktywny_format", "formaty",
    "mm_na_px", "ExportManager", "manager_dla_joba", "ProcesorKarty",
    "CELL", "CELL_SMALL", "StrategiaUkladu", "UkladA4", "UkladAtlas",
    "UkladPojedynczy", "WynikUkladu", "atlas_tts", "sprite_13x4",
    "StrategiaWyjscia", "WyjscieFolder", "WyjsciePDF", "WyjsciePNG",
    "WyjscieZIP",
]
