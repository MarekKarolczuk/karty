"""Widok Ekran roboczy: pula zdjęć, duży podgląd z efektem AI i podglądem
maski, właściwości karty (klawiatura wartości + siatka kolorów), suwaki
kadrowania zdjęcia (Zoom/X/Y), panel generacji (tryb, postęp, kolejka, log)
i film-strip całej talii z obsługą drag & drop."""
from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QScrollArea, QSlider, QSpinBox, QSplitter,
    QVBoxLayout, QWidget,
)

from app.core.compositor import DEFAULT_TRANSFORM
from app.core.masks import get_masks
from app.core.models import Suit
from app.gui import theme
from app.gui.card_grid import CardGrid, CardSlot
from app.gui.params_panel import PreviewPane, TemplatePicker
from app.gui.photo_gallery import MIME_PHOTO, GalleryPanel
from app.gui.views import view_header
from app.gui.views.generation_panel import GenerationPanel
from app.gui.widgets import cover_pixmap


class _StripList(QListWidget):
    """Film-strip talii przyjmujący upuszczane zdjęcia (drag & drop
    z puli po lewej bezpośrednio na kartę w pasku)."""

    photo_dropped = pyqtSignal(str, str)   # klucz "kolor:wartość", ścieżka

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        # KLUCZOWE: QListWidget przechwytuje drag&drop przez widok elementów —
        # bez trybu DropOnly zdarzenia nie docierają do dropEvent poniżej.
        self.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.viewport().setAcceptDrops(True)

    def dragEnterEvent(self, event):  # noqa: N802 (API Qt)
        if event.mimeData().hasFormat(MIME_PHOTO):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(MIME_PHOTO):
            item = self.itemAt(event.position().toPoint())
            self.setCurrentItem(item)
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(MIME_PHOTO):
            item = self.itemAt(event.position().toPoint())
            if item is not None:
                path = bytes(event.mimeData().data(MIME_PHOTO)).decode("utf-8")
                self.photo_dropped.emit(
                    item.data(Qt.ItemDataRole.UserRole), path
                )
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

STRIP_W, STRIP_H = 66, 92

CARD_NAMES = {
    "A": "As", "K": "Król", "Q": "Dama", "J": "Walet",
    "10": "Dziesiątka", "9": "Dziewiątka", "8": "Ósemka", "7": "Siódemka",
    "6": "Szóstka", "5": "Piątka", "4": "Czwórka", "3": "Trójka", "2": "Dwójka",
}

STATUS_STYLES = {
    "done": ("Gotowa", theme.GREEN),
    "assigned": ("Do generacji", theme.GOLD),
    "queued": ("W kolejce", theme.INFO),
    "empty": ("Pusta", theme.MUTED),
}


def _strip_pixmap(source: QPixmap | None, border: str, value: str,
                  suit: Suit, empty: bool) -> QPixmap:
    """Miniatura karty do film-stripu z czytelnym badge'em wartość+kolor
    w rogu (np. „A♥") oraz kolorową ramką stanu. Wskaźnik aktywnej karty
    rysuje natywnie QListWidget (zaznaczenie — patrz QSS #filmStrip::item:selected)."""
    out = QPixmap(STRIP_W, STRIP_H)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    body = QRectF(1, 1, STRIP_W - 2, STRIP_H - 2)
    # tło miniatury (obraz albo przygaszony placeholder pustego slotu)
    if source is not None and not source.isNull():
        painter.drawPixmap(0, 0, source)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.SURFACE if hasattr(theme, "SURFACE")
                                else "#1E1710"))
        painter.drawRoundedRect(body, 8, 8)

    # dolny scrim, żeby badge był czytelny na jasnym zdjęciu
    scrim_h = 30
    gradient = QLinearGradient(0, STRIP_H - scrim_h, 0, STRIP_H)
    gradient.setColorAt(0.0, QColor(0, 0, 0, 0))
    gradient.setColorAt(1.0, QColor(0, 0, 0, 165))
    clip = QRectF(1, STRIP_H - scrim_h, STRIP_W - 2, scrim_h - 1)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    painter.drawRoundedRect(clip, 8, 8)

    # badge „wartość+kolor" w lewym-dolnym rogu
    is_red = suit.is_red
    badge_color = QColor(theme.ACCENT_HOVER if is_red else "#EDE4D2")
    font = QFont()
    font.setPointSize(11 if len(value) == 1 else 9)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(0, 0, 0, 190))
    painter.drawText(QRectF(4, STRIP_H - 26, STRIP_W - 6, 22),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     f" {value}{suit.symbol}")
    painter.setPen(badge_color)
    painter.drawText(QRectF(3, STRIP_H - 27, STRIP_W - 6, 22),
                     Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                     f" {value}{suit.symbol}")

    # kolorowa ramka stanu
    painter.setPen(QPen(QColor(border), 2.4 if not empty else 1.4))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(body, 8, 8)
    painter.end()
    return out


