"""Dialog auto-przydziału zdjęć AI: konfiguracja → postęp → podgląd propozycji.

Trzy strony na QStackedWidget:
  0. konfiguracja — edytowalne motywy kolorów, checkbox nadpisywania,
     estymata liczby wywołań API (z cache) PRZED startem;
  1. postęp — pasek, bieżący plik, licznik błędów, anulowanie;
  2. podgląd — lista propozycji (miniatura + karta + powód), Zastosuj/Anuluj.

Dialog niczego nie mutuje — MainWindow uruchamia workera i stosuje propozycje
po sygnale apply_requested.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QProgressBar,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from app.core import photo_analyzer
from app.core.models import Suit
from app.gui.photo_gallery import load_thumbnail

_THUMB = 96


class AutoAssignDialog(QDialog):
    """Okno auto-przydziału. paths_provider(nadpisz) → lista ścieżek zdjęć
    do analizy (MainWindow filtruje nieużyte przy nadpisz=False)."""

    start_requested = pyqtSignal(dict, bool)   # motywy, nadpisz
    cancel_requested = pyqtSignal()            # anulowanie trwającej analizy
    apply_requested = pyqtSignal()             # zastosuj pokazane propozycje

    def __init__(self, motywy: dict[str, str],
                 paths_provider: Callable[[bool], list[str]], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto-przydział zdjęć AI")
        self.setModal(True)
        self.resize(780, 620)
        self._paths_provider = paths_provider
        self._analysing = False
        self._error_count = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self._stack = QStackedWidget()
        layout.addWidget(self._stack, stretch=1)

        self._stack.addWidget(self._build_config_page(motywy))
        self._stack.addWidget(self._build_progress_page())
        self._stack.addWidget(self._build_preview_page())
        self._refresh_estimate()

    # ===================== strona 0: konfiguracja =============================
    def _build_config_page(self, motywy: dict[str, str]) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        title = QLabel("🪄  AUTO-PRZYDZIAŁ ZDJĘĆ AI")
        title.setObjectName("sectionTitle")
        v.addWidget(title)

        hint = QLabel(
            "AI przeanalizuje zdjęcia z folderu zdjecia/ (liczba osób, motywy, "
            "jakość) i zaproponuje przypisanie do kart. Reguła wartości: "
            "1 osoba → figury (As, Król, Dama, Walet), 2–9 osób → odpowiadająca "
            "liczba, 10 i więcej → dziesiątka. Kolor karty wybiera dopasowanie "
            "do motywów poniżej — możesz je dowolnie edytować."
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)

        self._motyw_edits: dict[str, QLineEdit] = {}
        self._estimate_debounce = QTimer(self)
        self._estimate_debounce.setSingleShot(True)
        self._estimate_debounce.setInterval(350)
        self._estimate_debounce.timeout.connect(self._refresh_estimate)
        # tylko klasyczne kolory — jokery są poza auto-przydziałem
        for suit in Suit.kolory():
            row = QHBoxLayout()
            row.setSpacing(6)
            lab = QLabel(f"{suit.symbol} {suit.nazwa.upper()}")
            lab.setObjectName("sideCaption")
            lab.setFixedWidth(84)
            row.addWidget(lab)
            edit = QLineEdit(motywy.get(suit.nazwa, "") or
                             photo_analyzer.DOMYSLNE_MOTYWY[suit.nazwa])
            edit.setPlaceholderText(photo_analyzer.DOMYSLNE_MOTYWY[suit.nazwa])
            edit.textChanged.connect(self._estimate_debounce.start)
            self._motyw_edits[suit.nazwa] = edit
            row.addWidget(edit, stretch=1)
            v.addLayout(row)

        reset_row = QHBoxLayout()
        reset_btn = QPushButton("↺  Przywróć domyślne motywy")
        reset_btn.setObjectName("ghostBtn")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_motywy)
        reset_row.addWidget(reset_btn)
        reset_row.addStretch(1)
        v.addLayout(reset_row)

        self.overwrite_check = QCheckBox("Nadpisz istniejące przypisania")
        self.overwrite_check.setToolTip(
            "Odznaczone: wypełniane są tylko puste karty zdjęciami, które nie "
            "są jeszcze nigdzie przypisane (mniej wywołań API).\n"
            "Zaznaczone: AI układa całą talię od nowa ze wszystkich zdjęć."
        )
        self.overwrite_check.toggled.connect(self._refresh_estimate)
        v.addWidget(self.overwrite_check)

        self.estimate_label = QLabel()
        self.estimate_label.setObjectName("hint")
        self.estimate_label.setWordWrap(True)
        v.addWidget(self.estimate_label)
        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.setObjectName("ghostBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self.start_btn = QPushButton("🔍  Analizuj zdjęcia")
        self.start_btn.setObjectName("generateBtn")
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.clicked.connect(self._emit_start)
        buttons.addWidget(self.start_btn)
        v.addLayout(buttons)
        return page

    def motywy(self) -> dict[str, str]:
        """Aktualne opisy motywów (puste pole → domyślny opis)."""
        return {
            nazwa: (edit.text().strip()
                    or photo_analyzer.DOMYSLNE_MOTYWY[nazwa])
            for nazwa, edit in self._motyw_edits.items()
        }

    def nadpisz(self) -> bool:
        return self.overwrite_check.isChecked()

    def _reset_motywy(self) -> None:
        for nazwa, edit in self._motyw_edits.items():
            edit.setText(photo_analyzer.DOMYSLNE_MOTYWY[nazwa])

    def _refresh_estimate(self) -> None:
        paths = self._paths_provider(self.nadpisz())
        if not paths:
            self.estimate_label.setText(
                "Brak zdjęć do analizy — wszystkie zdjęcia są już przypisane "
                "albo folder zdjecia/ jest pusty."
            )
            self.start_btn.setEnabled(False)
            return
        hits = photo_analyzer.policz_cache_hits(paths, self.motywy())
        api_calls = len(paths) - hits
        self.estimate_label.setText(
            f"Do analizy: {len(paths)} zdjęć — {hits} z pamięci podręcznej, "
            f"{api_calls} wywołań API (zmiana motywów unieważnia pamięć "
            "podręczną)."
        )
        self.start_btn.setEnabled(True)

    def _emit_start(self) -> None:
        self._analysing = True
        self._error_count = 0
        self.error_label.hide()
        self.progress_bar.setValue(0)
        self.progress_label.setText("Przygotowuję analizę…")
        self.file_label.setText("")
        self._stack.setCurrentIndex(1)
        self.start_requested.emit(self.motywy(), self.nadpisz())

    # ===================== strona 1: postęp ===================================
    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        title = QLabel("⏳  ANALIZUJĘ ZDJĘCIA")
        title.setObjectName("sectionTitle")
        v.addWidget(title)

        v.addStretch(1)
        self.progress_label = QLabel("Przygotowuję analizę…")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        v.addWidget(self.progress_bar)
        self.file_label = QLabel("")
        self.file_label.setObjectName("hint")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self.file_label)
        self.error_label = QLabel("")
        self.error_label.setObjectName("hint")
        self.error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_label.hide()
        v.addWidget(self.error_label)
        v.addStretch(1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("✖  Anuluj analizę")
        cancel_btn.setObjectName("ghostBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        buttons.addStretch(1)
        v.addLayout(buttons)
        return page

    def show_progress(self, done: int, total: int) -> None:
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"Analizuję zdjęcia: {done} / {total}")

    def show_current_file(self, path: str) -> None:
        self.file_label.setText(Path(path).name)

    def add_error(self, path: str, message: str) -> None:
        self._error_count += 1
        self.error_label.setText(
            f"Błędy analizy: {self._error_count} (ostatni: {Path(path).name} — "
            f"{message[:80]})"
        )
        self.error_label.show()

    # ===================== strona 2: podgląd propozycji =======================
    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)

        title = QLabel("👀  PROPOZYCJA PRZYDZIAŁU")
        title.setObjectName("sectionTitle")
        v.addWidget(title)

        self._preview_scroll = QScrollArea()
        self._preview_scroll.setWidgetResizable(True)
        v.addWidget(self._preview_scroll, stretch=1)

        self.summary_label = QLabel()
        self.summary_label.setObjectName("hint")
        self.summary_label.setWordWrap(True)
        v.addWidget(self.summary_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.setObjectName("ghostBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(cancel_btn)
        self.apply_btn = QPushButton("✔  Zastosuj")
        self.apply_btn.setObjectName("generateBtn")
        self.apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.apply_btn.clicked.connect(self._emit_apply)
        buttons.addWidget(self.apply_btn)
        v.addLayout(buttons)
        return page

    def show_proposals(self, propozycje: list, puste: list[str],
                       nieuzyte: list[str]) -> None:
        """Wypełnia stronę podglądu (lista wierszy: miniatura + karta + powód)."""
        self._analysing = False
        host = QWidget()
        lv = QVBoxLayout(host)
        lv.setContentsMargins(4, 4, 4, 4)
        lv.setSpacing(6)
        for prop in propozycje:
            lv.addWidget(self._proposal_row(prop))
        lv.addStretch(1)
        self._preview_scroll.setWidget(host)

        czesci = [f"Propozycje: {len(propozycje)} kart"]
        if puste:
            czesci.append(f"bez propozycji: {len(puste)} kart "
                          "(brak zdjęć z pasującą liczbą osób)")
        if nieuzyte:
            czesci.append(f"nieużyte zdjęcia: {len(nieuzyte)}")
        if self._error_count:
            czesci.append(f"błędy analizy: {self._error_count}")
        self.summary_label.setText(" · ".join(czesci))
        if puste:
            self.summary_label.setToolTip(
                "Karty bez propozycji:\n" + "\n".join(self._karta_label(k)
                                                      for k in puste)
            )
        self.apply_btn.setText(f"✔  Zastosuj ({len(propozycje)})")
        self.apply_btn.setEnabled(bool(propozycje))
        self._stack.setCurrentIndex(2)

    @staticmethod
    def _karta_label(klucz: str) -> str:
        nazwa, value = klucz.split(":", 1)
        suit = Suit.from_nazwa(nazwa)
        return f"{value}{suit.symbol} ({photo_analyzer.nazwa_wartosci(value)} "\
               f"{nazwa})"

    def _proposal_row(self, prop) -> QWidget:
        row = QWidget()
        row.setObjectName("well")
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)

        thumb = QLabel()
        thumb.setFixedSize(_THUMB, _THUMB)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = load_thumbnail(Path(prop.sciezka), _THUMB)
        if not pix.isNull():
            thumb.setPixmap(pix)
        h.addWidget(thumb)

        nazwa, value = prop.klucz.split(":", 1)
        suit = Suit.from_nazwa(nazwa)
        badge = QLabel(f"{value}{suit.symbol}\n"
                       f"{photo_analyzer.nazwa_wartosci(value)}\n{nazwa}")
        badge.setObjectName("propValue")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedWidth(72)
        h.addWidget(badge)

        info = QVBoxLayout()
        name_lab = QLabel(Path(prop.sciezka).name)
        name_lab.setObjectName("propValue")
        info.addWidget(name_lab)
        why_lab = QLabel(prop.powod)
        why_lab.setObjectName("hint")
        why_lab.setWordWrap(True)
        info.addWidget(why_lab)
        h.addLayout(info, stretch=1)
        return row

    def _emit_apply(self) -> None:
        self.apply_requested.emit()
        self.accept()

    # ===================== wspólne ===========================================
    def analysis_failed(self, message: str) -> None:
        """Błąd krytyczny (konto/klucz) — wróć na stronę konfiguracji."""
        self._analysing = False
        self._stack.setCurrentIndex(0)
        self.estimate_label.setText(f"✖ {message}")

    def reject(self) -> None:  # noqa: N802 (API Qt)
        """Esc / Anuluj / X — w trakcie analizy najpierw anuluj workera."""
        if self._analysing:
            self._analysing = False
            self.cancel_requested.emit()
        super().reject()
