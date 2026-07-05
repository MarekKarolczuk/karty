"""Sidebar nawigacyjny „Atelier Kart": Nowa talia, menu WIDOKI z licznikami
i wskaźnik postępu talii (zgodnie z designem — logo/nazwa/API są w TitleBar)."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QVBoxLayout, QWidget,
)

from app.gui import theme

VIEWS = [
    ("◈", "Ekran roboczy"),
    ("▣", "Galeria zdjęć"),
    ("▦", "Talie"),
    ("❖", "Tła i rewersy"),
    ("⚙", "Ustawienia i style"),
    ("⇲", "Eksport"),
]


class Sidebar(QWidget):
    view_selected = pyqtSignal(int)
    new_deck_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(228)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 16)
        layout.setSpacing(10)

        new_deck = QPushButton("＋  Nowa talia")
        new_deck.setObjectName("newDeckBtn")
        new_deck.setCursor(Qt.CursorShape.PointingHandCursor)
        new_deck.clicked.connect(self.new_deck_clicked.emit)
        layout.addWidget(new_deck)

        caption = QLabel("WIDOKI")
        caption.setObjectName("sideCaption")
        layout.addWidget(caption)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.nav_buttons: list[QPushButton] = []
        self._badges: list[QLabel] = []
        for i, (icon, label) in enumerate(VIEWS):
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(0)

            btn = QPushButton(f"{icon}   {label}")
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(btn, i)
            row_layout.addWidget(btn, stretch=1)

            badge = QLabel("")
            badge.setObjectName("navBadge")
            badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
            badge.hide()
            row_layout.addWidget(badge)

            layout.addWidget(row)
            self.nav_buttons.append(btn)
            self._badges.append(badge)
        self.nav_buttons[0].setChecked(True)
        self._group.idClicked.connect(self.view_selected.emit)

        layout.addStretch(1)
        layout.addWidget(self._separator())

        progress_row = QHBoxLayout()
        progress_caption = QLabel("POSTĘP TALII")
        progress_caption.setObjectName("sideCaption")
        progress_row.addWidget(progress_caption)
        progress_row.addStretch(1)
        self.progress_text = QLabel("0/52")
        self.progress_text.setObjectName("deckProgressText")
        progress_row.addWidget(self.progress_text)
        layout.addLayout(progress_row)

        self.progress = QProgressBar()
        self.progress.setObjectName("deckProgress")
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        legend = QHBoxLayout()
        legend.setSpacing(14)
        self.legend_done = _LegendDot(theme.GREEN, "0 gotowe")
        self.legend_pending = _LegendDot(theme.GOLD, "0 w toku")
        legend.addWidget(self.legend_done)
        legend.addWidget(self.legend_pending)
        legend.addStretch(1)
        layout.addLayout(legend)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background: {theme.BORDER}; max-height: 1px; border: none;")
        return line

    # --- API -----------------------------------------------------------------
    def set_current(self, index: int) -> None:
        self.nav_buttons[index].setChecked(True)

    def set_badge(self, index: int, count: int) -> None:
        badge = self._badges[index]
        if count > 0:
            badge.setText(str(count))
            badge.show()
        else:
            badge.hide()

    def set_deck_progress(self, done: int, total: int, pending: int) -> None:
        self.progress_text.setText(f"{done}/{total}")
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.legend_done.set_text(f"{done} gotowe")
        self.legend_pending.set_text(f"{pending} w toku")


class _LegendDot(QWidget):
    def __init__(self, color: str, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 9px;")
        layout.addWidget(dot)
        self.label = QLabel(text)
        self.label.setObjectName("hint")
        layout.addWidget(self.label)

    def set_text(self, text: str) -> None:
        self.label.setText(text)
