"""Orkiestrator potoku eksportu: Etap A (procesor) → Etap B (układ) →
Etap C (wyjście). Niezależny od widoku — GUI dociera tu wyłącznie przez
fasadę exporter.run_export(ExportJob).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from app.core.eksport.formaty import aktywny_format
from app.core.eksport.procesor import (
    ProcesorKarty, wczytaj_karte, wczytaj_rewers,
)
from app.core.eksport.uklady import (
    Karta, ProgressCb, StrategiaUkladu, UkladA4, UkladPojedynczy,
    atlas_tts, sprite_13x4,
)
from app.core.eksport.wyjscia import (
    StrategiaWyjscia, WyjscieFolder, WyjsciePDF, WyjsciePNG, WyjscieZIP,
)

if TYPE_CHECKING:
    from app.core.exporter import ExportJob


@dataclass
class ExportManager:
    """Składa potok z trzech wymiennych etapów i przepuszcza przez niego talię.

    wymagaj_kart=False (atlas/sprite): pusta talia daje arkusz wypełniaczy
    zamiast błędu — zgodność z dotychczasowym zachowaniem.
    """
    procesor: ProcesorKarty | None
    uklad: StrategiaUkladu
    wyjscie: StrategiaWyjscia
    wymagaj_kart: bool = True

    def wykonaj(self, fronty: list[tuple[str, Path | None]],
                rewers: Path | None, out_path: Path,
                progress: ProgressCb | None = None) -> Path:
        karty: list[Karta] = []
        for nazwa, sciezka in fronty:
            img = None
            if sciezka is not None and sciezka.exists():
                img = wczytaj_karte(sciezka)
                if self.procesor is not None:
                    img = self.procesor.przetworz(img)
            karty.append((nazwa, img))
        if self.wymagaj_kart and not any(img for _n, img in karty):
            raise ValueError(
                "Brak wygenerowanych kart do eksportu (output/ puste)")

        rewers_img = None
        if rewers is not None and rewers.exists():
            rewers_img = wczytaj_rewers(rewers)
            if self.procesor is not None:
                rewers_img = self.procesor.przetworz(rewers_img)

        wynik = self.uklad.uloz(karty, rewers_img, progress)
        return self.wyjscie.zapisz(wynik, out_path, progress)


def manager_dla_joba(job: "ExportJob") -> ExportManager:
    """Fabryka: mapuje dotychczasowe rodzaje ExportJob na konfiguracje potoku."""
    fmt = aktywny_format()
    if job.kind == "pdf":
        return ExportManager(
            procesor=ProcesorKarty(fmt, spad=job.bleed, znaczniki=job.marks),
            uklad=UkladA4(fmt, spad=job.bleed, dwustronny=job.backs,
                          max_kolumny=job.columns),
            wyjscie=WyjsciePDF(),
        )
    if job.kind in ("zip", "files"):
        return ExportManager(
            procesor=None,
            uklad=UkladPojedynczy(fmt),
            wyjscie=WyjscieZIP() if job.kind == "zip" else WyjscieFolder(),
        )
    if job.kind == "atlas":
        return ExportManager(procesor=None, uklad=atlas_tts(job.small_atlas),
                             wyjscie=WyjsciePNG(), wymagaj_kart=False)
    if job.kind == "sprite":
        return ExportManager(procesor=None, uklad=sprite_13x4(job.small_atlas),
                             wyjscie=WyjsciePNG(), wymagaj_kart=False)
    raise ValueError(f"Nieznany rodzaj eksportu: {job.kind}")
