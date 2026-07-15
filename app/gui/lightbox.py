"""Lightbox kart: powiększenie z paskiem wariantów, nawigacją klawiaturą
i akcjami (główna/usuń/przestempluj/folder).

Dane i mutacje płyną przez MainWindow (zasada: widoki nie wołają logiki
bezpośrednio): kontekst LightboxContext dostarcza odczyty, akcje wychodzą
sygnałami. Tryb single (variants zwraca 1 plik bez akcji) obsługuje podgląd
dowolnego pliku (historia, backupy rewersu).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QVariantAnimation,
    pyqtSignal,
)
from PyQt6.QtGui import QGuiApplication, QIcon, QImageReader, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QGraphicsPixmapItem, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from app.gui.widgets import cover_pixmap

THUMB_W, THUMB_H = 64, 90
MAX_ZOOM = 4.0
ANIM_MS = 120     # standard: animacje lightboxa ≤ 120 ms


class ZoomableImage(QGraphicsView):
    """Podgląd obrazu z zoomem: kółko = skala 1.0–4.0 wokół kursora,
    przeciąganie przesuwa przy skali > 100%, dwuklik = animowany reset.
    Klik w obraz jest konsumowany tutaj — NIE zamyka lightboxa."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self._item = QGraphicsPixmapItem()
        self._item.setTransformationMode(
            Qt.TransformationMode.SmoothTransformation)
        self._scene.addItem(self._item)
        self.setScene(self._scene)
        self._zoom = 1.0

        self.setStyleSheet("background: transparent; border: none;")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._reset_anim = QVariantAnimation(self)
        self._reset_anim.setDuration(ANIM_MS)
        self._reset_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._reset_anim.valueChanged.connect(self._apply_zoom)

    def set_pixmap(self, pixmap: QPixmap) -> None:
        self._reset_anim.stop()
        self._item.setPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self._apply_zoom(1.0)

    def _apply_zoom(self, zoom: float) -> None:
        """Skala absolutna: fit-to-view (=100%) pomnożony przez zoom."""
        self._zoom = max(1.0, min(float(zoom), MAX_ZOOM))
        if self._item.pixmap().isNull():
            return
        self.resetTransform()
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        if self._zoom > 1.0:
            self.scale(self._zoom, self._zoom)
        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag if self._zoom > 1.0
            else QGraphicsView.DragMode.NoDrag)

    def wheelEvent(self, event):  # noqa: N802 (API Qt)
        factor = 1.18 if event.angleDelta().y() > 0 else 1 / 1.18
        self._reset_anim.stop()
        self._apply_zoom(self._zoom * factor)
        event.accept()

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        self._reset_anim.stop()
        self._reset_anim.setStartValue(self._zoom)
        self._reset_anim.setEndValue(1.0)
        self._reset_anim.start()
        event.accept()

    def mousePressEvent(self, event):  # noqa: N802 — klik w obraz nie zamyka
        super().mousePressEvent(event)
        event.accept()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._apply_zoom(self._zoom)


@dataclass
class LightboxContext:
    """Odczyty dostarczane przez MainWindow (lightbox niczego nie mutuje)."""
    cards: Callable[[], list[tuple[str, str]]]        # [(suit_nazwa, value)] wg filtra
    variants: Callable[[str, str], list[Path]]        # warianty karty (rosnąco)
    selected: Callable[[str, str], Path | None]       # główny wariant karty
    card_label: Callable[[str, str], str]             # etykieta np. "A♥"


