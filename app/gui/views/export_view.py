"""Widok Eksport: pliki do druku (IRL) i paczka do gry — dwa panele
z wyborem formatu radio-buttonami. Rewers generuje się w zakładce „Rewersy"."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from app import config
from app.core import style_store
from app.core.eksport.cmyk import SILA_DOMYSLNA, SILA_MAX, SILA_MIN
from app.core.eksport.formaty import MARGINES_BEZPIECZENSTWA_MM, SPAD_MM
from app.gui.views import view_header
from app.gui.widgets import SnapSlider


class ExportView(QWidget):
    export_clicked = pyqtSignal(str)   # "pdf" | "files" | "cmyk" | "krm" | "zip" | "atlas" | "sprite"
    preview_boost_clicked = pyqtSignal(int)   # siła podbicia → podgląd „przed | po"
    options_changed = pyqtSignal()     # zmiana opcji → zapis do projekt.json

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ready_done = 0   # liczba gotowych kart (blokada pustego eksportu)
        self._loading = False  # blokuje options_changed podczas apply_settings
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(10)

        top = QHBoxLayout()
        top.addWidget(view_header(
            "Eksport talii",
            "Pliki do druku oraz paczka do gry / programu komputerowego",
        ))
        top.addStretch(1)
        self.ready_label = QLabel()
        self.ready_label.setObjectName("readyBadge")
        top.addWidget(self.ready_label, alignment=Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(top)

        columns = QHBoxLayout()
        columns.setSpacing(10)

        # --- DO DRUKU (IRL) ---------------------------------------------------------
        print_panel = QWidget()
        print_panel.setObjectName("panel")
        print_layout = QVBoxLayout(print_panel)
        print_layout.setContentsMargins(14, 12, 14, 12)
        print_layout.setSpacing(8)

        print_caption = QLabel("🖨  DO DRUKU (IRL)")
        print_caption.setObjectName("sectionTitle")
        print_layout.addWidget(print_caption)

        self._print_group = QButtonGroup(self)
        self.radio_pdf = QRadioButton("Arkusz PDF (A4 · 9 kart/stronę)")
        self.radio_files = QRadioButton("Pojedyncze pliki PNG (300 DPI · RGB)")
        self.radio_cmyk = QRadioButton("Pliki CMYK do druku (TIFF · spad 3 mm)")
        self.radio_cmyk.setToolTip(
            "Jeden plik TIFF na kartę: CMYK, 300 DPI, spad 3 mm — gotowe do "
            "wysłania do drukarni. Profil ICC weź z assets/icc (można wrzucić "
            "profil własnej drukarni)."
        )
        self.radio_krm = QRadioButton("Druk do KRM (PDF CMYK · jeden plik)")
        self.radio_krm.setToolTip(
            "Wielostronicowy PDF CMYK 300 DPI wg specyfikacji drukarni KRM:\n"
            "• strona = pełne brutto formatu (netto + spad 3 mm)\n"
            "• karta przeskalowana z zachowaniem proporcji tak, by zmieścić się\n"
            "  5 mm w głąb od linii cięcia, i wyśrodkowana\n"
            "• całe tło zalane jednolitym kolorem z krawędzi karty — bez białych\n"
            "  rogów, przezroczystości i zaokrągleń\n"
            "• strona 1 to rewers, kolejne to awersy\n"
            "Spad i znaczniki cięcia nie mają tu zastosowania (geometria sztywna)."
        )
        self.radio_pdf.setChecked(True)
        for radio in (self.radio_pdf, self.radio_files, self.radio_cmyk,
                      self.radio_krm):
            self._print_group.addButton(radio)
            print_layout.addWidget(radio)

        check_row = QHBoxLayout()
        self.bleed_check = QCheckBox("Spad 3 mm")
        self.bleed_check.setChecked(True)
        check_row.addWidget(self.bleed_check)
        self.marks_check = QCheckBox("Znaczniki cięcia")
        self.marks_check.setChecked(True)
        check_row.addWidget(self.marks_check)
        check_row.addStretch(1)
        print_layout.addLayout(check_row)

        self.backs_check = QCheckBox("Strony rewersów (druk dwustronny)")
        self.backs_check.setChecked(True)
        print_layout.addWidget(self.backs_check)

        self.narrow_check = QCheckBox("2 × 3 na stronę — margines drukarki")
        self.narrow_check.setToolTip(
            "Spad 3 mm przy 3×3 zostawia tylko 1,5 mm marginesu — "
            "część drukarek tyle nie zadrukuje"
        )
        print_layout.addWidget(self.narrow_check)

        # --- podbicie kolorów (dotyczy wyjść CMYK) ------------------------------------
        boost_row = QHBoxLayout()
        self.boost_caption = QLabel("Podbicie kolorów (druk)")
        boost_row.addWidget(self.boost_caption)
        self.boost_slider = SnapSlider(SILA_MIN, SILA_MAX, SILA_DOMYSLNA)
        self.boost_slider.setFixedWidth(140)
        self.boost_slider.setToolTip(
            "Kompensuje węższy gamut CMYK: rozciągnięcie zakresu tonalnego, "
            "gamma, kontrast, nasycenie i mikrokontrast.\n"
            "1 = prawie bez ingerencji, 3 = domyślne, 5 = mocne."
        )
        boost_row.addWidget(self.boost_slider)
        self.boost_value = QLabel(str(SILA_DOMYSLNA))
        self.boost_value.setObjectName("hint")
        boost_row.addWidget(self.boost_value)
        self.boost_preview_btn = QPushButton("👁  Podgląd podbicia")
        self.boost_preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.boost_preview_btn.setToolTip(
            "Składa PNG z porównaniem przed/po na pierwszej gotowej karcie "
            "— ocena bez drukowania całego PDF-a."
        )
        self.boost_preview_btn.clicked.connect(
            lambda: self.preview_boost_clicked.emit(self.boost_level()))
        boost_row.addWidget(self.boost_preview_btn)
        boost_row.addStretch(1)
        print_layout.addLayout(boost_row)
        self.boost_slider.valueChanged.connect(self._on_boost_changed)

        # bez profilu ICC konwersja CMYK jest niekalibrowana (choć z uczciwą
        # czernią) — użytkownik ma to widzieć PRZED wysyłką do drukarni
        self.icc_hint = QLabel()
        self.icc_hint.setObjectName("hint")
        print_layout.addWidget(self.icc_hint)

        self.format_hint = QLabel()
        self.format_hint.setObjectName("hint")
        print_layout.addWidget(self.format_hint)
        print_layout.addStretch(1)

        pdf_btn = QPushButton("⇩  Pobierz do druku")
        pdf_btn.setObjectName("generateBtn")
        pdf_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pdf_btn.clicked.connect(self._emit_print_export)
        print_layout.addWidget(pdf_btn)
        columns.addWidget(print_panel, stretch=1)

        # --- DO GRY / PROGRAMU --------------------------------------------------------
        game_panel = QWidget()
        game_panel.setObjectName("panel")
        game_layout = QVBoxLayout(game_panel)
        game_layout.setContentsMargins(14, 12, 14, 12)
        game_layout.setSpacing(8)

        game_caption = QLabel("🎮  DO GRY / PROGRAMU")
        game_caption.setObjectName("sectionTitle")
        game_layout.addWidget(game_caption)

        self._game_group = QButtonGroup(self)
        self.radio_zip = QRadioButton("PNG w ZIP\n52 karty + rewers · "
                                      "nazwy [Wartość]_[kolor]")
        self.radio_sprite = QRadioButton("Arkusz-atlas (sprite sheet)\n"
                                         "jeden obraz · siatka 13×4")
        self.radio_tts = QRadioButton("Tabletop Simulator\n"
                                      "obraz talii 10×7 + rewers")
        self.radio_zip.setChecked(True)
        for radio in (self.radio_zip, self.radio_sprite, self.radio_tts):
            self._game_group.addButton(radio)
            game_layout.addWidget(radio)

        self.small_check = QCheckBox("Wersja lekka ≤ 4096 px (starsze GPU)")
        game_layout.addWidget(self.small_check)

        files_hint = QLabel("A_karo.png · K_kier.png · … · rewers.png")
        files_hint.setObjectName("folderName")
        files_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        game_layout.addWidget(files_hint)
        game_layout.addStretch(1)

        game_btn = QPushButton("⇩  Pobierz paczkę")
        game_btn.setObjectName("generateBtn")
        game_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        game_btn.clicked.connect(self._emit_game_export)
        game_layout.addWidget(game_btn)
        columns.addWidget(game_panel, stretch=1)

        layout.addLayout(columns, stretch=1)

        # --- pasek postępu eksportu ---------------------------------------------------
        progress_row = QHBoxLayout()
        self.progress_label = QLabel()
        self.progress_label.setObjectName("statusText")
        progress_row.addWidget(self.progress_label, stretch=1)
        self.progress = QProgressBar()
        self.progress.setFixedWidth(260)
        self.progress.hide()
        progress_row.addWidget(self.progress)
        layout.addLayout(progress_row)

        # każda zmiana opcji eksportu → sygnał zapisu (trwałość między sesjami)
        for btn in (self.radio_pdf, self.radio_files, self.radio_cmyk,
                    self.radio_krm, self.radio_zip, self.radio_sprite,
                    self.radio_tts):
            btn.toggled.connect(self._emit_options_changed)
        for chk in (self.bleed_check, self.marks_check, self.backs_check,
                    self.narrow_check, self.small_check):
            chk.toggled.connect(self._emit_options_changed)

        # podpowiedź rozmiaru pliku zależy od trybu CMYK i spadu
        for w in (self.radio_pdf, self.radio_files, self.radio_cmyk,
                  self.radio_krm, self.bleed_check):
            w.toggled.connect(lambda _c: self._refresh_format_hint())
        for w in (self.radio_pdf, self.radio_files, self.radio_cmyk,
                  self.radio_krm):
            w.toggled.connect(lambda _c: self._refresh_print_options())

        self._refresh_print_options()
        self._refresh_format_hint()

    def _emit_options_changed(self, _checked: bool = False) -> None:
        if not self._loading:
            self.options_changed.emit()

    def _on_boost_changed(self, value: int) -> None:
        self.boost_value.setText(str(value))
        self._emit_options_changed()

    def _refresh_print_options(self) -> None:
        """Podbicie kolorów dotyczy tylko wyjść CMYK; przy KRM geometria jest
        sztywna, więc spad i znaczniki cięcia są nieaktywne."""
        cmyk = self.radio_cmyk.isChecked() or self.radio_krm.isChecked()
        for w in (self.boost_caption, self.boost_slider, self.boost_value,
                  self.boost_preview_btn):
            w.setEnabled(cmyk)
        profil = config.cmyk_profile_path()
        self.icc_hint.setText(
            f"◈  profil ICC: {profil.name}" if profil is not None
            else "◈  brak profilu ICC — kolory niekalibrowane "
                 "(wrzuć plik .icc od drukarni do assets/icc/)")
        self.icc_hint.setVisible(cmyk)
        krm = self.radio_krm.isChecked()
        for chk in (self.bleed_check, self.marks_check):
            chk.setEnabled(not krm)

    def settings(self) -> dict:
        """Stan opcji eksportu do zapisania w projekt.json."""
        return {
            "print_kind": ("krm" if self.radio_krm.isChecked()
                           else "cmyk" if self.radio_cmyk.isChecked()
                           else "files" if self.radio_files.isChecked()
                           else "pdf"),
            "boost": self.boost_level(),
            "game_kind": ("sprite" if self.radio_sprite.isChecked()
                          else "atlas" if self.radio_tts.isChecked() else "zip"),
            "bleed": self.bleed_check.isChecked(),
            "marks": self.marks_check.isChecked(),
            "backs": self.backs_check.isChecked(),
            "narrow": self.narrow_check.isChecked(),
            "small": self.small_check.isChecked(),
        }

    def apply_settings(self, data: dict) -> None:
        """Odtwarza opcje eksportu z projekt.json (bez emitowania zapisu)."""
        if not isinstance(data, dict):
            return
        self._loading = True
        print_kind = data.get("print_kind")
        (self.radio_krm if print_kind == "krm"
         else self.radio_cmyk if print_kind == "cmyk"
         else self.radio_files if print_kind == "files"
         else self.radio_pdf).setChecked(True)
        self.boost_slider.setValue(int(data.get("boost", SILA_DOMYSLNA)))
        game = data.get("game_kind")
        (self.radio_sprite if game == "sprite"
         else self.radio_tts if game == "atlas"
         else self.radio_zip).setChecked(True)
        self.bleed_check.setChecked(bool(data.get("bleed", True)))
        self.marks_check.setChecked(bool(data.get("marks", True)))
        self.backs_check.setChecked(bool(data.get("backs", True)))
        self.narrow_check.setChecked(bool(data.get("narrow", False)))
        self.small_check.setChecked(bool(data.get("small", False)))
        self._loading = False

    def showEvent(self, event):  # noqa: N802 (API Qt)
        self._refresh_format_hint()
        super().showEvent(event)

    def _refresh_format_hint(self) -> None:
        w, h = config.CARD_MM
        if self.radio_krm.isChecked():
            from app.core.eksport.formaty import aktywny_format
            fmt = aktywny_format()
            brutto_mm, brutto_px = fmt.mm_ze_spadem, fmt.px_300dpi_ze_spadem
            # karta skalowana JEDNOLICIE do prostokąta bezpieczeństwa
            rw, rh = fmt.mm_ramki
            skala = min(rw / w, rh / h)
            self.format_hint.setText(
                f"⌗  plik {brutto_mm[0]:g} × {brutto_mm[1]:g} mm "
                f"({brutto_px[0]} × {brutto_px[1]} px)  ·  cięcie {w:g} × {h:g}"
                f"  ·  karta {w * skala:.0f} × {h * skala:.0f} mm "
                f"(margines bezp. {MARGINES_BEZPIECZENSTWA_MM:g} + spad "
                f"{SPAD_MM:g} mm)  ·  ◈  300 DPI · CMYK")
        elif self.radio_cmyk.isChecked() and self.bleed_check.isChecked():
            spad = 3
            self.format_hint.setText(
                f"⌗  plik {w + 2 * spad:g} × {h + 2 * spad:g} mm  "
                f"(netto {w:g} × {h:g} + spad {spad} mm)  ·  ◈  300 DPI · CMYK")
        else:
            self.format_hint.setText(f"⌗  {w:g} × {h:g} mm  ·  ◈  300 DPI  "
                                     "(format zmienisz w Ustawieniach)")

    # --- emisje -----------------------------------------------------------------------
    def _guard_ready(self) -> bool:
        """Nie eksportuj pustej talii — czytelny komunikat zamiast pliku z pustkami."""
        if self._ready_done <= 0:
            self.set_export_status(
                "Brak gotowych kart do eksportu — najpierw wygeneruj talię "
                "na Ekranie roboczym.", finished=True)
            return False
        return True

    def _emit_print_export(self) -> None:
        if not self._guard_ready():
            return
        if self.radio_krm.isChecked():
            self.export_clicked.emit("krm")
        elif self.radio_cmyk.isChecked():
            self.export_clicked.emit("cmyk")
        elif self.radio_files.isChecked():
            self.export_clicked.emit("files")
        else:
            self.export_clicked.emit("pdf")

    def _emit_game_export(self) -> None:
        if not self._guard_ready():
            return
        if self.radio_zip.isChecked():
            self.export_clicked.emit("zip")
        elif self.radio_sprite.isChecked():
            self.export_clicked.emit("sprite")
        else:
            self.export_clicked.emit("atlas")

    # --- API -----------------------------------------------------------------------
    def pdf_columns(self) -> int:
        return 2 if self.narrow_check.isChecked() else 3

    def boost_level(self) -> int:
        """Siła podbicia kolorów (1-5) dla wyjść CMYK."""
        return int(self.boost_slider.value())

    def krm_selected(self) -> bool:
        return self.radio_krm.isChecked()

    def set_ready_info(self, done: int, total: int) -> None:
        self._ready_done = done
        has_back = style_store.back_path().exists()
        if done == total and has_back:
            self.ready_label.setText(f"✔  {total} karty + rewers gotowe")
            state = "ok"
        else:
            self.ready_label.setText(
                f"{done}/{total} kart gotowych"
                + ("" if has_back else " · brak rewersu")
            )
            state = "warn"
        self.ready_label.setProperty("state", state)
        style = self.ready_label.style()
        if style is not None:
            style.unpolish(self.ready_label)
            style.polish(self.ready_label)

    def set_export_progress(self, done: int, total: int) -> None:
        self.progress.setVisible(True)
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)

    def set_export_status(self, text: str, finished: bool = False) -> None:
        self.progress_label.setText(text)
        if finished:
            self.progress.hide()
