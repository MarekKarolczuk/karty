"""Widok Ustawienia i style: klucze API (zapis do .env), wybór modelu,
styl postaci (4 presety + własny), format talii, foldery projektu
i podgląd system-promptu."""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import QThread, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFileDialog, QGridLayout, QHBoxLayout,
    QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QToolButton, QVBoxLayout, QWidget,
)

from app import config
from app.core import style_store
from app.gui.animations import Spinner
from app.gui.views import view_header
from app.gui.widgets import show_toast

MODEL_DESCRIPTIONS = {
    "gemini-2.5-flash-image": "Szybki inpainting image-to-image. "
                              "Najlepsza wierność detali.",
    "gemini-3-pro-image": "Najwyższa jakość ilustracji, wolniejszy.",
}
PROVIDER_TAGS = {"gemini": "Google AI Studio"}


class _TestWorker(QThread):
    """Test połączenia z API — poza wątkiem GUI."""

    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        results = []
        errors = []
        if config.GEMINI_API_KEY:
            try:
                from app.api import gemini_client
                models = gemini_client.get_client().models.list()
                next(iter(models), None)   # jedno lekkie żądanie
                results.append("Gemini: połączono ✔")
            except Exception as exc:
                errors.append(f"Gemini: {str(exc)[:120]}")
        else:
            errors.append("Brak klucza Gemini — uzupełnij pole powyżej")
        if results:
            self.finished_ok.emit("   ·   ".join(results + errors))
        else:
            self.finished_error.emit("   ·   ".join(errors))


