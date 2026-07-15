"""Główne okno (frameless) „Atelier Kart":
TitleBar → [Sidebar | FadingStackedWidget z 7 widokami] → pasek statusu.

MainWindow pełni rolę kontrolera: trzyma stan (przypisania, workery,
projekt.json), widoki są warstwą UI komunikującą się sygnałami.
"""
from __future__ import annotations

import json
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QCursor, QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from app import config
from app.core import photo_analyzer, prompts, style_store
from app.core.exporter import ExportJob
from app.core.models import CardSpec, GenMode, Suit
from app.gui import card_grid
from app.gui.animations import BusyOverlay, FadingStackedWidget
from app.gui.auto_assign_dialog import AutoAssignDialog
from app.gui.fix_dialog import FixRegionDialog
from app.gui.mask_editor import MaskEditorDialog
from app.gui.card_grid import CardSlot
from app.gui.lightbox import CardLightbox, LightboxContext
from app.gui.photo_gallery import load_thumbnail
from app.gui.sidebar import Sidebar
from app.gui.title_bar import TitleBar
from app.gui.views.back_view import BackView
from app.gui.views.deck_view import DeckView
from app.gui.views.export_view import ExportView
from app.gui.views.photo_library_view import PhotoLibraryView
from app.gui.views.settings_view import SettingsView
from app.gui.views.workspace_view import WorkspaceView
from app.gui.widgets import show_toast
from app.gui.worker import (
    AnalysisWorker, BackWorker, ExportWorker, FixWorker, GenerationWorker,
    RestampWorker, SampleWorker, TemplateSetWorker, TemplateWorker,
)

