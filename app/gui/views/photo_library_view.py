"""Widok Galeria zdjęć: zarządzanie zdjęciami wejściowymi z folderu /zdjecia.

Upuszczenie pliku z systemu (Eksplorator) kopiuje go do /zdjecia; przycisk
importu robi to samo przez okno wyboru plików. Miniatury są większe niż
w bocznym panelu Ekranu roboczego.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app import config
from app.gui.photo_gallery import GalleryPanel
from app.gui.views import view_header
from app.gui.widgets import show_toast


def _unique_target(name: str) -> Path:
    """Cel kopiowania w /zdjecia; kolizje nazw dostają sufiks _1, _2, …"""
    target = config.ZDJECIA_DIR / name
    stem, suffix = target.stem, target.suffix
    counter = 1
    while target.exists():
        target = config.ZDJECIA_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    return target


class PhotoLibraryView(QWidget):
    photo_deleted = pyqtSignal(str)     # ścieżka usuniętego pliku
    photos_imported = pyqtSignal(int)   # liczba skopiowanych zdjęć

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(view_header(
            "Galeria zdjęć",
            "Zdjęcia wejściowe z folderu /zdjecia — upuść pliki tutaj, "
            "aby je zaimportować",
        ))
        top.addStretch(1)
        import_btn = QPushButton("＋  Importuj zdjęcia")
        import_btn.setObjectName("generateBtn")
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.clicked.connect(self._import_dialog)
        top.addWidget(import_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(top)

        self.panel = GalleryPanel(thumb=168)
        self.panel.photo_deleted.connect(self.photo_deleted.emit)
        layout.addWidget(self.panel, stretch=1)

        hint = QLabel("Przeciągnij zdjęcie na kartę w Ekranie roboczym lub "
                      "w zakładce Talie, aby je przypisać")
        hint.setObjectName("hint")
        layout.addWidget(hint)

    def reload(self) -> None:
        self.panel.reload()

    # --- import ------------------------------------------------------------------
    def _import_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(config.IMAGE_EXTS))
        files, _ = QFileDialog.getOpenFileNames(
            self, "Importuj zdjęcia do /zdjecia", "", f"Obrazy ({exts})"
        )
        if files:
            self._import_files([Path(f) for f in files])

    def _import_files(self, paths: list[Path]) -> None:
        config.ZDJECIA_DIR.mkdir(parents=True, exist_ok=True)
        copied = 0
        for path in paths:
            if path.suffix.lower() not in config.IMAGE_EXTS or not path.is_file():
                continue
            try:
                # plik już w /zdjecia — nie dublujemy
                if path.parent.resolve() == config.ZDJECIA_DIR.resolve():
                    continue
                shutil.copy2(path, _unique_target(path.name))
                copied += 1
            except OSError as exc:
                show_toast(self, f"✖ nie skopiowano {path.name}: {exc}", "error")
        if copied:
            self.reload()
            show_toast(self, f"✔ zaimportowano {copied} zdjęć", "ok")
            self.photos_imported.emit(copied)

    # --- drag & drop z systemu ------------------------------------------------------
    def dragEnterEvent(self, event):  # noqa: N802 (API Qt)
        mime = event.mimeData()
        if mime.hasUrls() and any(
            Path(u.toLocalFile()).suffix.lower() in config.IMAGE_EXTS
            for u in mime.urls() if u.isLocalFile()
        ):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls():
            paths = [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]
            self._import_files(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
