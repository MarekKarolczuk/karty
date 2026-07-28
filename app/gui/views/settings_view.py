"""Widok Ustawienia: klucze API (zapis do .env), wybór modelu, format talii,
foldery projektu i podgląd system-promptu. Biblioteki presetów stylu żyją
w zakładce „Style" (back_view)."""
from __future__ import annotations

from PyQt6.QtCore import QThread, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from app import config
from app.core import style_store
from app.gui.animations import Spinner
from app.gui.views import view_header
from app.gui.widgets import NoScrollComboBox, SegmentedControl, show_toast

MODEL_DESCRIPTIONS = {
    "gemini-2.5-flash-image": "Szybki inpainting image-to-image. "
                              "Najlepsza wierność detali.",
    "gemini-3-pro-image": "Najwyższa jakość ilustracji, wolniejszy.",
    "gemini-3.1-flash-image": "Nano Banana 2 — szybki i tani model GA, dobry "
                              "do większości kart.",
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


class SettingsView(QWidget):
    keys_changed = pyqtSignal()
    model_changed = pyqtSignal(str)
    card_preset_changed = pyqtSignal(str)
    # synchronizacja przez pendrive (app/core/sync.py)
    sync_export_clicked = pyqtSignal(str, str, str)   # katalog, autor, profil
    sync_import_clicked = pyqtSignal(str, bool)       # folder paczki, na sucho
    sync_changed = pyqtSignal()                       # zapis ustawień do projekt.json

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

        model_caption = QLabel("✦  MODEL GENERUJĄCY OBRAZ")
        model_caption.setObjectName("sectionTitle")
        model_layout.addWidget(model_caption)

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
        left_column.addWidget(self._build_sync_panel())
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
        self.size_combo = NoScrollComboBox()
        self.size_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        for key, (label, *_) in config.CARD_PRESETS.items():
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

    # --- synchronizacja przez pendrive ------------------------------------------------
    def _build_sync_panel(self) -> QWidget:
        """Panel wymiany stanu z drugim komputerem BEZ sieci: eksport paczki na
        pendrive i import paczki od kolegi. Sama logika siedzi w `core/sync.py`
        — widok tylko zbiera parametry i emituje sygnały (jak reszta widoków)."""
        panel = QWidget()
        panel.setObjectName("panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        caption = QLabel("🔄  SYNCHRONIZACJA (pendrive)")
        caption.setObjectName("sectionTitle")
        lay.addWidget(caption)

        hint = QLabel("Wymiana talii z drugim komputerem bez internetu. Import "
                      "NIC NIE KASUJE: kolidująca karta wchodzi jako nowy "
                      "wariant, a przy rozbieżnościach zostaje Twoja wersja.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        autor_row = QHBoxLayout()
        autor_row.setSpacing(6)
        autor_caption = QLabel("Twoje imię")
        autor_caption.setObjectName("propKey")
        autor_row.addWidget(autor_caption)
        self.sync_autor_edit = QLineEdit()
        self.sync_autor_edit.setPlaceholderText("np. Marek — trafi do nazw "
                                                "plików przy kolizjach")
        self.sync_autor_edit.editingFinished.connect(self.sync_changed.emit)
        autor_row.addWidget(self.sync_autor_edit, stretch=1)
        lay.addLayout(autor_row)

        folder_row = QHBoxLayout()
        folder_row.setSpacing(6)
        self.sync_folder_edit = QLineEdit()
        self.sync_folder_edit.setPlaceholderText("folder pendrive'a lub paczki…")
        self.sync_folder_edit.editingFinished.connect(self.sync_changed.emit)
        folder_row.addWidget(self.sync_folder_edit, stretch=1)
        wybierz = QPushButton("Wybierz…")
        wybierz.setObjectName("ghostBtn")
        wybierz.setCursor(Qt.CursorShape.PointingHandCursor)
        wybierz.clicked.connect(self._pick_sync_folder)
        folder_row.addWidget(wybierz)
        lay.addLayout(folder_row)

        profil_row = QHBoxLayout()
        profil_row.setSpacing(6)
        profil_caption = QLabel("Zawartość")
        profil_caption.setObjectName("propKey")
        profil_row.addWidget(profil_caption)
        self.sync_profil_combo = NoScrollComboBox()
        for etykieta, wartosc in (
            ("Pełna (wszystko)", "pelny"),
            ("Robocza (bez surowych PNG i historii pudełka)", "roboczy"),
            ("Przypisane (użyte zdjęcia + gotowe karty + style)", "przypisane"),
            ("Lekka (same ustawienia i maski)", "lekki"),
        ):
            self.sync_profil_combo.addItem(etykieta, wartosc)
        self.sync_profil_combo.setToolTip(
            "Pełna = dokładna kopia stanu (kilka GB, wszystko działa).\n"
            "Robocza = bez output/_raw i historii pudełka — u odbiorcy nie "
            "zadziała „Przestempluj” ani selektywna poprawka przywiezionych kart.\n"
            "Przypisane = tylko zdjęcia realnie użyte w talii (bez archiwum "
            "odrzutów z folderu zdjęć) + gotowe karty + presety stylu; jak "
            "Robocza, ale zwykle kilkakrotnie mniejsza.\n"
            "Lekka = same presety tekstowe i maski (kilkanaście MB).")
        self.sync_profil_combo.currentIndexChanged.connect(
            lambda _=0: self.sync_changed.emit())
        profil_row.addWidget(self.sync_profil_combo, stretch=1)
        lay.addLayout(profil_row)

        akcje = QHBoxLayout()
        akcje.setSpacing(6)
        self.sync_spinner = Spinner(16)
        self.sync_spinner.hide()
        akcje.addWidget(self.sync_spinner)
        self.sync_export_btn = QPushButton("📤  Eksportuj paczkę")
        self.sync_export_btn.setObjectName("ghostBtn")
        self.sync_export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_export_btn.clicked.connect(self._emit_sync_export)
        akcje.addWidget(self.sync_export_btn, stretch=1)
        lay.addLayout(akcje)

        akcje2 = QHBoxLayout()
        akcje2.setSpacing(6)
        self.sync_dry_btn = QPushButton("🔍  Próbnie")
        self.sync_dry_btn.setObjectName("ghostBtn")
        self.sync_dry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_dry_btn.setToolTip("Pokazuje, co wejdzie, bez zapisywania "
                                     "czegokolwiek — rób to przed importem.")
        self.sync_dry_btn.clicked.connect(
            lambda: self._emit_sync_import(True))
        akcje2.addWidget(self.sync_dry_btn)
        self.sync_import_btn = QPushButton("📥  Wczytaj paczkę")
        self.sync_import_btn.setObjectName("ghostBtn")
        self.sync_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.sync_import_btn.clicked.connect(
            lambda: self._emit_sync_import(False))
        akcje2.addWidget(self.sync_import_btn, stretch=1)
        lay.addLayout(akcje2)

        self.sync_status = QLabel("")
        self.sync_status.setObjectName("hint")
        self.sync_status.setWordWrap(True)
        lay.addWidget(self.sync_status)
        return panel

    def _pick_sync_folder(self) -> None:
        start = self.sync_folder_edit.text().strip() or str(config.ROOT.parent)
        wybrany = QFileDialog.getExistingDirectory(
            self, "Folder pendrive'a (eksport) albo folder paczki (import)",
            start)
        if wybrany:
            self.sync_folder_edit.setText(wybrany)
            self.sync_changed.emit()

    def _emit_sync_export(self) -> None:
        folder = self.sync_folder_edit.text().strip()
        if not folder:
            show_toast(self, "Wskaż folder, w którym powstanie paczka", "warn")
            return
        self.sync_export_clicked.emit(
            folder, self.sync_autor_edit.text().strip(),
            self.sync_profil_combo.currentData() or "pelny")

    def _emit_sync_import(self, sucho: bool) -> None:
        folder = self.sync_folder_edit.text().strip()
        if not folder:
            show_toast(self, "Wskaż folder paczki (AtelierKart_paczka_…)", "warn")
            return
        self.sync_import_clicked.emit(folder, sucho)

    def set_sync_busy(self, busy: bool) -> None:
        for btn in (self.sync_export_btn, self.sync_import_btn, self.sync_dry_btn):
            btn.setEnabled(not busy)
        self.sync_spinner.setVisible(busy)

    def set_sync_status(self, tekst: str) -> None:
        self.sync_status.setText(tekst)

    def sync_settings(self) -> dict:
        return {"autor": self.sync_autor_edit.text().strip(),
                "folder": self.sync_folder_edit.text().strip(),
                "profil": self.sync_profil_combo.currentData() or "pelny"}

    def load_sync_settings(self, data: dict) -> None:
        self.sync_autor_edit.setText(str(data.get("autor", "")))
        self.sync_folder_edit.setText(str(data.get("folder", "")))
        idx = self.sync_profil_combo.findData(data.get("profil", "pelny"))
        if idx >= 0:
            self.sync_profil_combo.setCurrentIndex(idx)

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
            description = MODEL_DESCRIPTIONS.get(key, "Model obrazowy Gemini.")
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
        front_mode = (" — TRYB WŁASNY (prompt wysyłany dosłownie)"
                      if style_store.front_custom_mode() else "")
        self.prompt_preview.setPlainText(
            f"AKTYWNE PRESETY:  {actives}\n\n"
            "STYL POSTACI:\n"
            + style_store.character_style().strip()
            + "\n\nSTYL ORNAMENTYKI (edycja w zakładce Style, sekcja Tła "
              "przodu):\n"
            + style_store.template_style().strip()
            + f"\n\nTŁO PRZODU — CZERWONE (Kier/Karo){front_mode}:\n"
            + style_store.front_prompt(True).strip()
            + f"\n\nTŁO PRZODU — CZARNE (Pik/Trefl){front_mode}:\n"
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
