"""Widok Ekran roboczy: pula zdjęć, środek z siatką talii 4×13 (strona
domyślna) i szczegółem karty (podgląd + kadrowanie + historia wariantów),
właściwości karty (klawiatura wartości + siatka kolorów), panel generacji
oraz wysuwany drawer z kolejką i logiem API."""
from __future__ import annotations

from PIL import Image
from PyQt6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer, pyqtSignal,
)
from PyQt6.QtWidgets import (
    QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QSlider, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout,
    QWidget,
)

from app.core.compositor import DEFAULT_TRANSFORM
from app.core.masks import get_masks
from app.core.models import Suit
from app.gui import theme
from app.gui.card_grid import CardGrid, CardSlot
from app.gui.deck_grid_panel import DeckGridPanel
from app.gui.params_panel import PreviewPane, TemplatePicker
from app.gui.photo_gallery import GalleryPanel
from app.gui.views import view_header
from app.gui.views.generation_panel import GenerationPanel
from app.gui.widgets import cover_pixmap

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


class BottomDrawer(QWidget):
    """Wysuwany od dołu panel nakładany NA widok (nie zmienia layoutu pod
    spodem): kolejka + log API. Animacja geometrii ≤ 120 ms."""

    HEIGHT = 230

    def __init__(self, content: QWidget, parent: QWidget):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(content)
        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(120)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hide()

    def _geometries(self) -> tuple[QRect, QRect]:
        parent = self.parentWidget()
        open_rect = QRect(0, parent.height() - self.HEIGHT,
                          parent.width(), self.HEIGHT)
        closed_rect = QRect(0, parent.height(), parent.width(), self.HEIGHT)
        return open_rect, closed_rect

    def set_open(self, open_: bool) -> None:
        open_rect, closed_rect = self._geometries()
        self._anim.stop()
        if open_:
            self.setGeometry(closed_rect)
            self.show()
            self.raise_()
            self._anim.setStartValue(closed_rect)
            self._anim.setEndValue(open_rect)
            try:
                self._anim.finished.disconnect()
            except TypeError:
                pass
        else:
            self._anim.setStartValue(self.geometry())
            self._anim.setEndValue(closed_rect)
            try:
                self._anim.finished.disconnect()
            except TypeError:
                pass
            self._anim.finished.connect(self.hide)
        self._anim.start()

    def reposition(self) -> None:
        """Po zmianie rozmiaru rodzica (resizeEvent widoku)."""
        if self.isVisible():
            open_rect, _ = self._geometries()
            self.setGeometry(open_rect)