class _LegendDot(QWidget):
    def __init__(self, color: str, text: str, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 8px;")
        layout.addWidget(dot)
        label = QLabel(text)
        label.setObjectName("hint")
        layout.addWidget(label)


class WorkspaceView(QWidget):
    strip_card_selected = pyqtSignal(str, str)   # suit_nazwa, value
    card_picked = pyqtSignal(str, str)           # suit_nazwa, value (z klawiatury/siatki)
    regenerate_clicked = pyqtSignal(str, str)    # suit_nazwa, value
    generate_deck_clicked = pyqtSignal()
    unassign_clicked = pyqtSignal(str, str)      # suit_nazwa, value
    strip_photo_dropped = pyqtSignal(str, str)   # klucz "kolor:wartość", ścieżka
    preview_photo_dropped = pyqtSignal(str)      # drop na podgląd = swap na bieżącej karcie
    transform_changed = pyqtSignal(str, str, dict)    # podgląd na żywo (debounce)
    transform_committed = pyqtSignal(str, str, dict)  # puszczenie suwaka → zapis
    history_navigate = pyqtSignal(str, str, int)      # suit, value, kierunek (-1/+1)
    history_set_main = pyqtSignal(str, str)           # ustaw bieżący wariant jako główny

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_suit: Suit = Suit.KIER
        self._current_value: str = "A"
        self._mask_preview_on = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(view_header(
            "Ekran roboczy", "Przypisz zdjęcia do kart i wygeneruj spójną talię"
        ))
        top.addStretch(1)
        self.details_btn = QPushButton("☰  Kolejka i log")
        self.details_btn.setObjectName("ghostBtn")
        self.details_btn.setCheckable(True)
        self.details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        top.addWidget(self.details_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        self.mask_btn = QPushButton("▦  Podgląd maski")
        self.mask_btn.setObjectName("ghostBtn")
        self.mask_btn.setCheckable(True)
        self.mask_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.mask_btn.toggled.connect(self._toggle_mask_preview)
        top.addWidget(self.mask_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        self.generate_btn = QPushButton("⚡  Generuj talię")
        self.generate_btn.setObjectName("generateBtn")
        self.generate_btn.setToolTip("Generuje wszystkie przypisane karty (Ctrl+G)")
        self.generate_btn.setShortcut("Ctrl+G")
        self.generate_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.generate_btn.clicked.connect(self.generate_deck_clicked.emit)
        top.addWidget(self.generate_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- lewa kolumna: pula zdjęć ------------------------------------------
        self.gallery_panel = GalleryPanel()
        splitter.addWidget(self.gallery_panel)

        # --- środek: nagłówek karty + podgląd + film-strip -------------------------
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        card_header = QHBoxLayout()
        self.value_badge = QLabel("—")
        self.value_badge.setObjectName("cardBigValue")
        card_header.addWidget(self.value_badge)

        name_box = QVBoxLayout()
        name_box.setSpacing(0)
        self.card_name = QLabel("Wybierz kartę")
        self.card_name.setObjectName("cardName")
        name_box.addWidget(self.card_name)
        self.card_filename = QLabel("")
        self.card_filename.setObjectName("hint")
        name_box.addWidget(self.card_filename)
        card_header.addLayout(name_box)
        card_header.addStretch(1)

        self.status_pill = QLabel("Pusta")
        self.status_pill.setObjectName("statusPill")
        card_header.addWidget(self.status_pill, alignment=Qt.AlignmentFlag.AlignTop)
        center_layout.addLayout(card_header)

        self.preview = PreviewPane()
        self.preview.setToolTip(
            "Upuść zdjęcie = podmiana na wybranej karcie  ·  "
            "przeciągnij / kółko myszy = kadruj (tryb Hybrydowy)"
        )
        self.preview.photo_dropped.connect(self.preview_photo_dropped.emit)
        self.preview.pan_delta.connect(self._on_preview_pan)
        self.preview.zoom_delta.connect(self._on_preview_zoom)
        self.preview.crop_committed.connect(self._emit_transform_committed)
        center_layout.addWidget(self.preview, stretch=1)

        # --- historia karty: nawigacja po wygenerowanych wariantach --------------
        regen_row = QHBoxLayout()
        self.history_prev_btn = QPushButton("◀")
        self.history_prev_btn.setObjectName("ghostBtn")
        self.history_prev_btn.setToolTip("Poprzedni wariant tej karty")
        self.history_prev_btn.setFixedWidth(38)
        self.history_prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_prev_btn.clicked.connect(
            lambda: self.history_navigate.emit(
                self._current_suit.nazwa, self._current_value, -1)
        )
        regen_row.addWidget(self.history_prev_btn)

        self.history_label = QLabel("brak historii")
        self.history_label.setObjectName("hint")
        self.history_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.history_label.setMinimumWidth(120)
        regen_row.addWidget(self.history_label)

        self.history_next_btn = QPushButton("▶")
        self.history_next_btn.setObjectName("ghostBtn")
        self.history_next_btn.setToolTip("Następny wariant tej karty")
        self.history_next_btn.setFixedWidth(38)
        self.history_next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.history_next_btn.clicked.connect(
            lambda: self.history_navigate.emit(
                self._current_suit.nazwa, self._current_value, +1)
        )
        regen_row.addWidget(self.history_next_btn)

        self.set_main_btn = QPushButton("★ Ustaw jako główną")
        self.set_main_btn.setObjectName("ghostBtn")
        self.set_main_btn.setToolTip("Użyj pokazanego wariantu jako karty w talii/eksporcie")
        self.set_main_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.set_main_btn.clicked.connect(
            lambda: self.history_set_main.emit(
                self._current_suit.nazwa, self._current_value)
        )
        regen_row.addWidget(self.set_main_btn)

        regen_row.addStretch(1)
        self.regen_btn = QPushButton("⚡  Wygeneruj")
        self.regen_btn.setObjectName("outlineBtn")
        self.regen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.regen_btn.clicked.connect(
            lambda: self.regenerate_clicked.emit(
                self._current_suit.nazwa, self._current_value
            )
        )
        regen_row.addWidget(self.regen_btn)
        center_layout.addLayout(regen_row)

        strip_caption = QHBoxLayout()
        strip_label = QLabel("TALIA — przewiń, aby wybrać · upuść zdjęcie na kartę")
        strip_label.setObjectName("sideCaption")
        strip_caption.addWidget(strip_label)
        strip_caption.addStretch(1)
        for key in ("done", "assigned", "queued", "empty"):
            text, color = STATUS_STYLES[key]
            strip_caption.addWidget(_LegendDot(color, text))
        center_layout.addLayout(strip_caption)

        self.strip = _StripList()
        self.strip.setObjectName("filmStrip")
        self.strip.setViewMode(QListWidget.ViewMode.IconMode)
        self.strip.setFlow(QListWidget.Flow.LeftToRight)
        self.strip.setWrapping(False)
        self.strip.setIconSize(QSize(STRIP_W, STRIP_H))
        self.strip.setFixedHeight(STRIP_H + 40)
        self.strip.setHorizontalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.strip.setSpacing(6)
        # IconMode włącza wewnętrzne DnD i przesuwanie elementów — wymuszamy
        # tylko przyjmowanie zrzutów zdjęć, bez rearanżacji miniatur.
        self.strip.setMovement(QListWidget.Movement.Static)
        self.strip.setDragDropMode(QListWidget.DragDropMode.DropOnly)
        self.strip.viewport().setAcceptDrops(True)
        self.strip.itemClicked.connect(self._on_strip_clicked)
        self.strip.photo_dropped.connect(self.strip_photo_dropped.emit)
        center_layout.addWidget(self.strip)

        splitter.addWidget(center)

        # --- prawa kolumna: właściwości + kadrowanie + generacja --------------------
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right = QWidget()
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(16, 14, 16, 14)
        right_layout.setSpacing(8)

        props_title = QLabel("Właściwości karty")
        props_title.setObjectName("panelTitle")
        right_layout.addWidget(props_title)

        value_caption = QLabel("WARTOŚĆ")
        value_caption.setObjectName("sideCaption")
        right_layout.addWidget(value_caption)
        self._value_group = QButtonGroup(self)
        self._value_group.setExclusive(True)
        self._value_buttons: dict[str, QPushButton] = {}
        self.value_grid = QGridLayout()
        self.value_grid.setSpacing(6)
        right_layout.addLayout(self.value_grid)

        right_layout.addSpacing(10)
        suit_caption = QLabel("KOLOR / ZNAK")
        suit_caption.setObjectName("sideCaption")
        right_layout.addWidget(suit_caption)
        suit_grid = QGridLayout()
        suit_grid.setSpacing(6)
        self._suit_buttons: dict[Suit, QPushButton] = {}
        for i, suit in enumerate(Suit):
            btn = QPushButton(f"{suit.symbol}  {suit.nazwa.capitalize()}")
            btn.setObjectName("suitPickBtn")
            btn.setProperty("red", suit.is_red)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, s=suit: self.card_picked.emit(
                s.nazwa, self._current_value
            ))
            suit_grid.addWidget(btn, i // 2, i % 2)
            self._suit_buttons[suit] = btn
        right_layout.addLayout(suit_grid)

        right_layout.addSpacing(10)
        assigned_caption = QLabel("PRZYPISANE ZDJĘCIE")
        assigned_caption.setObjectName("sideCaption")
        right_layout.addWidget(assigned_caption)
        assigned_row = QWidget()
        assigned_row.setObjectName("well")
        assigned_layout = QHBoxLayout(assigned_row)
        assigned_layout.setContentsMargins(8, 6, 8, 6)
        self.assigned_thumb = QLabel()
        self.assigned_thumb.setFixedSize(36, 36)
        assigned_layout.addWidget(self.assigned_thumb)
        self.assigned_name = QLabel("— nieprzypisane —")
        self.assigned_name.setObjectName("propValue")
        assigned_layout.addWidget(self.assigned_name, stretch=1)
        self.unassign_btn = QPushButton("🗑")
        self.unassign_btn.setObjectName("ghostBtn")
        self.unassign_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.unassign_btn.clicked.connect(
            lambda: self.unassign_clicked.emit(
                self._current_suit.nazwa, self._current_value
            )
        )
        assigned_layout.addWidget(self.unassign_btn)
        right_layout.addWidget(assigned_row)

        # --- kadrowanie zdjęcia (jedyne sterowanie pozycją — bez myszki) ----------
        right_layout.addSpacing(10)
        crop_caption = QLabel("KADROWANIE ZDJĘCIA")
        crop_caption.setObjectName("sideCaption")
        right_layout.addWidget(crop_caption)

        self._transform_debounce = QTimer(self)
        self._transform_debounce.setSingleShot(True)
        self._transform_debounce.setInterval(120)
        self._transform_debounce.timeout.connect(self._emit_transform_changed)

        crop_box = QWidget()
        crop_box.setObjectName("well")
        crop_layout = QGridLayout(crop_box)
        crop_layout.setContentsMargins(10, 8, 10, 8)
        crop_layout.setHorizontalSpacing(8)
        crop_layout.setVerticalSpacing(4)

        self.zoom_slider = self._make_slider(50, 250, 100)
        self.dx_slider = self._make_slider(-100, 100, 0)
        self.dy_slider = self._make_slider(-100, 100, 0)
        self._slider_spins: dict[QSlider, QSpinBox] = {}
        for row, (label_text, slider, suffix) in enumerate((
            ("Zoom", self.zoom_slider, "%"),
            ("Pozycja X", self.dx_slider, ""),
            ("Pozycja Y", self.dy_slider, ""),
        )):
            label = QLabel(label_text)
            label.setObjectName("propKey")
            crop_layout.addWidget(label, row, 0)
            crop_layout.addWidget(slider, row, 1)
            spin = self._make_spin(slider, suffix)
            crop_layout.addWidget(spin, row, 2)
            self._slider_spins[slider] = spin
        reset_crop = QPushButton("↺  Wyśrodkuj kadr")
        reset_crop.setObjectName("ghostBtn")
        reset_crop.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_crop.clicked.connect(self._reset_transform)
        crop_layout.addWidget(reset_crop, 3, 0, 1, 3)
        right_layout.addWidget(crop_box)

        self.crop_hint = QLabel("Kadr działa tylko w trybie Hybrydowym.")
        self.crop_hint.setObjectName("hint")
        self.crop_hint.setWordWrap(True)
        self.crop_hint.hide()
        right_layout.addWidget(self.crop_hint)

        self._hybrid_mode = True
        self._current_has_photo = False
        self._refresh_slider_labels()
        self.set_transform_enabled(False)

        right_layout.addSpacing(12)
        right_layout.addWidget(self._separator())
        right_layout.addSpacing(4)

        # --- panel generacji (dawna zakładka „Generowanie") -------------------------
        self.gen_panel = GenerationPanel()
        self.gen_panel.generate_btn = self.generate_btn
        self.gen_panel.preview = self.preview
        right_layout.addWidget(self.gen_panel)

        right_layout.addSpacing(10)
        adv_caption = QLabel("TŁO KART (WYBÓR)")
        adv_caption.setObjectName("sideCaption")
        right_layout.addWidget(adv_caption)
        # Ekran roboczy tylko WYBIERA istniejące tła — bez generowania AI
        self.template_picker = TemplatePicker(show_generate=False)
        right_layout.addWidget(self.template_picker)

        right_layout.addStretch(1)
        right_scroll.setWidget(right)
        splitter.addWidget(right_scroll)

        splitter.setSizes([290, 700, 340])
        layout.addWidget(splitter, stretch=1)

        # --- wysuwany dolny panel: kolejka + log (z GenerationPanel) ---------------
        self.gen_panel.details.setVisible(False)
        self.gen_panel.details.setFixedHeight(190)
        self.details_btn.toggled.connect(self.gen_panel.details.setVisible)
        layout.addWidget(self.gen_panel.details)

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"background: {theme.BORDER}; max-height: 1px; border: none;")
        return line

    # --- suwaki kadrowania ---------------------------------------------------------
    def _make_slider(self, minimum: int, maximum: int, value: int) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(value)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        slider.valueChanged.connect(self._on_slider_moved)
        slider.sliderReleased.connect(self._emit_transform_committed)
        return slider

    def _make_spin(self, slider: QSlider, suffix: str = "") -> QSpinBox:
        """Edytowalne pole liczbowe zsynchronizowane z suwakiem (dwukierunkowo)."""
        spin = QSpinBox()
        spin.setRange(slider.minimum(), slider.maximum())
        spin.setValue(slider.value())
        spin.setFixedWidth(64)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if suffix:
            spin.setSuffix(suffix)
        # edycja pola → suwak (który odświeży podgląd i pole zwrotnie, bez pętli)
        spin.valueChanged.connect(lambda v, s=slider: s.setValue(v))
        spin.editingFinished.connect(self._emit_transform_committed)
        return spin

    def current_transform(self) -> dict:
        return {
            "zoom": self.zoom_slider.value() / 100.0,
            "dx": self.dx_slider.value() / 100.0,
            "dy": self.dy_slider.value() / 100.0,
        }

    def set_transform(self, transform: dict | None) -> None:
        """Ustawia suwaki bez emitowania sygnałów (wybór karty / wczytanie)."""
        t = {**DEFAULT_TRANSFORM, **(transform or {})}
        for slider, value in (
            (self.zoom_slider, round(t["zoom"] * 100)),
            (self.dx_slider, round(t["dx"] * 100)),
            (self.dy_slider, round(t["dy"] * 100)),
        ):
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self._refresh_slider_labels()

    def set_transform_enabled(self, enabled: bool) -> None:
        for slider in (self.zoom_slider, self.dx_slider, self.dy_slider):
            slider.setEnabled(enabled)
            self._slider_spins[slider].setEnabled(enabled)

    def set_hybrid_mode(self, hybrid: bool) -> None:
        """Kadr ma sens tylko w trybie Hybrydowym (Pełne AI ignoruje transform)."""
        self._hybrid_mode = hybrid
        self._update_crop_enabled()

    def _update_crop_enabled(self) -> None:
        enabled = self._hybrid_mode and self._current_has_photo
        self.set_transform_enabled(enabled)
        self.preview.set_crop_active(enabled)
        self.crop_hint.setVisible(self._current_has_photo and not self._hybrid_mode)

    def _on_preview_pan(self, udx: int, udy: int) -> None:
        """Przeciąganie myszą po podglądzie → Pozycja X/Y (suwaki + live podgląd)."""
        if not (self._hybrid_mode and self._current_has_photo):
            return
        self.dx_slider.setValue(self.dx_slider.value() + udx)
        self.dy_slider.setValue(self.dy_slider.value() + udy)

    def _on_preview_zoom(self, notches: int) -> None:
        """Kółko myszy po podglądzie → Zoom."""
        if not (self._hybrid_mode and self._current_has_photo):
            return
        self.zoom_slider.setValue(self.zoom_slider.value() + notches * 4)

    def set_history(self, index: int, total: int) -> None:
        """Aktualizuje nawigator historii wariantów bieżącej karty.

        index — pozycja pokazywanego wariantu (0-based), total — liczba wariantów.
        """
        if total <= 0:
            self.history_label.setText("brak historii")
            self.history_prev_btn.setEnabled(False)
            self.history_next_btn.setEnabled(False)
            self.set_main_btn.setEnabled(False)
            return
        self.history_label.setText(f"wariant {index + 1} z {total}")
        self.history_prev_btn.setEnabled(index > 0)
        self.history_next_btn.setEnabled(index < total - 1)
        self.set_main_btn.setEnabled(True)

    def _refresh_slider_labels(self) -> None:
        """Synchronizuje pola liczbowe z wartościami suwaków (bez emitowania)."""
        for slider, spin in self._slider_spins.items():
            if spin.value() != slider.value():
                spin.blockSignals(True)
                spin.setValue(slider.value())
                spin.blockSignals(False)

    def _on_slider_moved(self, _value: int) -> None:
        self._refresh_slider_labels()
        self._transform_debounce.start()

    def _emit_transform_changed(self) -> None:
        self.transform_changed.emit(
            self._current_suit.nazwa, self._current_value,
            self.current_transform(),
        )

    def _emit_transform_committed(self) -> None:
        self.transform_committed.emit(
            self._current_suit.nazwa, self._current_value,
            self.current_transform(),
        )

    def _reset_transform(self) -> None:
        self.set_transform(None)
        self._emit_transform_changed()
        self._emit_transform_committed()

    # --- klawiatura wartości (budowana raz na zestaw wartości talii) --------------
    def set_available_values(self, values: list[str]) -> None:
        while self.value_grid.count():
            item = self.value_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._value_buttons.clear()
        columns = 6
        for i, value in enumerate(values):
            btn = QPushButton(value)
            btn.setObjectName("valueKeyBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._value_group.addButton(btn)
            btn.clicked.connect(lambda _=False, v=value: self.card_picked.emit(
                self._current_suit.nazwa, v
            ))
            self.value_grid.addWidget(btn, i // columns, i % columns)
            self._value_buttons[value] = btn

    # --- właściwości karty --------------------------------------------------------
    def show_card(self, slot: CardSlot) -> None:
        self._current_suit = slot.suit
        self._current_value = slot.value

        color = theme.ACCENT_HOVER if slot.suit.is_red else theme.CREAM
        self.value_badge.setText(f"{slot.value}{slot.suit.symbol}")
        self.value_badge.setStyleSheet(f"color: {color};")
        name = CARD_NAMES.get(slot.value, slot.value)
        self.card_name.setText(f"{name} {slot.suit.nazwa.capitalize()}")
        self.card_filename.setText(
            (slot.generated_path or slot.photo_path).name
            if (slot.generated_path or slot.photo_path) else "brak przypisanego zdjęcia"
        )

        if slot.generated_path is not None:
            status_key = "done"
        elif slot.property("state") == "queued":
            status_key = "queued"
        elif slot.photo_path is not None:
            status_key = "assigned"
        else:
            status_key = "empty"
        text, color = STATUS_STYLES[status_key]
        self.status_pill.setText(text)
        self.status_pill.setStyleSheet(
            f"background: rgba(0,0,0,0.25); color: {color}; "
            f"border: 1px solid {color}; border-radius: 9px; padding: 2px 10px;"
        )

        if slot.value in self._value_buttons:
            self._value_buttons[slot.value].setChecked(True)
        for suit, btn in self._suit_buttons.items():
            btn.setChecked(suit is slot.suit)

        if slot.photo_path is not None:
            self.assigned_thumb.setPixmap(cover_pixmap(slot.photo_path, 36, 36, radius=6))
            self.assigned_name.setText(slot.photo_path.name)
            self.unassign_btn.setEnabled(True)
            self._current_has_photo = True
        else:
            self.assigned_thumb.clear()
            self.assigned_name.setText("— nieprzypisane —")
            self.unassign_btn.setEnabled(False)
            self._current_has_photo = False
        self._update_crop_enabled()
        self._sync_strip_selection()

        if self._mask_preview_on:
            self._apply_mask_overlay(slot.suit)

    def _sync_strip_selection(self) -> None:
        """Zaznacza w film-stripie miniaturę bieżącej karty (wskaźnik aktywnej
        karty — natywne zaznaczenie QListWidget, bez przebudowy ikon)."""
        key = f"{self._current_suit.nazwa}:{self._current_value}"
        for i in range(self.strip.count()):
            item = self.strip.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == key:
                self.strip.blockSignals(True)
                self.strip.setCurrentItem(item)
                self.strip.blockSignals(False)
                self.strip.scrollToItem(item)
                break

    # --- podgląd maski -------------------------------------------------------------
    def _toggle_mask_preview(self, on: bool) -> None:
        self._mask_preview_on = on
        if on:
            self._apply_mask_overlay(self._current_suit)
        else:
            self.preview.canvas.set_mask_boxes(None, (1, 1))

    def _apply_mask_overlay(self, suit: Suit) -> None:
        try:
            masks = get_masks(suit.template_path)
            with Image.open(suit.template_path) as img:
                size = img.size
            boxes = [masks.center.getbbox() or (0, 0, 0, 0), masks.tl_box, masks.br_box]
            self.preview.canvas.set_mask_boxes(boxes, size)
        except (FileNotFoundError, OSError):
            self.preview.canvas.set_mask_boxes(None, (1, 1))

    # --- film-strip -----------------------------------------------------------------
    def refresh_strip(self, values: list[str], grids: dict[Suit, CardGrid]) -> None:
        selected = self.strip.currentItem()
        selected_key = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self.strip.clear()
        for suit in Suit:
            grid = grids[suit]
            for value in values:
                slot = grid.slots.get(value)
                if slot is None:
                    continue
                if slot.generated_path is not None:
                    source_path, border = slot.generated_path, theme.GREEN
                elif slot.property("state") == "queued":
                    source_path, border = slot.photo_path, theme.INFO
                elif slot.photo_path is not None:
                    source_path, border = slot.photo_path, theme.GOLD
                else:
                    source_path, border = None, theme.BORDER
                base = (cover_pixmap(source_path, STRIP_W, STRIP_H, radius=8)
                        if source_path is not None else None)
                icon = _strip_pixmap(base, border, value, suit,
                                     empty=source_path is None)
                # tekst wypalony w miniaturze (badge) — pozycja bez podpisu
                item = QListWidgetItem(QIcon(icon), "")
                item.setData(Qt.ItemDataRole.UserRole, f"{suit.nazwa}:{value}")
                name = CARD_NAMES.get(value, value)
                item.setToolTip(f"{name} {suit.nazwa}")
                self.strip.addItem(item)
                if selected_key and item.data(Qt.ItemDataRole.UserRole) == selected_key:
                    self.strip.setCurrentItem(item)

    def _on_strip_clicked(self, item: QListWidgetItem) -> None:
        suit_nazwa, value = item.data(Qt.ItemDataRole.UserRole).split(":", 1)
        self.strip_card_selected.emit(suit_nazwa, value)
