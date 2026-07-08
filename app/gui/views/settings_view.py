"""Widok Ustawienia: klucze API (zapis do .env), wybór modelu, format talii,
foldery projektu i podgląd system-promptu. Biblioteki presetów stylu żyją
w zakładce „Style" (back_view)."""
from __future__ import annotations

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from app import config
from app.core import style_store
from app.gui.animations import Spinner
from app.gui.views import view_header
from app.gui.widgets import SegmentedControl, show_toast

MODEL_DESCRIPTIONS = {
    "gemini-2.5-flash-image": "Szybki inpainting image-to-image. "
                              "Najlepsza wierność detali.",
    "gemini-3-pro-image": "Najwyższa jakość ilustracji, wolniejszy.",
    "gemini-3.1-flash-image-preview": "Nano Banana 2 — szybki i tani następca "
                                      "Imagen (preview).",
    "gemini-3.1-flash-lite-image-preview": "Najtańszy wariant Nano Banana 2 "
                                           "(preview).",
}
PROVIDER_TAGS = {"gemini": "Google"}


class _TestWorker(QThread):
    """Test połączenia z API — poza wątkiem GUI."""

    finished_ok = pyqtSignal(str)
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        results = []
        errors = []
        label = "Vertex AI" if config.USE_VERTEX else "Gemini"
        if config.api_ready():
            try:
                from app.api import gemini_client
                models = gemini_client.get_client().models.list()
                next(iter(models), None)   # jedno lekkie żądanie
                results.append(f"{label}: połączono ✔")
            except Exception as exc:
                errors.append(f"{label}: {str(exc)[:140]}")
        elif config.USE_VERTEX:
            errors.append("Tryb Vertex bez ID projektu GCP — uzupełnij pole")
        else:
            errors.append("Brak klucza Gemini / trybu Vertex — uzupełnij powyżej")
        if results:
            self.finished_ok.emit("   ·   ".join(results + errors))
        else:
            self.finished_error.emit("   ·   ".join(errors))


class _RefreshModelsWorker(QThread):
    """Pobiera listę modeli obrazowych z aktywnego źródła — poza wątkiem GUI."""

    finished_ok = pyqtSignal(dict)     # {model_id: {label, vertex_location}}
    finished_error = pyqtSignal(str)

    def run(self) -> None:
        if not config.api_ready():
            self.finished_error.emit(
                "Brak skonfigurowanego źródła — uzupełnij klucz albo Vertex."
            )
            return
        try:
            from app.api import gemini_client
            self.finished_ok.emit(gemini_client.list_image_models())
        except Exception as exc:
            self.finished_error.emit(str(exc)[:200])


