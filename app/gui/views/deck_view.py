"""Widok Talie: zarządzanie talią — pigułka nazwy talii, siatka 4 kolorów
(wiersz = kolor × 13 wartości) z podglądem wygenerowanych kart, oraz historia
plików z output/. Kliknięcie karty otwiera ją w powiększeniu (lightbox)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QStackedWidget, QVBoxLayout, QWidget,
)

from app import config
from app.core import style_store
from app.core.models import Suit
from app.gui.card_grid import CardGrid
from app.gui.views import view_header
from app.gui.widgets import SegmentedControl, ZoomDialog

ROW_SCALE = 0.56   # kompaktowe sloty, żeby 13 kart mieściło się w wierszu


class DeckView(QWidget):
    slot_right_clicked = pyqtSignal(object)    # CardSlot (menu zarządzania)
    edit_values_clicked = pyqtSignal()
    deck_name_changed = pyqtSignal(str)

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

        self.section_seg = SegmentedControl(["▦ Siatka", "🕓 Historia"])
        self.section_seg.changed.connect(self._on_section_changed)
        top.addWidget(self.section_seg, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(top)

        # filtr kolorów — widoczny tylko w sekcji Siatka
        filter_row = QHBoxLayout()
        self.suit_seg = SegmentedControl(
            ["Wszystkie"] + [f"{s.symbol} {s.nazwa.capitalize()}" for s in Suit],
            red_flags=[False] + [s.is_red for s in Suit],
        )
        self.suit_seg.changed.connect(self._on_filter_changed)
        filter_row.addWidget(self.suit_seg)
        filter_row.addStretch(1)
        self._filter_row_host = QWidget()
        self._filter_row_host.setLayout(filter_row)
        layout.addWidget(self._filter_row_host)

        # --- sekcje: siatka | wygenerowane | historia ------------------------------
        self.sections = QStackedWidget()

        # 1) siatka talii
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.setSpacing(14)

        self.grids: dict[Suit, CardGrid] = {}
        self._rows: dict[Suit, QWidget] = {}
        for suit in Suit:
            row = QWidget()
            row.setObjectName("panel")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(10)

            label_box = QWidget()
            label_box.setFixedWidth(52)
            label_layout = QVBoxLayout(label_box)
            label_layout.setContentsMargins(0, 8, 0, 0)
            label_layout.setSpacing(0)
            symbol = QLabel(suit.symbol)
            symbol.setObjectName("suitRowSymbol")
            symbol.setProperty("red", suit.is_red)
            symbol.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label_layout.addWidget(symbol)
            name = QLabel(suit.nazwa.capitalize())
            name.setObjectName("hint")
            name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            label_layout.addWidget(name)
            label_layout.addStretch(1)
            row_layout.addWidget(label_box)

            # Talie = podgląd; klik otwiera lightbox, brak przypisywania (dodawania)
            grid = CardGrid(suit, columns=13, scale=ROW_SCALE, spacing=8,
                            droppable=False)
            grid.slot_clicked.connect(self._zoom_slot)
            grid.slot_right_clicked.connect(self.slot_right_clicked.emit)
            grid_scroll = QScrollArea()
            grid_scroll.setWidgetResizable(True)
            grid_scroll.setWidget(grid)
            grid_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            grid_scroll.setFixedHeight(round(210 * ROW_SCALE) + 26)
            row_layout.addWidget(grid_scroll, stretch=1)

            host_layout.addWidget(row)
            self.grids[suit] = grid
            self._rows[suit] = row

        self.empty_state = QLabel(
            "Jeszcze brak wygenerowanych kart.\n"
            "Przejdź na Ekran roboczy (◈), przypisz zdjęcia do kart "
            "i kliknij ⚡ Generuj talię."
        )
        self.empty_state.setObjectName("mutedInfo")
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        host_layout.addWidget(self.empty_state)

        hint = QLabel("klik = powiększ kartę (lightbox)   •   "
                      "prawy przycisk = opcje / usuwanie plików")
        hint.setObjectName("hint")
        host_layout.addWidget(hint)
        host_layout.addStretch(1)
        scroll.setWidget(host)
        self.sections.addWidget(scroll)

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
        self._filter_row_host.setVisible(index == 0)
        if index == 1:   # Historia
            self.refresh_history()

    def _on_filter_changed(self, index: int) -> None:
        selected = None if index == 0 else list(Suit)[index - 1]
        for suit, row in self._rows.items():
            row.setVisible(selected is None or suit is selected)

    # --- lightbox + odświeżanie ------------------------------------------------------
    def _zoom_slot(self, slot) -> None:
        """Kliknięcie karty w siatce = powiększenie (lightbox).

        Pokazuje wygenerowaną kartę, a jeśli jej nie ma — przypisane zdjęcie
        lub szablon tła."""
        target = slot.generated_path or slot.photo_path or slot.suit.template_path
        if target and Path(target).exists():
            ZoomDialog(target, self).exec()

    def set_variant_resolver(self, resolver) -> None:
        """Callback (suit_nazwa, value) -> Path|None zwracający WYBRANY wariant
        karty. Dostarcza go MainWindow (zna metadane selekcji)."""
        self._variant_resolver = resolver

    def mark_dirty(self) -> None:
        """Podgląd talii/historia wymaga odświeżenia (zmiana w output/).

        Uzupełnia sloty siatki o WYBRANY wariant karty i — jeśli sekcja
        Historia jest aktywna — odświeża listę."""
        resolver = getattr(self, "_variant_resolver", None)
        if resolver is not None:
            for suit, grid in self.grids.items():
                for value, slot in grid.slots.items():
                    chosen = resolver(suit.nazwa, value)
                    if chosen is not None and slot.generated_path != chosen:
                        slot.set_generated(chosen)
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
            ZoomDialog(path, self).exec()
