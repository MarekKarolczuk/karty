"""Wątki robocze — GUI pozostaje responsywne podczas wywołań API/eksportu."""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.core import generator
from app.core.models import CardSpec, Suit


class GenerationWorker(QThread):
    progress = pyqtSignal(int, int)            # zrobione, wszystkie
    card_started = pyqtSignal(object)          # CardSpec (start pracy nad kartą)
    card_done = pyqtSignal(object, str)        # CardSpec, ścieżka wyniku
    card_error = pyqtSignal(object, str)       # CardSpec, komunikat błędu
    fatal_error = pyqtSignal(str)              # błąd krytyczny — seria zatrzymana
    finished_all = pyqtSignal(int, int)        # sukcesy, błędy

    def __init__(self, specs: list[CardSpec], parent=None):
        super().__init__(parent)
        self.specs = specs
        self._cancelled = False
        self._paused = False

    def cancel(self) -> None:
        self._cancelled = True
        self._paused = False
        from app.api import stability_client
        stability_client.abort_active()   # przerwij żądanie HTTP w locie

    def set_paused(self, paused: bool) -> None:
        """Pauza między kartami (bieżące wywołanie API zawsze się kończy)."""
        self._paused = paused

    @property
    def paused(self) -> bool:
        return self._paused

    def run(self) -> None:
        from app.api.errors import FatalAPIError
        from app.api.stability_client import StabilityAborted
        done = errors = 0
        total = len(self.specs)
        for i, spec in enumerate(self.specs, start=1):
            while self._paused and not self._cancelled:
                self.msleep(150)
            if self._cancelled:
                break
            self.card_started.emit(spec)
            try:
                out = generator.generate_card(spec)
                done += 1
                self.card_done.emit(spec, str(out))
            except StabilityAborted:
                break   # anulowanie — bez błędu
            except FatalAPIError as exc:
                # błąd konta (brak kredytów / billing / klucz) — nie ma sensu
                # próbować kolejnych kart; zatrzymujemy całą serię jednym sygnałem
                if not self._cancelled:
                    self.fatal_error.emit(str(exc))
                break
            except Exception as exc:
                if self._cancelled:
                    break
                errors += 1
                self.card_error.emit(spec, str(exc))
            self.progress.emit(i, total)
        self.finished_all.emit(done, errors)


class TemplateWorker(QThread):
    """Generowanie teł przodu karty (AI) w tle — 1 lub kilka wariantów.

    Warianty generujemy sekwencyjnie; anulowanie zatrzymuje pętlę (bieżące
    żądanie może dokończyć się, chyba że zostanie przerwane globalnie)."""

    done = pyqtSignal(object, str)        # Suit, ścieżka wariantu
    failed = pyqtSignal(object, str)      # Suit, komunikat błędu
    finished_all = pyqtSignal(int, int)   # zrobione, wszystkie

    def __init__(self, suit: Suit, prompt: str | None = None,
                 count: int = 1, parent=None):
        super().__init__(parent)
        self.suit = suit
        self.prompt = prompt
        self.count = max(1, count)
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        from app.api import stability_client
        stability_client.abort_active()   # przerwij żądanie w locie (Stability)

    def run(self) -> None:
        made = 0
        for _ in range(self.count):
            if self._cancelled:
                break
            try:
                path = generator.generate_template(self.suit, self.prompt)
                made += 1
                self.done.emit(self.suit, str(path))
            except Exception as exc:
                if not self._cancelled:
                    self.failed.emit(self.suit, str(exc))
                break
        self.finished_all.emit(made, self.count)


class BackWorker(QThread):
    """Generowanie rewersu talii (AI) w tle."""

    done = pyqtSignal(str)     # ścieżka rewersu
    failed = pyqtSignal(str)   # komunikat błędu

    def __init__(self, prompt: str | None = None, source_photo=None,
                 orientation: str = "portrait", parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.source_photo = source_photo
        self.orientation = orientation
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        from app.api import stability_client
        stability_client.abort_active()

    def run(self) -> None:
        from app.api.stability_client import StabilityAborted
        try:
            path = generator.generate_back(
                self.prompt, self.source_photo, self.orientation
            )
            self.done.emit(str(path))
        except StabilityAborted:
            self.failed.emit("Anulowano generację rewersu")
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


class ExportWorker(QThread):
    """Eksport talii (PDF/ZIP/atlas) w tle — bez wywołań API."""

    progress = pyqtSignal(int, int)
    done = pyqtSignal(str)     # ścieżka pliku wynikowego
    failed = pyqtSignal(str)   # komunikat błędu

    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = job

    def run(self) -> None:
        try:
            from app.core import exporter
            path = exporter.run_export(
                self.job, lambda i, n: self.progress.emit(i, n)
            )
            self.done.emit(str(path))
        except Exception as exc:
            self.failed.emit(str(exc))