class SettingsView(QWidget):
    keys_changed = pyqtSignal()
    model_changed = pyqtSignal(str)
    card_preset_changed = pyqtSignal(str)
    models_refreshed = pyqtSignal()    # lista modeli przebudowana (odkrywanie)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._test_worker: _TestWorker | None = None
        self._models_worker: _RefreshModelsWorker | None = None

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

        # aktywne źródło generacji (Vertex albo AI Studio) — od razu widoczne
        self.active_source_label = QLabel()
        self.active_source_label.setObjectName("mutedInfo")
        self.active_source_label.setWordWrap(True)
        api_layout.addWidget(self.active_source_label)

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

        # --- Źródło generacji: klucz AI Studio albo Vertex AI (ADC) ----------
        source_cap = QLabel("ŹRÓDŁO GENERACJI")
        source_cap.setObjectName("propKey")
        api_layout.addWidget(source_cap)
        self.source_seg = SegmentedControl(
            ["Google AI Studio (klucz)", "Vertex AI (ADC)"]
        )
        self.source_seg.changed.connect(self._on_source_changed)
        api_layout.addWidget(self.source_seg)
        vertex_row = QHBoxLayout()
        self.gcp_project_edit = QLineEdit(config.GCP_PROJECT)
        self.gcp_project_edit.setPlaceholderText("ID projektu GCP (np. moj-projekt-123)")
        vertex_row.addWidget(self.gcp_project_edit, stretch=2)
        self.gcp_location_edit = QLineEdit(config.GCP_LOCATION)
        self.gcp_location_edit.setPlaceholderText("region")
        self.gcp_location_edit.setFixedWidth(130)
        vertex_row.addWidget(self.gcp_location_edit, stretch=1)
        api_layout.addLayout(vertex_row)
        self.source_hint = QLabel()
        self.source_hint.setObjectName("hint")
        self.source_hint.setWordWrap(True)
        api_layout.addWidget(self.source_hint)
        self._sync_source_seg()

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

        model_header = QHBoxLayout()
        model_caption = QLabel("✦  MODEL GENERUJĄCY OBRAZ")
        model_caption.setObjectName("sectionTitle")
        model_header.addWidget(model_caption)
        model_header.addStretch(1)
        self.models_spinner = Spinner(18)
        self.models_spinner.hide()
        model_header.addWidget(self.models_spinner)
        self.refresh_models_btn = QPushButton("🔄  Odśwież listę")
        self.refresh_models_btn.setObjectName("ghostBtn")
        self.refresh_models_btn.setToolTip(
            "Pobiera z API wszystkie dostępne modele obrazowe "
            "(z aktywnego źródła: klucz / Vertex)"
        )
        self.refresh_models_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.refresh_models_btn.clicked.connect(self._refresh_models)
        model_header.addWidget(self.refresh_models_btn)
        model_layout.addLayout(model_header)

        self._model_group = QButtonGroup(self)
        self._model_group.setExclusive(True)
        self._model_buttons: dict[str, QPushButton] = {}
        self._model_grid = QGridLayout()
        self._model_grid.setSpacing(10)
        self._rebuild_model_grid()
        model_layout.addLayout(self._model_grid)
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
            ("/Style", "presety stylu — tła, rewers, prompty",
             config.STYLE_ROOT),
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

        # ============ PRAWA KOLUMNA: format talii + prompt ========================
        right_column = QVBoxLayout()
        right_column.setSpacing(10)

        format_panel = QWidget()
        format_panel.setObjectName("panel")
        format_layout = QVBoxLayout(format_panel)
        format_layout.setContentsMargins(14, 12, 14, 12)
        format_layout.setSpacing(8)

        size_caption = QLabel("⌗  FORMAT TALII")
        size_caption.setObjectName("sectionTitle")
        format_layout.addWidget(size_caption)
        self.size_combo = QComboBox()
        self.size_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, (label, _) in config.CARD_PRESETS.items():
            self.size_combo.addItem(label, key)
        self.size_combo.currentIndexChanged.connect(self._on_card_preset)
        format_layout.addWidget(self.size_combo)
        size_hint = QLabel("Eksport PDF trzyma się wybranego formatu w 300 DPI.")
        size_hint.setObjectName("hint")
        format_layout.addWidget(size_hint)

        styles_moved_hint = QLabel("✎ Presety stylu (postać, styl tła, tła przodu, "
                                   "rewers) edytujesz w zakładce „Style” — każda "
                                   "biblioteka ma własne presety zapisywane na "
                                   "dysku w folderze Style/.")
        styles_moved_hint.setObjectName("hint")
        styles_moved_hint.setWordWrap(True)
        format_layout.addWidget(styles_moved_hint)
        right_column.addWidget(format_panel)

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
        self._refresh_active_source()

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

    def _refresh_active_source(self) -> None:
        """Pokazuje aktualnie aktywne źródło generacji (Vertex / AI Studio)."""
        provider = config.active_provider_label()
        if provider:
            self.active_source_label.setText(f"Aktywne źródło generacji:  {provider}")
        else:
            self.active_source_label.setText(
                "Aktywne źródło generacji:  brak — uzupełnij klucz albo włącz Vertex."
            )
        self._sync_source_seg()

    def _sync_source_seg(self) -> None:
        """Ustawia przełącznik wg config (set_current nie emituje changed)."""
        index = 1 if config.USE_VERTEX else 0
        self.source_seg.set_current(index)
        self._on_source_changed(index)

    def _on_source_changed(self, index: int) -> None:
        """Przełączono źródło: pola GCP aktywne tylko dla Vertex + opis."""
        is_vertex = index == 1
        self.gcp_project_edit.setEnabled(is_vertex)
        self.gcp_location_edit.setEnabled(is_vertex)
        if is_vertex:
            self.source_hint.setText(
                "Vertex AI: billing/budżet projektu GCP, logowanie przez ADC "
                "(`gcloud auth application-default login`) — bez klucza API. "
                "Region np. us-central1; modele Gemini 3 Image używają endpointu "
                "„global” automatycznie. Wybór zapisuje „Zapisz klucze”."
            )
        else:
            self.source_hint.setText(
                "Google AI Studio: generacja przez klucz GEMINI_API_KEY "
                "(wymaga włączonego billingu na https://aistudio.google.com/). "
                "Wybór zapisuje „Zapisz klucze”."
            )

    # --- model ------------------------------------------------------------------------
    def sync_model(self) -> None:
        """Zaznacza kartę aktualnie wybranego modelu."""
        for key, btn in self._model_buttons.items():
            btn.setChecked(key == config.SELECTED_MODEL)

    def refresh_model(self) -> None:   # zgodność ze starym API kontrolera
        self.sync_model()

    def _rebuild_model_grid(self) -> None:
        """(Prze)buduje siatkę kart modeli z config.MODELS."""
        for btn in self._model_buttons.values():
            self._model_group.removeButton(btn)
            btn.deleteLater()
        while self._model_grid.count():
            self._model_grid.takeAt(0)
        self._model_buttons.clear()

        for i, (key, model) in enumerate(config.MODELS.items()):
            provider = PROVIDER_TAGS.get(model["provider"], model["provider"])
            description = MODEL_DESCRIPTIONS.get(
                key, "Model obrazowy wykryty przez API."
            )
            if "preview" in key and "preview" not in description.lower():
                description += "   · preview"
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
            self._model_grid.addWidget(btn, i // 2, i % 2)
            self._model_buttons[key] = btn
        self.sync_model()

    def _refresh_models(self) -> None:
        """Pobiera z API listę wszystkich dostępnych modeli obrazowych."""
        if self._models_worker is not None:
            return
        self.refresh_models_btn.setEnabled(False)
        self.models_spinner.show()
        worker = _RefreshModelsWorker()
        worker.finished_ok.connect(self._models_done)
        worker.finished_error.connect(self._models_failed)
        self._models_worker = worker
        worker.start()

    def _models_done(self, discovered: dict) -> None:
        self._models_worker = None
        self.refresh_models_btn.setEnabled(True)
        self.models_spinner.hide()
        config.merge_discovered_models(discovered)
        config.save_models_cache(discovered)
        if config.SELECTED_MODEL not in config.MODELS:
            config.SELECTED_MODEL = config.DEFAULT_MODEL
            show_toast(self, "Wybrany model zniknął z API — wracam do "
                             "domyślnego", "info")
        self._rebuild_model_grid()
        self.models_refreshed.emit()
        show_toast(self, f"Modele obrazowe: {len(config.MODELS)} "
                         f"(API zwróciło {len(discovered)})", "ok")

    def _models_failed(self, message: str) -> None:
        self._models_worker = None
        self.refresh_models_btn.setEnabled(True)
        self.models_spinner.hide()
        show_toast(self, f"Nie pobrano listy modeli: {message}", "error")

    # --- format talii -----------------------------------------------------------------
    def sync_styles(self) -> None:
        """Ustawia kontrolki wg config (bez emitowania zmian)."""
        size_index = self.size_combo.findData(config.SELECTED_CARD_PRESET)
        self.size_combo.blockSignals(True)
        if size_index >= 0:
            self.size_combo.setCurrentIndex(size_index)
        self.size_combo.blockSignals(False)

    def _on_card_preset(self, _index: int) -> None:
        key = self.size_combo.currentData()
        config.set_card_preset(key)
        self.card_preset_changed.emit(key)

    # --- prompt -----------------------------------------------------------------------
    def refresh_prompt(self) -> None:
        """Składa podgląd promptu z aktywnych presetów stylu."""
        actives = "   ·   ".join(
            f"{style_store.CATEGORY_LABELS[cat]}: {style_store.active(cat)}"
            for cat in style_store.CATEGORIES
        )
        self.prompt_preview.setPlainText(
            f"AKTYWNE PRESETY:  {actives}\n\n"
            "STYL POSTACI:\n"
            + style_store.character_style().strip()
            + "\n\nSTYL TŁA / SZABLONU (edycja w zakładce Style):\n"
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
        self._refresh_active_source()
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
        use_vertex = self.source_seg.current() == 1
        project = self.gcp_project_edit.text().strip()
        location = self.gcp_location_edit.text().strip() or "us-central1"
        set_key(str(env_path), "GEMINI_API_KEY", gemini)
        set_key(str(env_path), "CUSTOM_API_KEY", custom)
        set_key(str(env_path), "GOOGLE_GENAI_USE_VERTEXAI",
                "true" if use_vertex else "false")
        set_key(str(env_path), "GOOGLE_CLOUD_PROJECT", project)
        set_key(str(env_path), "GOOGLE_CLOUD_LOCATION", location)
        config.GEMINI_API_KEY = gemini
        config.CUSTOM_API_KEY = custom
        config.USE_VERTEX = use_vertex
        config.GCP_PROJECT = project
        config.GCP_LOCATION = location
        from app.api import gemini_client
        gemini_client.reset_client()
        self._refresh_active_source()
        self.keys_changed.emit()
        show_toast(self, "Zapisano ustawienia do .env", "ok")

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
