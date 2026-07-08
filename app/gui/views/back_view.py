"""Widok „Style": cztery niezależne biblioteki presetów (postać, styl tła,
tła przodu, rewers). Każda ma wybór presetu + pełny CRUD (nowy/duplikuj/zmień
nazwę/zapisz/wczytaj/usuń), edytor promptu i podgląd. Wybór presetu teł przodu /
rewersu od razu staje się aktywnym wyglądem talii (sygnał preset_applied)."""
from __future__ import annotations

import zipfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from app import config
from app.core import prompts, style_store
from app.core.models import Suit
from app.gui.animations import Spinner
from app.gui.views import view_header
from app.gui.widgets import (
    SegmentedControl, cover_pixmap, pil_to_pixmap, show_toast,
)

BACK_W, BACK_H = 200, 279

# Przyciski CRUD wspólne dla każdej biblioteki presetów.
_CRUD_BUTTONS = (
    ("＋ Nowy", "Utwórz nowy preset (kopia domyślnych)"),
    ("⧉ Duplikuj", "Skopiuj bieżący preset"),
    ("✎ Zmień nazwę", "Zmień nazwę bieżącego presetu"),
    ("💾 Zapisz", "Zapisz bieżący preset do pliku (.zip)"),
    ("⬇ Wczytaj", "Wczytaj preset z pliku (.zip)"),
    ("🗑 Usuń", "Usuń bieżący preset"),
)