class SettingsView(QWidget):
    keys_changed = pyqtSignal()
    model_changed = pyqtSignal(str)
    card_preset_changed = pyqtSignal(str)
    style_slot_changed = pyqtSignal()   # zmiana aktywnego slotu / jego zawartości

    def __init__(self, parent=None):
        super().__init__(parent)
        self._test_worker: _TestWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        layout.addWidget(view_header(
            "Ustawienia i style",
            "API, model, styl postaci, format talii i foldery projektu"
        ))

        columns = QHBoxLayout()
        columns.setSpacing(10)

        # ==================== LEWA KOLUMNA: API + foldery =========================
        left_column = QVBoxLayout()
        left_column.setSpacing(10)

        api_panel = QWidget()
        api_panel.setObjectName("panel")
        api_layout = QVBoxLayout(api_panel)
        api_layout.setContentsMargins(14, 12, 14, 12)
        api_layout.setSpacing(8)

        api_caption = QLabel("⚡  KLUCZE API")
        api_caption.setObjectName("sectionTitle")
        api_layout.addWidget(api_caption)

        self.gemini_edit = self._key_row(api_layout, "GEMINI (GOOGLE AI STUDIO)",
                                         config.GEMINI_API_KEY)
        self.custom_key_edit = self._key_row(
            api_layout, "WŁASNY KLUCZ — INNY MODEL AI (np. Claude)",
            config.CUSTOM_API_KEY)
        custom_hint = QLabel("Miejsce na Twój własny klucz do dowolnego modelu "
                             "(zapisywany do .env jako CUSTOM_API_KEY). Generacja "
                             "obrazów kart używa modelu Gemini.")
        custom_hint.setObjectName("hint")
        custom_hint.setWordWrap(True)
        api_layout.addWidget(custom_hint)

        buttons = QHBoxLayout()
        save_btn = QPushButton("💾  Zapisz klucze (.env)")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._save_keys)
        buttons.addWidget(save_btn)
        self.test_spinner = Spinner(18)
        self.test_spinner.hide()
        buttons.addWidget(self.test_spinner)
        self.test_btn = QPushButton("⚡  Testuj połączenie")
        self.test_btn.setObjectName("ghostBtn")
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.clicked.connect(self._test_connection)
        buttons.addWidget(self.test_btn)
        buttons.addStretch(1)
        api_layout.addLayout(buttons)

        self.test_result = QLabel()
        self.test_result.setObjectName("mutedInfo")
        self.test_result.setWordWrap(True)
        api_layout.addWidget(self.test_result)
        left_column.addWidget(api_panel)

        # --- model generujący ------------------------------------------------------
        model_panel = QWidget()
        model_panel.setObjectName("panel")
        model_layout = QVBoxLayout(model_panel)
        model_layout.setContentsMargins(14, 12, 14, 12)
        model_layout.setSpacing(8)

        model_caption = QLabel("✦  MODEL GENERUJĄCY OBRAZ")
        model_caption.setObjectName("sectionTitle")
        model_layout.addWidget(model_caption)

        self._model_group = QButtonGroup(self)
        self._model_group.setExclusive(True)
        self._model_buttons: dict[str, QPushButton] = {}
        model_grid = QGridLayout()
        model_grid.setSpacing(10)
        for i, (key, model) in enumerate(config.MODELS.items()):
            provider = PROVIDER_TAGS.get(model["provider"], model["provider"])
            description = MODEL_DESCRIPTIONS.get(key, "")
            btn = QPushButton(
                f"{model['label']}   ·   {provider}\n{description}"
            )
            btn.setObjectName("modelCard")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setMinimumHeight(64)
            self._model_group.addButton(btn)
            btn.clicked.connect(
                lambda _=False, k=key: self.model_changed.emit(k)
            )
            model_grid.addWidget(btn, i // 2, i % 2)
            self._model_buttons[key] = btn
        model_layout.addLayout(model_grid)
        left_column.addWidget(model_panel)

        folders_panel = QWidget()
        folders_panel.setObjectName("panel")
        folders_layout = QVBoxLayout(folders_panel)
        folders_layout.setContentsMargins(14, 12, 14, 12)
        folders_layout.setSpacing(8)

        folders_caption = QLabel("📁  FOLDERY PROJEKTU")
        folders_caption.setObjectName("sectionTitle")
        folders_layout.addWidget(folders_caption)

        for label, hint, path in (
            ("/zdjecia", "zdjęcia wejściowe", config.ZDJECIA_DIR),
            ("/tla_kart", "szablony kart · nienaruszalne", config.TLA_DIR),
            ("/przykladowe_karty", "referencje stylu dla modelu",
             config.REFERENCJE_DIR),
            ("/output", "wygenerowane karty", config.OUTPUT_DIR),
        ):
            row = QWidget()
            row.setObjectName("well")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(10, 6, 10, 6)
            name_box = QVBoxLayout()
            name_box.setSpacing(0)
            name = QLabel(label)
            name.setObjectName("folderName")
            name_box.addWidget(name)
            sub = QLabel(hint)
            sub.setObjectName("hint")
            name_box.addWidget(sub)
            row_layout.addLayout(name_box, stretch=1)
            open_btn = QPushButton("Otwórz")
            open_btn.setObjectName("ghostBtn")
            open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            open_btn.clicked.connect(
                lambda _=False, p=path: QDesktopServices.openUrl(
                    QUrl.fromLocalFile(str(p))
                )
            )
            row_layout.addWidget(open_btn)
            folders_layout.addWidget(row)
        left_column.addWidget(folders_panel)
        left_column.addStretch(1)
        columns.addLayout(left_column, stretch=1)

        # ============ PRAWA KOLUMNA: styl postaci + format + prompt ================
        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        style_panel = QWidget()
        style_panel.setObjectName("panel")
        style_layout = QVBoxLayout(style_panel)
        style_layout.setContentsMargins(14, 12, 14, 12)
        style_layout.setSpacing(8)

        style_caption = QLabel("👤  STYL (ZESTAW PROMPTÓW)")
        style_caption.setObjectName("sectionTitle")
        style_layout.addWidget(style_caption)
        style_hint = QLabel("Nazwany zestaw: styl postaci + tło/szablon + tła "
                            "przodu (Kier/Karo i Pik/Trefl). Zapisuje się "
                            "automatycznie i przeżywa restart aplikacji.")
        style_hint.setObjectName("hint")
        style_hint.setWordWrap(True)
        style_layout.addWidget(style_hint)

        self.slot_combo = QComboBox()
        self.slot_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slot_combo.currentIndexChanged.connect(self._on_slot_selected)
        style_layout.addWidget(self.slot_combo)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(6)
        for text, tip, handler in (
            ("＋ Nowy", "Utwórz nowy zestaw (kopia domyślnych)", self._new_slot),
            ("⧉ Duplikuj", "Skopiuj bieżący zestaw", self._duplicate_slot),
            ("✎ Zmień nazwę", "Zmień nazwę bieżącego zestawu", self._rename_slot),
            ("🗑 Usuń", "Usuń bieżący zestaw", self._delete_slot),
        ):
            btn = QPushButton(text)
            btn.setObjectName("ghostBtn")
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            actions_row.addWidget(btn)
        actions_row.addStretch(1)
        style_layout.addLayout(actions_row)

        io_row = QHBoxLayout()
        io_row.setSpacing(6)
        for text, tip, handler in (
            ("⬆ Eksportuj zestaw", "Zapisz bieżący zestaw do pliku JSON",
             self._export_slot),
            ("⬇ Importuj zestaw", "Wczytaj zestaw z pliku JSON", self._import_slot),
        ):
            btn = QPushButton(text)
            btn.setObjectName("ghostBtn")
            btn.setToolTip(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            io_row.addWidget(btn)
        io_row.addStretch(1)
        style_layout.addLayout(io_row)

        self.char_cap = QLabel("PROMPT STYLU POSTACI")
        self.char_cap.setObjectName("sideCaption")
        style_layout.addWidget(self.char_cap)

        self._custom_debounce = QTimer(self)
        self._custom_debounce.setSingleShot(True)
        self._custom_debounce.setInterval(400)
        self._custom_debounce.timeout.connect(self._apply_custom_style)

        self.custom_edit = QPlainTextEdit()
        self.custom_edit.setObjectName("styleEdit")
        self.custom_edit.setPlaceholderText(
            "Opisz styl postaci (technika, paleta, nastrój, efekt pop-out)…"
        )
        self.custom_edit.setFixedHeight(110)
        self.custom_edit.textChanged.connect(self._custom_debounce.start)
        style_layout.addWidget(self.custom_edit)

        reset_slot_btn = QPushButton("↺  Przywróć domyślny zestaw")
        reset_slot_btn.setObjectName("ghostBtn")
        reset_slot_btn.setToolTip("Przywraca wszystkie prompty bieżącego zestawu "
                                  "do wartości domyślnych")
        reset_slot_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_slot_btn.clicked.connect(self._reset_slot)
        style_layout.addWidget(reset_slot_btn)

        size_caption = QLabel("⌗  FORMAT TALII")
        size_caption.setObjectName("sectionTitle")
        style_layout.addWidget(size_caption)
        self.size_combo = QComboBox()
        self.size_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, (label, _) in config.CARD_PRESETS.items():
            self.size_combo.addItem(label, key)
        self.size_combo.currentIndexChanged.connect(self._on_card_preset)
        style_layout.addWidget(self.size_combo)
        size_hint = QLabel("Eksport PDF trzyma się wybranego formatu w 300 DPI.")
        size_hint.setObjectName("hint")
        style_layout.addWidget(size_hint)
        right_column.addWidget(style_panel)

        prompt_panel = QWidget()
        prompt_panel.setObjectName("panel")
        prompt_layout = QVBoxLayout(prompt_panel)
        prompt_layout.setContentsMargins(14, 12, 14, 12)
        prompt_layout.setSpacing(8)

        prompt_row = QHBoxLayout()
        prompt_caption = QLabel("{ }  SYSTEM PROMPT (PODGLĄD)")
        prompt_caption.setObjectName("sectionTitle")
        prompt_row.addWidget(prompt_caption)
        prompt_row.addStretch(1)
        copy_btn = QPushButton("⧉  Kopiuj")
        copy_btn.setObjectName("ghostBtn")
        copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        copy_btn.clicked.connect(self._copy_prompt)
        prompt_row.addWidget(copy_btn)
        prompt_layout.addLayout(prompt_row)

        self.prompt_preview = QPlainTextEdit()
        self.prompt_preview.setObjectName("promptPreview")
        self.prompt_preview.setReadOnly(True)
        prompt_layout.addWidget(self.prompt_preview, stretch=1)
        right_column.addWidget(prompt_panel, stretch=1)

        columns.addLayout(right_column, stretch=1)
        layout.addLayout(columns, stretch=1)

        self.sync_model()
        self.sync_styles()
        self.refresh_prompt()

    # --- pomocnicze -----------------------------------------------------------------
    def _key_row(self, parent_layout: QVBoxLayout, label: str,
                 value: str) -> QLineEdit:
        caption = QLabel(f"KLUCZ API — {label}")
        caption.setObjectName("propKey")
        parent_layout.addWidget(caption)
        row = QHBoxLayout()
        edit = QLineEdit(value)
        edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setPlaceholderText("wklej klucz API…")
        row.addWidget(edit, stretch=1)
        eye = QToolButton()
        eye.setText("👁")
        eye.setCheckable(True)
        eye.setCursor(Qt.CursorShape.PointingHandCursor)
        eye.toggled.connect(
            lambda show, e=edit: e.setEchoMode(
                QLineEdit.EchoMode.Normal if show
                else QLineEdit.EchoMode.Password
            )
        )
        row.addWidget(eye)
        parent_layout.addLayout(row)
        return edit

    # --- model ------------------------------------------------------------------------
    def sync_model(self) -> None:
        """Zaznacza kartę aktualnie wybranego modelu."""
        for key, btn in self._model_buttons.items():
            btn.setChecked(key == config.SELECTED_MODEL)

    def refresh_model(self) -> None:   # zgodność ze starym API kontrolera
        self.sync_model()

    # --- style (zestawy) --------------------------------------------------------------
    def sync_styles(self) -> None:
        """Ustawia kontrolki wg style_store/config (bez emitowania zmian)."""
        self._refresh_slot_combo()
        self._reload_character_edit()

        size_index = self.size_combo.findData(config.SELECTED_CARD_PRESET)
        self.size_combo.blockSignals(True)
        if size_index >= 0:
            self.size_combo.setCurrentIndex(size_index)
        self.size_combo.blockSignals(False)

    def _refresh_slot_combo(self) -> None:
        self.slot_combo.blockSignals(True)
        self.slot_combo.clear()
        for name in style_store.slot_names():
            self.slot_combo.addItem(name, name)
        index = self.slot_combo.findData(style_store.active_slot())
        if index >= 0:
            self.slot_combo.setCurrentIndex(index)
        self.slot_combo.blockSignals(False)

    def _reload_character_edit(self) -> None:
        self.custom_edit.blockSignals(True)
        self.custom_edit.setPlainText(style_store.character_style())
        self.custom_edit.blockSignals(False)
        self._update_char_indicator()

    def _update_char_indicator(self) -> None:
        default = style_store.is_default("character")
        self.char_cap.setText("PROMPT STYLU POSTACI"
                              + ("" if default else "   • zmieniony"))

    def _export_slot(self) -> None:
        name = style_store.active_slot()
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Eksportuj zestaw stylu",
            str(config.ROOT / f"styl_{safe}.json"), "JSON (*.json)",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                json.dumps(style_store.export_slot(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            show_toast(self, "Wyeksportowano zestaw stylu", "ok")
        except OSError as exc:
            show_toast(self, f"Błąd eksportu: {exc}", "error")

    def _import_slot(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importuj zestaw stylu", str(config.ROOT), "JSON (*.json)",
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            show_toast(self, f"Nie wczytano pliku: {exc}", "error")
            return
        if not isinstance(data, dict):
            show_toast(self, "Niepoprawny plik zestawu stylu", "error")
            return
        style_store.import_slot(data)
        self._after_slot_change()
        show_toast(self, "Zaimportowano zestaw stylu", "ok")

    def _on_slot_selected(self, _index: int) -> None:
        name = self.slot_combo.currentData()
        if not name:
            return
        style_store.set_active_slot(name)
        self._reload_character_edit()
        self.refresh_prompt()
        self.style_slot_changed.emit()

    def _new_slot(self) -> None:
        name, ok = QInputDialog.getText(self, "Nowy zestaw stylu",
                                        "Nazwa nowego zestawu:")
        if not ok:
            return
        style_store.create_slot(name.strip())
        self._after_slot_change()

    def _duplicate_slot(self) -> None:
        style_store.duplicate_active()
        self._after_slot_change()

    def _rename_slot(self) -> None:
        current = style_store.active_slot()
        name, ok = QInputDialog.getText(self, "Zmień nazwę zestawu",
                                        "Nowa nazwa:", text=current)
        if not ok or not name.strip():
            return
        style_store.rename_slot(current, name.strip())
        self._after_slot_change()

    def _delete_slot(self) -> None:
        if len(style_store.slot_names()) <= 1:
            show_toast(self, "Nie można usunąć ostatniego zestawu", "info")
            return
        current = style_store.active_slot()
        answer = QMessageBox.question(
            self, "Usunąć zestaw?",
            f"Zestaw stylu „{current}” zostanie trwale usunięty.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        style_store.delete_slot(current)
        self._after_slot_change()

    def _reset_slot(self) -> None:
        answer = QMessageBox.question(
            self, "Przywrócić domyślny zestaw?",
            "Wszystkie prompty bieżącego zestawu (postać, tło, tła przodu) wrócą "
            "do wartości domyślnych.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        style_store.reset_slot()
        self._reload_character_edit()
        self.refresh_prompt()
        self.style_slot_changed.emit()
        show_toast(self, "Przywrócono domyślny zestaw", "ok")

    def _after_slot_change(self) -> None:
        """Po utworzeniu/usunięciu/zmianie nazwy zestawu — pełne odświeżenie."""
        self._refresh_slot_combo()
        self._reload_character_edit()
        self.refresh_prompt()
        self.style_slot_changed.emit()

    def _apply_custom_style(self) -> None:
        style_store.set_style("character", self.custom_edit.toPlainText())
        self._update_char_indicator()
        self.refresh_prompt()
        self.style_slot_changed.emit()

    def _on_card_preset(self, _index: int) -> None:
        key = self.size_combo.currentData()
        config.set_card_preset(key)
        self.card_preset_changed.emit(key)

    # --- prompt -----------------------------------------------------------------------
    def refresh_prompt(self) -> None:
        """Składa podgląd promptu z aktywnego zestawu stylu."""
        self.prompt_preview.setPlainText(
            f"ZESTAW: {style_store.active_slot()}\n\n"
            "STYL POSTACI:\n"
            + style_store.character_style().strip()
            + "\n\nSTYL TŁA / SZABLONU (edycja w zakładce Tła i rewersy):\n"
            + style_store.template_style().strip()
            + "\n\nTŁO PRZODU — CZERWONE (Kier/Karo):\n"
            + style_store.front_prompt(True).strip()
            + "\n\nTŁO PRZODU — CZARNE (Pik/Trefl):\n"
            + style_store.front_prompt(False).strip()
        )

    def showEvent(self, event):  # noqa: N802 (API Qt)
        self.sync_model()
        self.sync_styles()
        self.refresh_prompt()
        super().showEvent(event)

    def _copy_prompt(self) -> None:
        QApplication.clipboard().setText(self.prompt_preview.toPlainText())
        show_toast(self, "Skopiowano prompt do schowka", "ok")

    def _save_keys(self) -> None:
        from dotenv import set_key

        env_path = config.ROOT / ".env"
        env_path.touch(exist_ok=True)
        gemini = self.gemini_edit.text().strip()
        custom = self.custom_key_edit.text().strip()
        set_key(str(env_path), "GEMINI_API_KEY", gemini)
        set_key(str(env_path), "CUSTOM_API_KEY", custom)
        config.GEMINI_API_KEY = gemini
        config.CUSTOM_API_KEY = custom
        from app.api import gemini_client
        gemini_client.reset_client()
        self.keys_changed.emit()
        show_toast(self, "Zapisano klucze do .env", "ok")

    def _test_connection(self) -> None:
        if self._test_worker is not None:
            return
        self.test_btn.setEnabled(False)
        self.test_spinner.show()
        self.test_result.setText("Łączenie…")
        worker = _TestWorker()
        worker.finished_ok.connect(lambda t: self._test_done(t, ok=True))
        worker.finished_error.connect(lambda t: self._test_done(t, ok=False))
        self._test_worker = worker
        worker.start()

    def _test_done(self, text: str, ok: bool) -> None:
        self._test_worker = None
        self.test_btn.setEnabled(True)
        self.test_spinner.hide()
        self.test_result.setText(text)
        show_toast(self, "Połączenie OK" if ok else "Problem z połączeniem",
                   "ok" if ok else "error")
