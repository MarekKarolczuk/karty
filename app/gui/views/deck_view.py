"""Widok Talie: zarządzanie talią — pigułka nazwy talii, siatka 4 kolorów
(wiersz = kolor × 13 wartości) z podglądem wygenerowanych kart, oraz historia
plików z output/. Kliknięcie karty otwiera ją w powiększeniu (lightbox)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from app import config
from app.core import style_store
from app.core.models import Suit
from app.gui.deck_grid_panel import DeckGridPanel
from app.gui.views import view_header
from app.gui.widgets import SegmentedControl


class DeckView(QWidget):
    slot_right_clicked = pyqtSignal(object)    # CardSlot (menu zarządzania)
    edit_values_clicked = pyqtSignal()
    deck_name_changed = pyqtSignal(str)
    restamp_clicked = pyqtSignal()             # przestempluj narożniki (bez API)
    lightbox_requested = pyqtSignal(str, str)  # suit_nazwa, value (karta z wariantami)
    preview_file_requested = pyqtSignal(str)   # pojedynczy plik (historia/backup)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._deck_name = "Rodzinna talia"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self._header = view_header(
            "Talie — 52 karty",
            "Zarządzanie talią · siatka, podgląd wygenerowanych i historia",
        )
        top.addWidget(self._header)
        top.addStretch(1)

        self.deck_pill = QPushButton("📁  talia · Rodzinna talia  ⌄")
        self.deck_pill.setObjectName("deckPill")
        self.deck_pill.setCursor(Qt.CursorShape.PointingHandCursor)
        self.deck_pill.clicked.connect(self._rename_deck)
        top.addWidget(self.deck_pill, alignment=Qt.AlignmentFlag.AlignBottom)

        values_btn = QPushButton("✎ Wartości")
        values_btn.setObjectName("ghostBtn")
        values_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        values_btn.setToolTip("Zmień listę wartości talii (np. A, K, Q, J, 10)")
        values_btn.clicked.connect(self.edit_values_clicked.emit)
        top.addWidget(values_btn, alignment=Qt.AlignmentFlag.AlignBottom)

        restamp_btn = QPushButton("♻ Przestempluj narożniki")
        restamp_btn.setObjectName("ghostBtn")
        restamp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restamp_btn.setToolTip(
            "Nanosi wartości i symbole narożne na wszystkie wygenerowane "
            "karty wg presetu „wartości narożne” — bez wywołań API"
        )
        restamp_btn.clicked.connect(self.restamp_clicked.emit)
        top.addWidget(restamp_btn, alignment=Qt.AlignmentFlag.AlignBottom)

        self.section_seg = SegmentedControl(["▦ Siatka", "🕓 Historia"])
        self.section_seg.changed.connect(self._on_section_changed)
        top.addWidget(self.section_seg, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(top)

        # --- sekcje: siatka | historia ------------------------------------------
        self.sections = QStackedWidget()

        # 1) siatka talii (wspólny panel z filtrem — patrz DeckGridPanel);
        #    Talie = podgląd: klik otwiera lightbox, brak przypisywania
        self.grid_panel = DeckGridPanel(
            droppable=False,
            hint="klik = powiększ kartę (lightbox)   •   Spacja = szybki "
                 "podgląd   •   prawy przycisk = opcje / usuwanie plików",
        )
        self.grid_panel.slot_clicked.connect(self._zoom_slot)
        self.grid_panel.slot_right_clicked.connect(self.slot_right_clicked.emit)
        self.grids = self.grid_panel.grids
        self.suit_seg = self.grid_panel.suit_seg
        self.empty_state = self.grid_panel.empty_state
        self.sections.addWidget(self.grid_panel)

        # 2) historia generacji (output/ + backupy rewersu, po dacie)
        history_host = QWidget()
        history_layout = QVBoxLayout(history_host)
        history_layout.setContentsMargins(0, 0, 0, 0)
        history_layout.setSpacing(6)
        history_hint = QLabel("Pliki z /output i backupy rewersu, najnowsze "
                              "u góry · dwuklik = powiększenie")
        history_hint.setObjectName("hint")
        history_layout.addWidget(history_hint)
        self.history = QListWidget()
        self.history.setObjectName("queueList")
        self.history.itemDoubleClicked.connect(self._zoom_history_item)
        history_layout.addWidget(self.history, stretch=1)
        self.sections.addWidget(history_host)

        layout.addWidget(self.sections, stretch=1)

    # --- nazwa talii -------------------------------------------------------------
    def set_deck_name(self, name: str) -> None:
        self._deck_name = name
        self.deck_pill.setText(f"📁  talia · {name}  ⌄")

    def _rename_deck(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Nazwa talii", "Nazwa talii:", text=self._deck_name
        )
        if ok and text.strip():
            self.set_deck_name(text.strip())
            self.deck_name_changed.emit(text.strip())

    # --- sekcje ---------------------------------------------------------------------
    def _on_section_changed(self, index: int) -> None:
        self.sections.setCurrentIndex(index)
        if index == 1:   # Historia
            self.refresh_history()

    def current_filter(self) -> tuple[Suit, ...] | None:
        """Aktywna grupa filtra kolorów siatki (None = wszystkie; pozycja
        „Jokery" to dwa suity) — dla nawigacji ↑/↓ w lightboxie."""
        return self.grid_panel.current_filter()

    # --- lightbox + odświeżanie ------------------------------------------------------
    def _zoom_slot(self, slot) -> None:
        """Kliknięcie karty w siatce = lightbox z wariantami (obsługiwany
        w MainWindow); karta bez wygenerowanych plików = prosty podgląd
        zdjęcia/szablonu."""
        if slot.generated_path is not None:
            self.lightbox_requested.emit(slot.suit.nazwa, slot.value)
            return
        try:
            target = slot.photo_path or slot.suit.template_path
        except FileNotFoundError:   # świeży preset bez tła tego koloru
            return
        if target and Path(target).exists():
            self.preview_file_requested.emit(str(target))

    def set_variant_resolver(self, resolver) -> None:
        """Callback (suit_nazwa, value) -> Path|None zwracający WYBRANY wariant
        karty. Dostarcza go MainWindow (zna metadane selekcji)."""
        self._variant_resolver = resolver

    def set_variant_counter(self, counter) -> None:
        """Callback (suit_nazwa, value) -> int z liczbą wariantów karty —
        zasila badge'e na miniaturach siatki."""
        self._variant_counter = counter

    def mark_dirty(self) -> None:
        """Podgląd talii/historia wymaga odświeżenia (zmiana w output/).

        Uzupełnia sloty siatki o WYBRANY wariant karty i — jeśli sekcja
        Historia jest aktywna — odświeża listę."""
        resolver = getattr(self, "_variant_resolver", None)
        counter = getattr(self, "_variant_counter", None)
        if resolver is not None:
            for suit, grid in self.grids.items():
                for value, slot in grid.slots.items():
                    chosen = resolver(suit.nazwa, value)
                    if chosen is not None and slot.generated_path != chosen:
                        slot.set_generated(chosen)
                    if counter is not None:
                        slot.set_variant_count(counter(suit.nazwa, value))
        # pusty stan siatki: brak jakiejkolwiek wygenerowanej karty
        any_generated = any(
            slot.generated_path is not None
            for grid in self.grids.values() for slot in grid.slots.values()
        )
        self.empty_state.setVisible(not any_generated)
        if self.sections.currentIndex() == 1:
            self.refresh_history()

    def showEvent(self, event):  # noqa: N802 (API Qt)
        # wejście w Talie zawsze odświeża podgląd wygenerowanych z dysku
        self.mark_dirty()
        super().showEvent(event)

    def set_card_count(self, count: int) -> None:
        title = self._header.findChild(QLabel, "viewTitle")
        if title is not None:
            title.setText(f"Talie — {count} kart")

    # --- historia --------------------------------------------------------------------
    def refresh_history(self) -> None:
        self.history.clear()
        files: list[Path] = []
        if config.OUTPUT_DIR.exists():
            files += [p for p in config.OUTPUT_DIR.iterdir()
                      if p.suffix.lower() in config.IMAGE_EXTS]
        back_dir = style_store.preset_dir("rewers")
        if back_dir.is_dir():
            files += list(back_dir.glob("rewers_stary_*.png"))
        back = style_store.back_path()
        if back.exists():
            files.append(back)
        for path in sorted(files, key=lambda p: p.stat().st_mtime, reverse=True):
            stamp = datetime.fromtimestamp(path.stat().st_mtime)
            item = QListWidgetItem(
                f"{stamp:%Y-%m-%d %H:%M}   ·   {path.name}"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.history.addItem(item)

    def _zoom_history_item(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path and Path(path).exists():
            self.preview_file_requested.emit(str(path))
