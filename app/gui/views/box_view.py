"""Widok „Pudełko": projektowanie, edycja i eksport pudełka na karty.

Jedna spójna grafika AI ze WSZYSTKICH zdjęć osób talii, wciśnięta w wybrany
wykrojnik (dieline) z biblioteki Style/Pudełka/ i przycięta do spadu; linie
cięcia/bigowania nakładane jako warstwa proof. Widok emituje sygnały —
generację/import/poprawkę/eksport prowadzi MainWindow → worker → generator
(zasada: widoki nie wołają logiki bezpośrednio). Podgląd reużywa
lightbox.ZoomableImage (zoom kółkiem, pan). Zero wywołań API w tym pliku.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QCheckBox, QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from app import config
from app.core import pudelko, style_store
from app.gui.animations import Spinner
from app.gui.lightbox import ZoomableImage
from app.gui.views import view_header
from app.gui.widgets import (
    NoScrollComboBox, SegmentedControl, cover_pixmap, show_toast,
)

PREVIEW_W, PREVIEW_H = 460, 360
THUMB_W, THUMB_H = 150, 150


class BoxView(QWidget):
    generate_box_clicked = pyqtSignal(dict)   # {"custom": str}
    import_box_clicked = pyqtSignal(str)      # ścieżka własnego projektu
    fix_box_clicked = pyqtSignal()            # otwórz „Popraw selektywnie"
    export_box_clicked = pyqtSignal(dict)     # {"format": "png"|"pdf", "z_liniami": bool}
    box_changed = pyqtSignal()                # opis/wykrojnik zmieniony → zapis
    set_main_variant = pyqtSignal(str)        # stempel wariantu → ustaw główny

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(14)
        root.addWidget(view_header(
            "Pudełko na karty",
            "Zaprojektuj grafikę pudełka z twarzami wszystkich osób z talii, "
            "dopasowaną do wykrojnika, i wyeksportuj do druku"))

        columns = QHBoxLayout()
        columns.setSpacing(14)
        columns.addWidget(self._build_controls(), stretch=3)
        columns.addWidget(self._build_preview(), stretch=4)
        root.addLayout(columns)
        root.addStretch(1)

        self._refresh_dieline_thumb()
        self.refresh_box_preview()

    # --- lewa kolumna: sterowanie ---------------------------------------------
    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        cap = QLabel("▧  PROJEKT PUDEŁKA")
        cap.setObjectName("sectionTitle")
        lay.addWidget(cap)

        tryb_caption = QLabel("TRYB KOMPOZYCJI")
        tryb_caption.setObjectName("sideCaption")
        lay.addWidget(tryb_caption)
        self.tryb_seg = SegmentedControl(
            ["🖼 Jedna scena", "🧩 Osobne panele"])
        self.tryb_seg.changed.connect(lambda _=0: self._refresh_tryb_hint())
        lay.addWidget(self.tryb_seg)
        self.tryb_hint = QLabel("")
        self.tryb_hint.setObjectName("hint")
        self.tryb_hint.setWordWrap(True)
        lay.addWidget(self.tryb_hint)
        self._refresh_tryb_hint()

        die_caption = QLabel("WYKROJNIK (DIELINE)")
        die_caption.setObjectName("sideCaption")
        lay.addWidget(die_caption)
        self.dieline_combo = NoScrollComboBox()
        self.dieline_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reload_dielines()
        self.dieline_combo.currentIndexChanged.connect(self._on_dieline_changed)
        lay.addWidget(self.dieline_combo)

        self.dieline_thumb = QLabel()
        self.dieline_thumb.setObjectName("well")
        self.dieline_thumb.setFixedSize(THUMB_W, THUMB_H)
        self.dieline_thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.dieline_thumb, alignment=Qt.AlignmentFlag.AlignHCenter)

        self.dieline_info = QLabel("")
        self.dieline_info.setObjectName("hint")
        self.dieline_info.setWordWrap(True)
        lay.addWidget(self.dieline_info)

        people_caption = QLabel("OSOBY Z TALII")
        people_caption.setObjectName("sideCaption")
        lay.addWidget(people_caption)
        self.people_info = QLabel("—")
        self.people_info.setObjectName("hint")
        self.people_info.setWordWrap(True)
        lay.addWidget(self.people_info)

        # osobne portrety (1 osoba/plik) — dodatkowe referencje wierności twarzy
        self._osobne_folder = ""
        self.osobne_check = QCheckBox("🧑 Wyślij osobne portrety osób (1 os./plik)")
        self.osobne_check.setToolTip(
            "Dodatkowo wysyła zdjęcia z folderu, gdzie KAŻDY plik to jedna "
            "osoba — model wtedy wstawia każdego wiernie (własna twarz).")
        self.osobne_check.toggled.connect(self._on_osobne_toggled)
        lay.addWidget(self.osobne_check)
        osobne_row = QHBoxLayout()
        osobne_row.setSpacing(6)
        self.osobne_btn = QPushButton("📁 Folder portretów…")
        self.osobne_btn.setObjectName("ghostBtn")
        self.osobne_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.osobne_btn.clicked.connect(self._pick_osobne_folder)
        osobne_row.addWidget(self.osobne_btn)
        lay.addLayout(osobne_row)
        self.osobne_info = QLabel("")
        self.osobne_info.setObjectName("hint")
        self.osobne_info.setWordWrap(True)
        lay.addWidget(self.osobne_info)
        self._refresh_osobne_info()

        opis_caption = QLabel("OPIS STYLU (zapisywany w presecie)")
        opis_caption.setObjectName("sideCaption")
        lay.addWidget(opis_caption)
        self._opis_debounce = QTimer(self)
        self._opis_debounce.setSingleShot(True)
        self._opis_debounce.setInterval(400)
        self._opis_debounce.timeout.connect(self._apply_opis)
        self.opis_edit = QPlainTextEdit()
        self.opis_edit.setObjectName("styleEdit")
        self.opis_edit.setPlaceholderText(
            "Opisz styl grafiki pudełka (nastrój, kolory, aranżacja osób)… "
            "puste = domyślny styl talii")
        self.opis_edit.setFixedHeight(90)
        self.opis_edit.setPlainText(style_store.box_text())
        self.opis_edit.textChanged.connect(self._opis_debounce.start)
        lay.addWidget(self.opis_edit)

        self.custom_check = QCheckBox(
            "🧩 Tryb własnego promptu — wysyłaj opis dosłownie")
        self.custom_check.setToolTip(
            "Bez wbudowanych dopisków (wraparound, wierność twarzy, zakaz "
            "tekstu) — do modelu idzie wyłącznie opis powyżej. Zapisywane "
            "w presecie.")
        self.custom_check.setChecked(style_store.box_custom_mode())
        self.custom_check.toggled.connect(self._on_custom_toggled)
        lay.addWidget(self.custom_check)

        lay.addStretch(1)
        return panel

    # --- prawa kolumna: podgląd + akcje ---------------------------------------
    def _build_preview(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("panel")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(8)

        cap = QLabel("PODGLĄD (linie cięcia = niebieski, zgięcia = czerwony)")
        cap.setObjectName("sideCaption")
        lay.addWidget(cap)

        self.preview = ZoomableImage()
        self.preview.setMinimumSize(PREVIEW_W, PREVIEW_H)
        self.preview.setStyleSheet(
            f"background: {config.CREAM_HEX}; border-radius: 10px;")
        lay.addWidget(self.preview, stretch=1)

        self.placeholder = QLabel("brak grafiki pudełka —\nwygeneruj ją AI "
                                  "albo wgraj własny projekt")
        self.placeholder.setObjectName("hint")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.placeholder)

        # --- nawigator historii wariantów (jak przy taliach) ---
        self._warianty: list[str] = []
        self._pozycja = 0
        self.history_row = QWidget()
        hist = QHBoxLayout(self.history_row)
        hist.setContentsMargins(0, 0, 0, 0)
        hist.setSpacing(6)
        self.hist_prev = QPushButton("◀")
        self.hist_prev.setObjectName("ghostBtn")
        self.hist_prev.setFixedWidth(34)
        self.hist_prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_prev.clicked.connect(lambda: self._navigate(-1))
        hist.addWidget(self.hist_prev)
        self.hist_label = QLabel("—")
        self.hist_label.setObjectName("hint")
        self.hist_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hist.addWidget(self.hist_label, stretch=1)
        self.hist_next = QPushButton("▶")
        self.hist_next.setObjectName("ghostBtn")
        self.hist_next.setFixedWidth(34)
        self.hist_next.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_next.clicked.connect(lambda: self._navigate(1))
        hist.addWidget(self.hist_next)
        self.hist_set_main = QPushButton("✓ Ustaw jako główną")
        self.hist_set_main.setObjectName("outlineBtn")
        self.hist_set_main.setCursor(Qt.CursorShape.PointingHandCursor)
        self.hist_set_main.clicked.connect(self._emit_set_main)
        hist.addWidget(self.hist_set_main)
        lay.addWidget(self.history_row)

        # status generacji / treść błędu — widoczny NA TEJ zakładce (log API
        # jest na Ekranie roboczym; użytkownik nie widział, co poszło nie tak)
        self.box_status = QLabel("")
        self.box_status.setObjectName("hint")
        self.box_status.setWordWrap(True)
        self.box_status.hide()
        lay.addWidget(self.box_status)

        gen_row = QHBoxLayout()
        self.spinner = Spinner(18)
        self.spinner.hide()
        gen_row.addWidget(self.spinner)
        self.gen_btn = QPushButton("✨  Generuj pudełko")
        self.gen_btn.setObjectName("generateBtn")
        self.gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gen_btn.clicked.connect(self._emit_generate)
        gen_row.addWidget(self.gen_btn, stretch=1)
        lay.addLayout(gen_row)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.import_btn = QPushButton("🖼  Wgraj własny projekt")
        self.import_btn.setObjectName("ghostBtn")
        self.import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.import_btn.clicked.connect(self._pick_import)
        actions.addWidget(self.import_btn)
        self.fix_btn = QPushButton("🩹  Popraw selektywnie")
        self.fix_btn.setObjectName("ghostBtn")
        self.fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fix_btn.clicked.connect(self.fix_box_clicked.emit)
        actions.addWidget(self.fix_btn)
        lay.addLayout(actions)

        self.lines_check = QCheckBox("Eksportuj z liniami cięcia (proof)")
        self.lines_check.setToolTip(
            "Włączone = plik z naniesionymi liniami cięcia/bigowania (proof "
            "do sprawdzenia). Wyłączone = czysty artwork dla drukarni "
            "z osobną warstwą dieline.")
        self.lines_check.setChecked(True)
        lay.addWidget(self.lines_check)

        export = QHBoxLayout()
        export.setSpacing(6)
        self.export_png_btn = QPushButton("⇩  Eksport PNG (300 DPI)")
        self.export_png_btn.setObjectName("outlineBtn")
        self.export_png_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_png_btn.clicked.connect(lambda: self._emit_export("png"))
        export.addWidget(self.export_png_btn)
        self.export_pdf_btn = QPushButton("⇩  Eksport PDF")
        self.export_pdf_btn.setObjectName("outlineBtn")
        self.export_pdf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_pdf_btn.clicked.connect(lambda: self._emit_export("pdf"))
        export.addWidget(self.export_pdf_btn)
        lay.addLayout(export)

        self.export_cmyk_btn = QPushButton("⇩  Eksport CMYK (PDF 300 DPI)")
        self.export_cmyk_btn.setObjectName("outlineBtn")
        self.export_cmyk_btn.setToolTip(
            "PDF w CMYK 300 DPI z podbitymi kolorami (żywe jak w RGB) i "
            "osadzonym profilem ICC — gotowe do drukarni.")
        self.export_cmyk_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.export_cmyk_btn.clicked.connect(lambda: self._emit_export("cmyk"))
        lay.addWidget(self.export_cmyk_btn)
        return panel

    # --- dieline ---------------------------------------------------------------
    def _reload_dielines(self) -> None:
        self.dieline_combo.blockSignals(True)
        self.dieline_combo.clear()
        wykrojniki = pudelko.wykrojniki()
        if not wykrojniki:
            self.dieline_combo.addItem("— brak wykrojników w Style/Pudełka/ —", "")
        else:
            aktywny = style_store.active_dieline()
            for p in wykrojniki:
                self.dieline_combo.addItem(p.stem, p.name)
            idx = self.dieline_combo.findData(aktywny)
            self.dieline_combo.setCurrentIndex(max(0, idx))
        self.dieline_combo.blockSignals(False)

    def _current_dieline(self) -> Path | None:
        name = self.dieline_combo.currentData()
        if not name:
            return None
        p = pudelko.PUDELKA_DIR / name
        return p if p.exists() else None

    def _on_dieline_changed(self, _index: int) -> None:
        name = self.dieline_combo.currentData() or ""
        style_store.set_text("pudelko", "wykrojnik", name)
        self._refresh_dieline_thumb()
        self.box_changed.emit()

    def _refresh_dieline_thumb(self) -> None:
        die = self._current_dieline()
        if die is None:
            self.dieline_thumb.setText("—")
            self.dieline_info.setText("Dodaj plik wykrojnika PNG do "
                                      "folderu Style/Pudełka/.")
            return
        self.dieline_thumb.setPixmap(
            cover_pixmap(die, THUMB_W, THUMB_H, radius=8))
        dm = pudelko.design_area_mm(die)
        if dm:
            self.dieline_info.setText(
                f"Obszar projektu: {dm[0]:g} × {dm[1]:g} mm · eksport 300 DPI.")
        else:
            self.dieline_info.setText(
                "Brak wymiarów — zostaniesz o nie zapytany przy generacji.")

    # --- opis / tryb -----------------------------------------------------------
    def tryb(self) -> str:
        return "panele" if self.tryb_seg.current() == 1 else "scena"

    def _refresh_tryb_hint(self) -> None:
        if self.tryb() == "panele":
            self.tryb_hint.setText(
                "Przód i tył = osobne sceny AI z osobami (2 generacje, spójne "
                "przez wspólny styl). Boki = jednolite tło w kolorze frontu + "
                "prawdziwe mini-karty. Wymaga wygenerowanych kart.")
        else:
            self.tryb_hint.setText(
                "Jedna scena AI z wszystkimi osobami rozłożona na całym "
                "wykrojniku.")

    # --- osobne portrety -------------------------------------------------------
    def _on_osobne_toggled(self, _on: bool = False) -> None:
        self._refresh_osobne_info()
        self.box_changed.emit()

    def _pick_osobne_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Folder z osobnymi portretami (1 osoba/plik)",
            self._osobne_folder or "")
        if folder:
            self._osobne_folder = folder
            self.osobne_check.setChecked(True)
            self._refresh_osobne_info()
            self.box_changed.emit()

    def _osobne_liczba(self) -> int:
        d = Path(self._osobne_folder)
        if not self._osobne_folder or not d.is_dir():
            return 0
        return sum(1 for p in d.iterdir()
                   if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))

    def _refresh_osobne_info(self) -> None:
        aktywne = self.osobne_check.isChecked()
        self.osobne_btn.setEnabled(aktywne)
        if not self._osobne_folder:
            self.osobne_info.setText("Wskaż folder — każdy plik to jedna osoba.")
            return
        self.osobne_info.setText(
            f"{Path(self._osobne_folder).name} · {self._osobne_liczba()} zdjęć"
            + ("" if aktywne else " (opcja wyłączona)"))

    def _apply_opis(self) -> None:
        style_store.set_text("pudelko", "opis", self.opis_edit.toPlainText())
        self.box_changed.emit()

    def _on_custom_toggled(self, on: bool) -> None:
        style_store.set_text("pudelko", "tryb_wlasny", "1" if on else "0")
        self.box_changed.emit()

    # --- emisje ----------------------------------------------------------------
    def _emit_generate(self) -> None:
        if self._current_dieline() is None:
            show_toast(self, "Najpierw dodaj wykrojnik do Style/Pudełka/",
                       "error")
            return
        self.generate_box_clicked.emit(
            {"custom": self.opis_edit.toPlainText(), "tryb": self.tryb(),
             "osobne_on": self.osobne_check.isChecked(),
             "osobne_folder": self._osobne_folder})

    def _pick_import(self) -> None:
        if self._current_dieline() is None:
            show_toast(self, "Najpierw wybierz wykrojnik", "error")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Wybierz własny projekt pudełka", "",
            "Obrazy (*.png *.jpg *.jpeg *.webp)")
        if path:
            self.import_box_clicked.emit(path)

    def _emit_export(self, fmt: str) -> None:
        self.export_box_clicked.emit(
            {"format": fmt, "z_liniami": self.lines_check.isChecked()})

    # --- API dla MainWindow ----------------------------------------------------
    def current_dieline(self) -> Path | None:
        return self._current_dieline()

    def export_with_lines(self) -> bool:
        return self.lines_check.isChecked()

    def reload_library(self) -> None:
        """Odśwież listę wykrojników (np. po dodaniu pliku) + miniaturę."""
        self._reload_dielines()
        self._refresh_dieline_thumb()

    def set_people_info(self, liczba_zdjec: int, liczba_osob: int | None) -> None:
        if liczba_zdjec == 0:
            self.people_info.setText(
                "Brak przypisanych zdjęć — przypisz zdjęcia do kart na Ekranie "
                "roboczym, żeby trafiły na pudełko.")
            return
        osoby = (f" (≈{liczba_osob} osób)" if liczba_osob else "")
        self.people_info.setText(
            f"{liczba_zdjec} unikalnych zdjęć{osoby} trafi na grafikę pudełka.")

    def set_box_busy(self, busy: bool) -> None:
        self.gen_btn.setEnabled(not busy)
        self.import_btn.setEnabled(not busy)
        self.fix_btn.setEnabled(not busy)
        self.spinner.setVisible(busy)
        self.gen_btn.setText("⏳  Generuję pudełko..." if busy
                             else "✨  Generuj pudełko")
        if busy:
            self.set_box_status("")   # świeży start — czyść poprzedni błąd
        else:
            self.refresh_box_preview()

    def set_box_status(self, text: str, error: bool = False) -> None:
        """Pokaz etap generacji lub treść błędu na zakładce Pudełko. Pusty
        tekst chowa etykietę."""
        if not text:
            self.box_status.clear()
            self.box_status.hide()
            return
        self.box_status.setStyleSheet(
            "color:#c0392b;" if error else "")
        self.box_status.setText(text)
        self.box_status.show()

    def refresh_box_preview(self) -> None:
        box = style_store.box_path()
        if box.exists():
            self.preview.set_pixmap(QPixmap(str(box)))
            self.preview.show()
            self.placeholder.hide()
        else:
            self.preview.hide()
            self.placeholder.show()
        self.reload_history()

    # --- historia wariantów ----------------------------------------------------
    def reload_history(self) -> None:
        """Odświeża listę wariantów pudełka i ustawia pozycję na główny."""
        self._warianty = pudelko.warianty_pudelka()
        glowny = pudelko.glowny_stamp()
        if glowny in self._warianty:
            self._pozycja = self._warianty.index(glowny)
        else:
            self._pozycja = 0
        self._refresh_history_ui()

    def _refresh_history_ui(self) -> None:
        n = len(self._warianty)
        self.history_row.setVisible(n > 0)
        if n == 0:
            return
        stamp = self._warianty[self._pozycja]
        czytelny = stamp.replace("_", " ", 1)
        glowny = " · GŁÓWNY" if stamp == pudelko.glowny_stamp() else ""
        self.hist_label.setText(f"wariant {self._pozycja + 1}/{n} · {czytelny}{glowny}")
        self.hist_prev.setEnabled(self._pozycja < n - 1)   # dalej = starsze
        self.hist_next.setEnabled(self._pozycja > 0)
        self.hist_set_main.setEnabled(stamp != pudelko.glowny_stamp())

    def _navigate(self, krok: int) -> None:
        n = len(self._warianty)
        if n == 0:
            return
        # lista jest od najnowszego: ◀ (krok -1) idzie do starszych (indeks +1)
        self._pozycja = max(0, min(n - 1, self._pozycja - krok))
        _raw, proof = pudelko.sciezki_wariantu(self._warianty[self._pozycja])
        if proof.exists():
            self.preview.set_pixmap(QPixmap(str(proof)))
            self.preview.show()
            self.placeholder.hide()
        self._refresh_history_ui()

    def _emit_set_main(self) -> None:
        if self._warianty:
            self.set_main_variant.emit(self._warianty[self._pozycja])

    # --- stan projektu ---------------------------------------------------------
    def settings(self) -> dict:
        return {"z_liniami": self.lines_check.isChecked(), "tryb": self.tryb(),
                "osobne_on": self.osobne_check.isChecked(),
                "osobne_folder": self._osobne_folder}

    def apply_settings(self, data: dict) -> None:
        self.lines_check.setChecked(bool(data.get("z_liniami", True)))
        self.tryb_seg.set_current(1 if data.get("tryb") == "panele" else 0)
        if isinstance(data.get("osobne_folder"), str):
            self._osobne_folder = data["osobne_folder"]
        self.osobne_check.blockSignals(True)
        self.osobne_check.setChecked(bool(data.get("osobne_on", False)))
        self.osobne_check.blockSignals(False)
        self._refresh_osobne_info()
        self._refresh_tryb_hint()
        self.opis_edit.blockSignals(True)
        self.opis_edit.setPlainText(style_store.box_text())
        self.opis_edit.blockSignals(False)
        self.custom_check.blockSignals(True)
        self.custom_check.setChecked(style_store.box_custom_mode())
        self.custom_check.blockSignals(False)
        self._reload_dielines()
        self._refresh_dieline_thumb()