class CardLightbox(QDialog):
    """Powiększenie karty z wariantami. Klawiatura: ←/→ warianty, ↑/↓ karty,
    Home/End pierwszy/ostatni wariant, Esc zamyka."""

    set_main_requested = pyqtSignal(str, str, str)    # suit, value, ścieżka
    delete_requested = pyqtSignal(str, str, str)      # suit, value, ścieżka
    restamp_requested = pyqtSignal(str, str)          # suit, value
    fix_requested = pyqtSignal(str, str, str)         # suit, value, ścieżka wariantu
    open_folder_requested = pyqtSignal(str)           # ścieżka bieżącego pliku

    def __init__(self, ctx: LightboxContext, suit_nazwa: str, value: str,
                 parent=None, single_path: Path | None = None):
        super().__init__(parent)
        self.ctx = ctx
        self._single = single_path is not None
        self._suit = suit_nazwa
        self._value = value
        self._var_idx = 0
        self._single_path = single_path

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.Dialog)
        self.setModal(True)
        self.setObjectName("lightbox")
        self.setStyleSheet("QDialog#lightbox { background: rgba(12, 9, 6, 242); }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        screen = QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen else None
        if avail is not None:
            self.setFixedSize(round(avail.width() * 0.92),
                              round(avail.height() * 0.92))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 12)
        layout.setSpacing(8)

        # --- pasek górny: tytuł + licznik + × --------------------------------
        top = QHBoxLayout()
        self.title_label = QLabel()
        self.title_label.setStyleSheet(
            "color: #EFE6D5; font-size: 18px; font-weight: bold; "
            "background: transparent;")
        top.addWidget(self.title_label)
        top.addStretch(1)
        self.counter_label = QLabel()
        self.counter_label.setStyleSheet(
            "color: #B9AC98; font-size: 14px; background: transparent;")
        top.addWidget(self.counter_label)
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("ghostBtn")
        self.close_btn.setFixedSize(34, 34)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_btn.clicked.connect(self.reject)
        top.addWidget(self.close_btn)
        layout.addLayout(top)

        # --- obraz (zoom kółkiem, pan przy >100%, dwuklik = reset) -----------
        self.image = ZoomableImage()
        layout.addWidget(self.image, stretch=1)

        # --- pasek miniatur wariantów -------------------------------------------
        self.thumbs_host = QWidget()
        self.thumbs_host.setStyleSheet("background: transparent;")
        self.thumbs_row = QHBoxLayout(self.thumbs_host)
        self.thumbs_row.setContentsMargins(0, 0, 0, 0)
        self.thumbs_row.setSpacing(6)
        self.thumbs_row.addStretch(1)   # wyśrodkowanie (stretch po obu stronach)
        self.thumbs_row.addStretch(1)
        self._thumb_group = QButtonGroup(self)
        self._thumb_group.setExclusive(True)
        self._thumb_buttons: list[QPushButton] = []
        layout.addWidget(self.thumbs_host)

        # --- akcje ---------------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        self.set_main_btn = QPushButton("★  Ustaw jako główną")
        self.set_main_btn.clicked.connect(self._on_set_main)
        self.delete_btn = QPushButton("🗑  Usuń wariant")
        self.delete_btn.clicked.connect(self._on_delete)
        self.restamp_btn = QPushButton("♻  Przestempluj narożniki")
        self.restamp_btn.clicked.connect(
            lambda: self.restamp_requested.emit(self._suit, self._value))
        self.fix_btn = QPushButton("🩹  Popraw selektywnie")
        self.fix_btn.setToolTip(
            "Zamaluj obszar błędu i opisz poprawkę — model przerysuje TYLKO "
            "ten fragment (wynik jako nowy wariant)")
        self.fix_btn.clicked.connect(self._on_fix)
        self.folder_btn = QPushButton("📁  Otwórz folder")
        self.folder_btn.clicked.connect(self._on_open_folder)
        for btn in (self.set_main_btn, self.delete_btn,
                    self.restamp_btn, self.fix_btn, self.folder_btn):
            btn.setObjectName("ghostBtn")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            actions.addWidget(btn)
        actions.addStretch(1)
        self.actions_host = QWidget()
        self.actions_host.setStyleSheet("background: transparent;")
        self.actions_host.setLayout(actions)
        layout.addWidget(self.actions_host)

        hint = QLabel("← → warianty   ·   ↑ ↓ karty   ·   Home/End skrajne   ·   "
                      "Esc zamyka")
        hint.setStyleSheet("color: #8A7F6C; font-size: 11px; background: transparent;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        if self._single:
            self.thumbs_host.hide()
            self.actions_host.hide()
        if avail is not None:
            self.move(avail.center() - self.rect().center())

        # animacja otwarcia: fade 0 → 1 (≤ 120 ms)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(ANIM_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.refresh()

    def showEvent(self, event):  # noqa: N802 (API Qt)
        self.setWindowOpacity(0.0)
        self._fade.start()
        super().showEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        """Klik w przyciemnione TŁO zamyka; klik w obraz/panele — nie
        (ZoomableImage i przyciski konsumują swoje kliknięcia same)."""
        child = self.childAt(event.position().toPoint())
        if child is None or child in (self.title_label, self.counter_label):
            self.reject()
            return
        super().mousePressEvent(event)

    # ------------------------------------------------------------- stan / dane
    def _variants(self) -> list[Path]:
        if self._single:
            return [self._single_path] if self._single_path else []
        return self.ctx.variants(self._suit, self._value)

    def current_path(self) -> Path | None:
        variants = self._variants()
        if not variants:
            return None
        self._var_idx = max(0, min(self._var_idx, len(variants) - 1))
        return variants[self._var_idx]

    def refresh(self, keep_index: bool = True) -> None:
        """Przeładowuje warianty bieżącej karty (po mutacjach z zewnątrz)."""
        variants = self._variants()
        if not variants:
            self.reject()
            return
        if not keep_index:
            self._var_idx = len(variants) - 1
        self._var_idx = max(0, min(self._var_idx, len(variants) - 1))
        self._rebuild_thumbs(variants)
        self._show_current()

    def _show_current(self) -> None:
        path = self.current_path()
        if path is None:
            return
        variants = self._variants()
        # pełna rozdzielczość — ZoomableImage skaluje do widoku, a zapas
        # pikseli obsługuje zoom do 400%
        reader = QImageReader(str(path))
        reader.setAutoTransform(True)
        self.image.set_pixmap(QPixmap.fromImage(reader.read()))

        if self._single:
            self.title_label.setText(Path(path).name)
            self.counter_label.setText("")
            return
        selected = self.ctx.selected(self._suit, self._value)
        star = "  ★" if selected is not None and Path(path) == selected else ""
        self.title_label.setText(
            f"{self.ctx.card_label(self._suit, self._value)}   ·   "
            f"{Path(path).name}{star}")
        self.counter_label.setText(f"{self._var_idx + 1} / {len(variants)}")
        self.set_main_btn.setEnabled(not star)
        for i, btn in enumerate(self._thumb_buttons):
            btn.setChecked(i == self._var_idx)

    def _rebuild_thumbs(self, variants: list[Path]) -> None:
        for btn in self._thumb_buttons:
            self._thumb_group.removeButton(btn)
            btn.deleteLater()
        self._thumb_buttons.clear()
        selected = self.ctx.selected(self._suit, self._value) \
            if not self._single else None
        for i, path in enumerate(variants):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(THUMB_W + 8, THUMB_H + 8)
            btn.setIcon(QIcon(cover_pixmap(path, THUMB_W, THUMB_H, radius=6)))
            btn.setIconSize(QSize(THUMB_W, THUMB_H))
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: 2px solid "
                "transparent; border-radius: 8px; }"
                "QPushButton:checked { border-color: #C99A3C; }")
            if selected is not None and path == selected:
                btn.setToolTip(f"★ główna · {path.name}")
                btn.setText("★")
            else:
                btn.setToolTip(path.name)
            btn.clicked.connect(lambda _=False, idx=i: self._go_variant(idx))
            # wstaw przed końcowy stretch (ostatni element layoutu)
            self.thumbs_row.insertWidget(self.thumbs_row.count() - 1, btn)
            self._thumb_group.addButton(btn)
            self._thumb_buttons.append(btn)

    # ------------------------------------------------------------- nawigacja
    def _go_variant(self, idx: int) -> None:
        variants = self._variants()
        if not variants:
            return
        self._var_idx = max(0, min(idx, len(variants) - 1))
        self._show_current()

    def _go_card(self, step: int) -> None:
        if self._single:
            return
        cards = self.ctx.cards()
        if not cards:
            return
        key = (self._suit, self._value)
        idx = cards.index(key) if key in cards else 0
        idx = (idx + step) % len(cards)
        self._suit, self._value = cards[idx]
        self._var_idx = 0
        self.refresh()

    def keyPressEvent(self, event):  # noqa: N802 (API Qt)
        key = event.key()
        if key == Qt.Key.Key_Left:
            self._go_variant(self._var_idx - 1)
        elif key == Qt.Key.Key_Right:
            self._go_variant(self._var_idx + 1)
        elif key == Qt.Key.Key_Up:
            self._go_card(-1)
        elif key == Qt.Key.Key_Down:
            self._go_card(1)
        elif key == Qt.Key.Key_Home:
            self._go_variant(0)
        elif key == Qt.Key.Key_End:
            self._go_variant(len(self._variants()) - 1)
        else:
            super().keyPressEvent(event)   # Esc → reject (natywne QDialog)

    # ------------------------------------------------------------- akcje
    def _on_set_main(self) -> None:
        path = self.current_path()
        if path is not None:
            self.set_main_requested.emit(self._suit, self._value, str(path))

    def _on_delete(self) -> None:
        path = self.current_path()
        if path is not None:
            self.delete_requested.emit(self._suit, self._value, str(path))

    def _on_fix(self) -> None:
        path = self.current_path()
        if path is not None:
            self.fix_requested.emit(self._suit, self._value, str(path))

    def _on_open_folder(self) -> None:
        path = self.current_path()
        if path is not None:
            self.open_folder_requested.emit(str(path))
