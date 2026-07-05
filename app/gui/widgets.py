"""Nowoczesne kontrolki wielokrotnego użytku: SegmentedControl, Toast, cover_pixmap."""
from __future__ import annotations

import io
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRectF, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import QGuiApplication, QImageReader, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget,
)


def cover_pixmap(path: Path | str, w: int, h: int, radius: int = 10) -> QPixmap:
    """Miniatura wypełniająca cały prostokąt (crop środka) z zaokrąglonymi rogami."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid():
        scaled = size.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding)
        reader.setScaledSize(scaled)
    src = QPixmap.fromImage(reader.read())
    if src.isNull():
        return QPixmap(w, h)

    out = QPixmap(w, h)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    painter.setClipPath(clip)
    painter.drawPixmap((w - src.width()) // 2, (h - src.height()) // 2, src)
    painter.end()
    return out


def pil_to_pixmap(img) -> QPixmap:
    """Obraz PIL -> QPixmap (przez bufor PNG; bez zależności od ImageQt)."""
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    pixmap = QPixmap()
    pixmap.loadFromData(buffer.getvalue(), "PNG")
    return pixmap


class SegmentedControl(QWidget):
    """Pigułkowy przełącznik segmentowy (np. tryby, kolory talii)."""

    changed = pyqtSignal(int)  # indeks wybranego segmentu

    def __init__(self, labels: list[str], parent=None, red_flags: list[bool] | None = None):
        super().__init__(parent)
        self.setObjectName("segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._base_labels = list(labels)
        self.buttons: list[QPushButton] = []
        for i, label in enumerate(labels):
            btn = QPushButton(label)
            btn.setObjectName("segBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if red_flags and red_flags[i]:
                btn.setProperty("red", True)
            self._group.addButton(btn, i)
            layout.addWidget(btn)
            self.buttons.append(btn)
        self.buttons[0].setChecked(True)
        self._group.idClicked.connect(self.changed.emit)

    def current(self) -> int:
        return self._group.checkedId()

    def set_current(self, index: int) -> None:
        self.buttons[index].setChecked(True)

    def set_badge(self, index: int, badge: str) -> None:
        """Dopisek przy etykiecie segmentu, np. liczba przypisanych kart."""
        base = self._base_labels[index]
        self.buttons[index].setText(f"{base}  {badge}" if badge else base)


class Toast(QLabel):
    """Powiadomienie wjeżdżające w prawym dolnym rogu okna, znika samo."""

    MARGIN = 24

    def __init__(self, parent: QWidget, text: str, kind: str = "info",
                 timeout_ms: int = 3500):
        super().__init__(text, parent)
        self.setObjectName("toast")
        self.setProperty("kind", kind)
        self.setWordWrap(True)
        self.setMaximumWidth(420)
        self.adjustSize()

        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        self._fade = QPropertyAnimation(effect, b"opacity", self)
        self._fade.setDuration(250)
        self._slide = QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(250)
        self._slide.setEasingCurve(QEasingCurve.Type.OutCubic)

        end = self._target_pos()
        start = end + QPoint(0, 30)
        self.move(start)
        self.show()
        self.raise_()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._slide.setStartValue(start)
        self._slide.setEndValue(end)
        self._fade.start()
        self._slide.start()
        QTimer.singleShot(timeout_ms, self._dismiss)

    def _target_pos(self) -> QPoint:
        parent = self.parentWidget()
        return QPoint(
            parent.width() - self.width() - self.MARGIN,
            parent.height() - self.height() - self.MARGIN,
        )

    def _dismiss(self) -> None:
        self._fade.setStartValue(1.0)
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.deleteLater)
        self._fade.start()


def show_toast(parent: QWidget, text: str, kind: str = "info") -> None:
    Toast(parent, text, kind)


class ZoomDialog(QDialog):
    """Powiększony podgląd karty/pliku: ciemne tło, zamykanie kliknięciem/Esc."""

    def __init__(self, path: Path | str, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setStyleSheet("background: rgba(12, 9, 6, 235);")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        max_w = round(avail.width() * 0.9) if avail is not None else 1200
        max_h = round(avail.height() * 0.9) if avail is not None else 800

        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            scaled = size.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(scaled)
        pixmap = QPixmap.fromImage(reader.read())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 16)
        layout.setSpacing(8)
        image = QLabel()
        image.setPixmap(pixmap)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(image, stretch=1)
        caption = QLabel(f"{Path(path).name}   ·   kliknij albo Esc, aby zamknąć")
        caption.setStyleSheet("color: #B9AC98; background: transparent;")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)
        self.adjustSize()
        if avail is not None:
            self.move(avail.center() - self.rect().center())

    def mousePressEvent(self, event):  # noqa: N802 (API Qt)
        self.accept()
        super().mousePressEvent(event)
