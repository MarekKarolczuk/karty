"""Dialog selektywnej poprawy karty (korekcyjny inpainting): użytkownik
maluje pędzlem obszar błędu na WYBRANYM wariancie karty i wybiera tryb:
poprawa AI (własny prompt korygujący + suwak siły zmian) albo przywrócenie
tła szablonu (deterministyczne, bez API — np. krzywe linie ramki).

Dialog niczego nie generuje — zero wywołań API; komplet (maska, prompt,
tryb, siła) odbiera MainWindow i przekazuje do FixWorker →
generator.popraw_region (zmiana ograniczona do maski, strefy twarde
bordiury/tarcz z szablonu, wynik = NOWY wariant karty).
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QVBoxLayout,
)

from app.gui.mask_editor import _BRUSH_MAX, _BRUSH_MIN, _MaskCanvas
from app.gui.widgets import SegmentedControl, SnapSlider

# poprawki bywają punktowe (ucięty listek, oko) — start mniejszy niż
# w edytorze stref pop-out
_BRUSH_START_FIX = 60

_HINT_AI = (
    "Zamaluj pędzlem obszar do poprawy (np. uciętą twarz, brakujący "
    "detal) i opisz poniżej, co ma się w nim zmienić. Model przerysuje "
    "WYŁĄCZNIE zamalowany obszar — reszta karty, ramka i kolory "
    "pozostaną nienaruszone; wynik zapisze się jako NOWY wariant. "
    "Krzywe linie ramki i zniekształcony symbol naprawiaj trybem "
    "„Przywróć tło szablonu”."
)
_HINT_SZABLON = (
    "Zamaluj pędzlem obszar, który ma wrócić piksel-w-piksel do tła "
    "z szablonu (np. krzywe linie ramki, przestylizowany ornament). "
    "Bez wywołania API — deterministycznie; wynik zapisze się jako "
    "NOWY wariant."
)

# słowny opis pozycji suwaka „Siła poprawki" (1-5)
_SILA_OPISY = {
    1: "delikatny retusz",
    2: "zachowawcza",
    3: "standardowa",
    4: "mocna (detale od nowa)",
    5: "przemaluj od zera",
}


class FixRegionDialog(QDialog):
    """Maska korekty + tryb poprawy dla jednego wariantu karty.
    exec() → Accepted tylko z niepustą maską (tryb AI wymaga też promptu);
    wyniki przez maska(), prompt_uzytkownika(), tryb() i sila()."""

    def __init__(self, card_path: Path, etykieta: str,
                 template_path: Path | None = None, parent=None):
        super().__init__(parent)
        self._card_path = Path(card_path)
        # szablon tła karty — do ostrzeżenia, gdy maska leży głównie
        # w strefach twardych (bordiura/tarcze wracają z szablonu)
        self._template_path = Path(template_path) if template_path else None
        self._ostrzezono_strefy = False
        self.setWindowTitle(f"Popraw selektywnie — {etykieta} "
                            f"({self._card_path.name})")
        self.setModal(True)
        self.resize(760, 940)

        pix = QPixmap(str(self._card_path))
        maska = np.zeros((max(1, pix.height()), max(1, pix.width())), np.uint8)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        self._hint = QLabel(_HINT_AI)
        self._hint.setObjectName("hint")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        self.tryb_switch = SegmentedControl(
            ["✨ Poprawa AI", "⌫ Przywróć tło szablonu"])
        self.tryb_switch.changed.connect(self._on_tryb_changed)
        layout.addWidget(self.tryb_switch)

        self._canvas = _MaskCanvas(pix, maska)
        layout.addWidget(self._canvas, stretch=1)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText(
            "Opisz, co chcesz poprawić w zaznaczonym obszarze… "
            "(np. „znak trefla jest ucięty, uczyń go w pełni widocznym”)")
        self.prompt_edit.setFixedHeight(72)
        layout.addWidget(self.prompt_edit)

        # siła poprawki: jak mocno model może zmieniać istniejącą treść
        # (klauzula promptu + temperatura wywołania — tylko tryb AI)
        sila_row = QHBoxLayout()
        sila_row.setSpacing(8)
        self._sila_label = QLabel("Siła poprawki")
        self._sila_label.setObjectName("propKey")
        sila_row.addWidget(self._sila_label)
        self.sila_slider = SnapSlider(1, 5, 3)
        self.sila_slider.setFixedWidth(180)
        self.sila_slider.valueChanged.connect(self._on_sila_changed)
        sila_row.addWidget(self.sila_slider)
        self._sila_opis = QLabel(_SILA_OPISY[3])
        self._sila_opis.setObjectName("hint")
        sila_row.addWidget(self._sila_opis)
        sila_row.addStretch(1)
        # dokładnie ten obraz (crop + rozmycie/wymazanie wg siły + magenta
        # zaznaczenie), który pójdzie do modelu — wspólny kod z generatorem
        self.podglad_btn = QPushButton("👁  Podgląd dla modelu")
        self.podglad_btn.setObjectName("ghostBtn")
        self.podglad_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.podglad_btn.clicked.connect(self._pokaz_podglad)
        sila_row.addWidget(self.podglad_btn)
        layout.addLayout(sila_row)

        tools = QHBoxLayout()
        tools.setSpacing(6)
        group = QButtonGroup(self)
        group.setExclusive(True)
        self.brush_btn = QPushButton("🖌  Pędzel")
        self.eraser_btn = QPushButton("◻  Gumka")
        for btn, eraser in ((self.brush_btn, False), (self.eraser_btn, True)):
            btn.setObjectName("ghostBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.toggled.connect(
                lambda on, e=eraser: on and self._canvas.set_eraser(e))
            group.addButton(btn)
            tools.addWidget(btn)
        self.brush_btn.setChecked(True)

        tools.addSpacing(10)
        size_label = QLabel("Rozmiar")
        size_label.setObjectName("propKey")
        tools.addWidget(size_label)
        self.size_slider = SnapSlider(_BRUSH_MIN, _BRUSH_MAX, _BRUSH_START_FIX)
        self.size_slider.setFixedWidth(140)
        self.size_slider.valueChanged.connect(self._canvas.set_brush)
        tools.addWidget(self.size_slider)
        self._canvas.set_brush(_BRUSH_START_FIX)

        tools.addStretch(1)
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.setObjectName("ghostBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        tools.addWidget(cancel_btn)
        self.fix_btn = QPushButton("✨  Popraw (1 wywołanie API)")
        self.fix_btn.setObjectName("outlineBtn")
        self.fix_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.fix_btn.clicked.connect(self._on_accept)
        tools.addWidget(self.fix_btn)
        layout.addLayout(tools)

    # --- wyniki ---------------------------------------------------------------
    def maska(self) -> np.ndarray:
        return self._canvas.maska()

    def prompt_uzytkownika(self) -> str:
        return self.prompt_edit.toPlainText().strip()

    def tryb(self) -> str:
        """"ai" = poprawa modelem, "szablon" = przywrócenie tła bez API."""
        return "szablon" if self.tryb_switch.current() == 1 else "ai"

    def sila(self) -> int:
        return self.sila_slider.value()

    # --- tryb / siła ------------------------------------------------------------
    def _on_tryb_changed(self, index: int) -> None:
        ai = index == 0
        self.prompt_edit.setEnabled(ai)
        self.sila_slider.setEnabled(ai)
        self._sila_label.setEnabled(ai)
        self._sila_opis.setEnabled(ai)
        self.podglad_btn.setEnabled(ai)
        self._hint.setText(_HINT_AI if ai else _HINT_SZABLON)
        self._hint.setStyleSheet("")
        self.fix_btn.setText("✨  Popraw (1 wywołanie API)" if ai
                             else "⌫  Przywróć tło (bez API)")

    def _on_sila_changed(self, value: int) -> None:
        self._sila_opis.setText(_SILA_OPISY.get(value, ""))

    # --- podgląd ----------------------------------------------------------------
    def _pokaz_podglad(self) -> None:
        """Podgląd „co zobaczy model": crop wg bboxa maski + przygotowanie
        regionu wg aktualnej siły + magenta zaznaczenie — te same funkcje,
        których użyje generator.popraw_region (podgląd = rzeczywistość).
        Zero wywołań API."""
        m = self._canvas.maska()
        if cv2.countNonZero(m) == 0:
            self._hint.setText("⚠ Najpierw zamaluj obszar do poprawy.")
            self._hint.setStyleSheet("color: #C9A227;")
            return
        from PIL import Image
        from app.core import compositor, generator
        from app.gui.widgets import pil_to_pixmap
        baza = Image.open(self._card_path).convert("RGB")
        maska_img = Image.fromarray(m).convert("L").resize(
            baza.size, Image.Resampling.NEAREST)
        box = generator._bbox_poprawki(maska_img)
        crop = baza.crop(box)
        maska_crop = maska_img.crop(box)
        wejscie = generator._przygotuj_region_poprawki(
            crop, maska_crop, self.sila())
        podglad = compositor.zaznacz_region_poprawki(wejscie, maska_crop)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Podgląd dla modelu — siła {self.sila()} "
                           f"({_SILA_OPISY.get(self.sila(), '')})")
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(10, 10, 10, 10)
        label = QLabel()
        label.setPixmap(pil_to_pixmap(podglad).scaled(
            640, 760, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        lay.addWidget(label)
        dlg.exec()

    # --- walidacja -------------------------------------------------------------
    def _udzial_stref_twardych(self) -> float:
        """Ułamek maski leżący w strefach twardych (bordiura + tarcze) —
        te obszary ZAWSZE wracają z szablonu, poprawka AI ich nie zmieni."""
        if self._template_path is None or not self._template_path.exists():
            return 0.0
        from app.core import masks as core_masks
        m = self._canvas.maska()
        h, w = m.shape
        try:
            chronione = core_masks.strefy_chronione_poprawki(
                self._template_path, (w, h))
        except Exception:
            return 0.0
        pole = cv2.countNonZero(m)
        return (float(np.count_nonzero((m > 0) & (chronione > 0))) / pole
                if pole else 0.0)

    def _on_accept(self) -> None:
        braki = []
        if cv2.countNonZero(self._canvas.maska()) == 0:
            braki.append("zamaluj obszar do poprawy")
        if self.tryb() == "ai" and not self.prompt_uzytkownika():
            braki.append("opisz, co poprawić")
        if braki:
            self._hint.setText("⚠ Najpierw " + " i ".join(braki) + ".")
            self._hint.setStyleSheet("color: #C9A227;")   # złote ostrzeżenie
            return
        if (self.tryb() == "ai" and not self._ostrzezono_strefy
                and self._udzial_stref_twardych() > 0.4):
            self._ostrzezono_strefy = True
            self._hint.setText(
                "⚠ Większość zaznaczenia to narożnik/bordiura — te obszary "
                "ZAWSZE wracają z szablonu, a znaki narożne stempluje preset "
                "„Wartości” (poprawka AI ich nie zmieni). Kliknij ponownie, "
                "aby mimo to kontynuować.")
            self._hint.setStyleSheet("color: #C9A227;")
            return
        self.accept()
