"""Panel siatki talii 4×13 z filtrem kolorów — wspólny dla widoku Talie
i środka Ekranu roboczego (dwie niezależne instancje; CardSlot nie może mieć
dwóch rodziców). Stan slotów synchronizuje MainWindow."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from app.core.models import Suit, wartosci_dla
from app.gui.card_grid import CardGrid
from app.gui.widgets import SegmentedControl

ROW_SCALE = 0.56   # kompaktowe sloty, żeby 13 kart mieściło się w wierszu

# Definicja filtra kolorów: (etykieta, grupa suitów lub None=wszystkie, red).
# Jedno źródło prawdy dla segmentów, widoczności wierszy i badge'ów
# (main_window._update_badges).
FILTRY: list[tuple[str, tuple[Suit, ...] | None, bool]] = [
    ("Wszystkie", None, False),
    *[(f"{s.symbol} {s.etykieta}", (s,), s.is_red) for s in Suit.kolory()],
    ("🃏 Jokery", tuple(Suit.jokery()), False),
]


class DeckGridPanel(QWidget):
    """Filtr kolorów + 4 wiersze CardGrid (po jednym na kolor) + wiersz
    Jokerów (2 sloty) + pusty stan."""

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
            [f[0] for f in FILTRY],
            red_flags=[f[2] for f in FILTRY],
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
        self._rows: list[tuple[tuple[Suit, ...], QWidget]] = []
        for suit in Suit.kolory():
            row = QWidget()
            row.setObjectName("panel")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(12, 10, 12, 10)
            row_layout.setSpacing(10)
            row_layout.addWidget(self._label_box(suit.symbol,
                                                 suit.nazwa.capitalize(),
                                                 suit.is_red))

            grid = self._make_grid(suit, columns=13, scale=scale,
                                   droppable=droppable)
            grid_scroll = QScrollArea()
            grid_scroll.setWidgetResizable(True)
            grid_scroll.setWidget(grid)
            grid_scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            grid_scroll.setFixedHeight(round(210 * scale) + 26)
            row_layout.addWidget(grid_scroll, stretch=1)

            host_layout.addWidget(row)
            self._rows.append(((suit,), row))

        # Wiersz Jokerów: dwa pojedyncze sloty (czerwony i czarny) obok siebie
        joker_row = QWidget()
        joker_row.setObjectName("panel")
        joker_layout = QHBoxLayout(joker_row)
        joker_layout.setContentsMargins(12, 10, 12, 10)
        joker_layout.setSpacing(10)
        for suit in Suit.jokery():
            joker_layout.addWidget(self._label_box(suit.symbol,
                                                   suit.nazwa.split("_")[1],
                                                   suit.is_red))
            joker_layout.addWidget(self._make_grid(suit, columns=1,
                                                   scale=scale,
                                                   droppable=droppable))
        joker_layout.addStretch(1)
        host_layout.addWidget(joker_row)
        self._rows.append((tuple(Suit.jokery()), joker_row))

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

    # --- budowa pomocnicza ------------------------------------------------------
    def _label_box(self, symbol_txt: str, nazwa: str, red: bool) -> QWidget:
        """Etykieta wiersza: symbol koloru + nazwa pod spodem."""
        box = QWidget()
        box.setFixedWidth(52)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(0)
        symbol = QLabel(symbol_txt)
        symbol.setObjectName("suitRowSymbol")
        symbol.setProperty("red", red)
        symbol.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(symbol)
        name = QLabel(nazwa)
        name.setObjectName("hint")
        name.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(name)
        layout.addStretch(1)
        return box

    def _make_grid(self, suit: Suit, columns: int, scale: float,
                   droppable: bool) -> CardGrid:
        grid = CardGrid(suit, columns=columns, scale=scale, spacing=8,
                        droppable=droppable)
        grid.slot_clicked.connect(self.slot_clicked.emit)
        grid.slot_right_clicked.connect(self.slot_right_clicked.emit)
        grid.photo_dropped.connect(self.photo_dropped.emit)
        self.grids[suit] = grid
        return grid

    # --- filtr ----------------------------------------------------------------
    def _on_filter_changed(self, index: int) -> None:
        selected = FILTRY[index][1]
        for suits, row in self._rows:
            row.setVisible(selected is None
                           or any(s in selected for s in suits))

    def current_filter(self) -> tuple[Suit, ...] | None:
        """Aktywna grupa filtra kolorów (None = wszystkie)."""
        return FILTRY[self.suit_seg.current()][1]

    # --- budowa / stan ----------------------------------------------------------
    def rebuild(self, values: list[str], assignments: dict[str, str]) -> None:
        """Przebudowa slotów: jokery dostają jedną „wartość" JOKER,
        kolory pełną listę talii."""
        for grid in self.grids.values():
            grid.rebuild(wartosci_dla(grid.suit, values), assignments)

    def refresh_empty_state(self) -> None:
        any_generated = any(
            slot.generated_path is not None
            for grid in self.grids.values() for slot in grid.slots.values()
        )
        self.empty_state.setVisible(not any_generated)
