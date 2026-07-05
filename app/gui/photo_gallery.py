"""Panel zdjęć: szukajka, licznik, miniatury z zaokrąglonymi rogami, drag & drop."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QLineF, QMimeData, QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QDrag, QIcon, QImageReader, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from app import config

MIME_PHOTO = "application/x-karta-photo"
THUMB = 116

# role danych elementu galerii (poza domyślną ścieżką w UserRole)
_ROLE_USED = Qt.ItemDataRole.UserRole + 1     # bool: zdjęcie przypisane do karty
_ROLE_BASE = Qt.ItemDataRole.UserRole + 2     # QPixmap: miniatura bez znacznika


def load_thumbnail(path: Path, side: int = THUMB) -> QPixmap:
    """Miniatura zachowująca proporcje (do podglądów)."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)  # respektuj EXIF (orientacja zdjęć z telefonu)
    size = reader.size()
    if size.isValid():
        scaled = size.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(scaled)
    return QPixmap.fromImage(reader.read())


def _badge_used(base: QPixmap) -> QPixmap:
    """Nakłada zielony znacznik „✓ użyte" w prawym górnym rogu miniatury."""
    out = QPixmap(base)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = max(16, out.width() // 6)
    m = 4
    painter.setPen(QPen(QColor(0, 0, 0, 130), 1))
    painter.setBrush(QColor("#5FA463"))
    painter.drawEllipse(QRectF(out.width() - r - m, m, r, r))
    cx, cy = out.width() - r - m + r / 2, m + r / 2
    painter.setPen(QPen(QColor("#0F0C07"), max(2, r // 7)))
    painter.drawLine(QLineF(QPointF(cx - r * 0.22, cy),
                            QPointF(cx - r * 0.02, cy + r * 0.20)))
    painter.drawLine(QLineF(QPointF(cx - r * 0.02, cy + r * 0.20),
                            QPointF(cx + r * 0.25, cy - r * 0.22)))
    painter.end()
    return out


class PhotoGallery(QListWidget):
    photo_deleted = pyqtSignal(str)  # ścieżka usuniętego pliku

    def __init__(self, parent=None, thumb: int = THUMB):
        super().__init__(parent)
        self._thumb = thumb
        self._used: set[str] = set()
        self._only_unused = False
        self._sort = "name"    # "name" | "date"
        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setIconSize(QSize(thumb, thumb))
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setSpacing(8)
        self.setDragEnabled(True)
        # DragOnly — bez wewnętrznego przenoszenia elementów (to ono powodowało,
        # że zrzut wymagał dodatkowego kliknięcia); własny startDrag niżej.
        self.setDragDropMode(QListWidget.DragDropMode.DragOnly)
        self.setWordWrap(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.reload()

    def set_thumb(self, size: int) -> None:
        """Zmienia rozmiar miniatur (przełącznik gęstości siatki) i przeładowuje."""
        self._thumb = size
        self.setIconSize(QSize(size, size))
        self.reload()

    def reload(self) -> None:
        self.clear()
        if not config.ZDJECIA_DIR.exists():
            return
        from app.gui.widgets import cover_pixmap  # tu, by uniknąć cyklu importów
        paths = [p for p in config.ZDJECIA_DIR.iterdir()
                 if p.suffix.lower() in config.IMAGE_EXTS]
        if self._sort == "date":
            paths.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        else:
            paths.sort()
        for path in paths:
            base = cover_pixmap(path, self._thumb, self._thumb, 12)
            used = str(path) in self._used
            item = QListWidgetItem(
                QIcon(_badge_used(base) if used else base), path.name
            )
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setData(_ROLE_USED, used)
            item.setData(_ROLE_BASE, base)
            item.setToolTip(f"{path.name}  ·  ✓ użyte" if used else path.name)
            self.addItem(item)

    def set_sort(self, mode: str) -> None:
        self._sort = "date" if mode == "date" else "name"
        self.reload()

    def set_used_paths(self, used) -> None:
        """Aktualizuje znaczniki „użyte" bez czytania plików z dysku ponownie."""
        self._used = {str(p) for p in used}
        for i in range(self.count()):
            item = self.item(i)
            path = item.data(Qt.ItemDataRole.UserRole)
            base = item.data(_ROLE_BASE)
            used = path in self._used
            item.setData(_ROLE_USED, used)
            if base is not None:
                item.setIcon(QIcon(_badge_used(base) if used else base))
            item.setToolTip(f"{Path(path).name}  ·  ✓ użyte" if used
                            else Path(path).name)

    def set_only_unused(self, only_unused: bool) -> None:
        self._only_unused = only_unused

    def apply_filter(self, text: str) -> int:
        """Ukrywa niepasujące/użyte miniatury; zwraca liczbę widocznych."""
        text = text.strip().lower()
        visible = 0
        for i in range(self.count()):
            item = self.item(i)
            used = bool(item.data(_ROLE_USED))
            hidden = (bool(text) and text not in item.text().lower()) \
                or (self._only_unused and used)
            item.setHidden(hidden)
            visible += 0 if hidden else 1
        return visible

    def selected_photo(self) -> Path | None:
        item = self.currentItem()
        return Path(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def mimeData(self, items) -> QMimeData:  # noqa: N802 (API Qt)
        data = QMimeData()
        if items:
            data.setData(MIME_PHOTO, items[0].data(Qt.ItemDataRole.UserRole).encode("utf-8"))
        return data

    def startDrag(self, supported_actions) -> None:  # noqa: N802 (API Qt)
        """Własny start przeciągania: modalne drag.exec() kończy się na puszczeniu
        przycisku myszy (bez konieczności dodatkowego kliknięcia). Ustawia
        miniaturę jako obraz kursora przeciągania."""
        item = self.currentItem()
        if item is None:
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        mime = QMimeData()
        mime.setData(MIME_PHOTO, str(path).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = item.icon().pixmap(self._thumb, self._thumb)
        if not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().center())
        drag.exec(Qt.DropAction.CopyAction, Qt.DropAction.CopyAction)

    def _show_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        menu = QMenu(self)
        delete_action = menu.addAction(f"🗑  Usuń zdjęcie „{path.name}”")
        if menu.exec(self.mapToGlobal(pos)) is delete_action:
            answer = QMessageBox.question(
                self, "Usunąć zdjęcie?",
                f"Plik {path.name} zostanie trwale usunięty z folderu zdjecia/.\n"
                "Zniknie też z kart, do których był przypisany.",
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    path.unlink()
                except OSError as exc:
                    QMessageBox.warning(self, "Błąd", f"Nie udało się usunąć pliku:\n{exc}")
                    return
                self.takeItem(self.row(item))
                self.photo_deleted.emit(str(path))


class GalleryPanel(QWidget):
    """Kompletny lewy panel: nagłówek, szukajka, galeria, licznik, odśwież."""

    photo_deleted = pyqtSignal(str)

    def __init__(self, parent=None, thumb: int = THUMB):
        super().__init__(parent)
        self.setObjectName("panel")
        self._large_thumb = thumb
        self._compact_thumb = max(64, round(thumb * 0.62))
        self._compact = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Zdjęcia")
        title.setObjectName("panelTitle")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.unused_toggle = QPushButton("Nieużyte")
        self.unused_toggle.setObjectName("ghostBtn")
        self.unused_toggle.setCheckable(True)
        self.unused_toggle.setToolTip("Pokaż tylko zdjęcia jeszcze "
                                      "nieprzypisane do żadnej karty")
        self.unused_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unused_toggle.toggled.connect(self._on_unused_toggled)
        title_row.addWidget(self.unused_toggle)
        self.grid_toggle = QPushButton("▤")
        self.grid_toggle.setObjectName("ghostBtn")
        self.grid_toggle.setFixedSize(32, 26)
        self.grid_toggle.setToolTip("Przełącz gęstość siatki miniatur "
                                    "(duże kafle ↔ kompaktowa siatka)")
        self.grid_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.grid_toggle.clicked.connect(self._toggle_grid)
        title_row.addWidget(self.grid_toggle)
        layout.addLayout(title_row)

        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("searchEdit")
        self.search.setPlaceholderText("🔍  Szukaj zdjęcia...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        search_row.addWidget(self.search, stretch=1)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Nazwa", "name")
        self.sort_combo.addItem("Data", "date")
        self.sort_combo.setToolTip("Sortowanie miniatur")
        self.sort_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        search_row.addWidget(self.sort_combo)
        layout.addLayout(search_row)

        self.gallery = PhotoGallery(thumb=thumb)
        self.gallery.photo_deleted.connect(self.photo_deleted.emit)
        layout.addWidget(self.gallery, stretch=1)

        self.counter = QLabel()
        self.counter.setObjectName("counter")
        layout.addWidget(self.counter)

        refresh = QPushButton("⟳  Odśwież folder")
        refresh.setObjectName("ghostBtn")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.reload)
        layout.addWidget(refresh)

        self._update_counter(self.gallery.count())

    def _toggle_grid(self) -> None:
        self._compact = not self._compact
        size = self._compact_thumb if self._compact else self._large_thumb
        self.gallery.set_thumb(size)
        self.grid_toggle.setText("▦" if self._compact else "▤")
        # przeładowanie skasowało filtr — przywróć widoczność wg szukajki
        self._on_search(self.search.text())

    def _on_unused_toggled(self, only_unused: bool) -> None:
        self.gallery.set_only_unused(only_unused)
        self._on_search(self.search.text())

    def _on_sort_changed(self, _index: int) -> None:
        self.gallery.set_sort(self.sort_combo.currentData())
        self._on_search(self.search.text())

    def set_used_paths(self, used) -> None:
        """Aktualizuje znaczniki „użyte" na miniaturach (z MainWindow)."""
        self.gallery.set_used_paths(used)
        self._on_search(self.search.text())

    def reload(self) -> None:
        self.gallery.reload()
        self._on_search(self.search.text())

    def selected_photo(self) -> Path | None:
        return self.gallery.selected_photo()

    def _on_search(self, text: str) -> None:
        self._update_counter(self.gallery.apply_filter(text))

    def _update_counter(self, visible: int) -> None:
        self.counter.setText(f"{visible} zdjęć • kliknij albo przeciągnij na kartę")
