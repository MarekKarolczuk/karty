"""Dialog „Reżyser sceny" — akceptacja/poprawa wygenerowanych postaci.

Pokazuje siatkę kart: miniatura postaci + pole „dopisek do poprawy" + przycisk
„🔄 Regeneruj" (regeneruje CAŁĄ postać z dopiskiem, wątkiem — bez zawieszania
UI). „Zatwierdź wszystkie i skomponuj scenę" zwraca listę zaakceptowanych
ścieżek; MainWindow zleca wtedy `BoxComposeWorker` (AI komponuje przód/tył).
"""
from __future__ import annotations

import random
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from app.gui.animations import Spinner
from app.gui.widgets import cover_pixmap
from app.gui.worker import BoxCharacterOneWorker

_THUMB = 150


class _CharacterCard(QWidget):
    """Jedna karta postaci: miniatura + dopisek + regeneracja."""

    def __init__(self, indeks: int, path: str, zdjecia: list[Path], styl: str,
                 parent=None):
        super().__init__(parent)
        self._i = indeks
        self._path = path
        self._zdjecia = zdjecia
        self._styl = styl
        self._worker: BoxCharacterOneWorker | None = None

        self.setObjectName("panel")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(6)

        self.thumb = QLabel()
        self.thumb.setObjectName("well")
        self.thumb.setFixedSize(_THUMB, _THUMB)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.thumb, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._refresh_thumb()

        self.dopisek = QLineEdit()
        self.dopisek.setPlaceholderText("dopisek do poprawy (np. uśmiech, okulary)")
        lay.addWidget(self.dopisek)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.spinner = Spinner(16)
        self.spinner.hide()
        row.addWidget(self.spinner)
        self.regen_btn = QPushButton("🔄  Regeneruj")
        self.regen_btn.setObjectName("ghostBtn")
        self.regen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.regen_btn.clicked.connect(self._regeneruj)
        # regeneracja wymaga zdjęć źródłowych osoby (przy „Wznów" mogą być brak)
        if not self._zdjecia:
            self.regen_btn.setEnabled(False)
            self.regen_btn.setToolTip(
                "Brak zdjęć źródłowych osoby — wskaż folder osób, by regenerować.")
            self.dopisek.setEnabled(False)
        row.addWidget(self.regen_btn, stretch=1)
        lay.addLayout(row)

    def _refresh_thumb(self) -> None:
        if Path(self._path).exists():
            self.thumb.setPixmap(
                cover_pixmap(Path(self._path), _THUMB, _THUMB, radius=8))
        else:
            self.thumb.setText("—")

    def busy(self) -> bool:
        return self._worker is not None

    def _regeneruj(self) -> None:
        if self._worker is not None:
            return
        self.spinner.show()
        self.regen_btn.setEnabled(False)
        self.regen_btn.setText("⏳  Regeneruję…")
        self._worker = BoxCharacterOneWorker(
            self._i, self._zdjecia, self._styl,
            random.randrange(1, 10**6), self.dopisek.text().strip(), self._path)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_done(self, _i: int, path: str) -> None:
        self._path = path
        self._refresh_thumb()
        self._koniec()

    def _on_failed(self, _i: int, message: str) -> None:
        self.dopisek.setPlaceholderText(f"błąd: {message[:40]}… spróbuj ponownie")
        self._koniec()

    def _koniec(self) -> None:
        self.spinner.hide()
        self.regen_btn.setEnabled(True)
        self.regen_btn.setText("🔄  Regeneruj")
        self._worker = None

    def sciezka(self) -> str:
        return self._path


class CharacterReviewDialog(QDialog):
    """Przegląd i poprawa postaci przed komponowaniem sceny. exec()==Accepted
    → `zaakceptowane()` zwraca listę ścieżek wycinków w kolejności."""

    def __init__(self, paths: list[str], osoby: list[list[Path]], styl: str,
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reżyser sceny — akceptacja postaci")
        self.setModal(True)
        self.resize(720, 820)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(10)

        hint = QLabel(
            "Sprawdź wygenerowane postacie. Nie podoba się któraś? Wpisz dopisek "
            "(np. „uśmiech, okulary”) i kliknij „Regeneruj”. Gdy wszystkie są OK "
            "— zatwierdź, a AI ułoży je w scenę (bar/stół) z tłem.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(10)
        self._cards: list[_CharacterCard] = []
        kol = 4
        for i, p in enumerate(paths):
            zdj = osoby[i] if i < len(osoby) else []
            card = _CharacterCard(i, p, zdj, styl)
            self._cards.append(card)
            grid.addWidget(card, i // kol, i % kol)
        scroll.setWidget(host)
        root.addWidget(scroll, stretch=1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel = QPushButton("Anuluj")
        cancel.setObjectName("ghostBtn")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)
        self.accept_btn = QPushButton("✓  Zatwierdź wszystkie i skomponuj scenę")
        self.accept_btn.setObjectName("generateBtn")
        self.accept_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.accept_btn.clicked.connect(self._on_accept)
        actions.addWidget(self.accept_btn)
        root.addLayout(actions)

    def _on_accept(self) -> None:
        if any(c.busy() for c in self._cards):
            self.accept_btn.setText("⏳  Poczekaj — trwa regeneracja…")
            return
        self.accept()

    def zaakceptowane(self) -> list[str]:
        return [c.sciezka() for c in self._cards]