class BackView(QWidget):
    # {"mode": "t2i"|"i2i", "orientation": "portrait"|"landscape",
    #  "preset": str, "custom": str, "source_photo": str|None}
    generate_back_clicked = pyqtSignal(dict)
    # {"suit": Suit, "prompt": str, "count": int}
    generate_front_clicked = pyqtSignal(dict)
    character_changed = pyqtSignal()   # edycja dowolnego promptu → zapis + podgląd
    style_slot_changed = pyqtSignal()  # zmiana struktury presetów (nowy/usuń/...)
    preset_applied = pyqtSignal(str)   # aktywowano preset danej kategorii (cat)
    # {"photo": str|None} — generuj podgląd przykładowej karty w bieżącym stylu
    generate_sample_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_photo: Path | None = None
        self._sample_photo: Path | None = None
        self._cat_combos: dict[str, QComboBox] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(10)

        outer.addWidget(view_header(
            "Style — postać, tło, tła przodu i rewers",
            "Cztery biblioteki presetów z pełnym zapisem na dysku — wybór presetu "
            "teł/rewersu od razu ustawia wygląd całej talii",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(self._build_character_panel())
        layout.addWidget(self._build_template_panel())
        layout.addWidget(self._build_front_panel())
        layout.addWidget(self._build_back_panel())
        layout.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll, stretch=1)

        self.refresh_back_preview()
        self.refresh_front_preview()

    # ================= wspólny nagłówek biblioteki presetów ===================
    def _library_header(self, cat: str) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        cap = QLabel(f"PRESET — {style_store.CATEGORY_LABELS[cat].upper()}")
        cap.setObjectName("sideCaption")
        v.addWidget(cap)

        combo = QComboBox()
        combo.setCursor(Qt.CursorShape.PointingHandCursor)
        combo.currentIndexChanged.connect(
            lambda _i, c=cat: self._on_preset_selected(c)
        )
        self._cat_combos[cat] = combo
        v.addWidget(combo)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        handlers = (
            self._new_preset, self._duplicate_preset, self._rename_preset,
            self._export_preset, self._import_preset, self._delete_preset,
        )
        for (text, tip), handler in zip(_CRUD_BUTTONS, handlers):
            btn = QPushButton(text)
            btn.setObjectName("ghostBtn")
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, c=cat, h=handler: h(c))
            actions.addWidget(btn)
        actions.addStretch(1)
        v.addLayout(actions)

        self._refresh_combo(cat)
        return box

    def _refresh_combo(self, cat: str) -> None:
        combo = self._cat_combos[cat]
        combo.blockSignals(True)
        combo.clear()
        for name in style_store.presets(cat):
            combo.addItem(name, name)
        idx = combo.findData(style_store.active(cat))
        if idx >= 0:
            combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    # --- akcje CRUD (współdzielone przez wszystkie kategorie) ------------------
    def _on_preset_selected(self, cat: str) -> None:
        name = self._cat_combos[cat].currentData()
        if not name or name == style_store.active(cat):
            return
        style_store.set_active(cat, name)
        self._activate(cat)

    def _new_preset(self, cat: str) -> None:
        label = style_store.CATEGORY_LABELS[cat]
        name, ok = QInputDialog.getText(
            self, "Nowy preset", f"Nazwa nowego presetu ({label}):")
        if not ok:
            return
        style_store.create(cat, name.strip())
        self._after_structure_change(cat)

    def _duplicate_preset(self, cat: str) -> None:
        style_store.duplicate(cat)
        self._after_structure_change(cat)

    def _rename_preset(self, cat: str) -> None:
        current = style_store.active(cat)
        name, ok = QInputDialog.getText(
            self, "Zmień nazwę presetu", "Nowa nazwa:", text=current)
        if not ok or not name.strip():
            return
        style_store.rename(cat, current, name.strip())
        self._after_structure_change(cat)

    def _delete_preset(self, cat: str) -> None:
        if len(style_store.presets(cat)) <= 1:
            show_toast(self, "Nie można usunąć ostatniego presetu", "info")
            return
        current = style_store.active(cat)
        answer = QMessageBox.question(
            self, "Usunąć preset?",
            f"Preset „{current}” ({style_store.CATEGORY_LABELS[cat]}) zostanie "
            "trwale usunięty (wraz z plikami na dysku).",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        style_store.delete(cat, current)
        self._after_structure_change(cat)

    def _export_preset(self, cat: str) -> None:
        name = style_store.active(cat)
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Zapisz preset do pliku",
            str(config.ROOT / f"{cat}_{safe}.zip"), "Preset (*.zip)",
        )
        if not path:
            return
        try:
            style_store.export_preset(cat, path)
            show_toast(self, "Zapisano preset do pliku", "ok")
        except OSError as exc:
            show_toast(self, f"Błąd zapisu: {exc}", "error")

    def _import_preset(self, cat: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Wczytaj preset z pliku", str(config.ROOT), "Preset (*.zip)",
        )
        if not path:
            return
        try:
            style_store.import_preset(cat, path)
        except (OSError, zipfile.BadZipFile) as exc:
            show_toast(self, f"Nie wczytano pliku: {exc}", "error")
            return
        self._after_structure_change(cat)
        show_toast(self, "Wczytano preset", "ok")

    def _activate(self, cat: str) -> None:
        """Aktywny preset kategorii się zmienił → przeładuj edytory i zastosuj."""
        self._reload_editors(cat)
        self.preset_applied.emit(cat)
        self.character_changed.emit()   # podgląd promptu + zapis projektu

    def _after_structure_change(self, cat: str) -> None:
        """Po nowym/usuń/zmianie nazwy/imporcie — odśwież combo i aktywuj."""
        self._refresh_combo(cat)
        self._reload_editors(cat)
        self.preset_applied.emit(cat)
        self.style_slot_changed.emit()

    def _reload_editors(self, cat: str) -> None:
        if cat == "postac":
            self._reload_character_edit()
            self.refresh_style_preview()
        elif cat == "styl_tla":
            self._reload_template_edit()
        elif cat == "tla_przodu":
            self._reload_front_prompt()
            self.refresh_front_preview()
        elif cat == "rewers":
            self._reload_back_opis()
            self.refresh_back_preview()

    def reload_style_slot(self) -> None:
        """Pełne odświeżenie wszystkich bibliotek (np. po wczytaniu projektu)."""
        for cat in style_store.CATEGORIES:
            self._refresh_combo(cat)
            self._reload_editors(cat)

    # ======================= SEKCJA: STYL POSTACI =============================
    def _build_character_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)

        self.char_caption = QLabel("👤  STYL POSTACI (POP-OUT)")
        self.char_caption.setObjectName("sectionTitle")
        pl.addWidget(self.char_caption)
        pl.addWidget(self._library_header("postac"))

        char_hint = QLabel("Opis stylizacji postaci ze zdjęcia (technika, paleta, "
                           "efekt pop-out). Zapisuje się automatycznie w wybranym "
                           "presecie.")
        char_hint.setObjectName("hint")
        char_hint.setWordWrap(True)
        pl.addWidget(char_hint)

        row = QHBoxLayout()
        row.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(6)
        self._char_debounce = QTimer(self)
        self._char_debounce.setSingleShot(True)
        self._char_debounce.setInterval(400)
        self._char_debounce.timeout.connect(self._apply_character_style)

        self.character_edit = QPlainTextEdit()
        self.character_edit.setObjectName("styleEdit")
        self.character_edit.setPlaceholderText(
            "Opisz styl postaci (technika, paleta, nastrój, efekt pop-out)…"
        )
        self.character_edit.setPlainText(style_store.character_style())
        self.character_edit.textChanged.connect(self._char_debounce.start)
        left.addWidget(self.character_edit, stretch=1)

        reset_char = QPushButton("↺  Przywróć domyślny styl postaci")
        reset_char.setObjectName("ghostBtn")
        reset_char.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_char.clicked.connect(self._reset_character_style)
        left.addWidget(reset_char)
        row.addLayout(left, stretch=2)

        right = QVBoxLayout()
        right.setSpacing(6)
        prev_cap = QLabel("PODGLĄD STYLU (przykładowa karta)")
        prev_cap.setObjectName("sideCaption")
        right.addWidget(prev_cap)
        self.style_preview = QLabel()
        self.style_preview.setObjectName("preview")
        self.style_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.style_preview.setFixedSize(126, 176)
        self.style_preview.setWordWrap(True)
        right.addWidget(self.style_preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.sample_photo_row = QWidget()
        self.sample_photo_row.setObjectName("well")
        sp_layout = QHBoxLayout(self.sample_photo_row)
        sp_layout.setContentsMargins(8, 6, 8, 6)
        self.sample_thumb = QLabel()
        self.sample_thumb.setFixedSize(30, 30)
        sp_layout.addWidget(self.sample_thumb)
        self.sample_name = QLabel("— zdjęcie auto —")
        self.sample_name.setObjectName("propValue")
        self.sample_name.setWordWrap(True)
        sp_layout.addWidget(self.sample_name, stretch=1)
        pick_sample = QPushButton("Wybierz…")
        pick_sample.setObjectName("ghostBtn")
        pick_sample.setCursor(Qt.CursorShape.PointingHandCursor)
        pick_sample.clicked.connect(self._pick_sample_photo)
        sp_layout.addWidget(pick_sample)
        right.addWidget(self.sample_photo_row)

        sample_gen_row = QHBoxLayout()
        self.sample_spinner = Spinner(18)
        self.sample_spinner.hide()
        sample_gen_row.addWidget(self.sample_spinner)
        self.sample_btn = QPushButton("🎬  Wygeneruj podgląd")
        self.sample_btn.setObjectName("outlineBtn")
        self.sample_btn.setToolTip("Generuje jedną przykładową kartę w bieżącym "
                                   "stylu (nie zapisuje do talii)")
        self.sample_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sample_btn.clicked.connect(self._emit_generate_sample)
        sample_gen_row.addWidget(self.sample_btn, stretch=1)
        right.addLayout(sample_gen_row)
        right.addStretch(1)
        row.addLayout(right, stretch=1)

        pl.addLayout(row)
        self._update_character_caption()
        self.refresh_style_preview()
        return panel

    def _pick_sample_photo(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(config.IMAGE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Zdjęcie do podglądu przykładowej karty",
            str(config.ZDJECIA_DIR), f"Obrazy ({exts})",
        )
        if path:
            self._set_sample_photo(Path(path))

    def _set_sample_photo(self, path: Path | None) -> None:
        self._sample_photo = path if (path and path.exists()) else None
        if self._sample_photo is not None:
            self.sample_thumb.setPixmap(
                cover_pixmap(self._sample_photo, 30, 30, radius=6))
            self.sample_name.setText(self._sample_photo.name)
        else:
            self.sample_thumb.clear()
            self.sample_name.setText("— zdjęcie auto —")

    def _emit_generate_sample(self) -> None:
        self.generate_sample_clicked.emit(
            {"photo": str(self._sample_photo) if self._sample_photo else None}
        )

    def set_sample_busy(self, busy: bool) -> None:
        self.sample_btn.setEnabled(not busy)
        self.sample_spinner.setVisible(busy)
        self.sample_btn.setText("⏳  Generuję podgląd…" if busy
                                else "🎬  Wygeneruj podgląd")

    def set_style_preview_image(self, image) -> None:
        pix = pil_to_pixmap(image).scaled(
            126, 176, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.style_preview.setPixmap(pix)

    def _apply_character_style(self) -> None:
        style_store.set_text("postac", "styl", self.character_edit.toPlainText())
        self._update_character_caption()
        self.character_changed.emit()

    def _reset_character_style(self) -> None:
        default = style_store.reset("postac", "styl")
        self.character_edit.blockSignals(True)
        self.character_edit.setPlainText(default)
        self.character_edit.blockSignals(False)
        self._update_character_caption()
        self.character_changed.emit()

    def _reload_character_edit(self) -> None:
        self.character_edit.blockSignals(True)
        self.character_edit.setPlainText(style_store.character_style())
        self.character_edit.blockSignals(False)
        self._update_character_caption()

    def _update_character_caption(self) -> None:
        self.char_caption.setText(
            "👤  STYL POSTACI (POP-OUT)"
            + ("" if style_store.is_default("postac", "styl") else "   • zmieniony")
        )

    def refresh_style_preview(self) -> None:
        newest = None
        if config.OUTPUT_DIR.exists():
            cards = [p for p in config.OUTPUT_DIR.iterdir()
                     if p.suffix.lower() in config.IMAGE_EXTS]
            if cards:
                newest = max(cards, key=lambda p: p.stat().st_mtime)
        if newest is not None:
            self.style_preview.setPixmap(cover_pixmap(newest, 126, 176, radius=8))
        else:
            self.style_preview.setText("Wygeneruj kartę,\naby zobaczyć\npodgląd stylu")

    # ======================= SEKCJA: STYL TŁA / SZABLONU ======================
    def _build_template_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)

        self.tmpl_caption = QLabel("▦  STYL TŁA / SZABLONU KART")
        self.tmpl_caption.setObjectName("sectionTitle")
        pl.addWidget(self.tmpl_caption)
        pl.addWidget(self._library_header("styl_tla"))

        hint = QLabel("Wspólny opis ornamentyki — używany przy generowaniu nowych "
                      "teł kart i rewersu w stylu domyślnym. Zapisuje się w wybranym "
                      "presecie.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        pl.addWidget(hint)

        self._tmpl_debounce = QTimer(self)
        self._tmpl_debounce.setSingleShot(True)
        self._tmpl_debounce.setInterval(400)
        self._tmpl_debounce.timeout.connect(self._apply_template_style)

        self.template_edit = QPlainTextEdit()
        self.template_edit.setObjectName("styleEdit")
        self.template_edit.setPlainText(style_store.template_style())
        self.template_edit.textChanged.connect(self._tmpl_debounce.start)
        pl.addWidget(self.template_edit, stretch=1)

        reset_btn = QPushButton("↺  Przywróć domyślny styl tła")
        reset_btn.setObjectName("ghostBtn")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_template_style)
        pl.addWidget(reset_btn)

        self._update_template_caption()
        return panel

    def _apply_template_style(self) -> None:
        style_store.set_text("styl_tla", "styl", self.template_edit.toPlainText())
        self._update_template_caption()
        self.character_changed.emit()

    def _reset_template_style(self) -> None:
        answer = QMessageBox.question(
            self, "Przywrócić domyślny styl tła?",
            "Opis stylu tła/szablonu wróci do wartości domyślnej.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        default = style_store.reset("styl_tla", "styl")
        self.template_edit.blockSignals(True)
        self.template_edit.setPlainText(default)
        self.template_edit.blockSignals(False)
        self._update_template_caption()
        self.character_changed.emit()
        show_toast(self, "Przywrócono domyślny styl tła", "ok")

    def _reload_template_edit(self) -> None:
        self.template_edit.blockSignals(True)
        self.template_edit.setPlainText(style_store.template_style())
        self.template_edit.blockSignals(False)
        self._update_template_caption()

    def _update_template_caption(self) -> None:
        self.tmpl_caption.setText(
            "▦  STYL TŁA / SZABLONU KART"
            + ("" if style_store.is_default("styl_tla", "styl") else "   • zmieniony")
        )

    # ======================= SEKCJA: TŁA PRZODU KART ==========================
    def _build_front_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)

        cap = QLabel("🃏  TŁA PRZODU KART")
        cap.setObjectName("sectionTitle")
        pl.addWidget(cap)
        pl.addWidget(self._library_header("tla_przodu"))

        hint = QLabel("Preset teł przodu = 2 prompty (Kier/Karo i Pik/Trefl) + 4 "
                      "obrazy kart. Wybór presetu od razu ustawia aktywne tła całej "
                      "talii. Prompt jest osobny dla kart czerwonych i czarnych.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        pl.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(6)
        suit_cap = QLabel("KOLOR")
        suit_cap.setObjectName("sideCaption")
        left.addWidget(suit_cap)
        self.front_suit_combo = QComboBox()
        self.front_suit_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for suit in Suit:
            self.front_suit_combo.addItem(f"{suit.symbol} {suit.nazwa}", suit)
        self.front_suit_combo.currentIndexChanged.connect(
            self._on_front_suit_changed
        )
        left.addWidget(self.front_suit_combo)

        count_cap = QLabel("LICZBA WARIANTÓW")
        count_cap.setObjectName("sideCaption")
        left.addWidget(count_cap)
        self.front_count_seg = SegmentedControl(["1 wariant", "4 warianty"])
        left.addWidget(self.front_count_seg)

        self.front_preview = QLabel()
        self.front_preview.setObjectName("preview")
        self.front_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.front_preview.setFixedSize(126, 176)
        left.addWidget(self.front_preview, alignment=Qt.AlignmentFlag.AlignHCenter)

        gen_row = QHBoxLayout()
        self.front_spinner = Spinner(18)
        self.front_spinner.hide()
        gen_row.addWidget(self.front_spinner)
        self.front_btn = QPushButton("🎨  Generuj tło przodu")
        self.front_btn.setObjectName("generateBtn")
        self.front_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.front_btn.clicked.connect(self._emit_generate_front)
        gen_row.addWidget(self.front_btn, stretch=1)
        left.addLayout(gen_row)
        left.addStretch(1)
        row.addLayout(left, stretch=1)

        right = QVBoxLayout()
        right.setSpacing(6)
        self.front_prompt_cap = QLabel("PROMPT TŁA PRZODU")
        self.front_prompt_cap.setObjectName("sideCaption")
        right.addWidget(self.front_prompt_cap)

        self._front_debounce = QTimer(self)
        self._front_debounce.setSingleShot(True)
        self._front_debounce.setInterval(400)
        self._front_debounce.timeout.connect(self._apply_front_prompt)

        self.front_prompt = QPlainTextEdit()
        self.front_prompt.setObjectName("styleEdit")
        self.front_prompt.textChanged.connect(self._front_debounce.start)
        right.addWidget(self.front_prompt, stretch=1)
        reset_front = QPushButton("↺  Przywróć domyślny prompt")
        reset_front.setObjectName("ghostBtn")
        reset_front.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_front.clicked.connect(self._reset_front_prompt)
        right.addWidget(reset_front)
        row.addLayout(right, stretch=2)

        pl.addLayout(row)
        self._reload_front_prompt()
        return panel

    def _current_front_suit(self) -> Suit:
        return self.front_suit_combo.currentData()

    def _on_front_suit_changed(self, _index: int) -> None:
        self.refresh_front_preview()
        self._reload_front_prompt()

    def _reload_front_prompt(self) -> None:
        is_red = self._current_front_suit().is_red
        self.front_prompt.blockSignals(True)
        self.front_prompt.setPlainText(style_store.front_prompt(is_red))
        self.front_prompt.blockSignals(False)
        self._update_front_caption()

    def _update_front_caption(self) -> None:
        is_red = self._current_front_suit().is_red
        field = "front_red" if is_red else "front_black"
        base = ("PROMPT TŁA PRZODU — CZERWONE (Kier/Karo)" if is_red
                else "PROMPT TŁA PRZODU — CZARNE (Pik/Trefl)")
        self.front_prompt_cap.setText(
            base + ("" if style_store.is_default("tla_przodu", field)
                    else "   • zmieniony")
        )

    def _apply_front_prompt(self) -> None:
        field = "front_red" if self._current_front_suit().is_red else "front_black"
        style_store.set_text("tla_przodu", field, self.front_prompt.toPlainText())
        self._update_front_caption()
        self.character_changed.emit()

    def _reset_front_prompt(self) -> None:
        field = "front_red" if self._current_front_suit().is_red else "front_black"
        default = style_store.reset("tla_przodu", field)
        self.front_prompt.blockSignals(True)
        self.front_prompt.setPlainText(default)
        self.front_prompt.blockSignals(False)
        self._update_front_caption()
        self.character_changed.emit()

    def _emit_generate_front(self) -> None:
        prompt = self.front_prompt.toPlainText().strip() \
            or style_store.front_prompt(self._current_front_suit().is_red)
        count = 4 if self.front_count_seg.current() == 1 else 1
        self.generate_front_clicked.emit({
            "suit": self._current_front_suit(),
            "prompt": prompt,
            "count": count,
        })

    def refresh_front_preview(self) -> None:
        suit = self._current_front_suit()
        try:
            path = suit.template_path
        except (FileNotFoundError, StopIteration):
            path = None
        if path is not None and Path(path).exists():
            self.front_preview.setPixmap(cover_pixmap(path, 126, 176, radius=8))
        else:
            self.front_preview.setText("brak tła")

    def set_front_busy(self, busy: bool) -> None:
        self.front_btn.setEnabled(not busy)
        self.front_spinner.setVisible(busy)
        self.front_btn.setText("⏳  Generuję tła..." if busy
                               else "🎨  Generuj tło przodu")
        if not busy:
            self.refresh_front_preview()

    # ======================= SEKCJA: REWERS (TYŁ KART) ========================
    def _build_back_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)

        cap = QLabel("🂠  REWERS (TYŁ KART)")
        cap.setObjectName("sectionTitle")
        pl.addWidget(cap)
        pl.addWidget(self._library_header("rewers"))

        hint = QLabel("Preset rewersu = opis + obraz. Wybór presetu od razu ustawia "
                      "aktywny rewers całej talii.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        pl.addWidget(hint)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        # --- lewa kolumna: sterowanie generacją ---
        controls = QWidget()
        controls.setObjectName("panel")
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(14, 12, 14, 12)
        controls_layout.setSpacing(8)

        src_caption = QLabel("ŹRÓDŁO")
        src_caption.setObjectName("sideCaption")
        controls_layout.addWidget(src_caption)
        self.mode_seg = SegmentedControl(["📝 Generuj z opisu",
                                          "🖼 Generuj ze zdjęcia"])
        self.mode_seg.changed.connect(self._on_mode_changed)
        controls_layout.addWidget(self.mode_seg)

        self.photo_row = QWidget()
        self.photo_row.setObjectName("well")
        photo_layout = QHBoxLayout(self.photo_row)
        photo_layout.setContentsMargins(8, 6, 8, 6)
        self.photo_thumb = QLabel()
        self.photo_thumb.setFixedSize(36, 36)
        photo_layout.addWidget(self.photo_thumb)
        self.photo_name = QLabel("— nie wybrano zdjęcia —")
        self.photo_name.setObjectName("propValue")
        photo_layout.addWidget(self.photo_name, stretch=1)
        pick_btn = QPushButton("Wybierz…")
        pick_btn.setObjectName("ghostBtn")
        pick_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pick_btn.clicked.connect(self._pick_photo)
        photo_layout.addWidget(pick_btn)
        self.photo_row.hide()
        controls_layout.addWidget(self.photo_row)

        orient_caption = QLabel("ORIENTACJA WZORU")
        orient_caption.setObjectName("sideCaption")
        controls_layout.addWidget(orient_caption)
        self.orient_seg = SegmentedControl(["▯ Pionowo", "▭ Poziomo"])
        controls_layout.addWidget(self.orient_seg)

        preset_caption = QLabel("SZYBKI STYL REWERSU")
        preset_caption.setObjectName("sideCaption")
        controls_layout.addWidget(preset_caption)
        self.preset_combo = QComboBox()
        self.preset_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, (label, _) in prompts.BACK_PRESETS.items():
            self.preset_combo.addItem(label, key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        controls_layout.addWidget(self.preset_combo)

        opis_caption = QLabel("OPIS REWERSU (zapisywany w presecie)")
        opis_caption.setObjectName("sideCaption")
        controls_layout.addWidget(opis_caption)
        self._opis_debounce = QTimer(self)
        self._opis_debounce.setSingleShot(True)
        self._opis_debounce.setInterval(400)
        self._opis_debounce.timeout.connect(self._apply_back_opis)
        self.custom_edit = QPlainTextEdit()
        self.custom_edit.setObjectName("styleEdit")
        self.custom_edit.setPlaceholderText(
            "Opisz wzór rewersu (kolory, motywy, nastrój)…"
        )
        self.custom_edit.setFixedHeight(96)
        self.custom_edit.setPlainText(style_store.back_text())
        self.custom_edit.textChanged.connect(self._opis_debounce.start)
        controls_layout.addWidget(self.custom_edit)

        columns.addWidget(controls, stretch=3)

        # --- prawa kolumna: podgląd + backupy ---
        preview_panel = QWidget()
        preview_panel.setObjectName("panel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(14, 12, 14, 12)
        preview_layout.setSpacing(8)

        prev_caption = QLabel("AKTUALNY REWERS")
        prev_caption.setObjectName("sideCaption")
        preview_layout.addWidget(prev_caption)

        self.back_preview = QLabel("brak rewersu —\nwygeneruj go AI")
        self.back_preview.setObjectName("preview")
        self.back_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.back_preview.setFixedSize(BACK_W, BACK_H)
        preview_layout.addWidget(self.back_preview,
                                 alignment=Qt.AlignmentFlag.AlignHCenter)

        gen_row = QHBoxLayout()
        self.back_spinner = Spinner(18)
        self.back_spinner.hide()
        gen_row.addWidget(self.back_spinner)
        self.back_btn = QPushButton("✨  Generuj rewers")
        self.back_btn.setObjectName("generateBtn")
        self.back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.back_btn.clicked.connect(self._emit_generate)
        gen_row.addWidget(self.back_btn, stretch=1)
        preview_layout.addLayout(gen_row)

        backups_caption = QLabel("POPRZEDNIE REWERSY (BACKUP)")
        backups_caption.setObjectName("sideCaption")
        preview_layout.addWidget(backups_caption)
        self.backups = QListWidget()
        self.backups.setObjectName("queueList")
        self.backups.setToolTip("Dwuklik otwiera plik w podglądzie systemowym")
        self.backups.itemDoubleClicked.connect(self._open_backup)
        preview_layout.addWidget(self.backups, stretch=1)

        columns.addWidget(preview_panel, stretch=2)
        pl.addLayout(columns)
        return panel

    def _on_mode_changed(self, index: int) -> None:
        self.photo_row.setVisible(index == 1)

    def _on_preset_changed(self, _index: int) -> None:
        """Szybki styl: wstaw jego opis do edytora (jeśli ma własny tekst)."""
        key = self.preset_combo.currentData()
        style_text = prompts.BACK_PRESETS.get(key, (None, None))[1]
        if style_text:
            self.custom_edit.setPlainText(style_text)   # zapis przez debounce

    def _apply_back_opis(self) -> None:
        style_store.set_text("rewers", "opis", self.custom_edit.toPlainText())
        self.character_changed.emit()

    def _reload_back_opis(self) -> None:
        self.custom_edit.blockSignals(True)
        self.custom_edit.setPlainText(style_store.back_text())
        self.custom_edit.blockSignals(False)

    def _pick_photo(self) -> None:
        exts = " ".join(f"*{e}" for e in sorted(config.IMAGE_EXTS))
        path, _ = QFileDialog.getOpenFileName(
            self, "Zdjęcie źródłowe rewersu", str(config.ZDJECIA_DIR),
            f"Obrazy ({exts})",
        )
        if path:
            self.set_source_photo(Path(path))

    def set_source_photo(self, path: Path | None) -> None:
        self._source_photo = path
        if path is not None and path.exists():
            self.photo_thumb.setPixmap(cover_pixmap(path, 36, 36, radius=6))
            self.photo_name.setText(path.name)
        else:
            self._source_photo = None
            self.photo_thumb.clear()
            self.photo_name.setText("— nie wybrano zdjęcia —")

    def _emit_generate(self) -> None:
        settings = self.settings()
        if settings["mode"] == "i2i" and not settings["source_photo"]:
            show_toast(self, "Wybierz zdjęcie źródłowe rewersu", "error")
            return
        self.generate_back_clicked.emit(settings)

    def _open_backup(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.ItemDataRole.UserRole)
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def refresh_back_preview(self) -> None:
        back = style_store.back_path()
        if back.exists():
            self.back_preview.setPixmap(
                cover_pixmap(back, BACK_W, BACK_H, radius=10)
            )
            self.back_btn.setText("✨  Wygeneruj nowy rewers")
        else:
            self.back_preview.setText("brak rewersu —\nwygeneruj go AI")
        self._refresh_backups()

    def _refresh_backups(self) -> None:
        self.backups.clear()
        back_dir = style_store.preset_dir("rewers")
        if not back_dir.is_dir():
            return
        backups = sorted(back_dir.glob("rewers_stary_*.png"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for path in backups:
            item = QListWidgetItem(f"🕓  {path.name}")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.backups.addItem(item)

    def set_back_busy(self, busy: bool) -> None:
        self.back_btn.setEnabled(not busy)
        self.back_spinner.setVisible(busy)
        self.back_btn.setText(
            "⏳  Generuję rewers..." if busy else "✨  Generuj rewers"
        )
        if not busy:
            self.refresh_back_preview()

    # --- API dla MainWindow ---------------------------------------------------
    def settings(self) -> dict:
        return {
            "mode": "i2i" if self.mode_seg.current() == 1 else "t2i",
            "orientation": ("landscape" if self.orient_seg.current() == 1
                            else "portrait"),
            "preset": self.preset_combo.currentData(),
            "custom": self.custom_edit.toPlainText().strip(),
            "source_photo": (str(self._source_photo)
                             if self._source_photo else None),
        }

    def apply_settings(self, data: dict) -> None:
        self.mode_seg.set_current(1 if data.get("mode") == "i2i" else 0)
        self._on_mode_changed(self.mode_seg.current())
        self.orient_seg.set_current(
            1 if data.get("orientation") == "landscape" else 0
        )
        preset = data.get("preset", "klasyczny")
        index = self.preset_combo.findData(preset)
        if index >= 0:
            self.preset_combo.blockSignals(True)
            self.preset_combo.setCurrentIndex(index)
            self.preset_combo.blockSignals(False)
        source = data.get("source_photo")
        self.set_source_photo(Path(source) if source else None)

    def showEvent(self, event):  # noqa: N802 (API Qt)
        self.reload_style_slot()
        self.refresh_style_preview()
        super().showEvent(event)
