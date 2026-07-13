"""Siatka slotów kart: sloty w proporcjach karty 63:88, chipy wartości, cienie."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QRectF, QVariantAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QImageReader, QPainter, \
    QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QGridLayout, QLabel, QWidget,
)

from app.core.models import Suit
from app.gui.photo_gallery import MIME_PHOTO
from app.gui.widgets import cover_pixmap

SLOT_W, SLOT_H = 150, 210          # proporcje ~63:88 (bazowy rozmiar)
PAD = 6
COLUMNS = 5

_template_thumbs: dict[tuple, QPixmap] = {}
_template_ghosts: dict[tuple, QPixmap] = {}


def clear_template_cache() -> None:
    _template_thumbs.clear()
    _template_ghosts.clear()


def _template_thumb(suit: Suit, w: int, h: int) -> QPixmap:
    key = (str(suit.template_path), w, h)
    if key not in _template_thumbs:
        _template_thumbs[key] = cover_pixmap(suit.template_path, w, h, radius=8)
    return _template_thumbs[key]


def _template_ghost(suit: Suit, w: int, h: int) -> QPixmap:
    """Przygaszona miniatura szablonu — stan „pusty slot”. Brak szablonu
    (świeży preset teł, np. w trakcie generowania kompletu) = pusty pixmap,
    slot pokazuje sam chip i znak „＋”."""
    try:
        key = (str(suit.template_path), w, h)
    except FileNotFoundError:
        empty = QPixmap(w, h)
        empty.fill(Qt.GlobalColor.transparent)
        return empty
    if key not in _template_ghosts:
        base = _template_thumb(suit, w, h)
        out = QPixmap(base.size())
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(0.22)
        painter.drawPixmap(0, 0, base)
        painter.setOpacity(1.0)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, out.width(), out.height()), 8, 8)
        painter.setClipPath(clip)
        painter.end()
        _template_ghosts[key] = out
    return _template_ghosts[key]


class CardSlot(QFrame):
    clicked = pyqtSignal()
    right_clicked = pyqtSignal()
    photo_dropped = pyqtSignal(str)

    def __init__(self, value: str, suit: Suit, parent=None, scale: float = 1.0,
                 droppable: bool = True):
        super().__init__(parent)
        self.value = value
        self.suit = suit
        self.photo_path: Path | None = None
        self.generated_path: Path | None = None
        self._w = round(SLOT_W * scale)
        self._h = round(SLOT_H * scale)
        self._img_w = self._w - 2 * PAD
        self._img_h = self._h - 2 * PAD

        self.setObjectName("cardSlot")
        self.setFixedSize(self._w, self._h)
        self.setAcceptDrops(droppable)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setProperty("state", "empty")

        self.image = QLabel(self)
        self.image.setGeometry(PAD, PAD, self._img_w, self._img_h)
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.ghost = QLabel("＋\nprzeciągnij\nzdjęcie" if scale >= 0.8 else "＋", self)
        self.ghost.setObjectName("slotGhost")
        self.ghost.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ghost.setGeometry(PAD, PAD, self._img_w, self._img_h)

        self.chip = QLabel(f"{value}{suit.symbol}", self)
        self.chip.setObjectName("slotChip")
        self.chip.setProperty("red", suit.is_red)
        if scale < 0.8:
            self.chip.setStyleSheet("font-size: 11px; padding: 1px 5px;")
        self.chip.adjustSize()
        self.chip.move(max(6, round(14 * scale)), max(6, round(14 * scale)))

        # badge liczby wariantów (prawy górny róg, widoczny gdy > 1)
        self.badge = QLabel("", self)
        self.badge.setObjectName("variantBadge")
        self.badge.hide()

        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setBlurRadius(16)
        self._shadow.setOffset(0, 4)
        self._shadow.setColor(QColor(0, 0, 0, 140))
        self.setGraphicsEffect(self._shadow)

        # płynny hover-lift (blur 16→28, offset 4→8)
        self._lift = QVariantAnimation(self)
        self._lift.setDuration(140)
        self._lift.valueChanged.connect(self._on_lift_tick)

        self._refresh_image()

    # --- stan -----------------------------------------------------------------
    def _refresh_image(self) -> None:
        if self.generated_path is not None:
            self.image.setPixmap(
                cover_pixmap(self.generated_path, self._img_w, self._img_h, 8)
            )
            self.ghost.hide()
        elif self.photo_path is not None:
            self.image.setPixmap(
                cover_pixmap(self.photo_path, self._img_w, self._img_h, 8)
            )
            self.ghost.hide()
        else:
            self.image.setPixmap(_template_ghost(self.suit, self._img_w, self._img_h))
            self.ghost.show()
        self.chip.raise_()

    def set_photo(self, path: Path | None) -> None:
        self.photo_path = path
        self.generated_path = None
        self.setProperty("state", "empty" if path is None else "assigned")
        self.setToolTip("" if path is None else str(path))
        self._refresh_image()
        self._repolish()

    def set_generated(self, path: Path) -> None:
        self.generated_path = path
        self.setProperty("state", "done")
        self.setToolTip(f"✔ {path}")
        self._refresh_image()
        self._repolish()

    def set_variant_count(self, count: int) -> None:
        """Badge z liczbą wariantów karty — pokazywany tylko gdy > 1."""
        if count > 1:
            self.badge.setText(f"×{count}")
            self.badge.adjustSize()
            self.badge.move(self._w - self.badge.width() - 6, 6)
            self.badge.show()
            self.badge.raise_()
        else:
            self.badge.hide()

    def set_error(self, message: str) -> None:
        self.setProperty("state", "error")
        self.setToolTip(message)
        self._repolish()

    def set_queued(self, queued: bool) -> None:
        """Oznaczenie „w kolejce" podczas generacji wsadowej."""
        if queued:
            self.setProperty("state", "queued")
        elif self.property("state") == "queued":
            self.setProperty(
                "state", "assigned" if self.photo_path is not None else "empty"
            )
        self._repolish()

    def _repolish(self) -> None:
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    # --- interakcje -------------------------------------------------------------
    def _on_lift_tick(self, value) -> None:
        t = float(value)
        self._shadow.setBlurRadius(16 + 12 * t)
        self._shadow.setOffset(0, 4 + 4 * t)

    def _animate_lift(self, up: bool) -> None:
        self._lift.stop()
        current = (self._shadow.blurRadius() - 16) / 12
        self._lift.setStartValue(max(0.0, min(1.0, current)))
        self._lift.setEndValue(1.0 if up else 0.0)
        self._lift.start()

    def enterEvent(self, event):  # noqa: N802 (API Qt) — efekt „uniesienia”
        self._animate_lift(True)
        grid = self.parentWidget()
        if hasattr(grid, "_set_hovered_slot"):
            grid._set_hovered_slot(self)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._animate_lift(False)
        grid = self.parentWidget()
        if hasattr(grid, "_set_hovered_slot"):
            grid._set_hovered_slot(None)
        super().leaveEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit()
        super().mousePressEvent(event)

    def _set_drag_ring(self, active: bool) -> None:
        self.setProperty("drag", active)
        self._repolish()

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(MIME_PHOTO):
            self._set_drag_ring(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):  # noqa: N802
        self._set_drag_ring(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        self._set_drag_ring(False)
        path = bytes(event.mimeData().data(MIME_PHOTO)).decode("utf-8")
        self.photo_dropped.emit(path)
        event.acceptProposedAction()


class _PeekOverlay(QLabel):
    """Lekki podgląd przelotny (peek): przytrzymanie Spacji nad kartą w siatce
    pokazuje powiększenie, puszczenie chowa. ToolTip-window = zero kradzieży
    focusu, bez wchodzenia w pełny lightbox."""

    _instance: "_PeekOverlay | None" = None

    @classmethod
    def instance(cls) -> "_PeekOverlay":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__(None, Qt.WindowType.ToolTip
                         | Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(
            "background: #14100B; border: 1px solid #4A3F2C; "
            "border-radius: 12px; padding: 10px;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def show_for(self, path: Path) -> None:
        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_h = round(avail.height() * 0.7) if avail else 700
        max_w = round(avail.width() * 0.7) if avail else 900
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(
                max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio))
        self.setPixmap(QPixmap.fromImage(reader.read()))
        self.adjustSize()
        if avail is not None:
            self.move(avail.center() - self.rect().center())
        self.show()
        self.raise_()


class CardGrid(QWidget):
    """Siatka slotów dla jednego koloru; sloty tworzone z listy wartości.

    Peek: przytrzymanie Spacji nad kartą pokazuje szybkie powiększenie
    (siatka przejmuje focus po najechaniu myszą)."""

    slot_clicked = pyqtSignal(object)          # CardSlot
    slot_right_clicked = pyqtSignal(object)    # CardSlot
    photo_dropped = pyqtSignal(object, str)    # CardSlot, ścieżka

    def __init__(self, suit: Suit, parent=None, columns: int = COLUMNS,
                 scale: float = 1.0, spacing: int = 18, droppable: bool = True):
        super().__init__(parent)
        self.suit = suit
        self._columns = columns
        self._scale = scale
        self._droppable = droppable
        self._hovered: CardSlot | None = None
        self.slots: dict[str, CardSlot] = {}
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self._layout = QGridLayout(self)
        self._layout.setSpacing(spacing)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

    # --- peek Spacją ------------------------------------------------------------
    def _set_hovered_slot(self, slot: "CardSlot | None") -> None:
        self._hovered = slot

    def enterEvent(self, event):  # noqa: N802 — Spacja działa po najechaniu
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        super().enterEvent(event)

    def keyPressEvent(self, event):  # noqa: N802
        if (event.key() == Qt.Key.Key_Space and not event.isAutoRepeat()
                and self._hovered is not None):
            slot = self._hovered
            target = slot.generated_path or slot.photo_path
            if target is None:
                try:
                    target = slot.suit.template_path
                except FileNotFoundError:
                    target = None
            if target is not None and Path(target).exists():
                _PeekOverlay.instance().show_for(Path(target))
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            _PeekOverlay.instance().hide()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def rebuild(self, values: list[str], assignments: dict[str, str]) -> None:
        """Odtwarza sloty dla podanych wartości, zachowując istniejące przypisania."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.slots.clear()

        for i, value in enumerate(values):
            slot = CardSlot(value, self.suit, scale=self._scale,
                            droppable=self._droppable)
            key = f"{self.suit.nazwa}:{value}"
            if key in assignments:
                slot.set_photo(Path(assignments[key]))
            slot.clicked.connect(lambda s=slot: self.slot_clicked.emit(s))
            slot.right_clicked.connect(lambda s=slot: self.slot_right_clicked.emit(s))
            slot.photo_dropped.connect(lambda p, s=slot: self.photo_dropped.emit(s, p))
            self._layout.addWidget(slot, i // self._columns, i % self._columns)
            self.slots[value] = slot
