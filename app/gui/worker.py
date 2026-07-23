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


class AnalysisWorker(QThread):
    """Analiza zdjęć przez Gemini (auto-przydział) — sekwencyjnie, z cache
    na dysku (analiza_zdjec.json). Cache-hit = zero API; po każdej udanej
    analizie natychmiastowy dopis do cache, więc anulowanie w połowie nie
    marnuje wykonanych analiz."""

    progress = pyqtSignal(int, int)        # zrobione, wszystkie
    photo_done = pyqtSignal(str, object)   # ścieżka, AnalizaZdjecia
    photo_error = pyqtSignal(str, str)     # ścieżka, komunikat błędu
    fatal_error = pyqtSignal(str)          # błąd konta — stop całej serii
    finished_all = pyqtSignal(object)      # list[AnalizaZdjecia] (udane)

    def __init__(self, paths: list[str], motywy: dict[str, str], parent=None):
        super().__init__(parent)
        self.paths = paths
        self.motywy = dict(motywy)
        self._cancelled = False

    def cancel(self) -> None:
        # tylko flaga — abort_active() to mechanizm Stability, tu niepotrzebny;
        # bieżące żądanie Gemini dokończy się w tle
        self._cancelled = True

    def run(self) -> None:
        from pathlib import Path

        from app.api.errors import FatalAPIError
        from app.core import photo_analyzer

        wyniki: list = []
        total = len(self.paths)
        for i, path_str in enumerate(self.paths, start=1):
            if self._cancelled:
                break
            path = Path(path_str)
            try:
                analiza = photo_analyzer.z_cache(path, self.motywy)
                if analiza is None:
                    analiza = photo_analyzer.analizuj_zdjecie(path, self.motywy)
                    photo_analyzer.dopisz_cache(path, self.motywy, analiza)
                    # tani bezpiecznik RPM darmowego planu między wywołaniami
                    self.msleep(300)
                wyniki.append(analiza)
                self.photo_done.emit(path_str, analiza)
            except FatalAPIError as exc:
                if not self._cancelled:
                    self.fatal_error.emit(str(exc))
                break
            except Exception as exc:
                if self._cancelled:
                    break
                self.photo_error.emit(path_str, str(exc))
            self.progress.emit(i, total)
        self.finished_all.emit(wyniki)


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


class TemplateSetWorker(QThread):
    """Generowanie KOMPLETU teł przodu (domyślnie 4 kolory jednym stylem,
    opcjonalnie też jokery) + opcjonalnie rewers — sekwencyjnie, ze spójnością
    zestawu: pierwsze tło (kier) powstaje bez referencji, kolejne kolory
    dostają je jako obraz referencyjny i ten sam seed."""

    variant_done = pyqtSignal(object, str)   # Suit, ścieżka tła
    back_done = pyqtSignal(str)              # ścieżka rewersu
    failed = pyqtSignal(object, str)         # Suit|None (None = rewers), błąd
    progress = pyqtSignal(int, int)          # zrobione, wszystkie
    finished_all = pyqtSignal(int, int)      # zrobione, wszystkie

    def __init__(self, suits: list[Suit] | None = None,
                 back_prompt: str | None = None, back_source=None,
                 back_orientation: str = "portrait",
                 jokery_odbarw: bool = True, parent=None):
        super().__init__(parent)
        self.suits = list(suits) if suits else Suit.kolory()
        self.back_prompt = back_prompt       # None = bez rewersu
        self.back_source = back_source
        self.back_orientation = back_orientation
        # True = tło czarnego jokera powstaje jako czarno-biała kopia czerwonego
        # (bez osobnej generacji AI) — identyczne tła obu jokerów
        self.jokery_odbarw = jokery_odbarw
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        from app.api import stability_client
        stability_client.abort_active()

    def run(self) -> None:
        from pathlib import Path

        from app import config
        from app.core import prompts

        total = len(self.suits) + (1 if self.back_prompt else 0)
        made = 0
        anchor: Path | None = None   # pierwsze tło zestawu = referencja reszty
        joker_czerwony_path: Path | None = None   # źródło derywacji czarnego
        for suit in self.suits:
            if self._cancelled:
                break
            try:
                if (self.jokery_odbarw and suit is Suit.JOKER_CZARNY
                        and joker_czerwony_path is not None):
                    # tło czarnego jokera = czarno-biała kopia czerwonego (bez AI)
                    path = generator.derywuj_tlo_czarnego_jokera(
                        joker_czerwony_path)
                else:
                    path = generator.generate_template(
                        suit,
                        prompts.front_set_prompt(
                            suit, with_reference=anchor is not None),
                        reference=anchor,
                        use_auto_reference=False,
                        seed=config.GEN_SEED,
                    )
                if anchor is None:
                    anchor = path
                if suit is Suit.JOKER_CZERWONY:
                    joker_czerwony_path = path
                made += 1
                self.variant_done.emit(suit, str(path))
            except Exception as exc:
                if not self._cancelled:
                    self.failed.emit(suit, str(exc))
                break
            self.progress.emit(made, total)
        if self.back_prompt and not self._cancelled and made == len(self.suits):
            try:
                path = generator.generate_back(
                    self.back_prompt, self.back_source, self.back_orientation
                )
                made += 1
                self.back_done.emit(str(path))
            except Exception as exc:
                if not self._cancelled:
                    self.failed.emit(None, str(exc))
            self.progress.emit(made, total)
        self.finished_all.emit(made, total)


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


