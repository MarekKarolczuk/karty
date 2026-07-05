"""Ciemny toolbar marki pod natywnym paskiem tytułu Windows: logo aplikacji
i status API (po prawej). Przyciski okna (─ ▢ ✕), przeciąganie i zmiana
rozmiaru należą teraz do natywnej ramki systemu. Można też chwycić i przeciągnąć
okno za ten pasek (startSystemMove), a dwuklik maksymalizuje."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.gui.animations import PulseDot
from app.gui import theme

HEIGHT = 52


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self._window = window
        self.setObjectName("titleBar")
        self.setFixedHeight(HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        logo_icon = QLabel("A")
        logo_icon.setObjectName("logoBadge")
        logo_icon.setFixedSize(30, 30)
        logo_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo_icon)

        logo_box = QWidget()
        logo_layout = QVBoxLayout(logo_box)
        logo_layout.setContentsMargins(0, 4, 0, 0)
        logo_layout.setSpacing(0)
        title = QLabel("ATELIER KART")
        title.setObjectName("appLogo")
        subtitle = QLabel("AI · GENERATOR TALII")
        subtitle.setObjectName("appSubtitle")
        logo_layout.addWidget(title)
        logo_layout.addWidget(subtitle)
        layout.addWidget(logo_box)

        layout.addStretch(1)

        api_pill = QWidget()
        api_pill.setObjectName("apiPill")
        api_layout = QHBoxLayout(api_pill)
        api_layout.setContentsMargins(12, 4, 12, 4)
        api_layout.setSpacing(6)
        self.api_dot = PulseDot(theme.GREEN, size=10)
        api_layout.addWidget(self.api_dot)
        self.api_label = QLabel("API połączone")
        self.api_label.setObjectName("apiPillText")
        api_layout.addWidget(self.api_label)
        layout.addWidget(api_pill)

    # --- API -------------------------------------------------------------------
    def refresh_api_status(self, connected: bool) -> None:
        from app.gui import theme as _theme
        self.api_dot.set_color(_theme.GREEN if connected else _theme.GOLD)
        self.api_label.setText("API połączone" if connected else "brak klucza API")

    def _toggle_maximize(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def mousePressEvent(self, event):  # noqa: N802 (API Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._window.windowHandle()
            if handle is not None:
                handle.startSystemMove()  # natywne przeciąganie + Windows snap
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_maximize()
        super().mouseDoubleClickEvent(event)
