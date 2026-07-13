"""Panel siatki talii 4×13 z filtrem kolorów — wspólny dla widoku Talie
i środka Ekranu roboczego (dwie niezależne instancje; CardSlot nie może mieć
dwóch rodziców). Stan slotów synchronizuje MainWindow."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from app.core.models import Suit
from app.gui.card_grid import CardGrid
from app.gui.widgets import SegmentedControl

ROW_SCALE = 0.56   # kompaktowe sloty, żeby 13 kart mieściło się w wierszu


class DeckGridPanel(QWidget):
    """Filtr kolorów + 4 wiersze CardGrid (po jednym na kolor) + pusty stan."""

    slot_clicked = pyqtSignal(object)          # CardSlot
    slot_right_clicked = pyqtSignal(object)    # CardSlot
    photo_dropped = pyqtSignal(object, str)    # CardSlot, ścieżka zdjęcia

    def __init__(self, parent=None, droppable: bool = False,
                 hint: str | None = None, scale: float = ROW_SCALE):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        filter_row = QHBoxLayout()
        self.suit_seg = SegmentedControl(
            ["Wszystkie"] + [f"{s.symbol} {s.nazwa.capitalize()}" for s in Suit],
            red_flags=[False] + [s.is_red for s in Suit],
        )
        self.suit_seg.changed.connect(self._on_filter_changed)
        filter_row.addWidget(self.suit_seg)
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

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

            grid = CardGrid(suit, columns=13, scale=scale, spacing=8,
                            droppable=droppable)
            grid.slot_clicked.connect(self.slot_clicked.emit)
            grid.slot_right_clicked.connect(self.slot_right_clicked.emit)
            grid.photo_dropped.connect(self.photo_dropped.emit)
            grid_scroll = QScrollArea()
            grid_scroll.setWidgetResizable(True)
            grid_scroll.setWidget(grid)
            grid_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            grid_scroll.setFixedHeight(round(210 * scale) + 26)
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

        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("hint")
            host_layout.addWidget(hint_label)
        host_layout.addStretch(1)
        scroll.setWidget(host)
        layout.addWidget(scroll, stretch=1)

    # --- filtr ----------------------------------------------------------------
    def _on_filter_changed(self, index: int) -> None:
        selected = None if index == 0 else list(Suit)[index - 1]
        for suit, row in self._rows.items():
            row.setVisible(selected is None or suit is selected)

    def current_filter(self) -> Suit | None:
        """Aktywny filtr koloru (None = wszystkie)."""
        index = self.suit_seg.current()
        return None if index == 0 else list(Suit)[index - 1]

    # --- budowa / stan ----------------------------------------------------------
    def rebuild(self, values: list[str], assignments: dict[str, str]) -> None:
        for grid in self.grids.values():
            grid.rebuild(values, assignments)

    def refresh_empty_state(self) -> None:
        any_generated = any(
            slot.generated_path is not None
            for grid in self.grids.values() for slot in grid.slots.values()
        )
        self.empty_state.setVisible(not any_generated)
