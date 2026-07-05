"""Animacje z designu „Atelier Kart": przejścia widoków, spinner, pulsujące
kropki statusu, smuga skanująca AI (sweep) i pseudo-3D flip kart.

Wszystkie animacje pętlowe zatrzymują się, gdy widget jest niewidoczny
(showEvent/hideEvent) — zero kosztu CPU w tle.
"""
from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, QRectF,
    Qt, QVariantAnimation, pyqtSignal,
)
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
    QRadialGradient,
)
from PyQt6.QtWidgets import (
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QStackedWidget, QWidget,
)

from app.gui import theme


class BusyOverlay(QWidget):
    """Półprzezroczysta nakładka „Przetwarzanie AI…" blokująca podgląd
    podczas wywołań API (dopasowuje się do rodzica w resizeEvent)."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("busyOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#busyOverlay { background: rgba(10, 7, 4, 150);"
            " border-radius: 12px; }"
        )
        layout = QHBoxLayout(self)
        layout.setSpacing(10)
        layout.addStretch(1)
        self._spinner = Spinner(26)
        layout.addWidget(self._spinner)
        label = QLabel("Przetwarzanie AI…")
        label.setStyleSheet(
            "color: #F5EFE0; font-size: 14px; font-weight: 600;"
            " background: transparent;"
        )
        layout.addWidget(label)
        layout.addStretch(1)
        self.hide()

    def show_over(self, target: QWidget) -> None:
        if self.parent() is not target:
            self.setParent(target)
        self.setGeometry(target.rect())
        self.raise_()
        self.show()

    def resizeEvent(self, event):  # noqa: N802 (API Qt)
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        super().resizeEvent(event)


class FadingStackedWidget(QStackedWidget):
    """QStackedWidget z przejściem fade-up (opacity 0→1 + wjazd 14 px)."""

    def fade_to(self, index: int) -> None:
        if index == self.currentIndex():
            return
        self.setCurrentIndex(index)
        page = self.currentWidget()
        if page is None:
            return
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        end_pos = QPoint(0, 0)
        page.move(end_pos + QPoint(0, 14))

        fade = QPropertyAnimation(effect, b"opacity", page)
        fade.setDuration(190)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        slide = QPropertyAnimation(page, b"pos", page)
        slide.setDuration(190)
        slide.setEasingCurve(QEasingCurve.Type.OutCubic)
        slide.setStartValue(end_pos + QPoint(0, 14))
        slide.setEndValue(end_pos)

        group = QParallelAnimationGroup(page)
        group.addAnimation(fade)
        group.addAnimation(slide)

        def _cleanup() -> None:
            # QGraphicsOpacityEffect psuje niektóre natywne widgety — zdejmujemy
            page.setGraphicsEffect(None)
            page.move(end_pos)

        group.finished.connect(_cleanup)
        group.start(QParallelAnimationGroup.DeletionPolicy.DeleteWhenStopped)


class Spinner(QWidget):
    """Wirujący łuk (odpowiednik akSpin / ph-circle-notch)."""

    def __init__(self, size: int = 20, color: str = theme.ACCENT, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(color)
        self._angle = 0
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0)
        self._anim.setEndValue(360)
        self._anim.setDuration(800)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_tick)

    def _on_tick(self, value) -> None:
        self._angle = int(value)
        self.update()

    def showEvent(self, event):  # noqa: N802 (API Qt)
        self._anim.start()
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._anim.stop()
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(self._color, 2.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        margin = 3
        rect = QRectF(margin, margin, self.width() - 2 * margin,
                      self.height() - 2 * margin)
        painter.drawArc(rect, -self._angle * 16, 100 * 16)


class PulseDot(QWidget):
    """Pulsująca kropka statusu z poświatą (akPulse / akDot / akGlow)."""

    def __init__(self, color: str = theme.GREEN, size: int = 14,
                 pulsing: bool = True, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._color = QColor(color)
        self._phase = 1.0
        self._pulsing = pulsing
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.35)
        self._anim.setKeyValueAt(0.5, 1.0)
        self._anim.setEndValue(0.35)
        self._anim.setDuration(1600)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_tick)

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def set_pulsing(self, pulsing: bool) -> None:
        self._pulsing = pulsing
        if self.isVisible():
            if pulsing:
                self._anim.start()
            else:
                self._anim.stop()
                self._phase = 1.0
                self.update()

    def _on_tick(self, value) -> None:
        self._phase = float(value)
        self.update()

    def showEvent(self, event):  # noqa: N802
        if self._pulsing:
            self._anim.start()
        super().showEvent(event)

    def hideEvent(self, event):  # noqa: N802
        self._anim.stop()
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QRectF(0, 0, self.width(), self.height()).center()
        # poświata
        glow = QRadialGradient(center, self.width() / 2)
        glow_color = QColor(self._color)
        glow_color.setAlphaF(0.55 * self._phase)
        glow.setColorAt(0.0, glow_color)
        glow_color2 = QColor(self._color)
        glow_color2.setAlphaF(0.0)
        glow.setColorAt(1.0, glow_color2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, self.width(), self.height()))
        # kropka
        dot = QColor(self._color)
        dot.setAlphaF(0.45 + 0.55 * self._phase)
        painter.setBrush(dot)
        radius = self.width() * 0.22
        painter.drawEllipse(center, radius, radius)


class SweepPixmap(QWidget):
    """Podgląd obrazu z efektem „transformacji AI": wersja w skali szarości
    odsłaniana kolorem przez przesuwającą się smugę (akSweep + grayscale→kolor).
    Bez animacji działa jak zwykły podgląd zachowujący proporcje."""

    def __init__(self, placeholder: str = "", parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._gray: QPixmap | None = None
        self._placeholder = placeholder
        self._sweep_pos = -1.0     # <0 = brak efektu
        self._mask_boxes: list[tuple[int, int, int, int]] | None = None
        self._mask_source_size: tuple[int, int] = (1, 1)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(1900)
        self._anim.setLoopCount(-1)
        self._anim.valueChanged.connect(self._on_tick)
        self.setMinimumSize(200, 260)

    # --- API ------------------------------------------------------------------
    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pix = pixmap
        self._gray = self._make_gray(pixmap) if pixmap is not None else None
        self.update()

    def set_mask_boxes(self, boxes: list[tuple[int, int, int, int]] | None,
                       source_size: tuple[int, int]) -> None:
        """Nakładka „Podgląd maski": prostokąty (w px obrazu źródłowego)
        rysowane na podglądzie jako kreskowane ramki akcentu."""
        self._mask_boxes = boxes
        self._mask_source_size = source_size
        self.update()

    def start_sweep(self) -> None:
        self._sweep_pos = 0.0
        self._anim.start()

    def stop_sweep(self) -> None:
        self._anim.stop()
        self._sweep_pos = -1.0
        self.update()

    @property
    def sweeping(self) -> bool:
        return self._sweep_pos >= 0.0

    # --- wewnętrzne -------------------------------------------------------------
    @staticmethod
    def _make_gray(pixmap: QPixmap) -> QPixmap:
        image = pixmap.toImage().convertToFormat(
            pixmap.toImage().Format.Format_Grayscale8
        )
        return QPixmap.fromImage(image)

    def _on_tick(self, value) -> None:
        self._sweep_pos = float(value)
        self.update()

    def hideEvent(self, event):  # noqa: N802
        if self._anim.state() == QVariantAnimation.State.Running:
            self._anim.pause()
        super().hideEvent(event)

    def showEvent(self, event):  # noqa: N802
        if self._anim.state() == QVariantAnimation.State.Paused:
            self._anim.resume()
        super().showEvent(event)

    def _target_rect(self) -> QRectF:
        assert self._pix is not None
        scaled = self._pix.size().scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio
        )
        return QRectF(
            (self.width() - scaled.width()) / 2,
            (self.height() - scaled.height()) / 2,
            scaled.width(), scaled.height(),
        )

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if self._pix is None:
            painter.setPen(QColor(theme.MUTED))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             self._placeholder)
            return
        rect = self._target_rect()
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)

        if self._sweep_pos < 0.0:
            painter.drawPixmap(rect, self._pix, QRectF(self._pix.rect()))
            self._draw_mask_overlay(painter, rect)
            return

        # faza skanowania: szarość + kolor odsłonięty do pozycji smugi
        painter.drawPixmap(rect, self._gray, QRectF(self._gray.rect()))
        sweep_y = rect.top() + rect.height() * self._sweep_pos
        color_rect = QRectF(rect.left(), rect.top(),
                            rect.width(), sweep_y - rect.top())
        painter.setClipRect(color_rect)
        painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
        painter.drawPixmap(rect, self._pix, QRectF(self._pix.rect()))

        # smuga
        painter.setClipPath(clip)
        band_h = max(34.0, rect.height() * 0.07)
        band = QRectF(rect.left(), sweep_y - band_h / 2, rect.width(), band_h)
        gradient = QLinearGradient(band.topLeft(), band.bottomLeft())
        edge = QColor(theme.ACCENT_HOVER)
        edge.setAlphaF(0.0)
        core = QColor(theme.ACCENT_HOVER)
        core.setAlphaF(0.55)
        gradient.setColorAt(0.0, edge)
        gradient.setColorAt(0.5, core)
        gradient.setColorAt(1.0, edge)
        painter.fillRect(band, gradient)
        self._draw_mask_overlay(painter, rect)

    def _draw_mask_overlay(self, painter: QPainter, rect: QRectF) -> None:
        if not self._mask_boxes:
            return
        sw, sh = self._mask_source_size
        if sw <= 0 or sh <= 0:
            return
        scale_x = rect.width() / sw
        scale_y = rect.height() / sh
        veil = QColor(theme.BG)
        veil.setAlphaF(0.35)
        painter.fillRect(rect, veil)
        pen = QPen(QColor(theme.ACCENT), 2, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        fill = QColor(theme.ACCENT)
        fill.setAlphaF(0.18)
        painter.setBrush(fill)
        for x0, y0, x1, y1 in self._mask_boxes:
            painter.drawRect(QRectF(
                rect.left() + x0 * scale_x, rect.top() + y0 * scale_y,
                (x1 - x0) * scale_x, (y1 - y0) * scale_y,
            ))


class FlipCard(QWidget):
    """Karta z pseudo-3D flipem (skala X + podmiana awers/rewers) — akFlip."""

    clicked = pyqtSignal()

    def __init__(self, front: QPixmap, back: QPixmap, parent=None):
        super().__init__(parent)
        self._front = front
        self._back = back
        self._t = 1.0            # 1 = awers, -1 = rewers
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._anim.valueChanged.connect(self._on_tick)

    def set_faces(self, front: QPixmap, back: QPixmap) -> None:
        self._front = front
        self._back = back
        self.update()

    def flip(self) -> None:
        start, end = self._t, (-1.0 if self._t > 0 else 1.0)
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _on_tick(self, value) -> None:
        self._t = float(value)
        self.update()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            self.flip()
        super().mousePressEvent(event)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pix = self._front if self._t >= 0 else self._back
        if pix.isNull():
            return
        scale_x = max(abs(self._t), 0.02)
        painter.translate(self.width() / 2, self.height() / 2)
        painter.scale(scale_x, 1.0)
        target = QRectF(-self.width() / 2, -self.height() / 2,
                        self.width(), self.height())
        clip = QPainterPath()
        clip.addRoundedRect(target, 10, 10)
        painter.setClipPath(clip)
        painter.drawPixmap(target, pix, QRectF(pix.rect()))
