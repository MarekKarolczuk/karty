"""Panel generacji osadzony w Ekranie roboczym (dawny widok „Generowanie"):
tryb, limit, wersje, postęp oraz — w wysuwanym panelu dolnym — kolejka i log.

Nazwy atrybutów i metod są identyczne jak w dawnym GenerationView —
MainWindow używa ich w kilkudziesięciu miejscach (alias self.generation).
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from app import config
from app.core.models import CardSpec
from app.gui.params_panel import LogPane, PreviewPane
from app.gui.widgets import SegmentedControl


class GenerationPanel(QWidget):
    generate_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    retry_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        caption = QLabel("GENERACJA")
        caption.setObjectName("sideCaption")
        layout.addWidget(caption)

        self.mode_seg = SegmentedControl(["◈ Hybrydowy", "✦ Pełne AI"])
        self.mode_seg.buttons[0].setToolTip(
            "AI stylizuje tylko zdjęcie — szablon i czcionki w 100% powtarzalne"
        )
        self.mode_seg.buttons[1].setToolTip(
            "Całą kartę komponuje AI (wymaga modelu Gemini)"
        )
        layout.addWidget(self.mode_seg)

        spins = QHBoxLayout()
        spins.setSpacing(6)

        def spin_group(label_text: str, spin: QSpinBox) -> QWidget:
            box = QWidget()
            box_layout = QHBoxLayout(box)
            box_layout.setContentsMargins(0, 0, 0, 0)
            box_layout.setSpacing(6)
            label = QLabel(label_text)
            label.setObjectName("actionLabel")
            box_layout.addWidget(label)
            box_layout.addWidget(spin)
            return box

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(0, 999)
        self.limit_spin.setSpecialValueText("wszystkie")
        self.limit_spin.setToolTip(
            "Ile kart wygenerować w tej serii (0 = wszystkie przypisane)"
        )
        spins.addWidget(spin_group("Karty:", self.limit_spin))

        self.versions_spin = QSpinBox()
        self.versions_spin.setRange(1, 10)
        self.versions_spin.setToolTip("Ile wariantów każdej karty naraz "
                                      "(v2+ → K_kier_v2.jpg, potem wybór w historii)")
        spins.addWidget(spin_group("Warianty na kartę:", self.versions_spin))
        spins.addStretch(1)
        layout.addLayout(spins)

        self.skip_done_check = QCheckBox("Pomiń już gotowe karty")
        self.skip_done_check.setToolTip(
            "Generuj tylko karty bez gotowego wariantu (oszczędza czas i kredyty)"
        )
        layout.addWidget(self.skip_done_check)

        # szacowana skala serii (liczba kart / generacji / kredytów)
        self.estimate_label = QLabel("—")
        self.estimate_label.setObjectName("hint")
        self.estimate_label.setWordWrap(True)
        layout.addWidget(self.estimate_label)

        # --- postęp ----------------------------------------------------------
        counters = QHBoxLayout()
        self.count_label = QLabel("0")
        self.count_label.setObjectName("bigCounter")
        counters.addWidget(self.count_label)
        self.total_label = QLabel("/ 0")
        self.total_label.setObjectName("mutedInfo")
        counters.addWidget(self.total_label, alignment=Qt.AlignmentFlag.AlignBottom)
        counters.addStretch(1)
        self.percent_label = QLabel("0%")
        self.percent_label.setObjectName("bigPercentAccent")
        counters.addWidget(self.percent_label)
        layout.addLayout(counters)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        stats = QHBoxLayout()
        stats.setSpacing(10)
        self.done_number = QLabel("0")
        self.done_number.setObjectName("statNumber")
        self.done_number.setProperty("tone", "ok")
        stats.addWidget(self._stat("Gotowe", self.done_number))
        self.left_number = QLabel("0")
        self.left_number.setObjectName("statNumber")
        self.left_number.setProperty("tone", "warn")
        stats.addWidget(self._stat("Pozostało", self.left_number))
        self.engine_label = QLabel("—")
        self.engine_label.setObjectName("statNumber")
        stats.addWidget(self._stat("Silnik", self.engine_label))
        stats.addStretch(1)
        layout.addLayout(stats)

        self.pause_btn = QPushButton("⏸  Wstrzymaj")
        self.pause_btn.setObjectName("ghostBtn")
        self.pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        self.pause_btn.hide()
        layout.addWidget(self.pause_btn)

        self.retry_btn = QPushButton("↻  Ponów nieudane")
        self.retry_btn.setObjectName("generateBtn")
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.clicked.connect(self.retry_clicked.emit)
        self.retry_btn.hide()
        layout.addWidget(self.retry_btn)

        # Przycisk „Generuj talię" należy do WorkspaceView — rejestrowany
        # z zewnątrz, żeby set_busy mógł go blokować.
        self.generate_btn: QPushButton = QPushButton()

        # Podgląd na żywo to PreviewPane Ekranu roboczego — przypisywany
        # z zewnątrz (WorkspaceView) tuż po utworzeniu panelu.
        self.preview: PreviewPane = None  # type: ignore[assignment]

        # --- wysuwany panel dolny: kolejka + log ------------------------------
        self.details = QWidget()
        self.details.setObjectName("panel")
        details_layout = QHBoxLayout(self.details)
        details_layout.setContentsMargins(14, 10, 14, 10)
        details_layout.setSpacing(10)

        queue_box = QVBoxLayout()
        queue_caption = QLabel("KOLEJKA")
        queue_caption.setObjectName("sideCaption")
        queue_box.addWidget(queue_caption)
        self.queue = QListWidget()
        self.queue.setObjectName("queueList")
        queue_box.addWidget(self.queue, stretch=1)
        details_layout.addLayout(queue_box, stretch=2)

        self.log_pane = LogPane("LOG API")
        details_layout.addWidget(self.log_pane, stretch=3)

        self._rows: dict[str, int] = {}
        self.refresh_engine()

    def set_full_ai_enabled(self, enabled: bool) -> None:
        """Blokuje/odblokowuje segment „Pełne AI". Gdy zablokowany i aktywny,
        wraca na tryb Hybrydowy."""
        btn = self.mode_seg.buttons[1]
        btn.setEnabled(enabled)
        btn.setToolTip(
            "Całą kartę komponuje AI (wymaga modelu Gemini)" if enabled
            else "Niedostępne dla modeli Stability — wybierz model Gemini "
                 "w Ustawieniach"
        )
        if not enabled and self.mode_seg.current() == 1:
            self.mode_seg.set_current(0)

    @staticmethod
    def _stat(caption: str, number_label: QLabel) -> QWidget:
        box = QWidget()
        box.setObjectName("statCard")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)
        cap = QLabel(caption)
        cap.setObjectName("propKey")
        layout.addWidget(cap)
        layout.addWidget(number_label)
        return box

    def set_estimate(self, text: str) -> None:
        self.estimate_label.setText(text)

    # --- silnik ---------------------------------------------------------------
    def refresh_engine(self) -> None:
        model = config.current_model()
        self.engine_label.setText(model["label"])
        self.engine_label.setStyleSheet("font-size: 13px;")

    # --- kolejka ----------------------------------------------------------------
    def set_queue(self, specs: list[CardSpec]) -> None:
        self.queue.clear()
        self._rows.clear()
        for spec in specs:
            item = QListWidgetItem(f"◌  {spec.label}  ·  w kolejce")
            self.queue.addItem(item)
            self._rows[spec.label] = self.queue.count() - 1

    def mark_running(self, spec: CardSpec) -> None:
        row = self._rows.get(spec.label)
        if row is not None:
            self.queue.item(row).setText(f"⟳  {spec.label}  ·  generuję…")
            self.queue.scrollToItem(self.queue.item(row))

    def mark_done(self, spec: CardSpec) -> None:
        row = self._rows.get(spec.label)
        if row is not None:
            self.queue.item(row).setText(f"✔  {spec.label}  ·  gotowa")

    def mark_error(self, spec: CardSpec) -> None:
        row = self._rows.get(spec.label)
        if row is not None:
            self.queue.item(row).setText(f"✖  {spec.label}  ·  błąd")

    # --- postęp -------------------------------------------------------------------
    def set_progress(self, done: int, total: int) -> None:
        self.progress.setRange(0, max(total, 1))
        self.progress.setValue(done)
        self.count_label.setText(str(done))
        self.total_label.setText(f"/ {total}")
        pct = round(100 * done / total) if total else 0
        self.percent_label.setText(f"{pct}%")
        self.done_number.setText(str(done))
        self.left_number.setText(str(max(0, total - done)))

    def set_busy(self, busy: bool) -> None:
        if self.generate_btn is not None:
            self.generate_btn.setEnabled(not busy)
        self.pause_btn.setVisible(busy)
        if busy:
            self.retry_btn.hide()
        else:
            self.set_paused(False)

    def show_retry(self, count: int) -> None:
        self.retry_btn.setText(f"↻  Ponów nieudane ({count})")
        self.retry_btn.setVisible(count > 0)

    def hide_retry(self) -> None:
        self.retry_btn.hide()

    def set_paused(self, paused: bool) -> None:
        self.pause_btn.setText("▶  Wznów" if paused else "⏸  Wstrzymaj")
