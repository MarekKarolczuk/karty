"""Edytor maski pop-out: rysowanie pędzlem strefy, w której postać może
wychodzić poza okno symbolu (bramka `allowed` w masks.maska_klampu).

Zamalowany obszar ZASTĘPUJE domyślną strefę (hull okna + anizotropowy ring
+ prostokąt nad symbolem); twarde gwarancje klampu — bordiura, tarcze
narożne, proste linie ramki i rdzeń okna — pozostają niezależne od maski.
Zapis: Style/tla_przodu/<preset>/maski/<stem>.png
(masks.sciezka_maski_uzytkownika); „Przywróć domyślną" + Zapisz USUWA plik
(powrót do automatu, przyszłe strojenie stałych KLAMP_* dalej działa).
Dialog niczego nie generuje — zero wywołań API.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from app.core import masks
from app.core.models import Suit
from app.gui import theme
from app.gui.widgets import SnapSlider

# Alpha nakładki strefy (0-255) — na tyle gęsta, żeby było widać zasięg,
# na tyle rzadka, żeby ornament szablonu pozostał czytelny pod spodem
_OVERLAY_ALPHA = 110
# Zakres i start suwaka rozmiaru pędzla (px w skali szablonu)
_BRUSH_MIN, _BRUSH_MAX, _BRUSH_START = 20, 400, 120
# Zakres zoomu i mnożnik na „notch" kółka myszy (tylko canvasy z zoom_pan=True)
_ZOOM_MIN, _ZOOM_MAX, _ZOOM_STEP = 1.0, 4.0, 1.15


def _koloruj_strefe(strefa: np.ndarray, szer_docelowa: int,
                    kolor: str, alpha: int) -> QImage:
    """Binarna strefa (0/255) → półprzezroczysta nakładka RGBA przeskalowana
    do zadanej szerokości (NEAREST — bez rozmywania granicy). Zwraca QImage
    z własną kopią bufora (bezpieczny czas życia)."""
    h, w = strefa.shape
    tw = max(1, min(szer_docelowa, w))
    th = max(1, round(h * tw / w))
    scaled = cv2.resize(strefa, (tw, th), interpolation=cv2.INTER_NEAREST)
    rgba = np.zeros((th, tw, 4), np.uint8)
    c = QColor(kolor)
    rgba[scaled > 0] = (c.red(), c.green(), c.blue(), alpha)
    return QImage(rgba.tobytes(), tw, th, 4 * tw,
                  QImage.Format.Format_RGBA8888).copy()


def nakladka_strefy(suit: Suit, szer: int = 640,
                    wartosc: str | None = None) -> QImage | None:
    """Nakładka podglądu strefy pop-out dla „Podglądu maski" na Ekranie
    roboczym: maska z AKTYWNEGO presetu masek (złota — odróżnialna od
    domyślnej; przy `wartosc` honoruje maskę per karta z fallbackiem na maskę
    koloru) albo strefa domyślna (akcent). None, gdy maski nie da się
    policzyć."""
    try:
        user = masks.maska_uzytkownika(suit, wartosc=wartosc)
        if user is not None:
            return _koloruj_strefe(user, szer, theme.GOLD, _OVERLAY_ALPHA)
        strefa, _ = masks.domyslna_strefa_popout(suit.template_path)
        return _koloruj_strefe(strefa, szer, theme.ACCENT, _OVERLAY_ALPHA)
    except (FileNotFoundError, OSError, RuntimeError):
        return None


class _MaskCanvas(QWidget):
    """Płótno edytora: szablon + nakładka maski + kursor-okrąg pędzla.
    Maska trzymana w PEŁNEJ rozdzielczości szablonu (numpy 0/255); rysowanie
    cv2.line/circle mapowane z pozycji myszy — zapis bez strat skali.

    `zoom_pan=True` (na razie tylko `FixRegionDialog`) włącza powiększanie
    kółkiem myszy (zakotwiczone pod kursorem, Shift+kółko = przesuw poziomy)
    i przesuwanie widoku środkowym przyciskiem — lewy przycisk zostaje
    zarezerwowany dla pędzla/gumki. Przy `zoom_pan=False` (domyślnie,
    `MaskEditorDialog`) `_zoom`/`_center_mask` nigdy się nie zmieniają, więc
    geometria jest bit-w-bit identyczna z dawnym fit-to-view."""

    stroke_painted = pyqtSignal()   # dowolne pociągnięcie = maska nie-domyślna

    def __init__(self, template_pix: QPixmap, mask: np.ndarray, parent=None,
                 *, zoom_pan: bool = False):
        super().__init__(parent)
        self._pix = template_pix
        self._mask = mask
        self._brush_px = _BRUSH_START
        self._eraser = False
        self._last_pt: tuple[int, int] | None = None
        self._cursor_pos: QPointF | None = None
        self._overlay: QImage | None = None
        self._overlay_dirty = True
        self._zoom_pan = zoom_pan
        self._zoom = 1.0
        self._center_mask = QPointF(template_pix.width() / 2,
                                     template_pix.height() / 2)
        self._panning = False
        self._pan_last_pos: QPointF | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(360, 480)
        self.setCursor(Qt.CursorShape.BlankCursor)
        if zoom_pan:
            self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)

    # --- API (maska/ustaw_maske — QWidget.mask()/setMask() to metody Qt) ------
    def maska(self) -> np.ndarray:
        return self._mask

    def ustaw_maske(self, mask: np.ndarray) -> None:
        self._mask = mask
        self._overlay_dirty = True
        self.update()

    def set_brush(self, px: int) -> None:
        self._brush_px = px
        self.update()

    def set_eraser(self, eraser: bool) -> None:
        self._eraser = eraser

    def reset_view(self) -> None:
        """Powrót do fit-to-view (100%, wyśrodkowany) — stan startowy."""
        self._zoom = 1.0
        self._center_mask = QPointF(self._pix.width() / 2,
                                     self._pix.height() / 2)
        self._overlay_dirty = True
        self.update()

    # --- geometria -----------------------------------------------------------
    def _fit_scale(self) -> float:
        """Skala fit-to-view — obraz w całości mieści się w widgecie."""
        pw, ph = self._pix.width(), self._pix.height()
        if pw <= 0 or ph <= 0 or self.width() <= 0 or self.height() <= 0:
            return 1.0
        return min(self.width() / pw, self.height() / ph)

    def _effective_scale(self) -> float:
        return self._fit_scale() * self._zoom

    def _target_rect(self) -> tuple[float, float, float, float]:
        """(x, y, w, h) obrazu w widgecie — fit-to-view uogólniony o zoom/pan
        (`_center_mask` = punkt obrazu widoczny na środku widgetu). Przy
        zoom=1 i center=środek obrazu wynik jest identyczny jak dawny
        czysty fit-to-view."""
        pw, ph = self._pix.width(), self._pix.height()
        s = self._effective_scale()
        w, h = pw * s, ph * s
        x = self.width() / 2 - self._center_mask.x() * s
        y = self.height() / 2 - self._center_mask.y() * s
        return x, y, w, h

    def _unproject(self, pos: QPointF) -> QPointF:
        """Punkt obrazu pod pozycją widgetu — do kotwiczenia zoomu."""
        s = self._effective_scale()
        if s <= 0:
            return QPointF(self._center_mask)
        return QPointF(
            self._center_mask.x() + (pos.x() - self.width() / 2) / s,
            self._center_mask.y() + (pos.y() - self.height() / 2) / s)

    def _clamp_center(self) -> None:
        """`_center_mask` zawsze na obrazie — obraz nigdy nie „ucieka"
        całkowicie poza widok przy panie."""
        pw, ph = self._pix.width(), self._pix.height()
        self._center_mask.setX(max(0.0, min(self._center_mask.x(), float(pw))))
        self._center_mask.setY(max(0.0, min(self._center_mask.y(), float(ph))))

    def _zoom_at(self, anchor: QPointF, factor: float) -> None:
        mask_pt = self._unproject(anchor)
        new_zoom = max(_ZOOM_MIN, min(self._zoom * factor, _ZOOM_MAX))
        if new_zoom == self._zoom:
            return
        self._zoom = new_zoom
        s = self._effective_scale()
        self._center_mask = QPointF(
            mask_pt.x() - (anchor.x() - self.width() / 2) / s,
            mask_pt.y() - (anchor.y() - self.height() / 2) / s)
        self._clamp_center()
        self._overlay_dirty = True   # szerokość docelowa nakładki się zmieniła
        self.update()

    def _map_to_mask(self, pos: QPointF) -> tuple[int, int] | None:
        x, y, w, h = self._target_rect()
        if w <= 0 or h <= 0:
            return None
        mh, mw = self._mask.shape
        mx = int((pos.x() - x) / w * mw)
        my = int((pos.y() - y) / h * mh)
        if not (0 <= mx < mw and 0 <= my < mh):
            return None
        return mx, my

    # --- rysowanie po masce ----------------------------------------------------
    def _stamp(self, p0: tuple[int, int], p1: tuple[int, int]) -> None:
        value = 0 if self._eraser else 255
        r = max(1, self._brush_px // 2)
        # gruba linia + koła na końcach = ciągła kreska z okrągłymi końcami
        cv2.line(self._mask, p0, p1, value, thickness=2 * r)
        cv2.circle(self._mask, p0, r, value, thickness=-1)
        cv2.circle(self._mask, p1, r, value, thickness=-1)
        self._overlay_dirty = True
        self.stroke_painted.emit()
        self.update()

    def mousePressEvent(self, event):  # noqa: N802 (API Qt)
        if (self._zoom_pan and event.button() == Qt.MouseButton.MiddleButton
                and self._zoom > 1.0):
            self._panning = True
            self._pan_last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if event.button() == Qt.MouseButton.LeftButton and not self._panning:
            pt = self._map_to_mask(event.position())
            if pt is not None:
                self._last_pt = pt
                self._stamp(pt, pt)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._panning and self._pan_last_pos is not None:
            delta = event.position() - self._pan_last_pos
            self._pan_last_pos = event.position()
            s = self._effective_scale()
            if s > 0:
                self._center_mask -= QPointF(delta.x() / s, delta.y() / s)
                self._clamp_center()
            self.update()
            return
        self._cursor_pos = event.position()
        if event.buttons() & Qt.MouseButton.LeftButton:
            pt = self._map_to_mask(event.position())
            if pt is not None:
                self._stamp(self._last_pt or pt, pt)
                self._last_pt = pt
        else:
            self.update()   # sam ruch kursora — odśwież okrąg pędzla

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = False
            self._pan_last_pos = None
            self.setCursor(Qt.CursorShape.BlankCursor)
            return
        self._last_pt = None

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if self._zoom_pan and event.button() == Qt.MouseButton.MiddleButton:
            self.reset_view()

    def leaveEvent(self, event):  # noqa: N802
        self._cursor_pos = None
        self.update()

    def wheelEvent(self, event):  # noqa: N802
        if not self._zoom_pan:
            event.ignore()
            return
        if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            if self._zoom > 1.0:
                s = self._effective_scale()
                self._center_mask.setX(
                    self._center_mask.x() - event.angleDelta().y() / s)
                self._clamp_center()
                self.update()
            event.accept()
            return
        factor = _ZOOM_STEP if event.angleDelta().y() > 0 else 1 / _ZOOM_STEP
        self._zoom_at(event.position(), factor)
        event.accept()

    def keyPressEvent(self, event):  # noqa: N802
        if self._zoom_pan and event.key() == Qt.Key.Key_0:
            self.reset_view()
            return
        super().keyPressEvent(event)

    # --- malowanie widgetu -------------------------------------------------------
    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.SURFACE))
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        x, y, w, h = self._target_rect()
        rect = QRectF(x, y, w, h)
        painter.drawPixmap(rect, self._pix, QRectF(self._pix.rect()))

        if self._overlay_dirty or self._overlay is None:
            # nakładka w rozdzielczości WYŚWIETLANIA (nie szablonu), capowana
            # do natywnej szerokości maski — powyżej niej nakładka binarna
            # (INTER_NEAREST) nie zyskuje żadnego detalu, a przy wysokim
            # zoomie `w` mogłoby wielokrotnie przekroczyć rozdzielczość maski
            mw = self._mask.shape[1]
            szer = min(max(1, int(w)), mw)
            self._overlay = _koloruj_strefe(
                self._mask, szer, theme.ACCENT, _OVERLAY_ALPHA)
            self._overlay_dirty = False
        painter.drawImage(rect, self._overlay)

        # kursor: okrąg o średnicy pędzla w skali widoku
        if self._cursor_pos is not None:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            scale = w / self._pix.width() if self._pix.width() else 1.0
            r_view = max(2.0, self._brush_px * scale / 2)
            pen = QPen(QColor(theme.CREAM if not self._eraser else theme.GOLD),
                       1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(self._cursor_pos, r_view, r_view)

        if self._zoom > 1.001:
            label = f"{round(self._zoom * 100)}%"
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            fm = painter.fontMetrics()
            pad = 6
            badge = QRectF(
                self.width() - fm.horizontalAdvance(label) - 2 * pad - 10, 10,
                fm.horizontalAdvance(label) + 2 * pad, fm.height() + 6)
            painter.setPen(Qt.PenStyle.NoPen)
            bg = QColor(theme.SURFACE_HOVER)
            bg.setAlpha(210)
            painter.setBrush(bg)
            painter.drawRoundedRect(badge, 6, 6)
            painter.setPen(QColor(theme.GOLD))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)


class MaskEditorDialog(QDialog):
    """Edytor maski pop-out w AKTYWNYM presecie masek (style_store.
    active_mask() — wołający gwarantuje, że nie jest to „Maska automatyczna").
    Bez `wartosc` = maska CAŁEGO KOLORU (widok Style); z `wartosc` (np. "A")
    = maska JEDNEJ KARTY (Ekran roboczy) — nadpisuje maskę koloru tylko dla
    niej. exec() → Accepted po Zapisz (plik maski zapisany albo usunięty przy
    stanie domyślnym)."""

    def __init__(self, suit: Suit, template_path: Path,
                 wartosc: str | None = None, parent=None):
        super().__init__(parent)
        from app.core import style_store
        self._suit = suit
        self._template_path = Path(template_path)
        self._wartosc = wartosc
        preset_maski = style_store.active_mask() or "maska"
        zakres = (f"karta {wartosc}{suit.symbol}" if wartosc
                  else f"cały kolor {suit.nazwa.capitalize()} {suit.symbol}")
        self.setWindowTitle(
            f"Maska pop-out „{preset_maski}” — {zakres} "
            f"({self._template_path.name})")
        self.setModal(True)
        self.resize(760, 860)

        # stan startowy: maska tej karty → maska koloru → strefa domyślna;
        # _is_default = True gdy nie istnieje PLIK dla edytowanego zakresu
        # (zapis w tym stanie usuwa plik zakresu = powrót do fallbacku)
        wlasna = masks._wczytaj_maske_uzytkownika(
            masks.sciezka_maski_uzytkownika(suit, wartosc))
        self._is_default = wlasna is None
        start = wlasna
        if start is None and wartosc:
            start = masks._wczytaj_maske_uzytkownika(
                masks.sciezka_maski_uzytkownika(suit))
        if start is None:
            start = masks.domyslna_strefa_popout(self._template_path)[0]
        start = start.copy()

        pix = QPixmap(str(self._template_path))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        if wartosc:
            opis_zakresu = (f"Maska dotyczy TYLKO karty {wartosc}{suit.symbol} "
                            "— nadpisuje maskę wspólną koloru; „Przywróć "
                            "domyślną” wraca do maski koloru/automatu.")
        else:
            opis_zakresu = ("Maska wspólna WSZYSTKICH kart tego koloru "
                            "(pojedynczą kartę nadpiszesz na Ekranie roboczym).")
        hint = QLabel(
            "Zamalowany obszar = strefa, w której postać może wychodzić poza "
            "okno symbolu. Bordiura, tarcze narożne, proste linie ramki i sam "
            "symbol są chronione niezależnie od maski. " + opis_zakresu
        )
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._canvas = _MaskCanvas(pix, start)
        self._canvas.stroke_painted.connect(self._on_painted)
        layout.addWidget(self._canvas, stretch=1)

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
        self.size_slider = SnapSlider(_BRUSH_MIN, _BRUSH_MAX, _BRUSH_START)
        self.size_slider.setFixedWidth(140)
        self.size_slider.valueChanged.connect(self._canvas.set_brush)
        tools.addWidget(self.size_slider)

        tools.addSpacing(10)
        reset_btn = QPushButton("↺  Przywróć domyślną")
        reset_btn.setObjectName("ghostBtn")
        reset_btn.setToolTip(
            "Wraca do maski nadrzędnej (karta → maska koloru → strefa "
            "automatyczna); po Zapisz plik tego zakresu jest usuwany")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_default)
        tools.addWidget(reset_btn)

        tools.addStretch(1)
        cancel_btn = QPushButton("Anuluj")
        cancel_btn.setObjectName("ghostBtn")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        tools.addWidget(cancel_btn)
        save_btn = QPushButton("💾  Zapisz maskę")
        save_btn.setObjectName("outlineBtn")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.clicked.connect(self._zapisz)
        tools.addWidget(save_btn)
        layout.addLayout(tools)

    def _on_painted(self) -> None:
        self._is_default = False

    def _reset_default(self) -> None:
        """Powrót do fallbacku edytowanego zakresu: per karta → maska koloru
        (jeśli jest) albo strefa automatyczna; per kolor → strefa automatyczna.
        Zapis w tym stanie USUWA plik zakresu."""
        strefa = None
        if self._wartosc:
            strefa = masks._wczytaj_maske_uzytkownika(
                masks.sciezka_maski_uzytkownika(self._suit))
        if strefa is None:
            strefa = masks.domyslna_strefa_popout(self._template_path)[0]
        self._canvas.ustaw_maske(strefa.copy())
        self._is_default = True

    def _zapisz(self) -> None:
        path = masks.sciezka_maski_uzytkownika(self._suit, self._wartosc)
        if path is None:            # aktywna „automatyczna" — nie powinno się
            self.reject()           # zdarzyć (wołający tworzy preset)
            return
        if self._is_default:
            path.unlink(missing_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            ok, buf = cv2.imencode(".png", self._canvas.maska())
            if not ok:
                self.reject()
                return
            buf.tofile(str(path))   # imencode+tofile — polskie znaki w ścieżce
        self.accept()
