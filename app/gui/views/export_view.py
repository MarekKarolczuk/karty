"""Widok Eksport: pliki do druku (IRL) i paczka do gry — dwa panele
z wyborem formatu radio-buttonami. Rewers generuje się w zakładce „Rewersy"."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QRadioButton, QVBoxLayout, QWidget,
)

from app import config
from app.gui.views import view_header


class ExportView(QWidget):
    export_clicked = pyqtSignal(str)   # "pdf" | "files" | "zip" | "atlas" | "sprite"

    def __init__(self, parent=None):
        super().__init__(parent)
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
        self.radio_files = QRadioButton("Pojedyncze pliki (300 DPI)")
        self.radio_pdf.setChecked(True)
        self._print_group.addButton(self.radio_pdf)
        self._print_group.addButton(self.radio_files)
        print_layout.addWidget(self.radio_pdf)
        print_layout.addWidget(self.radio_files)

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

        self._refresh_format_hint()

    def showEvent(self, event):  # noqa: N802 (API Qt)
        self._refresh_format_hint()
        super().showEvent(event)

    def _refresh_format_hint(self) -> None:
        w, h = config.CARD_MM
        self.format_hint.setText(f"⌗  {w:g} × {h:g} mm  ·  ◈  300 DPI  "
                                 "(format zmienisz w Ustawieniach)")

    # --- emisje -----------------------------------------------------------------------
    def _emit_print_export(self) -> None:
        self.export_clicked.emit(
            "pdf" if self.radio_pdf.isChecked() else "files"
        )

    def _emit_game_export(self) -> None:
        if self.radio_zip.isChecked():
            self.export_clicked.emit("zip")
        elif self.radio_sprite.isChecked():
            self.export_clicked.emit("sprite")
        else:
            self.export_clicked.emit("atlas")

    # --- API -----------------------------------------------------------------------
    def pdf_columns(self) -> int:
        return 2 if self.narrow_check.isChecked() else 3

    def set_ready_info(self, done: int, total: int) -> None:
        if done == total and config.BACK_PATH.exists():
            self.ready_label.setText(f"✔  {total} karty + rewers gotowe")
            state = "ok"
        else:
            self.ready_label.setText(
                f"{done}/{total} kart gotowych"
                + ("" if config.BACK_PATH.exists() else " · brak rewersu")
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
