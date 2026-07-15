"""Nowoczesne kontrolki wielokrotnego użytku: SnapSlider, NoScrollComboBox,
NoScrollSpinBox, SegmentedControl, Toast, cover_pixmap."""
from __future__ import annotations

import io
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve, QPoint, QPropertyAnimation, QRectF, QTimer, Qt, pyqtSignal,
)
from PyQt6.QtGui import QImageReader, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QComboBox, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
    QPushButton, QSlider, QSpinBox, QStyle, QWidget,
)


class SnapSlider(QSlider):
    """Poziomy suwak dla całej aplikacji (NIE używać surowego QSlider):
    klik w tor = natychmiastowy skok uchwytu do klikniętego miejsca (domyślny
    QSlider ruszał się tylko o page-step — trzeba było celować w mały uchwyt),
    potem normalne przeciąganie; pageStep ~10% zakresu; kursor wskazujący.
    Wygląd stylizuje sekcja QSlider w theme.QSS (tor + akcentowe wypełnienie
    + duży okrągły uchwyt)."""

    def __init__(self, minimum: int = 0, maximum: int = 100,
                 value: int = 0, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setRange(minimum, maximum)
        self.setValue(value)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPageStep(max(1, (maximum - minimum) // 10))

    def mousePressEvent(self, event):  # noqa: N802 (API Qt)
        if event.button() == Qt.MouseButton.LeftButton:
            # skok do klikniętej pozycji PRZED standardową obsługą — uchwyt
            # ląduje pod kursorem, więc super() od razu zaczyna przeciąganie
            self.setValue(QStyle.sliderValueFromPosition(
                self.minimum(), self.maximum(),
                round(event.position().x()), max(1, self.width())))
        super().mousePressEvent(event)

    def wheelEvent(self, event):  # noqa: N802 (API Qt)
        # kółko myszy NIE rusza suwaka — zdarzenie idzie do QScrollArea
        # (ochrona przed przypadkową zmianą wartości przy przewijaniu strony)
        event.ignore()


class NoScrollComboBox(QComboBox):
    """Lista wyboru dla całej aplikacji (NIE używać surowego QComboBox):
    kółko myszy NIE zmienia wyboru — zdarzenie propaguje do QScrollArea
    i strona się przewija (przewijanie nad combo zmieniało preset/kolor
    przypadkiem). Zmiana tylko przez rozwinięcie listy; przewijanie
    WEWNĄTRZ rozwiniętej listy działa normalnie (popup to osobny widżet)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        # domyślne WheelFocus dawało fokus od samego kółka
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 (API Qt)
        event.ignore()


class NoScrollSpinBox(QSpinBox):
    """Pole liczbowe dla całej aplikacji (NIE używać surowego QSpinBox):
    kółko myszy NIE zmienia wartości (jak NoScrollComboBox); strzałki ▲▼,
    klawiatura i wpisywanie działają bez zmian."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 (API Qt)
        event.ignore()


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


# ZoomDialog usunięty — powiększenia obsługuje CardLightbox (app/gui/lightbox.py):
# tryb wariantów w Taliach i tryb single dla pojedynczych plików.
