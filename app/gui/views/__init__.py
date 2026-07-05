"""Widoki aplikacji (sidebar → FadingStackedWidget)."""
from __future__ import annotations

from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget


def view_header(title: str, subtitle: str) -> QWidget:
    """Nagłówek widoku: tytuł serif + podtytuł, jak w designie."""
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    title_label = QLabel(title)
    title_label.setObjectName("viewTitle")
    layout.addWidget(title_label)
    subtitle_label = QLabel(subtitle)
    subtitle_label.setObjectName("viewSubtitle")
    layout.addWidget(subtitle_label)
    return box
