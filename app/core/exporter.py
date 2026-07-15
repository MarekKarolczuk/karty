"""Fasada eksportu talii — utrzymuje dotychczasowe API (`ExportJob`,
`run_export`, `CELL`/`CELL_SMALL`) dla GUI (`worker.ExportWorker`,
`main_window._start_export`) i testów, a realną pracę wykonuje potok
z pakietu `app.core.eksport` (Etap A: procesor karty → Etap B: strategia
układu → Etap C: strategia wyjścia; patrz `eksport.manager.manager_dla_joba`).

Wszystko działa wyłącznie na plikach z dysku — zero wywołań API.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from app.core.eksport import CELL, CELL_SMALL, manager_dla_joba
from app.core.eksport.uklady import ProgressCb

__all__ = ["ExportJob", "run_export", "ProgressCb", "CELL", "CELL_SMALL"]


@dataclass
class ExportJob:
    kind: str                                   # "pdf" | "zip" | "files" | "atlas" | "sprite"
    out_path: Path
    fronts: list[tuple[str, Path | None]]       # (nazwa np. "A_kier", ścieżka|None)
    back: Path | None = None
    columns: int = 3                            # PDF: górny limit kolumn (siatka liczona dynamicznie z formatu)
    bleed: bool = True                          # PDF: spad 3 mm
    marks: bool = True                          # PDF: znaczniki cięcia
    backs: bool = True                          # PDF: strony rewersów (duplex, kolumny lustrzane)
    small_atlas: bool = False                   # atlas ≤4096 px
    extra: dict = field(default_factory=dict)


def run_export(job: ExportJob, progress: ProgressCb | None = None) -> Path:
    return manager_dla_joba(job).wykonaj(job.fronts, job.back,
                                         job.out_path, progress)