class WorkspaceView(QWidget):
    card_picked = pyqtSignal(str, str)           # suit_nazwa, value (z klawiatury/siatki)
    regenerate_clicked = pyqtSignal(str, str)    # suit_nazwa, value
    generate_deck_clicked = pyqtSignal()
    unassign_clicked = pyqtSignal(str, str)      # suit_nazwa, value
    grid_photo_dropped = pyqtSignal(str, str)    # klucz "kolor:wartość", ścieżka
    preview_photo_dropped = pyqtSignal(str)      # drop na podgląd = swap na bieżącej karcie
    transform_changed = pyqtSignal(str, str, dict)    # podgląd na żywo (debounce)
    transform_committed = pyqtSignal(str, str, dict)  # puszczenie suwaka → zapis
    history_navigate = pyqtSignal(str, str, int)      # suit, value, kierunek (-1/+1)
    history_set_main = pyqtSignal(str, str)           # ustaw bieżący wariant jako główny
    restamp_clicked = pyqtSignal()                    # przestempluj narożniki (bez API)
    auto_assign_clicked = pyqtSignal()                # auto-przydział zdjęć AI

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
        self.auto_assign_btn = QPushButton("🪄  Auto-przydział AI")
        self.auto_assign_btn.setObjectName("ghostBtn")
        self.auto_assign_btn.setToolTip(
            "AI analizuje zdjęcia z folderu zdjecia/ (liczba osób, motywy, "
            "jakość)\ni proponuje przypisanie zdjęć do kart — z podglądem "
            "przed zatwierdzeniem"
        )
        self.auto_assign_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_assign_btn.clicked.connect(self.auto_assign_clicked.emit)
        top.addWidget(self.auto_assign_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        self.restamp_btn = QPushButton("♻  Przestempluj narożniki")
        self.restamp_btn.setObjectName("ghostBtn")
        self.restamp_btn.setToolTip(
            "Nanosi wartości i symbole narożne na wszystkie wygenerowane "
            "karty wg presetu „wartości narożne” — bez wywołań API"
        )
        self.restamp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.restamp_btn.clicked.connect(self.restamp_clicked.emit)
        top.addWidget(self.restamp_btn, alignment=Qt.AlignmentFlag.AlignBottom)
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

        # --- środek: QStackedWidget — strona 0: siatka talii 4×13 (domyślna),
        #     strona 1: szczegół karty (nagłówek + podgląd + historia) ---------
        self.center_stack = QStackedWidget()

        # strona 0: siatka talii z filtrem (druga instancja panelu — sloty
        # nie mogą być współdzielone z widokiem Talie; stan synchronizuje
        # MainWindow przez sync_deck)
        self.deck_panel = DeckGridPanel(
            droppable=True,
            hint="klik = wybierz kartę   •   upuść zdjęcie na slot = przypisz"
                 "   •   Spacja = szybki podgląd",
        )
        self.deck_panel.slot_clicked.connect(
            lambda slot: self.card_picked.emit(slot.suit.nazwa, slot.value))
        self.deck_panel.photo_dropped.connect(
            lambda slot, path: self.grid_photo_dropped.emit(
                f"{slot.suit.nazwa}:{slot.value}", path))
        self.center_stack.addWidget(self.deck_panel)

        # strona 1: szczegół wybranej karty
        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(8)

        card_header = QHBoxLayout()
        self.back_to_deck_btn = QPushButton("▦  Talia")
        self.back_to_deck_btn.setObjectName("ghostBtn")
        self.back_to_deck_btn.setToolTip("Wróć do siatki całej talii")
        self.back_to_deck_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_to_deck_btn.clicked.connect(
            lambda: self.center_stack.setCurrentIndex(0))
        card_header.addWidget(self.back_to_deck_btn,
                              alignment=Qt.AlignmentFlag.AlignTop)
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

        self.center_stack.addWidget(center)
        splitter.addWidget(self.center_stack)

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

        # --- wysuwany dolny drawer: kolejka + log (nakładka NA widok — layout
        #     pod spodem się nie przesuwa) --------------------------------------
        self.drawer = BottomDrawer(self.gen_panel.details, self)
        self.details_btn.toggled.connect(self.drawer.set_open)

    def resizeEvent(self, event):  # noqa: N802 (API Qt)
        super().resizeEvent(event)
        self.drawer.reposition()

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
        # wybór karty (siatka/klawiatura/drop) = wejście w stronę szczegółu
        self.center_stack.setCurrentIndex(1)

        if self._mask_preview_on:
            self._apply_mask_overlay(slot.suit)

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

    # --- siatka talii (strona 0 środka) ----------------------------------------
    def sync_deck(self, values: list[str], grids: dict[Suit, CardGrid]) -> None:
        """Lustro stanu głównych siatek (instancje widoku Talie — self.grids
        w MainWindow) w panelu talii Ekranu roboczego; wołane po każdej
        zmianie przypisań / generacji (patrz MainWindow._refresh_overview)."""
        for suit, grid in grids.items():
            mirror = self.deck_panel.grids[suit]
            for value, src in grid.slots.items():
                dst = mirror.slots.get(value)
                if dst is None:
                    continue
                state = src.property("state")
                if (dst.photo_path, dst.generated_path, dst.property("state")) \
                        == (src.photo_path, src.generated_path, state):
                    continue
                dst.set_photo(src.photo_path)
                if src.generated_path is not None:
                    dst.set_generated(src.generated_path)
                if state == "queued":
                    dst.set_queued(True)
                elif state == "error":
                    dst.set_error(src.toolTip())
        self.deck_panel.refresh_empty_state()
