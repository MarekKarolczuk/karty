"""Punkt wejścia aplikacji: python -m app.main"""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from app.core import style_store
from app.gui import theme
from app.gui.main_window import MainWindow


def main() -> None:
    style_store.load()   # biblioteki presetów stylu (Style/) + migracja
    app = QApplication(sys.argv)
    theme.apply(app)
    app.setWindowIcon(theme.app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