class MainWindow(QMainWindow):
    _deck_values: list[str] = list(config.DEFAULT_VALUES)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Atelier Kart — generator talii 63×88 mm")
        # natywny pasek tytułu Windows (ikona, tytuł, ─ ▢ ✕, snap, animacje);
        # ciemny pasek z logo/API zostaje jako toolbar pod spodem (TitleBar)
        self.resize(1560, 960)

        # przypisania: "kier:A" -> ścieżka zdjęcia
        self.assignments: dict[str, str] = {}
        # kadrowanie per karta: "kier:A" -> {"zoom","dx","dy"}
        self.transforms: dict[str, dict] = {}
        # pozycja w historii wariantów per karta: "kier:A" -> index
        self.card_history_pos: dict[str, int] = {}
        # wybrany wariant per karta: "kier:A" -> ścieżka pliku (talia/eksport)
        self.selections: dict[str, str] = {}
        # karty nieudane w bieżącej serii (do ponowienia)
        self._failed_specs: list[CardSpec] = []
        # guard: po anulowaniu ignorujemy spóźnione sygnały porzuconych wątków
        self._gen_cancelled = False
        # guard: po błędzie krytycznym _on_finished nie nadpisuje komunikatu
        self._gen_fatal = False
        # porzucone wątki trzymamy tu, dopóki się nie zakończą (inaczej GC
        # zniszczyłby żywy QThread → „Destroyed while thread is still running")
        self._abandoned: list = []
        # aktualnie wybrana karta na Ekranie roboczym
        self._current_suit: Suit = Suit.KIER
        self._current_value: str = "A"
        self.worker: GenerationWorker | None = None
        self.template_worker: TemplateWorker | TemplateSetWorker | None = None
        self.back_worker: BackWorker | None = None
        self.export_worker: ExportWorker | None = None
        self.sample_worker: SampleWorker | None = None
        self.restamp_worker: RestampWorker | None = None
        self.fix_worker: FixWorker | None = None
        self.analysis_worker: AnalysisWorker | None = None
        # auto-przydział: edytowalne motywy kolorów + stan bieżącej sesji
        self.auto_motywy: dict[str, str] = dict(photo_analyzer.DOMYSLNE_MOTYWY)
        self._auto_dialog: AutoAssignDialog | None = None
        self._auto_propozycje: list = []
        self._auto_nadpisz = False
        self._analysis_cancelled = False
        self._analysis_fatal = False
        self.deck_name: str = "Rodzinna talia"

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(10, 8, 10, 10)
        root_layout.setSpacing(10)
        self.title_bar = TitleBar(self)
        self.title_bar.settings_requested.connect(self._open_settings)
        root_layout.addWidget(self.title_bar)

        body = QHBoxLayout()
        body.setSpacing(10)

        self.sidebar = Sidebar()
        self.sidebar.view_selected.connect(self._switch_view)
        self.sidebar.new_deck_clicked.connect(self._new_deck)
        body.addWidget(self.sidebar)

        # --- widoki (kolejność = indeksy w sidebarze) ----------------------------
        self.workspace = WorkspaceView()
        self.photo_library = PhotoLibraryView()
        self.deck = DeckView()
        self.back_view = BackView()
        self.settings_view = SettingsView()
        self.export_view = ExportView()
        # panel generacji wchłonięty przez Ekran roboczy — alias dla kontrolera
        self.generation = self.workspace.gen_panel
        # podgląd wygenerowanych kart to teraz siatka w zakładce Talie
        self.gallery = self.deck   # DeckView.mark_dirty() odświeża podgląd/historię
        self.grids = self.deck.grids

        self.stack = FadingStackedWidget()
        for view in (self.workspace, self.photo_library, self.deck,
                     self.back_view, self.settings_view, self.export_view):
            self.stack.addWidget(view)
        body.addLayout(self._wrap_stack(), stretch=1)
        root_layout.addLayout(body, stretch=1)

        # nakładka „Przetwarzanie AI…" nad podglądem Ekranu roboczego
        self.busy_overlay = BusyOverlay(self.workspace.preview)

        root_layout.addWidget(self._build_status_bar())

        self.deck.set_variant_resolver(self._selected_variant)
        self.deck.set_variant_counter(
            lambda suit, value: len(self._card_variants(suit, value)))
        self._lightbox: CardLightbox | None = None
        self._wire_views()
        self._load_project()
        # suwak kreskówki czyta pole aktywnego presetu postaci (po load)
        self.workspace.set_cartoon_level(style_store.cartoon_level())
        self.workspace.refresh_mask_presets()
        self._rebuild_grids(self._values())
        self._load_generated_state()   # pokaż karty z poprzednich sesji
        self._refresh_overview()
        self._refresh_used_photos()
        self._refresh_estimate()
        self._refresh_api_status()
        if config.api_ready():
            self._set_status("Gotowe — przypisz zdjęcia do kart i kliknij GENERUJ")
        else:
            self._set_status("Zacznij od skonfigurowania API w Ustawieniach (⚙) "
                             "— kliknij pigułkę API u góry")

    def _wrap_stack(self) -> QVBoxLayout:
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(self.stack)
        return wrap

    # ------------------------------------------------------------------ okablowanie
    def _wire_views(self) -> None:
        ws = self.workspace
        ws.gallery_panel.photo_deleted.connect(self._on_photo_deleted)
        ws.card_picked.connect(self._select_card)
        ws.regenerate_clicked.connect(self._regenerate_single)
        ws.generate_deck_clicked.connect(self._generate_from_workspace)
        ws.unassign_clicked.connect(self._unassign_card)
        ws.grid_photo_dropped.connect(self._on_grid_photo_dropped)
        ws.preview_photo_dropped.connect(self._on_preview_photo_dropped)
        ws.transform_changed.connect(self._on_transform_changed)
        ws.transform_committed.connect(self._on_transform_committed)
        ws.history_navigate.connect(self._on_history_navigate)
        ws.history_set_main.connect(self._on_history_set_main)
        ws.fix_requested.connect(self._on_workspace_fix)
        ws.restamp_clicked.connect(self._start_restamp)
        ws.auto_assign_clicked.connect(self._start_auto_assign)
        ws.edit_mask_requested.connect(self._open_mask_editor)
        ws.cartoon_level_changed.connect(self._on_cartoon_level_changed)
        ws.mask_preset_selected.connect(self._on_mask_preset_selected)

        self.photo_library.photo_deleted.connect(self._on_photo_deleted)
        self.photo_library.photos_imported.connect(self._on_photos_imported)

        # Talie = podgląd (klik → lightbox obsługiwany wewnątrz DeckView);
        # zostaje tylko menu zarządzania plikami i edycja wartości.
        self.deck.slot_right_clicked.connect(self._on_slot_menu)
        self.deck.edit_values_clicked.connect(self._edit_values)
        self.deck.deck_name_changed.connect(self._on_deck_name_changed)
        self.deck.restamp_clicked.connect(self._start_restamp)
        self.deck.lightbox_requested.connect(self._open_lightbox)
        self.deck.preview_file_requested.connect(self._preview_file)

        gen = self.generation
        gen.generate_clicked.connect(self._start_generation)
        gen.pause_clicked.connect(self._toggle_pause)
        gen.retry_clicked.connect(self._retry_failed)
        gen.mode_seg.changed.connect(
            lambda _=0: self.workspace.set_hybrid_mode(self._mode() is GenMode.HYBRID)
        )
        # licznik szacunkowy serii — odśwież po zmianie opcji generacji
        gen.skip_done_check.toggled.connect(lambda _=False: self._refresh_estimate())
        gen.limit_spin.valueChanged.connect(lambda _=0: self._refresh_estimate())
        gen.versions_spin.valueChanged.connect(lambda _=0: self._refresh_estimate())

        self.settings_view.model_changed.connect(self._on_model_changed)
        self.settings_view.keys_changed.connect(self._refresh_api_status)
        self.settings_view.card_preset_changed.connect(self._on_card_preset_changed)

        # edycja stylu postaci w zakładce „Style" → zapis + odśwież podgląd promptu
        self.back_view.character_changed.connect(self._save_project)
        self.back_view.character_changed.connect(self.settings_view.refresh_prompt)
        # zmiana struktury presetów (nowy/usuń/import) → odśwież podgląd + zapis
        self.back_view.style_slot_changed.connect(self.settings_view.refresh_prompt)
        self.back_view.style_slot_changed.connect(self._save_project)
        # aktywowano preset kategorii → zastosuj do roboczego wyglądu talii
        self.back_view.preset_applied.connect(self._on_preset_applied)
        self.back_view.generate_sample_clicked.connect(self._generate_sample)
        self.back_view.generate_back_clicked.connect(self._start_back_generation)
        self.back_view.generate_front_clicked.connect(self._start_front_generation)
        self.back_view.generate_front_set_clicked.connect(self._start_front_set)
        self.back_view.import_front_clicked.connect(self._on_front_import)
        self.back_view.normalize_fronts_clicked.connect(self._on_front_normalize)
        # maska pop-out CAŁEGO koloru (widok Style) — wspólny handler z maską
        # per karta z Ekranu roboczego (pusta wartość = zakres koloru)
        self.back_view.edit_mask_clicked.connect(
            lambda suit_nazwa: self._open_mask_editor(suit_nazwa, ""))
        self.back_view.mask_library_changed.connect(
            self._on_mask_library_changed)
        self.export_view.export_clicked.connect(self._start_export)
        self.export_view.options_changed.connect(self._save_project)

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        self.status_text = QLabel()
        self.status_text.setObjectName("statusText")
        layout.addWidget(self.status_text, stretch=1)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(240)
        self.progress.hide()
        layout.addWidget(self.progress)

        self.cancel_btn = QPushButton("Przerwij")
        self.cancel_btn.setObjectName("ghostBtn")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self._cancel_generation)
        self.cancel_btn.hide()
        layout.addWidget(self.cancel_btn)
        return bar

    # ------------------------------------------------------------- pomocnicze stany
    def _switch_view(self, index: int) -> None:
        self.stack.fade_to(index)

    _SETTINGS_INDEX = 4   # kolejność wg VIEWS w sidebarze

    def _open_settings(self) -> None:
        """Skok do Ustawień (np. z klikniętej pigułki API na pasku tytułu)."""
        self.sidebar.set_current(self._SETTINGS_INDEX)
        self._switch_view(self._SETTINGS_INDEX)

    def _values(self) -> list[str]:
        return list(self._deck_values)

    def _mode(self) -> GenMode:
        return GenMode.HYBRID if self.generation.mode_seg.current() == 0 \
            else GenMode.FULL_AI

    def _on_model_changed(self, key: str) -> None:
        if key not in config.MODELS or key == config.SELECTED_MODEL:
            self._sync_model_views()
            return
        config.SELECTED_MODEL = key
        model = config.current_model()
        if model["provider"] != "gemini" and self._mode() is GenMode.FULL_AI:
            self.generation.mode_seg.set_current(0)
            show_toast(self, "Pełne AI wymaga Gemini — przełączono na tryb "
                             "hybrydowy", "info")
        self._sync_model_views()
        self._set_status(f"Model: {model['label']}")
        self._save_project()

    def _sync_model_views(self) -> None:
        self.generation.refresh_engine()
        self.settings_view.sync_model()
        # „Pełne AI" wymaga Gemini — blokujemy segment na modelach Stability
        is_gemini = config.current_model()["provider"] == "gemini"
        self.generation.set_full_ai_enabled(is_gemini)
        self.workspace.set_hybrid_mode(self._mode() is GenMode.HYBRID)
        self._refresh_estimate()

    def _refresh_api_status(self) -> None:
        self.title_bar.refresh_api_status(config.api_ready())
        # backend (Vertex/AI Studio) mógł się zmienić → odśwież pole „Silnik"
        self.generation.refresh_engine()

    def _set_status(self, text: str) -> None:
        self.status_text.setText(text)
        self.generation.log_pane.log_line(text)

    def _show_preview(self, pixmap) -> None:
        self.workspace.preview.show_preview(pixmap)

    def _edit_values(self) -> None:
        from PyQt6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(
            self, "Wartości talii", "Wartości kart (po przecinku):",
            text=", ".join(self._values()),
        )
        if ok:
            values = [v.strip() for v in text.split(",") if v.strip()]
            if values:
                self._rebuild_grids(values)
                self._set_status(f"Talia: {len(values)} wartości × 4 kolory")

    def _update_badges(self) -> None:
        # indeks 0 filtra to "Wszystkie" — badge'e kolorów zaczynają się od 1
        for i, suit in enumerate(Suit, start=1):
            count = sum(
                1 for slot in self.grids[suit].slots.values()
                if slot.photo_path is not None
            )
            badge = str(count) if count else ""
            self.deck.suit_seg.set_badge(i, badge)
            self.workspace.deck_panel.suit_seg.set_badge(i, badge)

    def _deck_progress(self) -> tuple[int, int, int]:
        """(gotowe, wszystkie, w toku) — karta gotowa, gdy istnieje jej wybrany
        wariant; w toku = ma przypisane zdjęcie, ale jeszcze nie wygenerowana."""
        values = self._values()
        total = len(values) * len(Suit)
        done = pending = 0
        for suit in Suit:
            for value in values:
                slot = self.grids[suit].slots.get(value)
                if self._selected_variant(suit.nazwa, value) is not None:
                    done += 1
                elif slot is not None and slot.photo_path is not None:
                    pending += 1
        return done, total, pending

    def _load_generated_state(self) -> None:
        """Wczytuje z dysku stan wygenerowanych kart do slotów siatki — dzięki
        temu karty z poprzednich sesji są widoczne od razu po starcie (siatki
        Talii i Ekranu roboczego), nie dopiero po kolejnej generacji."""
        for suit in Suit:
            for value, slot in self.grids[suit].slots.items():
                selected = self._selected_variant(suit.nazwa, value)
                if selected is not None and slot.generated_path != selected:
                    slot.set_generated(selected)

    def _refresh_overview(self) -> None:
        """Sidebar (postęp, liczniki), siatka talii Ekranu roboczego i licznik
        eksportu — po każdej zmianie."""
        done, total, pending = self._deck_progress()
        self.sidebar.set_deck_progress(done, total, pending)
        # indeksy sidebara: 0 Ekran roboczy · 2 Talie
        self.sidebar.set_badge(0, pending)    # Ekran roboczy — do generacji
        self.sidebar.set_badge(2, done)       # Talie — gotowe
        self.workspace.sync_deck(self._values(), self.grids)
        self.export_view.set_ready_info(done, total)

    # --------------------------------------------------------------- nowa talia
    def _new_deck(self) -> None:
        answer = QMessageBox.question(
            self, "Nowa talia?",
            "Wyczyścić wszystkie przypisania zdjęć?\n"
            "(Wygenerowane pliki w output/ zostają na dysku.)",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.assignments.clear()
        self.transforms.clear()
        self.deck_name = "Nowa talia"
        self.deck.set_deck_name(self.deck_name)
        self._rebuild_grids(list(config.DEFAULT_VALUES))
        self._set_status("Nowa talia — przypisz zdjęcia do kart")

    def _on_deck_name_changed(self, name: str) -> None:
        self.deck_name = name.strip() or "Talia bez nazwy"
        self._save_project()

    def _on_photos_imported(self, _count: int) -> None:
        """Import w Galerii zdjęć — odśwież pulę zdjęć na Ekranie roboczym."""
        self.workspace.gallery_panel.reload()

    # --------------------------------------------------------------- przypisywanie
    def _key(self, slot: CardSlot) -> str:
        return f"{slot.suit.nazwa}:{slot.value}"

    def _select_card(self, suit_nazwa: str, value: str) -> None:
        """Wybór karty z siatki talii / klawiatury wartości / siatki kolorów."""
        slot = self.grids[Suit.from_nazwa(suit_nazwa)].slots.get(value)
        if slot is None:
            return
        self._current_suit = Suit.from_nazwa(suit_nazwa)
        self._current_value = value
        self.workspace.show_card(slot)
        self.workspace.set_transform(self.transforms.get(f"{suit_nazwa}:{value}"))
        shown = slot.generated_path or slot.photo_path
        if shown is not None:
            self.workspace.preview.show_preview(load_thumbnail(shown, 900))
        else:
            try:
                self.workspace.preview.show_preview(
                    load_thumbnail(slot.suit.template_path, 900)
                )
            except FileNotFoundError:   # świeży preset bez tła tego koloru
                self.workspace.preview.clear_preview()
        self._refresh_history(suit_nazwa, value)

    def _unassign_card(self, suit_nazwa: str, value: str) -> None:
        slot = self.grids[Suit.from_nazwa(suit_nazwa)].slots.get(value)
        if slot is None or slot.photo_path is None:
            return
        key = f"{suit_nazwa}:{value}"
        self.assignments.pop(key, None)
        self.transforms.pop(key, None)
        slot.set_photo(None)
        self._after_assignment_change()
        self.workspace.show_card(slot)
        # natychmiast czyścimy podgląd do samego szablonu
        self.workspace.preview.show_preview(
            load_thumbnail(slot.suit.template_path, 900)
        )

    def _on_grid_photo_dropped(self, key: str, path: str) -> None:
        """Upuszczenie zdjęcia na slot siatki talii Ekranu roboczego."""
        suit_nazwa, value = key.split(":", 1)
        slot = self.grids[Suit.from_nazwa(suit_nazwa)].slots.get(value)
        if slot is not None:
            self._on_photo_dropped(slot, path)

    def _on_preview_photo_dropped(self, path: str) -> None:
        """Upuszczenie zdjęcia na duży podgląd = szybka podmiana (swap)
        zdjęcia na aktualnie wybranej karcie."""
        slot = self.grids[self._current_suit].slots.get(self._current_value)
        if slot is None:
            show_toast(self, "Najpierw wybierz kartę", "info")
            return
        swapped = slot.photo_path is not None
        self._on_photo_dropped(slot, path)
        show_toast(self, "Podmieniono zdjęcie" if swapped
                   else "Przypisano zdjęcie", "ok")

    # ------------------------------------------------------------ historia karty
    def _card_variants(self, suit_nazwa: str, value: str) -> list[Path]:
        """Wszystkie wygenerowane warianty karty w output/, od najstarszego."""
        base = f"{value}_{suit_nazwa}"
        files = list(config.OUTPUT_DIR.glob(f"{base}.jpg")) \
            + list(config.OUTPUT_DIR.glob(f"{base}_v*.jpg"))
        return sorted(files, key=lambda p: p.stat().st_mtime)

    def _selected_variant(self, suit_nazwa: str, value: str) -> Path | None:
        """Wybrany wariant karty (talia/eksport). Wskaźnik z projekt.json, a gdy
        go brak / plik zniknął — najnowszy istniejący wariant."""
        key = f"{suit_nazwa}:{value}"
        chosen = self.selections.get(key)
        if chosen and Path(chosen).exists():
            return Path(chosen)
        variants = self._card_variants(suit_nazwa, value)
        return variants[-1] if variants else None

    def _next_variant_index(self, suit_nazwa: str, value: str) -> int:
        """Następny wolny numer wariantu — generacja DOKŁADA, nie nadpisuje."""
        base = f"{value}_{suit_nazwa}"
        indices = [1] if (config.OUTPUT_DIR / f"{base}.jpg").exists() else []
        for p in config.OUTPUT_DIR.glob(f"{base}_v*.jpg"):
            try:
                indices.append(int(p.stem.rsplit("_v", 1)[1]))
            except (ValueError, IndexError):
                continue
        return (max(indices) + 1) if indices else 1

    def _refresh_history(self, suit_nazwa: str, value: str) -> None:
        """Odświeża nawigator historii dla wskazanej karty."""
        variants = self._card_variants(suit_nazwa, value)
        key = f"{suit_nazwa}:{value}"
        if not variants:
            self.card_history_pos.pop(key, None)
            self.workspace.set_history(0, 0)
            return
        # domyślnie ustawiamy nawigator na WYBRANYM wariancie (nie najnowszym)
        if key not in self.card_history_pos:
            selected = self._selected_variant(suit_nazwa, value)
            default = variants.index(selected) if selected in variants \
                else len(variants) - 1
        else:
            default = self.card_history_pos[key]
        pos = max(0, min(default, len(variants) - 1))
        self.card_history_pos[key] = pos
        self.workspace.set_history(pos, len(variants))

    def _on_history_navigate(self, suit_nazwa: str, value: str,
                             direction: int) -> None:
        variants = self._card_variants(suit_nazwa, value)
        if not variants:
            return
        key = f"{suit_nazwa}:{value}"
        pos = self.card_history_pos.get(key, len(variants) - 1) + direction
        pos = max(0, min(pos, len(variants) - 1))
        self.card_history_pos[key] = pos
        self.workspace.set_history(pos, len(variants))
        self.workspace.preview.show_preview(load_thumbnail(variants[pos], 900))
        self._set_status(f"Historia {value}{Suit.from_nazwa(suit_nazwa).symbol}: "
                         f"wariant {pos + 1}/{len(variants)} — {variants[pos].name}")

    def _on_history_set_main(self, suit_nazwa: str, value: str) -> None:
        """Ustawia pokazywany wariant jako wybrany — WSKAŹNIK, bez kopiowania
        i bez niszczenia plików puli."""
        variants = self._card_variants(suit_nazwa, value)
        if not variants:
            return
        key = f"{suit_nazwa}:{value}"
        pos = max(0, min(self.card_history_pos.get(key, len(variants) - 1),
                         len(variants) - 1))
        chosen = variants[pos]
        self.selections[key] = str(chosen)
        slot = self.grids[Suit.from_nazwa(suit_nazwa)].slots.get(value)
        if slot is not None:
            slot.set_generated(chosen)
        self.gallery.mark_dirty()
        self._refresh_overview()
        self._refresh_history(suit_nazwa, value)
        self._save_project()
        show_toast(self, f"✓ {value}{Suit.from_nazwa(suit_nazwa).symbol}: "
                   "użyto tego wariantu", "ok")

    def _on_transform_changed(self, suit_nazwa: str, value: str,
                              transform: dict) -> None:
        """Suwaki kadrowania — zapis + tani podgląd na żywo (niska rozdzielczość)."""
        key = f"{suit_nazwa}:{value}"
        if key not in self.assignments:
            return
        self.transforms[key] = transform
        try:
            from app.core import compositor
            from app.gui.widgets import pil_to_pixmap
            suit = Suit.from_nazwa(suit_nazwa)
            init = compositor.build_init_image(
                suit, Path(self.assignments[key]), transform, max_side=640
            )
            self.workspace.preview.show_preview(pil_to_pixmap(init))
        except (OSError, ValueError, RuntimeError):
            pass

    def _on_transform_committed(self, suit_nazwa: str, value: str,
                                transform: dict) -> None:
        key = f"{suit_nazwa}:{value}"
        if key in self.assignments:
            self.transforms[key] = transform
        self._save_project()

    def _generate_from_workspace(self) -> None:
        """Przycisk „Generuj talię" na Ekranie roboczym — startuje serię w miejscu."""
        self._start_generation()

    def _regenerate_single(self, suit_nazwa: str, value: str) -> None:
        slot = self.grids[Suit.from_nazwa(suit_nazwa)].slots.get(value)
        if slot is None:
            return
        if slot.photo_path is None:
            show_toast(self, "Najpierw przypisz zdjęcie do tej karty", "error")
            return
        if self.worker is not None:
            show_toast(self, "Poczekaj — trwa generacja", "info")
            return
        if not self._guard_api_ready() or not self._guard_full_ai():
            return
        suit = Suit.from_nazwa(suit_nazwa)
        transform = self.transforms.get(f"{suit_nazwa}:{value}")
        count = max(1, self.generation.versions_spin.value())
        start = self._next_variant_index(suit_nazwa, value)
        specs = [
            CardSpec(value=value, suit=suit, photo_path=slot.photo_path,
                     mode=self._mode(), variant=v, transform=transform)
            for v in range(start, start + count)
        ]
        self._run_generation(specs)

    def _on_photo_dropped(self, slot: CardSlot, path: str) -> None:
        self.assignments[self._key(slot)] = path
        slot.set_photo(Path(path))
        self._after_assignment_change()
        self.workspace.show_card(slot)

    def _on_slot_menu(self, slot: CardSlot) -> None:
        menu = QMenu(self)
        key = self._key(slot)
        clear_action = menu.addAction("Usuń przypisane zdjęcie")
        clear_action.setEnabled(slot.photo_path is not None)

        variants = self._card_variants(slot.suit.nazwa, slot.value)
        delete_action = menu.addAction(
            f"🗑  Usuń wszystkie warianty ({len(variants)})")
        delete_action.setEnabled(bool(variants))
        selected = self._selected_variant(slot.suit.nazwa, slot.value)
        prune_action = menu.addAction("✂  Zostaw tylko wybrany wariant")
        prune_action.setEnabled(selected is not None and len(variants) > 1)

        chosen = menu.exec(QCursor.pos())
        if chosen is clear_action:
            self.assignments.pop(key, None)
            self.transforms.pop(key, None)
            slot.set_photo(None)
            self._after_assignment_change()
        elif chosen is delete_action:
            self._delete_variants(variants)
            self.selections.pop(key, None)
            self.card_history_pos.pop(key, None)
            show_toast(self, f"Usunięto {len(variants)} wariantów karty "
                             f"{slot.value}{slot.suit.symbol}", "ok")
            slot.set_photo(slot.photo_path)  # wraca do stanu "przypisane zdjęcie"
            self._after_card_files_changed(slot.suit.nazwa, slot.value)
        elif chosen is prune_action and selected is not None:
            others = [p for p in variants if p != selected]
            self._delete_variants(others)
            self.selections[key] = str(selected)
            self.card_history_pos.pop(key, None)
            show_toast(self, f"Zostawiono wybrany wariant ({len(others)} usunięto)",
                       "ok")
            self._after_card_files_changed(slot.suit.nazwa, slot.value)

    def _delete_variants(self, paths: list[Path]) -> None:
        for path in paths:
            try:
                path.unlink()
            except OSError as exc:
                self.generation.log_pane.log_line(f"✖ nie usunięto {path.name}: {exc}")

    def _after_card_files_changed(self, suit_nazwa: str, value: str) -> None:
        """Po usunięciu/zmianie plików wariantów: odśwież slot, historię, overview."""
        slot = self.grids[Suit.from_nazwa(suit_nazwa)].slots.get(value)
        selected = self._selected_variant(suit_nazwa, value)
        if slot is not None:
            if selected is not None:
                slot.set_generated(selected)
            else:
                slot.set_photo(slot.photo_path)
        self.gallery.mark_dirty()
        self._refresh_overview()
        if suit_nazwa == self._current_suit.nazwa and value == self._current_value:
            self._refresh_history(suit_nazwa, value)
        self._save_project()

    # -------------------------------------------------- przestemplowanie narożników
    def _collect_restamp_targets(self) -> list[CardSpec]:
        """CardSpec dla KAŻDEGO istniejącego pliku karty (wszystkie warianty)."""
        targets: list[CardSpec] = []
        for suit in Suit:
            for value in self._values():
                for path in self._card_variants(suit.nazwa, value):
                    variant = 1
                    stem = path.stem
                    if "_v" in stem:
                        try:
                            variant = int(stem.rsplit("_v", 1)[1])
                        except ValueError:
                            pass
                    targets.append(CardSpec(value=value, suit=suit, variant=variant))
        return targets

    def _start_restamp(self, targets: list[CardSpec] | None = None) -> None:
        """Przestemplowuje narożniki wygenerowanych kart wg aktywnego presetu
        „wartości narożne" — czyta output/_raw/, ZERO wywołań API.
        targets=None → wszystkie karty talii (wszystkie warianty)."""
        if self.restamp_worker is not None:
            return
        if targets is None:
            targets = self._collect_restamp_targets()
        if not targets:
            show_toast(self, "Brak wygenerowanych kart do przestemplowania", "info")
            return
        self._set_status(f"Przestemplowuję narożniki: 0 / {len(targets)}…")
        worker = RestampWorker(targets)
        worker.progress.connect(
            lambda i, n: self._set_status(f"Przestemplowuję narożniki: {i} / {n}…")
        )
        worker.done.connect(self._on_restamp_done)
        worker.failed.connect(
            lambda msg: show_toast(self, f"Błąd przestemplowania: {msg}", "error")
        )
        self.restamp_worker = worker
        worker.start()

    def _on_restamp_done(self, ok: int, errors: int) -> None:
        self.restamp_worker = None
        # te same ścieżki plików — set_generated wymusza ponowny odczyt pikseli
        # (obie instancje siatki: Talie + Ekran roboczy)
        for grids in (self.grids, self.workspace.deck_panel.grids):
            for grid in grids.values():
                for slot in grid.slots.values():
                    if slot.generated_path is not None:
                        slot.set_generated(slot.generated_path)
        self.gallery.mark_dirty()
        self.deck.mark_dirty()
        self._refresh_history(self._current_suit.nazwa, self._current_value)
        if self._lightbox is not None:
            self._lightbox.refresh()
        self._set_status(f"Przestemplowano narożniki: {ok} kart"
                         + (f", błędy: {errors}" if errors else ""))
        show_toast(self, f"Przestemplowano {ok} kart (bez API)"
                   + (f" · błędów: {errors}" if errors else ""),
                   "error" if errors and not ok else "ok")

    # -------------------------------------------------------------- lightbox kart
    def _lightbox_ctx(self) -> LightboxContext:
        return LightboxContext(
            cards=self._lightbox_cards,
            variants=self._card_variants,
            selected=self._selected_variant,
            card_label=lambda s, v: f"{v}{Suit.from_nazwa(s).symbol}",
        )

    def _lightbox_cards(self) -> list[tuple[str, str]]:
        """Karty z wygenerowanymi plikami, wg aktywnego filtra koloru Talii."""
        selected_suit = self.deck.current_filter()
        cards: list[tuple[str, str]] = []
        for suit in Suit:
            if selected_suit is not None and suit is not selected_suit:
                continue
            for value in self._values():
                if self._card_variants(suit.nazwa, value):
                    cards.append((suit.nazwa, value))
        return cards

    def _open_lightbox(self, suit_nazwa: str, value: str) -> None:
        box = CardLightbox(self._lightbox_ctx(), suit_nazwa, value, self)
        box.set_main_requested.connect(self._on_lightbox_set_main)
        box.delete_requested.connect(self._on_lightbox_delete)
        box.restamp_requested.connect(self._on_lightbox_restamp)
        box.fix_requested.connect(self._on_lightbox_fix)
        box.open_folder_requested.connect(self._open_in_folder)
        self._lightbox = box
        try:
            box.exec()
        finally:
            self._lightbox = None

    def _preview_file(self, path: str) -> None:
        """Prosty podgląd pojedynczego pliku (historia, backup rewersu,
        szablon) — lightbox w trybie single."""
        box = CardLightbox(self._lightbox_ctx(), "", "", self,
                           single_path=Path(path))
        box.open_folder_requested.connect(self._open_in_folder)
        box.exec()

    def _on_lightbox_set_main(self, suit_nazwa: str, value: str,
                              path: str) -> None:
        """Wybrany w lightboxie wariant staje się głównym — WSKAŹNIK,
        bez kopiowania plików (jak _on_history_set_main)."""
        key = f"{suit_nazwa}:{value}"
        self.selections[key] = path
        slot = self.grids[Suit.from_nazwa(suit_nazwa)].slots.get(value)
        if slot is not None:
            slot.set_generated(Path(path))
        self.gallery.mark_dirty()
        self._refresh_overview()
        self._refresh_history(suit_nazwa, value)
        self._save_project()
        if self._lightbox is not None:
            self._lightbox.refresh()
        show_toast(self, f"★ {value}{Suit.from_nazwa(suit_nazwa).symbol}: "
                   "ustawiono jako główną", "ok")

    def _on_lightbox_delete(self, suit_nazwa: str, value: str,
                            path: str) -> None:
        target = Path(path)
        answer = QMessageBox.question(
            self, "Usunąć wariant?",
            f"Plik {target.name} (oraz jego surowa wersja z _raw/) zostanie "
            "trwale usunięty.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        raw = config.RAW_DIR / (target.stem + ".png")
        for p in (target, raw):
            try:
                p.unlink(missing_ok=True)
            except OSError as exc:
                show_toast(self, f"Nie usunięto {p.name}: {exc}", "error")
                return
        key = f"{suit_nazwa}:{value}"
        if self.selections.get(key) == path:
            self.selections.pop(key, None)
        self._after_card_files_changed(suit_nazwa, value)
        self.deck.mark_dirty()
        if self._lightbox is not None:
            self._lightbox.refresh()

    def _on_lightbox_restamp(self, suit_nazwa: str, value: str) -> None:
        """Przestemplowanie wszystkich wariantów jednej karty (bez API)."""
        suit = Suit.from_nazwa(suit_nazwa)
        targets = []
        for p in self._card_variants(suit_nazwa, value):
            variant = 1
            if "_v" in p.stem:
                try:
                    variant = int(p.stem.rsplit("_v", 1)[1])
                except ValueError:
                    pass
            targets.append(CardSpec(value=value, suit=suit, variant=variant))
        self._start_restamp(targets)

    def _on_workspace_fix(self, suit_nazwa: str, value: str) -> None:
        """Poprawa selektywna z Ekranu roboczego: działa na wariancie
        POKAZYWANYM w nawigatorze historii (◀ ▶ pozwala wskazać np.
        przedostatni) — reszta przepływu wspólna z lightboxem."""
        variants = self._card_variants(suit_nazwa, value)
        if not variants:
            show_toast(self, "Brak wygenerowanych wariantów tej karty", "info")
            return
        key = f"{suit_nazwa}:{value}"
        pos = max(0, min(self.card_history_pos.get(key, len(variants) - 1),
                         len(variants) - 1))
        self._on_lightbox_fix(suit_nazwa, value, str(variants[pos]))

    def _on_lightbox_fix(self, suit_nazwa: str, value: str, path: str) -> None:
        """Selektywna poprawa OGLĄDANEGO wariantu: dialog maski+promptu →
        FixWorker → generator.popraw_region (wynik = nowy wariant)."""
        if self.fix_worker is not None:
            show_toast(self, "Poczekaj — trwa poprzednia poprawka", "info")
            return
        p = Path(path)
        variant = 1
        if "_v" in p.stem:
            try:
                variant = int(p.stem.rsplit("_v", 1)[1])
            except ValueError:
                pass
        spec = CardSpec(value=value, suit=Suit.from_nazwa(suit_nazwa),
                        variant=variant)
        dialog = FixRegionDialog(p, spec.label,
                                 parent=self._lightbox or self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        worker = FixWorker(spec, dialog.maska(), dialog.prompt_uzytkownika(),
                           tryb=dialog.tryb(), sila=dialog.sila())
        worker.done.connect(self._on_fix_done)
        worker.failed.connect(self._on_fix_failed)
        self.fix_worker = worker
        self._set_status(f"Przywracam tło {spec.label}…"
                         if dialog.tryb() == "szablon"
                         else f"Poprawiam {spec.label}…")
        worker.start()

    def _on_fix_done(self, spec: CardSpec, path: str) -> None:
        self.fix_worker = None
        self._after_card_files_changed(spec.suit.nazwa, spec.value)
        self.deck.mark_dirty()
        if self._lightbox is not None:
            self._lightbox.refresh()
        self._set_status(f"✔ poprawka: {Path(path).name}")
        show_toast(self, "✔ Poprawka zapisana jako nowy wariant — "
                         "zaakceptuj przez „Ustaw jako główną”", "ok")

    def _on_fix_failed(self, message: str) -> None:
        self.fix_worker = None
        self._set_status("✖ poprawka nieudana")
        self.generation.log_pane.log_line(f"✖ poprawka selektywna: {message}")
        show_toast(self, f"Błąd poprawki: {message}", "error")

    def _open_in_folder(self, path: str) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))

    def _on_photo_deleted(self, path: str) -> None:
        """Zdjęcie usunięte z galerii — czyścimy karty, które go używały."""
        removed = [k for k, v in self.assignments.items() if v == path]
        for key in removed:
            del self.assignments[key]
            self.transforms.pop(key, None)
            suit_name, value = key.split(":", 1)
            slot = self.grids[Suit.from_nazwa(suit_name)].slots.get(value)
            if slot:
                slot.set_photo(None)
        if removed:
            show_toast(self, f"Zdjęcie usunięte — wyczyszczono {len(removed)} kart",
                       "info")
        # obie galerie zdjęć muszą być zsynchronizowane z dyskiem
        self.workspace.gallery_panel.reload()
        self.photo_library.reload()
        self._after_assignment_change()

    def _after_assignment_change(self) -> None:
        self._update_badges()
        self._refresh_overview()
        self._refresh_used_photos()
        self._refresh_estimate()
        self._save_project()

    def _refresh_used_photos(self) -> None:
        """Oznacza w galeriach zdjęcia już przypisane do kart (badge „użyte")."""
        used = set(self.assignments.values())
        self.workspace.gallery_panel.set_used_paths(used)
        self.photo_library.panel.set_used_paths(used)

    # ---------------------------------------------- auto-przydział zdjęć AI
    def _auto_assign_paths(self, nadpisz: bool) -> list[str]:
        """Zdjęcia do analizy: cała galeria, a przy nadpisz=False tylko
        nieużyte w przypisaniach (mniej wywołań API)."""
        if not config.ZDJECIA_DIR.exists():
            return []
        paths = [str(p) for p in sorted(config.ZDJECIA_DIR.iterdir())
                 if p.is_file() and p.suffix.lower() in config.IMAGE_EXTS]
        if not nadpisz:
            used = set(self.assignments.values())
            paths = [p for p in paths if p not in used]
        return paths

    def _start_auto_assign(self) -> None:
        """Przycisk „Auto-przydział AI" — dialog: konfiguracja → analiza →
        podgląd propozycji → zastosowanie."""
        if self.analysis_worker is not None:
            return
        if not photo_analyzer._fake_api() and not self._guard_api_ready():
            return
        if not self._auto_assign_paths(True):
            show_toast(self, "Folder zdjecia/ jest pusty — dodaj zdjęcia "
                       "w Galerii", "info")
            return
        dialog = AutoAssignDialog(self.auto_motywy, self._auto_assign_paths,
                                  parent=self)
        dialog.start_requested.connect(self._run_analysis)
        dialog.cancel_requested.connect(self._cancel_analysis)
        dialog.apply_requested.connect(self._apply_auto_assign)
        self._auto_dialog = dialog
        dialog.exec()
        self._auto_dialog = None

    # ---------------------------------------------- edytor maski pop-out
    def _open_mask_editor(self, suit_nazwa: str, wartosc: str = "") -> None:
        """Rysowanie strefy pop-out pędzlem (bez API) w AKTYWNYM presecie
        masek. Z Ekranu roboczego przychodzi wartość karty (maska TEJ karty,
        np. A♠); z widoku Style pusta wartość = maska CAŁEGO koloru. Przy
        aktywnej „Masce automatycznej" najpierw powstaje nowy preset.
        Zapis/reset w dialogu, tu odświeżenie comb i nakładki podglądu."""
        from app.core import masks
        suit = Suit.from_nazwa(suit_nazwa)
        try:
            template_path = suit.template_path
        except FileNotFoundError:
            show_toast(self, f"Brak szablonu tła dla koloru {suit.nazwa} — "
                       "wygeneruj lub zaimportuj tło", "error")
            return
        if not style_store.active_mask():
            nowa = masks.utworz_maske()
            style_store.set_text("tla_przodu", "maska_aktywna", nowa)
            self._sync_mask_widgets()
            show_toast(self, f"Utworzono preset maski „{nowa}” — rysujesz "
                       "w nim (nie w automatycznej)", "info")
        dialog = MaskEditorDialog(suit, template_path,
                                  wartosc=wartosc or None, parent=self)
        if dialog.exec():
            self.workspace.refresh_mask_preview()
            zakres = f"{wartosc}{suit.symbol}" if wartosc else suit.nazwa
            show_toast(self, f"✓ Maska „{style_store.active_mask()}” "
                       f"({zakres}) zapisana", "success")
        self._save_project()

    def _sync_mask_widgets(self) -> None:
        """Comba presetów masek (Ekran roboczy + Style) po każdej zmianie
        biblioteki/aktywnego presetu + nakładka podglądu."""
        self.workspace.refresh_mask_presets()
        self.back_view.refresh_mask_presets()
        self.workspace.refresh_mask_preview()

    def _on_mask_preset_selected(self, nazwa: str) -> None:
        """Combo na Ekranie roboczym → aktywny preset maski."""
        style_store.set_text("tla_przodu", "maska_aktywna", nazwa)
        self._sync_mask_widgets()
        self._save_project()

    def _on_mask_library_changed(self) -> None:
        """CRUD/wybór maski w widoku Style → sync + zapis."""
        self._sync_mask_widgets()
        self._save_project()

    def _on_cartoon_level_changed(self, level: int) -> None:
        """Suwak „Poziom kreskówki" na Ekranie roboczym → pole presetu
        postaci (postac/poziom_kreskowki); wpływa na prompty obu trybów."""
        style_store.set_text("postac", "poziom_kreskowki", str(level))
        self.settings_view.refresh_prompt()
        self._save_project()
        # dialog zamknięty w trakcie analizy bez „Anuluj" nie zostawia workera
        if self.analysis_worker is not None:
            self._cancel_analysis()

    def _run_analysis(self, motywy: dict, nadpisz: bool) -> None:
        """Start workera analizy (strona postępu dialogu już widoczna)."""
        self.auto_motywy = {k: str(v) for k, v in motywy.items()}
        self._save_project()
        self._auto_nadpisz = nadpisz
        self._auto_propozycje = []
        self._analysis_cancelled = False
        self._analysis_fatal = False
        worker = AnalysisWorker(self._auto_assign_paths(nadpisz),
                                self.auto_motywy)
        worker.progress.connect(self._on_analysis_progress)
        worker.photo_done.connect(self._on_analysis_photo_done)
        worker.photo_error.connect(self._on_analysis_photo_error)
        worker.fatal_error.connect(self._on_analysis_fatal)
        worker.finished_all.connect(self._on_analysis_finished)
        self.analysis_worker = worker
        worker.start()

    def _cancel_analysis(self) -> None:
        """Anulowanie analizy: flaga + porzucenie żywego wątku (wzorzec
        _cancel_generation — QThread nie może być zniszczony w locie)."""
        worker = self.analysis_worker
        if worker is None:
            return
        self._analysis_cancelled = True
        worker.cancel()
        self._abandoned.append(worker)
        worker.finished.connect(
            lambda w=worker: self._abandoned.remove(w)
            if w in self._abandoned else None
        )
        self.analysis_worker = None
        self._set_status("Anulowano analizę zdjęć")

    def _on_analysis_progress(self, done: int, total: int) -> None:
        if self._auto_dialog is not None and not self._analysis_cancelled:
            self._auto_dialog.show_progress(done, total)

    def _on_analysis_photo_done(self, path: str, _analiza) -> None:
        if self._auto_dialog is not None and not self._analysis_cancelled:
            self._auto_dialog.show_current_file(path)

    def _on_analysis_photo_error(self, path: str, message: str) -> None:
        if self._analysis_cancelled:
            return
        self.generation.log_pane.log_line(
            f"✖ analiza {Path(path).name}: {message}")
        if self._auto_dialog is not None:
            self._auto_dialog.add_error(path, message)

    def _on_analysis_fatal(self, message: str) -> None:
        self._analysis_fatal = True
        if self._auto_dialog is not None:
            self._auto_dialog.analysis_failed(message)
        show_toast(self, f"✖ analiza zdjęć: {message[:160]}", "error")

    def _on_analysis_finished(self, wyniki: list) -> None:
        self.analysis_worker = None
        if self._analysis_cancelled or self._analysis_fatal:
            return
        dialog = self._auto_dialog
        if dialog is None:
            return
        propozycje, puste, nieuzyte = photo_analyzer.uloz_propozycje(
            wyniki, self._values(), self.assignments, self._auto_nadpisz)
        # czytelna kolejność podglądu: kolory wg Suit, wartości wg talii
        order_s = {s.nazwa: i for i, s in enumerate(Suit)}
        order_v = {v: i for i, v in enumerate(self._values())}
        propozycje.sort(key=lambda p: (
            order_s.get(p.klucz.split(":", 1)[0], 9),
            order_v.get(p.klucz.split(":", 1)[1], 99),
        ))
        self._auto_propozycje = propozycje
        dialog.show_proposals(propozycje, puste, nieuzyte)

    def _apply_auto_assign(self) -> None:
        """Zastosowanie zatwierdzonych propozycji — masowo, z JEDNYM
        odświeżeniem (_after_assignment_change) na końcu."""
        zastosowane = 0
        for prop in self._auto_propozycje:
            suit_nazwa, value = prop.klucz.split(":", 1)
            try:
                suit = Suit.from_nazwa(suit_nazwa)
            except ValueError:
                continue
            slot = self.grids[suit].slots.get(value)
            if slot is None:   # wartość mogła zniknąć po edycji talii
                continue
            self.assignments[prop.klucz] = prop.sciezka
            self.transforms.pop(prop.klucz, None)  # stary kadr ≠ nowe zdjęcie
            slot.set_photo(Path(prop.sciezka))
            zastosowane += 1
        self._auto_propozycje = []
        self._after_assignment_change()
        show_toast(self, f"Auto-przydział: przypisano {zastosowane} kart", "ok")

    def _rebuild_grids(self, values: list[str]) -> None:
        self._deck_values = list(values)
        for suit, grid in self.grids.items():
            grid.rebuild(values, self.assignments)
        # druga instancja siatki na Ekranie roboczym — te same wartości
        # i przypisania; stan generacji dosypie sync_deck w _refresh_overview
        self.workspace.deck_panel.rebuild(values, self.assignments)
        self.workspace.set_available_values(values)
        self.deck.set_card_count(len(values) * len(Suit))
        self._update_badges()
        self._refresh_overview()
        self._refresh_estimate()
        self._save_project()

    # ----------------------------------------------------------------- generowanie
    def _collect_specs(self) -> list[CardSpec]:
        cards = []
        mode = self._mode()
        skip_done = self.generation.skip_done_check.isChecked()
        for suit, grid in self.grids.items():
            for value, slot in grid.slots.items():
                if slot.photo_path is None:
                    continue
                if skip_done and self._selected_variant(suit.nazwa, value) is not None:
                    continue
                cards.append((value, suit, slot.photo_path))
        limit = self.generation.limit_spin.value()
        if limit > 0:
            cards = cards[:limit]
        count = max(1, self.generation.versions_spin.value())
        specs = []
        for value, suit, photo in cards:
            transform = self.transforms.get(f"{suit.nazwa}:{value}")
            # DOKŁADAMY warianty od następnego wolnego numeru — historia rośnie,
            # nie jest kasowana
            start = self._next_variant_index(suit.nazwa, value)
            for variant in range(start, start + count):
                specs.append(CardSpec(value=value, suit=suit, photo_path=photo,
                                      mode=mode, variant=variant,
                                      transform=transform))
        return specs

    def _planned_generation_count(self) -> tuple[int, int]:
        """(liczba kart, liczba generacji) planowanej serii — jak _collect_specs,
        ale bez tworzenia specyfikacji (do licznika szacunkowego)."""
        skip_done = self.generation.skip_done_check.isChecked()
        cards = 0
        for suit, grid in self.grids.items():
            for value, slot in grid.slots.items():
                if slot.photo_path is None:
                    continue
                if skip_done and self._selected_variant(suit.nazwa, value) is not None:
                    continue
                cards += 1
        limit = self.generation.limit_spin.value()
        if limit > 0:
            cards = min(cards, limit)
        gens = cards * max(1, self.generation.versions_spin.value())
        return cards, gens

    def _refresh_estimate(self) -> None:
        cards, gens = self._planned_generation_count()
        if cards == 0:
            self.generation.set_estimate(
                "Brak kart do wygenerowania — przypisz zdjęcia do kart."
            )
            return
        text = f"Do wygenerowania: {cards} kart · {gens} generacji"
        credits = config.current_model().get("credits")
        if credits:
            text += f" · ≈ {round(gens * credits)} kr. Stability"
        self.generation.set_estimate(text)

    def _start_generation(self) -> None:
        if not self._guard_api_ready() or not self._guard_full_ai():
            return
        specs = self._collect_specs()
        if not specs:
            show_toast(self, "Brak kart do wygenerowania — przypisz zdjęcia "
                       "(lub odznacz „Pomiń gotowe”)", "error")
            return
        self._run_generation(specs)

    def _guard_api_ready(self) -> bool:
        """Blokuje generację, gdy API nie jest skonfigurowane — jeden czytelny
        komunikat i skok do Ustawień zamiast serii błędów per karta."""
        if not config.api_ready():
            show_toast(self, "Najpierw skonfiguruj API w Ustawieniach "
                       "(klucz Google AI Studio lub Vertex)", "error")
            self._open_settings()
            return False
        return True

    def _guard_full_ai(self) -> bool:
        """Blokuje tryb Pełne AI na modelu innym niż Gemini (inaczej każda
        karta rzuciłaby ValueError)."""
        if self._mode() is GenMode.FULL_AI \
                and config.current_model()["provider"] != "gemini":
            show_toast(self, "Tryb Pełne AI wymaga modelu Gemini — zmień model "
                       "w Ustawieniach albo wróć do trybu Hybrydowego", "error")
            return False
        return True

    def _retry_failed(self) -> None:
        """Ponawia tylko karty, które w poprzedniej serii zakończyły się błędem."""
        if self.worker is not None or not self._failed_specs:
            return
        self._run_generation(list(self._failed_specs))

    def _run_generation(self, specs: list[CardSpec]) -> None:
        # pre-check: każdy kolor w serii musi mieć tło przodu (inaczej
        # generacja rzuciłaby FileNotFoundError na każdej karcie)
        missing = sorted({spec.suit for spec in specs
                          if not spec.suit.available_templates()},
                         key=lambda s: s.nazwa)
        if missing:
            names = ", ".join(f"{s.symbol} {s.nazwa}" for s in missing)
            show_toast(self, f"Brak tła przodu dla: {names} — wygeneruj je w "
                       "„Tła i rewersy” (np. „Generuj komplet”) albo wgraj "
                       "tam własne tło", "error")
            return
        from app.api import stability_client
        stability_client.reset_abort()   # świeży start serii (kasuje flagę Anuluj)
        self._gen_cancelled = False
        self._gen_fatal = False
        self._failed_specs = []          # nowa seria — czyścimy listę nieudanych
        self.generation.hide_retry()
        self._set_generation_busy(True, len(specs))
        self.generation.set_queue(specs)
        for spec in specs:
            slot = self._slot_for(spec)
            if slot is not None:
                slot.set_queued(True)
        # siatka Ekranu roboczego od razu pokazuje karty „w kolejce"
        self.workspace.sync_deck(self._values(), self.grids)
        self._set_status(f"Generuję {len(specs)} kart ({self._mode().value})...")
        self.worker = GenerationWorker(specs)
        self.worker.progress.connect(self._on_progress)
        self.worker.card_started.connect(self._on_card_started)
        self.worker.card_done.connect(self._on_card_done)
        self.worker.card_error.connect(self._on_card_error)
        self.worker.fatal_error.connect(self._on_fatal_error)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    def _toggle_pause(self) -> None:
        if self.worker is None:
            return
        paused = not self.worker.paused
        self.worker.set_paused(paused)
        self.generation.set_paused(paused)
        self._set_status("Wstrzymano po bieżącej karcie"
                         if paused else "Wznowiono generację")

    def _cancel_generation(self) -> None:
        """Natychmiastowe anulowanie: odblokowuje UI od razu, a porzucony wątek
        (którego bieżące żądanie HTTP dokończy się w tle) zostaje zignorowany
        dzięki fladze _gen_cancelled. Dodatkowo zamykamy sesję (best-effort)."""
        from app.api import stability_client
        if not (self.worker or self.template_worker or self.back_worker):
            return
        self._gen_cancelled = True
        stability_client.abort_active()
        # przenosimy żywe wątki do „porzuconych" (trzymamy referencję, aż same
        # się zakończą) i zwalniamy aktywne uchwyty — UI działa dalej od razu
        for worker in (self.worker, self.template_worker, self.back_worker):
            if worker is not None:
                worker.cancel()
                self._abandoned.append(worker)
                worker.finished.connect(
                    lambda w=worker: self._abandoned.remove(w)
                    if w in self._abandoned else None
                )
        self.worker = None
        self.template_worker = None
        self.back_worker = None
        self.generation.set_paused(False)
        self.generation.set_busy(False)
        self._set_generation_busy(False)
        self.generation.preview.stop_sweep()
        self.back_view.set_front_busy(False)
        self.back_view.set_back_busy(False)
        self.cancel_btn.setVisible(False)
        for grid in self.grids.values():
            for slot in grid.slots.values():
                slot.set_queued(False)
        self._refresh_overview()
        self._set_status("Anulowano generację")
        show_toast(self, "Anulowano generację", "info")

    def _set_generation_busy(self, busy: bool, total: int = 0) -> None:
        self.generation.set_busy(busy)
        self.workspace.regen_btn.setEnabled(not busy)
        self.cancel_btn.setVisible(busy)
        self.progress.setVisible(busy)
        if busy:
            self.progress.setRange(0, total)
            self.progress.setValue(0)
            self.generation.set_progress(0, total)
            self.busy_overlay.show_over(self.workspace.preview)
        else:
            self.busy_overlay.hide()

    def _slot_for(self, spec: CardSpec) -> CardSlot | None:
        return self.grids[spec.suit].slots.get(spec.value)

    def _on_progress(self, done: int, total: int) -> None:
        if self._gen_cancelled:
            return
        self.progress.setValue(done)
        self.generation.set_progress(done, total)

    def _on_card_started(self, spec: CardSpec) -> None:
        if self._gen_cancelled:
            return
        self.generation.mark_running(spec)
        if spec.photo_path is not None:
            self.generation.preview.show_preview(
                load_thumbnail(spec.photo_path, 900)
            )
            self.generation.preview.start_sweep()
        self.status_text.setText(f"⟳ {spec.label} — transformacja AI…")

    def _on_card_done(self, spec: CardSpec, path: str) -> None:
        if self._gen_cancelled:
            return
        self.generation.preview.stop_sweep()
        # najnowszy wariant staje się wybrany (wskaźnik, nie kopia)
        key = f"{spec.suit.nazwa}:{spec.value}"
        self.selections[key] = path
        slot = self._slot_for(spec)
        if slot:
            slot.set_generated(Path(path))
        self._show_preview(load_thumbnail(Path(path), 900))
        self.generation.mark_done(spec)
        self.gallery.mark_dirty()
        self.back_view.refresh_style_preview()   # podgląd stylu = najnowsza karta
        self._refresh_overview()
        # nowy wariant trafia do historii — nawigator skacze na najnowszy
        self.card_history_pos.pop(key, None)
        if (spec.suit is self._current_suit
                and spec.value == self._current_value):
            self._refresh_history(spec.suit.nazwa, spec.value)
        self._set_status(f"✔ {spec.output_name} · inpaint OK · "
                         f"{config.ACCENT_HEX} · serif · 63×88 mm")
        show_toast(self, f"✔ {spec.output_name}", "ok")

    def _on_card_error(self, spec: CardSpec, message: str) -> None:
        if self._gen_cancelled:
            return
        self._failed_specs.append(spec)
        self.generation.preview.stop_sweep()
        slot = self._slot_for(spec)
        if slot:
            slot.set_error(message)
        self.generation.mark_error(spec)
        self.generation.log_pane.log_line(f"✖ {spec.label}: {message}")
        self.status_text.setText(f"✖ {spec.label} — szczegóły w logu")
        show_toast(self, f"✖ {spec.label}: {message[:120]}", "error")

    def _on_fatal_error(self, message: str) -> None:
        """Błąd krytyczny konta (brak kredytów / billing / klucz) — seria
        zatrzymana po pierwszej karcie, jeden czytelny komunikat zamiast 52."""
        if self._gen_cancelled:
            return
        self._gen_fatal = True
        self._set_generation_busy(False)
        self.generation.preview.stop_sweep()
        for grid in self.grids.values():
            for slot in grid.slots.values():
                slot.set_queued(False)
        self.generation.log_pane.log_line(f"✖ BŁĄD KRYTYCZNY: {message}")
        self._set_status("Zatrzymano — błąd krytyczny API (szczegóły w logu)")
        show_toast(self, message, "error")
        self._refresh_overview()
        self.worker = None

    def _on_finished(self, done: int, errors: int) -> None:
        if self._gen_cancelled or self._gen_fatal:
            self._gen_fatal = False
            self.worker = None
            return
        self._set_generation_busy(False)
        self.generation.preview.stop_sweep()
        for grid in self.grids.values():
            for slot in grid.slots.values():
                slot.set_queued(False)
        self.gallery.mark_dirty()
        self._refresh_overview()
        # udostępnij ponowienie, jeśli część kart się nie udała
        if self._failed_specs:
            self.generation.show_retry(len(self._failed_specs))
        self._set_status(f"Koniec: {done} OK, {errors} błędów → {config.OUTPUT_DIR}")
        self.worker = None

    # --------------------------------------------------------------------- tła kart
    def _on_template_changed(self, suit: Suit, path: str) -> None:
        config.TEMPLATE_OVERRIDES[suit.nazwa] = path
        # Tło spoza programu (np. wrzucone ręcznie do folderu presetu) od razu
        # dopasowuje się do wybranego formatu i rozdzielczości — podgląd
        # siatki i kolaż widzą już znormalizowany plik
        from app.core import generator
        generator.normalizuj_szablon(Path(path))
        card_grid.clear_template_cache()
        self._rebuild_grids(self._values())
        self._set_status(f"Tło {suit.symbol} {suit.nazwa}: {Path(path).name}")

    def _on_preset_applied(self, cat: str) -> None:
        """Aktywowano preset w zakładce „Style" — silnik, siatki i eksport
        czytają wprost z folderu aktywnego presetu, więc wystarczy zrzucić
        nieaktualne wybory wariantów i odświeżyć widoki."""
        if cat == "tla_przodu":
            # wybory wariantów wskazywały pliki poprzedniego presetu
            config.TEMPLATE_OVERRIDES.clear()
            # tła spoza programu (wrzucone ręcznie do folderu presetu) mogą mieć
            # złą proporcję — aktywacja presetu wymusza dokładny format karty
            from app.core import generator
            generator.normalizuj_aktywny_preset()
            card_grid.clear_template_cache()
            self._rebuild_grids(self._values())
            self.back_view.refresh_front_preview()
            # inny preset teł = inna biblioteka masek + pole maska_aktywna
            self.workspace.refresh_mask_presets()
            self.workspace.refresh_mask_preview()
        elif cat == "postac":
            # inny preset = inny poziom kreskówki — zsynchronizuj suwak
            self.workspace.set_cartoon_level(style_store.cartoon_level())
        elif cat == "rewers":
            self.back_view.refresh_back_preview()
            self.gallery.mark_dirty()
        elif cat == "wartosci":
            show_toast(self, "Preset wartości aktywny — „Przestempluj narożniki” "
                             "naniesie go na istniejące karty (bez API)", "info")
        self.settings_view.refresh_prompt()
        self._save_project()

    def _start_front_generation(self, settings: dict) -> None:
        """Generowanie teł PRZODU karty (zakładka „Tła i rewersy") —
        1 lub 4 warianty tym samym promptem, z możliwością przerwania."""
        if self.template_worker is not None:
            return
        if not self._guard_api_ready():
            return
        suit = settings["suit"]
        # baza z edytora + twardy layout (kształt symbolu koloru, tarcze TL/BR,
        # zakaz tekstu); w trybie własnym presetu baza idzie dosłownie
        prompt = prompts.front_background_prompt(suit, settings.get("prompt"))
        count = int(settings.get("count", 1))
        from app.api import stability_client
        stability_client.reset_abort()
        self._gen_cancelled = False
        self.back_view.set_front_busy(True)
        self.cancel_btn.setVisible(True)
        self._front_made = 0
        self._set_status(
            f"Generuję {count} tło/tła dla {suit.symbol} {suit.nazwa}...")
        worker = TemplateWorker(suit, prompt=prompt, count=count)
        worker.done.connect(self._on_front_variant_done)
        worker.failed.connect(self._on_front_failed)
        worker.finished_all.connect(self._on_front_finished)
        self.template_worker = worker
        worker.start()

    def _on_front_variant_done(self, suit: Suit, path: str) -> None:
        if self._gen_cancelled:
            return
        self._front_made = getattr(self, "_front_made", 0) + 1
        show_toast(self, f"✔ tło {suit.symbol}: {Path(path).name}", "ok")
        # pierwszy wariant od razu ustawiamy jako aktywne tło koloru
        # (plik leży już w folderze aktywnego presetu teł przodu)
        if self._front_made == 1:
            self._on_template_changed(suit, path)
        self.back_view.refresh_front_preview()
        self._show_preview(load_thumbnail(Path(path), 900))

    def _on_front_failed(self, suit: Suit, message: str) -> None:
        self.generation.log_pane.log_line(f"✖ tło {suit.nazwa}: {message}")
        show_toast(self, f"✖ tło {suit.nazwa}: {message[:120]}", "error")

    def _on_front_finished(self, made: int, total: int) -> None:
        if self._gen_cancelled:
            self.template_worker = None
            return
        self.template_worker = None
        self.back_view.set_front_busy(False)
        self.cancel_btn.setVisible(bool(self.worker))
        self._save_project()
        if made < total:
            self._set_status(f"Przerwano — wygenerowano {made}/{total} teł")
        else:
            self._set_status(f"✔ wygenerowano {made} teł przodu")

    # ------------------------------------------- komplet wyglądu talii (4 tła)
    def _start_front_set(self, opts: dict) -> None:
        """Komplet 4 teł jednym stylem (+ opcjonalnie rewers) — spójny zestaw:
        pierwsze tło kotwiczy pozostałe kolory (referencja + wspólny seed)."""
        if self.template_worker is not None or self.back_worker is not None:
            return
        if not self._guard_api_ready():
            return
        back_prompt = back_source = None
        orientation = "portrait"
        if opts.get("include_back"):
            settings = self.back_view.settings()
            orientation = settings.get("orientation", "portrait")
            back_source = settings.get("source_photo") \
                if settings.get("mode") == "i2i" else None
            back_prompt = prompts.back_generation_prompt(
                preset=settings.get("preset", "klasyczny"),
                custom_text=settings.get("custom", ""),
                orientation=orientation,
                from_photo=bool(back_source),
            )
        from app.api import stability_client
        stability_client.reset_abort()
        self._gen_cancelled = False
        self.back_view.set_front_busy(True)
        self.cancel_btn.setVisible(True)
        total = len(Suit) + (1 if back_prompt else 0)
        self._set_status(f"Komplet wyglądu talii: 0 / {total}…")
        worker = TemplateSetWorker(back_prompt=back_prompt,
                                   back_source=back_source,
                                   back_orientation=orientation)
        worker.variant_done.connect(self._on_set_variant_done)
        worker.back_done.connect(self._on_set_back_done)
        worker.failed.connect(self._on_set_failed)
        worker.progress.connect(
            lambda i, n: self._set_status(f"Komplet wyglądu talii: {i} / {n}…")
        )
        worker.finished_all.connect(self._on_set_finished)
        self.template_worker = worker   # slot template_worker → działa Przerwij
        worker.start()

    def _on_set_variant_done(self, suit: Suit, path: str) -> None:
        if self._gen_cancelled:
            return
        # każde tło kompletu od razu staje się aktywnym tłem swojego koloru
        self._on_template_changed(suit, path)
        self.back_view.refresh_front_preview()
        self._show_preview(load_thumbnail(Path(path), 900))
        show_toast(self, f"✔ tło {suit.symbol}: {Path(path).name}", "ok")

    def _on_set_back_done(self, path: str) -> None:
        if self._gen_cancelled:
            return
        self.gallery.mark_dirty()
        self.back_view.refresh_back_preview()
        show_toast(self, f"✔ rewers zestawu: {Path(path).name}", "ok")

    def _on_set_failed(self, suit, message: str) -> None:
        label = f"tło {suit.nazwa}" if suit is not None else "rewers"
        self.generation.log_pane.log_line(f"✖ {label}: {message}")
        show_toast(self, f"✖ {label}: {message[:120]}", "error")

    def _on_set_finished(self, made: int, total: int) -> None:
        if self._gen_cancelled:
            self.template_worker = None
            return
        self.template_worker = None
        self.back_view.set_front_busy(False)
        self.cancel_btn.setVisible(bool(self.worker))
        self._save_project()
        if made < total:
            self._set_status(f"Komplet przerwany — {made}/{total} elementów")
        else:
            self._set_status(f"✔ komplet wyglądu talii gotowy ({made} elementów)"
                             " — teraz przypisz zdjęcia na Ekranie roboczym")

    def _on_front_import(self, suit: Suit, src: str) -> None:
        """Własny obraz użytkownika jako tło koloru — dopasowanie do proporcji
        karty (bez API) i natychmiastowa aktywacja. Przy dużym odchyle
        proporcji użytkownik wybiera: rozciągnięcie całości czy docięcie."""
        from app.core import generator
        try:
            odchyl = generator.odchyl_proporcji(Path(src))
        except (OSError, ValueError) as exc:
            show_toast(self, f"Nie wczytano obrazu: {exc}", "error")
            return
        # mały odchył: rozciągnięcie jest niewidoczne, a nic nie ginie —
        # bez pytania; duży odchył: dystorsja vs utrata brzegów to wybór
        rozciagnij = True
        if odchyl > generator.PROG_ODCHYLU_PROPORCJI:
            box = QMessageBox(self)
            box.setWindowTitle("Dopasowanie tła do formatu karty")
            box.setText(
                f"Proporcje obrazu odbiegają od formatu karty o {odchyl:.0%}.\n\n"
                "• Rozciągnij — cały obraz zostaje, ale będzie ściśnięty/"
                "rozciągnięty (widoczna dystorsja).\n"
                "• Dotnij — bez dystorsji, ale brzegi obrazu zostaną ucięte."
            )
            stretch_btn = box.addButton(
                "Rozciągnij (cały obraz)", QMessageBox.ButtonRole.AcceptRole)
            crop_btn = box.addButton(
                "Dotnij brzegi", QMessageBox.ButtonRole.AcceptRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(stretch_btn)
            box.exec()
            if box.clickedButton() is crop_btn:
                rozciagnij = False
            elif box.clickedButton() is not stretch_btn:
                return
        try:
            path = generator.import_template(suit, Path(src),
                                             rozciagnij=rozciagnij)
        except (OSError, ValueError) as exc:
            show_toast(self, f"Nie wczytano obrazu: {exc}", "error")
            return
        self._on_template_changed(suit, str(path))
        self.back_view.refresh_front_preview()
        self._save_project()
        show_toast(self, f"✔ własne tło {suit.symbol}: {path.name}", "ok")

    def _on_front_normalize(self) -> None:
        """Wymuszone dopasowanie WSZYSTKICH teł aktywnego presetu do formatu
        karty — tła docięte przed wprowadzeniem rozciągania odzyskują pełną
        treść z oryginałów w zrodla/ (bez API)."""
        from app.core import generator
        try:
            zmienione = generator.renormalizuj_wszystkie()
        except (OSError, ValueError) as exc:
            show_toast(self, f"Nie dopasowano teł: {exc}", "error")
            return
        if not zmienione:
            show_toast(self, "Tła już pasują do wybranego formatu — bez zmian",
                       "info")
            return
        card_grid.clear_template_cache()
        self._rebuild_grids(self._values())
        self.back_view.refresh_front_preview()
        show_toast(self, f"✔ dopasowano tła do formatu ({zmienione} plików)",
                   "ok")

    # ----------------------------------------------------------------------- rewers
    def _start_back_generation(self, settings: dict) -> None:
        if self.back_worker is not None:
            return
        if not self._guard_api_ready():
            return
        source = settings.get("source_photo") if settings.get("mode") == "i2i" \
            else None
        prompt = prompts.back_generation_prompt(
            preset=settings.get("preset", "klasyczny"),
            custom_text=settings.get("custom", ""),
            orientation=settings.get("orientation", "portrait"),
            from_photo=bool(source),
        )
        from app.api import stability_client
        stability_client.reset_abort()
        self._gen_cancelled = False
        self.back_view.set_back_busy(True)
        self.cancel_btn.setVisible(True)
        self._set_status("Generuję rewers talii (AI)...")
        worker = BackWorker(prompt=prompt, source_photo=source,
                            orientation=settings.get("orientation", "portrait"))
        worker.done.connect(self._on_back_generated)
        worker.failed.connect(self._on_back_failed)
        self.back_worker = worker
        worker.start()
        self._save_project()

    def _on_back_generated(self, path: str) -> None:
        if self._gen_cancelled:
            self.back_worker = None
            return
        self.back_worker = None
        self.back_view.set_back_busy(False)
        self.cancel_btn.setVisible(bool(self.worker or self.template_worker))
        self.gallery.mark_dirty()
        self._set_status(f"✔ rewers: {Path(path).name}")
        show_toast(self, "✔ rewers talii wygenerowany", "ok")

    def _on_back_failed(self, message: str) -> None:
        if self._gen_cancelled:
            self.back_worker = None
            return
        self.back_worker = None
        self.back_view.set_back_busy(False)
        self.cancel_btn.setVisible(bool(self.worker or self.template_worker))
        self.generation.log_pane.log_line(f"✖ rewers: {message}")
        show_toast(self, f"✖ rewers: {message[:120]}", "error")

    # ----------------------------------------------- podgląd przykładowej karty
    def _first_available_photo(self) -> Path | None:
        if config.ZDJECIA_DIR.exists():
            for p in sorted(config.ZDJECIA_DIR.iterdir()):
                if p.suffix.lower() in config.IMAGE_EXTS:
                    return p
        return None

    def _generate_sample(self, payload: dict) -> None:
        """Zakładka „Style" → jedna przykładowa karta w bieżącym stylu (bez zapisu)."""
        if self.sample_worker is not None:
            show_toast(self, "Poczekaj — trwa generacja podglądu", "info")
            return
        if not self._guard_api_ready() or not self._guard_full_ai():
            return
        photo = payload.get("photo")
        photo_path = Path(photo) if photo else self._first_available_photo()
        if photo_path is None or not photo_path.exists():
            show_toast(self, "Dodaj zdjęcie do podglądu (wybierz plik albo wrzuć "
                       "zdjęcie do folderu zdjecia/)", "error")
            return
        suit = Suit.KIER
        if not suit.available_templates():
            show_toast(self, "Brak tła przodu dla Kier — wygeneruj je najpierw "
                       "w tej zakładce", "error")
            return
        spec = CardSpec(value="A", suit=suit, photo_path=photo_path,
                        mode=self._mode(), variant=1, transform=None)
        self.back_view.set_sample_busy(True)
        self._set_status("Generuję podgląd przykładowej karty…")
        worker = SampleWorker(spec)
        worker.done.connect(self._on_sample_done)
        worker.failed.connect(self._on_sample_failed)
        self.sample_worker = worker
        worker.start()

    def _on_sample_done(self, image) -> None:
        self.sample_worker = None
        self.back_view.set_sample_busy(False)
        self.back_view.set_style_preview_image(image)
        self._set_status("✔ podgląd przykładowej karty gotowy")
        show_toast(self, "✔ podgląd przykładowej karty gotowy", "ok")

    def _on_sample_failed(self, message: str) -> None:
        self.sample_worker = None
        self.back_view.set_sample_busy(False)
        self.generation.log_pane.log_line(f"✖ podgląd: {message}")
        show_toast(self, f"✖ podgląd: {message[:120]}", "error")

    def _on_card_preset_changed(self, _key: str) -> None:
        # nowy format = nowa proporcja docelowa tła: przelicz tła aktywnego
        # presetu od oryginałów w zrodla/ (dopasowanie do NOWEJ proporcji),
        # unieważnij cache masek/kolażu i odśwież podglądy
        from app.core import generator
        try:
            generator.renormalizuj_wszystkie()
        except (OSError, ValueError) as exc:
            show_toast(self, f"Nie dopasowano teł do formatu: {exc}", "error")
        card_grid.clear_template_cache()
        self._rebuild_grids(self._values())
        self.back_view.refresh_front_preview()
        self._set_status(
            f"Format talii: {config.CARD_PRESETS[config.SELECTED_CARD_PRESET][0]}"
        )
        self._save_project()

    # ----------------------------------------------------------------------- eksport
    _EXPORT_FILES = {
        "pdf": ("arkusz_druku.pdf", "PDF (*.pdf)"),
        "files": ("karty_png", ""),   # folder docelowy
        "zip": ("talia_png.zip", "Archiwum ZIP (*.zip)"),
        "atlas": ("atlas_tts_10x7.png", "PNG (*.png)"),
        "sprite": ("sprite_13x4.png", "PNG (*.png)"),
    }

    def _deck_fronts(self) -> list[tuple[str, Path | None]]:
        fronts: list[tuple[str, Path | None]] = []
        for suit in Suit:
            for value in self._values():
                name = f"{value}_{suit.nazwa}"
                # eksport bierze WYBRANY wariant (nazwa logiczna karty bez zmian)
                fronts.append((name, self._selected_variant(suit.nazwa, value)))
        return fronts

    def _start_export(self, kind: str) -> None:
        if self.export_worker is not None:
            show_toast(self, "Poczekaj — trwa poprzedni eksport", "info")
            return
        default_name, file_filter = self._EXPORT_FILES[kind]
        if kind == "files":
            out_path = QFileDialog.getExistingDirectory(
                self, "Folder na pojedyncze pliki PNG", str(config.ROOT)
            )
        else:
            out_path, _ = QFileDialog.getSaveFileName(
                self, "Zapisz eksport", str(config.ROOT / default_name),
                file_filter,
            )
        if not out_path:
            return
        job = ExportJob(
            kind=kind,
            out_path=Path(out_path),
            fronts=self._deck_fronts(),
            back=style_store.back_path() if style_store.back_path().exists()
            else None,
            columns=self.export_view.pdf_columns(),
            bleed=self.export_view.bleed_check.isChecked(),
            marks=self.export_view.marks_check.isChecked(),
            backs=self.export_view.backs_check.isChecked(),
            small_atlas=self.export_view.small_check.isChecked(),
        )
        self.export_view.set_export_status(f"Eksportuję {default_name}…")
        self._set_status(f"Eksport: {Path(out_path).name}…")
        worker = ExportWorker(job)
        worker.progress.connect(self.export_view.set_export_progress)
        worker.done.connect(self._on_export_done)
        worker.failed.connect(self._on_export_failed)
        self.export_worker = worker
        worker.start()

    def _on_export_done(self, path: str) -> None:
        self.export_worker = None
        self.export_view.set_export_status(f"✔ zapisano: {path}", finished=True)
        self._set_status(f"✔ eksport: {path}")
        show_toast(self, f"✔ zapisano {Path(path).name}", "ok")

    def _on_export_failed(self, message: str) -> None:
        self.export_worker = None
        self.export_view.set_export_status(f"✖ {message}", finished=True)
        self.generation.log_pane.log_line(f"✖ eksport: {message}")
        show_toast(self, f"✖ eksport: {message[:120]}", "error")

    # ----------------------------------------------- ciemny natywny pasek tytułu
    def showEvent(self, event):  # noqa: N802 (API Qt)
        super().showEvent(event)
        if not getattr(self, "_dark_titlebar_done", False):
            self._dark_titlebar_done = True
            self._apply_dark_titlebar()

    def _apply_dark_titlebar(self) -> None:
        """Ciemny pasek tytułu Windows (DWM immersive dark mode), by natywna
        ramka pasowała do ciemnego motywu aplikacji. No-op poza Windows."""
        import sys
        if sys.platform != "win32":
            return
        try:
            import ctypes
            hwnd = int(self.winId())
            value = ctypes.c_int(1)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 2004+), 19 = starsze buildy
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
                )
        except Exception:
            pass

    # --------------------------------------------------------- zapis/odczyt projektu
    def _save_project(self) -> None:
        data = {
            "deck_name": self.deck_name,
            "assignments": self.assignments,
            "transforms": self.transforms,
            "selections": self.selections,
            "values": self._values(),
            "mode": self._mode().value,
            "templates": config.TEMPLATE_OVERRIDES,
            "limit": self.generation.limit_spin.value(),
            "versions": self.generation.versions_spin.value(),
            "skip_done": self.generation.skip_done_check.isChecked(),
            "style_presets": {cat: style_store.active(cat)
                              for cat in style_store.CATEGORIES},
            "model": config.SELECTED_MODEL,
            "card_preset": config.SELECTED_CARD_PRESET,
            "back": self.back_view.settings(),
            "export": self.export_view.settings(),
            "auto_przydzial": {"motywy": self.auto_motywy},
        }
        config.PROJEKT_JSON.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _load_project(self) -> None:
        self.deck.set_deck_name(self.deck_name)
        if not config.PROJEKT_JSON.exists():
            return
        try:
            data = json.loads(config.PROJEKT_JSON.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if data.get("deck_name"):
            self.deck_name = data["deck_name"]
            self.deck.set_deck_name(self.deck_name)
        self.assignments = {
            k: v for k, v in data.get("assignments", {}).items() if Path(v).exists()
        }
        # kadrowanie tylko dla kart z aktualnym przypisaniem
        self.transforms = {
            k: v for k, v in data.get("transforms", {}).items()
            if k in self.assignments and isinstance(v, dict)
        }
        # wybrane warianty — tylko te, których plik nadal istnieje
        self.selections = {
            k: v for k, v in data.get("selections", {}).items()
            if isinstance(v, str) and Path(v).exists()
        }
        if data.get("values"):
            self._deck_values = list(data["values"])
        if data.get("mode"):
            self.generation.mode_seg.set_current(
                0 if data["mode"] == GenMode.HYBRID.value else 1
            )
        config.TEMPLATE_OVERRIDES.update({
            suit: path for suit, path in data.get("templates", {}).items()
            if Path(path).exists()
        })
        self.generation.limit_spin.setValue(data.get("limit", 0))
        self.generation.versions_spin.setValue(max(1, data.get("versions", 1)))
        self.generation.skip_done_check.setChecked(bool(data.get("skip_done", False)))
        if data.get("card_preset") in config.CARD_PRESETS:
            config.set_card_preset(data["card_preset"])
            self.settings_view.sync_styles()
        auto = data.get("auto_przydzial")
        if isinstance(auto, dict) and isinstance(auto.get("motywy"), dict):
            for kolor in photo_analyzer.DOMYSLNE_MOTYWY:
                motyw = auto["motywy"].get(kolor)
                if isinstance(motyw, str) and motyw.strip():
                    self.auto_motywy[kolor] = motyw
        if isinstance(data.get("back"), dict):
            self.back_view.apply_settings(data["back"])
        if isinstance(data.get("export"), dict):
            self.export_view.apply_settings(data["export"])
        if data.get("model") in config.MODELS:
            config.SELECTED_MODEL = data["model"]
            self._sync_model_views()
        # aktywne presety stylu zapamiętane dla tej talii
        chosen = data.get("style_presets")
        if isinstance(chosen, dict):
            changed = False
            for cat in style_store.CATEGORIES:
                name = chosen.get(cat)
                if isinstance(name, str) and name != style_store.active(cat) \
                        and name in style_store.presets(cat):
                    style_store.set_active(cat, name)
                    changed = True
            if changed:
                # wybory wariantów z projekt.json dotyczyły innych presetów
                config.TEMPLATE_OVERRIDES.clear()
                card_grid.clear_template_cache()
                self.settings_view.refresh_prompt()
                self.back_view.reload_style_slot()