class BoxWorker(QThread):
    """Generowanie grafiki pudełka (AI) w tle — jedna scena ze wszystkich
    zdjęć osób talii wciśnięta w wykrojnik."""

    done = pyqtSignal(str)     # ścieżka proof pudełka
    failed = pyqtSignal(str)   # komunikat błędu
    progress = pyqtSignal(str) # etap generacji (status na zakładce Pudełko)

    def __init__(self, prompt, dieline_path, foto_paths, design_mm,
                 seed=None, tryb="scena", prompt_front=None, prompt_back=None,
                 card_paths=None, boki_ai=False, liczba_osob=None,
                 osobne_foto=None, parent=None):
        super().__init__(parent)
        self.prompt = prompt
        self.dieline_path = dieline_path
        self.foto_paths = foto_paths
        self.design_mm = design_mm
        self.seed = seed
        self.tryb = tryb
        self.prompt_front = prompt_front
        self.prompt_back = prompt_back
        self.card_paths = card_paths
        self.boki_ai = boki_ai
        self.liczba_osob = liczba_osob
        self.osobne_foto = osobne_foto
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        from app.api import stability_client
        stability_client.abort_active()

    def run(self) -> None:
        from app.api.stability_client import StabilityAborted
        try:
            path = generator.generate_box(
                self.prompt, self.dieline_path, self.foto_paths,
                self.design_mm, seed=self.seed, tryb=self.tryb,
                prompt_front=self.prompt_front, prompt_back=self.prompt_back,
                card_paths=self.card_paths, boki_ai=self.boki_ai,
                liczba_osob=self.liczba_osob, osobne_foto=self.osobne_foto,
                postep=self.progress.emit)
            self.done.emit(str(path))
        except StabilityAborted:
            self.failed.emit("Anulowano generację pudełka")
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


class BoxFixWorker(QThread):
    """Selektywna poprawa artworku pudełka (reużyty FixRegionDialog) →
    generator.popraw_pudelko. Wynik nadpisuje raw i proof."""

    done = pyqtSignal(str)     # ścieżka proof
    failed = pyqtSignal(str)

    def __init__(self, maska, prompt_text, dieline_path, design_mm,
                 tryb="ai", sila=3, parent=None):
        super().__init__(parent)
        self.maska = maska
        self.prompt_text = prompt_text
        self.dieline_path = dieline_path
        self.design_mm = design_mm
        self.tryb = tryb
        self.sila = sila
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        from app.api import stability_client
        stability_client.abort_active()

    def run(self) -> None:
        try:
            path = generator.popraw_pudelko(
                self.maska, self.prompt_text, self.dieline_path,
                self.design_mm, tryb=self.tryb, sila=self.sila)
            if not self._cancelled:
                self.done.emit(str(path))
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


class SampleWorker(QThread):
    """Generuje pojedynczą kartę PODGLĄDU (zakładka Style) — bez zapisu do output/."""

    done = pyqtSignal(object)   # PIL.Image.Image
    failed = pyqtSignal(str)

    def __init__(self, spec: CardSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        from app.api import stability_client
        stability_client.abort_active()

    def run(self) -> None:
        from app.api.stability_client import StabilityAborted
        try:
            img = generator.generate_sample(self.spec)
            if not self._cancelled:
                self.done.emit(img)
        except StabilityAborted:
            if not self._cancelled:
                self.failed.emit("Anulowano podgląd")
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


class FixWorker(QThread):
    """Selektywna poprawa jednego wariantu karty (lightbox → „Popraw
    selektywnie"): generator.popraw_region — zmiana tylko w masce
    użytkownika, wynik = NOWY wariant. tryb "ai" (prompt + siła 1-5)
    albo "szablon" (przywrócenie tła, bez API)."""

    done = pyqtSignal(object, str)   # CardSpec (poprawiany), ścieżka nowego wariantu
    failed = pyqtSignal(str)         # komunikat błędu

    def __init__(self, spec: CardSpec, maska, prompt_text: str,
                 tryb: str = "ai", sila: int = 3, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.maska = maska
        self.prompt_text = prompt_text
        self.tryb = tryb
        self.sila = sila
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True
        from app.api import stability_client
        stability_client.abort_active()

    def run(self) -> None:
        try:
            path = generator.popraw_region(self.spec, self.maska,
                                           self.prompt_text,
                                           tryb=self.tryb, sila=self.sila)
            if not self._cancelled:
                self.done.emit(self.spec, str(path))
        except Exception as exc:
            if not self._cancelled:
                self.failed.emit(str(exc))


class RestampWorker(QThread):
    """Przestemplowuje narożniki kart z output/_raw/ (lub finalnych z resetem
    tarcz) wg aktywnego presetu „wartosci" — ZERO wywołań API."""

    progress = pyqtSignal(int, int)   # zrobione, wszystkie
    done = pyqtSignal(int, int)       # sukcesy, błędy
    failed = pyqtSignal(str)          # błąd krytyczny (pierwsza karta)

    def __init__(self, targets: list[CardSpec], parent=None):
        super().__init__(parent)
        self.targets = targets
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        ok = errors = 0
        total = len(self.targets)
        for i, spec in enumerate(self.targets, start=1):
            if self._cancelled:
                break
            try:
                generator.przestempluj_plik(spec)
                ok += 1
            except Exception as exc:
                errors += 1
                if ok == 0 and errors == 1:
                    self.failed.emit(f"{spec.label}: {exc}")
            self.progress.emit(i, total)
        self.done.emit(ok, errors)


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
