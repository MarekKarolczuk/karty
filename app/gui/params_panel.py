"""Widgety Studia (używane w widokach): wybór tła kart, podgląd z efektem
skanowania AI i log w stylu terminala."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QComboBox, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from app.core.models import Suit
from app.gui.animations import SweepPixmap
from app.gui.photo_gallery import MIME_PHOTO


class TemplatePicker(QWidget):
    """Sekcja „Tło kart": wybór koloru i szablonu (opcjonalnie generowanie AI).

    Na Ekranie roboczym służy WYŁĄCZNIE do wyboru istniejącego tła
    (show_generate=False); generowanie nowych teł żyje w zakładce
    „Domyślne style / Tła i rewersy"."""

    template_changed = pyqtSignal(object, str)      # Suit, ścieżka szablonu
    generate_template_clicked = pyqtSignal(object)  # Suit

    def __init__(self, parent=None, show_generate: bool = True):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        title = QLabel("Tło kart")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        self.suit_combo = QComboBox()
        for suit in Suit:
            self.suit_combo.addItem(f"{suit.symbol} {suit.nazwa}", suit)
        self.suit_combo.currentIndexChanged.connect(self._refresh_templates)
        self.suit_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.suit_combo)

        self.template_combo = QComboBox()
        self.template_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.template_combo.activated.connect(self._on_template_picked)
        layout.addWidget(self.template_combo)

        self.gen_template_btn = QPushButton("🎨  Generuj nowe tło (AI)")
        self.gen_template_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gen_template_btn.clicked.connect(
            lambda: self.generate_template_clicked.emit(self.current_suit())
        )
        self.gen_template_btn.setVisible(show_generate)
        layout.addWidget(self.gen_template_btn)
        if not show_generate:
            hint = QLabel("Nowe tła wygenerujesz w „Domyślne style / Tła "
                          "i rewersy".rstrip())
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        self._refresh_templates()

    def current_suit(self) -> Suit:
        return self.suit_combo.currentData()

    def _refresh_templates(self) -> None:
        suit = self.current_suit()
        active = str(suit.template_path) if suit.available_templates() else ""
        self.template_combo.blockSignals(True)
        self.template_combo.clear()
        for path in suit.available_templates():
            self.template_combo.addItem(path.name, str(path))
            if str(path) == active:
                self.template_combo.setCurrentIndex(self.template_combo.count() - 1)
        self.template_combo.blockSignals(False)

    def _on_template_picked(self, index: int) -> None:
        path = self.template_combo.itemData(index)
        if path:
            self.template_changed.emit(self.current_suit(), path)

    def refresh_templates(self) -> None:
        """Do wywołania z zewnątrz po wygenerowaniu nowego tła."""
        self._refresh_templates()

    def set_template_busy(self, busy: bool) -> None:
        self.gen_template_btn.setEnabled(not busy)
        self.gen_template_btn.setText(
            "⏳  Generuję tło..." if busy else "🎨  Generuj nowe tło (AI)"
        )


class PreviewPane(QWidget):
    """Duży podgląd karty/zdjęcia z opcjonalnym efektem skanowania AI.

    Przyjmuje upuszczane zdjęcia (drag & drop z puli) — służy do szybkiego
    przypisania / podmiany zdjęcia na aktualnie wybranej karcie. Gdy kadr jest
    edytowalny (tryb Hybrydowy + przypisane zdjęcie), pozwala kadrować myszą:
    przeciąganie = pozycja X/Y, kółko = zoom."""

    photo_dropped = pyqtSignal(str)   # ścieżka upuszczonego zdjęcia
    pan_delta = pyqtSignal(int, int)  # przesunięcie kadru w jednostkach suwaka
    zoom_delta = pyqtSignal(int)      # obrót kółka (w „ząbkach")
    crop_committed = pyqtSignal()     # koniec gestu kadrowania (zapis)

    # czułość: przeciągnięcie przez całą szerokość/wysokość podglądu ≈ tyle jednostek
    _PAN_SPAN = 140

    def __init__(self, placeholder: str = "kliknij kartę,\nżeby zobaczyć podgląd",
                 parent=None):
        super().__init__(parent)
        self.setObjectName("well")
        self.setAcceptDrops(True)
        self._crop_active = False
        self._drag_pos = None
        self._dragged = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)

        self.canvas = SweepPixmap(placeholder)
        # przezroczysty dla myszy → gesty kadrowania trafiają do PreviewPane
        self.canvas.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self.canvas, stretch=1)

        self.caption = QLabel("63 × 88 mm · 300 DPI · JPG")
        self.caption.setObjectName("hint")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.caption)

    # --- kadrowanie myszą -----------------------------------------------------
    def set_crop_active(self, active: bool) -> None:
        self._crop_active = active
        self.setCursor(Qt.CursorShape.OpenHandCursor if active
                       else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event):  # noqa: N802 (API Qt)
        if self._crop_active and event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.position()
            self._dragged = False
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._crop_active and self._drag_pos is not None:
            cur = event.position()
            w = max(1, self.canvas.width())
            h = max(1, self.canvas.height())
            udx = round((cur.x() - self._drag_pos.x()) / w * self._PAN_SPAN)
            udy = round((cur.y() - self._drag_pos.y()) / h * self._PAN_SPAN)
            if udx or udy:
                self._dragged = True
                self.pan_delta.emit(udx, udy)
                self._drag_pos = cur
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._drag_pos is not None:
            self._drag_pos = None
            self.setCursor(Qt.CursorShape.OpenHandCursor if self._crop_active
                           else Qt.CursorShape.ArrowCursor)
            if self._dragged:
                self.crop_committed.emit()
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):  # noqa: N802
        if self._crop_active:
            notches = event.angleDelta().y() // 120
            if notches:
                self.zoom_delta.emit(notches)
                self.crop_committed.emit()
            event.accept()
        else:
            super().wheelEvent(event)

    def dragEnterEvent(self, event):  # noqa: N802 (API Qt)
        if event.mimeData().hasFormat(MIME_PHOTO):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(MIME_PHOTO):
            path = bytes(event.mimeData().data(MIME_PHOTO)).decode("utf-8")
            self.photo_dropped.emit(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def show_preview(self, pixmap: QPixmap) -> None:
        self.canvas.set_pixmap(pixmap)

    def clear_preview(self) -> None:
        self.canvas.set_pixmap(None)

    def start_sweep(self) -> None:
        self.canvas.start_sweep()

    def stop_sweep(self) -> None:
        self.canvas.stop_sweep()

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)


class LogPane(QWidget):
    """LOG API — monospace, w stylu terminala z designu."""

    def __init__(self, title: str = "LOG API", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel(title)
        header.setObjectName("sectionTitle")
        layout.addWidget(header)

        self.log = QPlainTextEdit()
        self.log.setObjectName("logMono")
        self.log.setReadOnly(True)
        layout.addWidget(self.log, stretch=1)

    def log_line(self, text: str) -> None:
        self.log.appendPlainText(f"›  {text}")
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
