"""Widok „Domyślne style / Tła i rewersy": generowanie teł PRZODU kart oraz
tyłu kart (rewersu) na podstawie opisów (promptów) — z opisu (T2I) lub ze
zdjęcia (I2I), presety, orientacja, edytor domyślnego stylu tła."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from app import config
from app.core import prompts, style_store
from app.core.models import Suit
from app.gui.animations import Spinner
from app.gui.views import view_header
from app.gui.widgets import SegmentedControl, cover_pixmap, show_toast

BACK_W, BACK_H = 200, 279


class BackView(QWidget):
    # {"mode": "t2i"|"i2i", "orientation": "portrait"|"landscape",
    #  "preset": str, "custom": str, "source_photo": str|None}
    generate_back_clicked = pyqtSignal(dict)
    # {"suit": Suit, "prompt": str, "count": int}
    generate_front_clicked = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source_photo: Path | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(10)

        outer.addWidget(view_header(
            "Domyślne style / Tła i rewersy",
            "Generuj tła przodu kart i wspólny rewers z opisu (promptu) — "
            "spójny styl całej talii",
        ))

        # scroll, bo zakładka mieści teraz dwie sekcje (tła przodu + rewers)
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        # ================= SEKCJA: TŁA PRZODU KART ============================
        layout.addWidget(self._build_front_panel())

        rewers_caption = QLabel("REWERS (TYŁ KART)")
        rewers_caption.setObjectName("sectionTitle")
        layout.addWidget(rewers_caption)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        # ================= LEWA KOLUMNA: sterowanie ============================
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

        # wiersz zdjęcia źródłowego (tylko tryb I2I)
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

        preset_caption = QLabel("STYL REWERSU")
        preset_caption.setObjectName("sideCaption")
        controls_layout.addWidget(preset_caption)
        self.preset_combo = QComboBox()
        self.preset_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, (label, _) in prompts.BACK_PRESETS.items():
            self.preset_combo.addItem(label, key)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        controls_layout.addWidget(self.preset_combo)

        self.custom_edit = QPlainTextEdit()
        self.custom_edit.setObjectName("styleEdit")
        self.custom_edit.setPlaceholderText(
            "Opisz własny wzór rewersu (kolory, motywy, nastrój)…"
        )
        self.custom_edit.setFixedHeight(84)
        self.custom_edit.hide()
        controls_layout.addWidget(self.custom_edit)

        # --- edytor stylu tła/szablonu (dawny „Styl AI") -----------------------
        self.bg_caption = QLabel("▦  STYL TŁA / SZABLONU KART")
        self.bg_caption.setObjectName("sideCaption")
        controls_layout.addWidget(self.bg_caption)
        bg_hint = QLabel("Wspólny opis ornamentyki — używany przy generowaniu "
                         "nowych teł kart i rewersu w stylu domyślnym.")
        bg_hint.setObjectName("hint")
        bg_hint.setWordWrap(True)
        controls_layout.addWidget(bg_hint)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)
        self._debounce.timeout.connect(self._apply_template_style)

        self.template_edit = QPlainTextEdit()
        self.template_edit.setObjectName("styleEdit")
        self.template_edit.setPlainText(style_store.template_style())
        self.template_edit.textChanged.connect(self._debounce.start)
        controls_layout.addWidget(self.template_edit, stretch=1)

        reset_btn = QPushButton("↺  Przywróć domyślny styl tła")
        reset_btn.setObjectName("ghostBtn")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_template_style)
        controls_layout.addWidget(reset_btn)

        columns.addWidget(controls, stretch=3)

        # ================= PRAWA KOLUMNA: podgląd + historia ======================
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
        layout.addLayout(columns)
        layout.addStretch(1)

        scroll.setWidget(host)
        outer.addWidget(scroll, stretch=1)

        self.refresh_back_preview()
        self.refresh_front_preview()
        self._update_template_caption()

    # --- panel teł przodu ---------------------------------------------------------
    def _build_front_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)

        cap = QLabel("🃏  TŁA PRZODU KART")
        cap.setObjectName("sectionTitle")
        pl.addWidget(cap)
        self.slot_label = QLabel(f"Zestaw stylu: {style_store.active_slot()}")
        self.slot_label.setObjectName("hint")
        pl.addWidget(self.slot_label)
        hint = QLabel("Wygeneruj tło przodu w spójnym stylu. Prompt jest osobny "
                      "dla kart czerwonych (Kier/Karo) i czarnych (Pik/Trefl) "
                      "i zapisuje się w aktywnym zestawie stylu.")
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
        self._reload_front_prompt()   # wczytaj prompt dla bieżącego koloru
        return panel

    def _current_front_suit(self) -> Suit:
        return self.front_suit_combo.currentData()

    def _on_front_suit_changed(self, _index: int) -> None:
        self.refresh_front_preview()
        self._reload_front_prompt()

    def _reload_front_prompt(self) -> None:
        """Wczytuje prompt tła przodu dla koloru wybranego w comboboxie."""
        is_red = self._current_front_suit().is_red
        self.front_prompt.blockSignals(True)
        self.front_prompt.setPlainText(style_store.front_prompt(is_red))
        self.front_prompt.blockSignals(False)
        self._update_front_caption()

    def _update_front_caption(self) -> None:
        is_red = self._current_front_suit().is_red
        kind = "front_red" if is_red else "front_black"
        base = ("PROMPT TŁA PRZODU — CZERWONE (Kier/Karo)" if is_red
                else "PROMPT TŁA PRZODU — CZARNE (Pik/Trefl)")
        self.front_prompt_cap.setText(
            base + ("" if style_store.is_default(kind) else "   • zmieniony")
        )

    def _update_template_caption(self) -> None:
        self.bg_caption.setText("▦  STYL TŁA / SZABLONU KART"
                                + ("" if style_store.is_default("template")
                                   else "   • zmieniony"))

    def _apply_front_prompt(self) -> None:
        kind = "front_red" if self._current_front_suit().is_red else "front_black"
        style_store.set_style(kind, self.front_prompt.toPlainText())
        self._update_front_caption()

    def _reset_front_prompt(self) -> None:
        kind = "front_red" if self._current_front_suit().is_red else "front_black"
        default = style_store.reset(kind)
        self.front_prompt.blockSignals(True)
        self.front_prompt.setPlainText(default)
        self.front_prompt.blockSignals(False)

    def reload_style_slot(self) -> None:
        """Odświeża edytory stylu po zmianie aktywnego zestawu (z Ustawień)."""
        self.slot_label.setText(f"Zestaw stylu: {style_store.active_slot()}")
        self.template_edit.blockSignals(True)
        self.template_edit.setPlainText(style_store.template_style())
        self.template_edit.blockSignals(False)
        self._update_template_caption()
        self._reload_front_prompt()

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

    # --- interakcje ----------------------------------------------------------------
    def _on_mode_changed(self, index: int) -> None:
        self.photo_row.setVisible(index == 1)

    def _on_preset_changed(self, _index: int) -> None:
        self.custom_edit.setVisible(self.preset_combo.currentData() == "custom")

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

    # --- styl tła --------------------------------------------------------------------
    def _apply_template_style(self) -> None:
        style_store.set_style("template", self.template_edit.toPlainText())
        self._update_template_caption()

    def _reset_template_style(self) -> None:
        answer = QMessageBox.question(
            self, "Przywrócić domyślny styl tła?",
            "Opis stylu tła/szablonu wróci do wartości domyślnej.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        default = style_store.reset("template")
        self.template_edit.blockSignals(True)
        self.template_edit.setPlainText(default)
        self.template_edit.blockSignals(False)
        show_toast(self, "Przywrócono domyślny styl tła", "ok")

    # --- API dla MainWindow ------------------------------------------------------------
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
            self.preset_combo.setCurrentIndex(index)
        self.custom_edit.setPlainText(data.get("custom", ""))
        self._on_preset_changed(self.preset_combo.currentIndex())
        source = data.get("source_photo")
        self.set_source_photo(Path(source) if source else None)

    def refresh_back_preview(self) -> None:
        if config.BACK_PATH.exists():
            self.back_preview.setPixmap(
                cover_pixmap(config.BACK_PATH, BACK_W, BACK_H, radius=10)
            )
            self.back_btn.setText("✨  Wygeneruj nowy rewers")
        else:
            self.back_preview.setText("brak rewersu —\nwygeneruj go AI")
        self._refresh_backups()

    def _refresh_backups(self) -> None:
        self.backups.clear()
        if not config.TLA_DIR.exists():
            return
        backups = sorted(config.TLA_DIR.glob("rewers_stary_*.png"),
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
