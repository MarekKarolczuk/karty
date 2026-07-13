"""Motyw „Atelier Kart": ciemna, grawersko-vintage paleta z designu HTML,
fonty Archivo / Cormorant Garamond / JetBrains Mono (assets/fonts/ui/),
arkusz QSS i konfiguracja QPalette.
"""
from __future__ import annotations

from PyQt6.QtGui import QColor, QFontDatabase, QPalette
from PyQt6.QtWidgets import QApplication

from app import config

# --- paleta (Design/Generator Kart - offline.html) ---------------------------
BG = "#120E09"             # tło okna
BG_DEEP = "#0F0C07"        # sidebar / studnie / log
SURFACE = "#1E1710"        # panele
SURFACE_HOVER = "#2A2118"
SURFACE_INPUT = "#171109"
BORDER = "#3A2F22"         # ciepły brąz
ACCENT_DEEP = "#801515"    # bordo marki
ACCENT = "#C6402E"         # aktywne stany / glow
ACCENT_HOVER = "#E0574E"
GOLD = "#C99A3B"           # status „do generacji", nagłówki sekcji
GREEN = "#5FA463"          # status „gotowa"
RED = "#E0574E"
INFO = "#7C8CA6"           # status „w kolejce"
TEXT = "#EFE4CE"           # krem
TEXT_BRIGHT = "#F5EAD3"
CREAM = "#DCCFB4"
MUTED = "#8A7C64"
MUTED_2 = "#B9AA8D"

# Rodziny po ekstrakcji z bundla (scripts/wyciagnij_fonty.py); fallbacki
# systemowe w listach niżej — apka działa też bez plików w assets/fonts/ui/.
UI_FAMILY = "'Archivo SemiBold', 'Segoe UI Variable', 'Segoe UI', sans-serif"
SERIF = "'Cormorant Garamond Light', Georgia, 'Times New Roman', serif"
MONO = "'JetBrains Mono', Consolas, 'Courier New', monospace"

QSS = f"""
* {{ outline: none; }}
QMainWindow, QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: {UI_FAMILY};
    font-size: 13px;
}}
QLabel {{ background: transparent; }}

/* ---------- pasek tytułu ---------- */
QWidget#titleBar {{
    background: {BG};
    border-bottom: 1px solid {BORDER};
}}
QLabel#logoBadge {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {ACCENT}, stop:1 {ACCENT_DEEP});
    color: {TEXT_BRIGHT};
    font-family: {SERIF};
    font-size: 15px;
    font-weight: bold;
    border-radius: 8px;
}}
QLabel#appLogo {{
    font-family: {SERIF};
    font-size: 15px;
    font-weight: bold;
    color: {TEXT_BRIGHT};
    letter-spacing: 2px;
}}
QLabel#appLogoSuit {{ font-size: 19px; color: {ACCENT}; }}
QLabel#appSubtitle {{ color: {MUTED}; font-size: 9px; letter-spacing: 1px; }}
QPushButton#deckPill {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 15px;
    color: {CREAM};
    padding: 6px 16px;
    font-weight: 600;
}}
QPushButton#deckPill:hover {{ border-color: {ACCENT}; color: {ACCENT_HOVER}; }}
QWidget#apiPill {{
    background: {SURFACE};
    border: 1px solid {GREEN};
    border-radius: 13px;
}}
QLabel#apiPillText {{ color: {CREAM}; font-size: 11px; font-weight: 600; }}
QPushButton#winBtn, QPushButton#winCloseBtn {{
    background: transparent;
    border: none;
    border-radius: 0;
    color: {MUTED};
    font-size: 13px;
    padding: 0;
}}
QPushButton#winBtn:hover {{ background: {SURFACE_HOVER}; color: {TEXT}; }}
QPushButton#winCloseBtn:hover {{ background: #b23434; color: #ffffff; }}

/* ---------- sidebar ---------- */
QWidget#sidebar {{
    background: {BG_DEEP};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#sideLogo {{
    font-family: {SERIF};
    font-size: 21px;
    color: {TEXT_BRIGHT};
    letter-spacing: 3px;
}}
QLabel#sideSub {{
    color: {MUTED};
    font-size: 10px;
    letter-spacing: 2px;
}}
QLabel#sideCaption {{
    color: {MUTED_2};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}}
QPushButton#navBtn {{
    background: transparent;
    border: none;
    border-radius: 9px;
    color: {MUTED_2};
    padding: 9px 12px;
    text-align: left;
    font-size: 13px;
}}
QPushButton#navBtn:hover {{ background: {SURFACE}; color: {TEXT}; }}
QPushButton#navBtn:checked {{
    background: {SURFACE};
    color: {TEXT_BRIGHT};
    border-left: 3px solid {ACCENT};
    padding-left: 9px;
}}
QLabel#navBadge {{
    background: {SURFACE_HOVER};
    color: {MUTED_2};
    font-size: 11px;
    font-weight: 600;
    border-radius: 8px;
    padding: 1px 8px;
    margin-right: 4px;
}}
QPushButton#newDeckBtn {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 10px;
    color: {CREAM};
    padding: 8px 12px;
}}
QPushButton#newDeckBtn:hover {{ border-color: {ACCENT}; color: {ACCENT_HOVER}; }}
QLabel#apiStatus {{ color: {MUTED}; font-size: 11px; }}
QLabel#deckProgressText {{ color: {CREAM}; font-size: 12px; }}
QProgressBar#deckProgress {{
    background: {SURFACE_INPUT};
    border: none;
    border-radius: 5px;
    min-height: 11px;
    max-height: 11px;
    color: transparent;
}}
QProgressBar#deckProgress::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {ACCENT_DEEP}, stop:1 {ACCENT});
    border-radius: 5px;
}}

/* ---------- nagłówki widoków / sekcji ---------- */
QLabel#viewTitle {{
    font-family: {SERIF};
    font-size: 26px;
    color: {TEXT_BRIGHT};
    letter-spacing: 1px;
}}
QLabel#viewSubtitle {{ color: {MUTED}; font-size: 12px; }}
QLabel#panelTitle {{
    font-family: {SERIF};
    font-size: 20px;
    color: {TEXT_BRIGHT};
    padding: 0 0 2px 0;
}}
QLabel#sectionTitle {{
    color: {GOLD};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
}}
QLabel#hint {{ color: {MUTED}; font-size: 11px; }}
QLabel#counter {{ color: {MUTED}; font-size: 11px; }}
QLabel#propKey {{ color: {MUTED}; font-size: 11px; letter-spacing: 1px; }}
QLabel#propValue {{ color: {TEXT_BRIGHT}; font-size: 13px; }}
QLabel#mutedInfo {{ color: {MUTED_2}; font-size: 12px; }}

/* ---------- ekran roboczy: nagłówek karty + właściwości ---------- */
/* cyfry w licznikach: font UI (Archivo) ma lining figures — serif Cormorant
   renderuje old-style („10" wygląda jak „1o") */
QLabel#cardBigValue {{
    font-family: {UI_FAMILY};
    font-size: 34px;
    font-weight: bold;
}}
QLabel#cardName {{
    font-family: {SERIF};
    font-size: 20px;
    color: {TEXT_BRIGHT};
}}
QPushButton#valueKeyBtn {{
    background: {SURFACE_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {CREAM};
    font-family: {SERIF};
    font-size: 14px;
    font-weight: bold;
    min-width: 24px;
    max-width: 40px;
    padding: 6px 0;
}}
QPushButton#valueKeyBtn:hover {{ border-color: {ACCENT}; color: {ACCENT_HOVER}; }}
QPushButton#valueKeyBtn:checked {{
    background: {ACCENT_DEEP};
    border: 1px solid {ACCENT};
    color: {TEXT_BRIGHT};
}}
QPushButton#suitPickBtn {{
    background: {SURFACE_INPUT};
    border: 1px solid {BORDER};
    border-radius: 9px;
    color: {CREAM};
    padding: 8px 10px;
    text-align: left;
    font-weight: 600;
}}
QPushButton#suitPickBtn:hover {{ border-color: {ACCENT}; }}
QPushButton#suitPickBtn:checked {{
    background: rgba(128, 21, 21, 0.35);
    border: 1px solid {ACCENT};
    color: {TEXT_BRIGHT};
}}

QLabel#suitRowSymbol {{ font-size: 24px; color: {CREAM}; }}
QLabel#suitRowSymbol[red="true"] {{ color: {ACCENT_HOVER}; }}
QWidget#rulesBar {{
    background: rgba(128, 21, 21, 0.16);
    border: 1px solid {ACCENT_DEEP};
    border-radius: 12px;
}}
QWidget#rulesPanel {{
    background: {SURFACE};
    border: 1px solid {ACCENT_DEEP};
    border-left: 3px solid {ACCENT};
    border-radius: 14px;
}}
QLabel#folderName {{
    font-family: {MONO};
    font-size: 12px;
    color: {TEXT_BRIGHT};
}}
QLabel#chip {{
    background: {SURFACE_INPUT};
    border: 1px solid {BORDER};
    border-radius: 9px;
    color: {MUTED_2};
    font-family: {MONO};
    font-size: 11px;
    padding: 3px 10px;
}}
QLabel#readyBadge {{
    background: {SURFACE};
    border: 1px solid {GOLD};
    border-radius: 13px;
    color: {CREAM};
    font-size: 12px;
    font-weight: 600;
    padding: 5px 14px;
}}
QLabel#readyBadge[state="ok"] {{ border-color: {GREEN}; }}
QLabel#statusPill {{ font-size: 12px; font-weight: 600; }}

/* ---------- karty modeli (Styl AI) / karty statystyk ---------- */
QPushButton#modelCard {{
    background: {SURFACE_INPUT};
    border: 1px solid {BORDER};
    border-radius: 12px;
    color: {CREAM};
    padding: 12px 14px;
    text-align: left;
}}
QPushButton#modelCard:hover {{ border-color: {ACCENT}; }}
QPushButton#modelCard:checked {{
    background: rgba(128, 21, 21, 0.28);
    border: 1px solid {ACCENT};
    color: {TEXT_BRIGHT};
}}
QWidget#statCard {{
    background: {BG_DEEP};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLabel#statNumber {{
    font-family: {UI_FAMILY};
    font-size: 22px;
    font-weight: bold;
    color: {TEXT_BRIGHT};
}}
QLabel#statNumber[tone="ok"] {{ color: {GREEN}; }}
QLabel#statNumber[tone="warn"] {{ color: {GOLD}; }}
QLabel#bigCounter {{
    font-family: {UI_FAMILY};
    font-size: 40px;
    font-weight: bold;
    color: {TEXT_BRIGHT};
}}
QLabel#bigPercentAccent {{
    font-family: {UI_FAMILY};
    font-size: 34px;
    font-weight: bold;
    color: {ACCENT_HOVER};
}}

/* ---------- pasek akcji / panele ---------- */
QWidget#actionBar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QLabel#actionLabel {{ color: {MUTED}; font-size: 12px; }}
QWidget#panel {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 14px;
}}
QWidget#well {{
    background: {BG_DEEP};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}

/* ---------- segmented control ---------- */
QWidget#segmented {{
    background: {SURFACE_INPUT};
    border: 1px solid {BORDER};
    border-radius: 11px;
}}
QPushButton#segBtn {{
    background: transparent;
    border: none;
    border-radius: 8px;
    color: {MUTED};
    padding: 6px 14px;
    font-weight: 600;
}}
QPushButton#segBtn:hover {{ color: {TEXT}; }}
QPushButton#segBtn:checked {{
    background: {SURFACE_HOVER};
    color: {TEXT_BRIGHT};
    border: 1px solid {BORDER};
}}
QPushButton#segBtn[red="true"]:checked {{ color: {ACCENT_HOVER}; }}

/* ---------- przyciski ---------- */
QPushButton {{
    background: {SURFACE_HOVER};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 600;
}}
QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT_HOVER}; }}
QPushButton:pressed {{ background: {SURFACE_INPUT}; }}
QPushButton:disabled {{ color: #5A5142; background: {SURFACE}; }}
QPushButton#generateBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {ACCENT}, stop:1 {ACCENT_DEEP});
    color: {TEXT_BRIGHT};
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 1px;
    padding: 10px 26px;
    border: none;
    border-radius: 11px;
}}
QPushButton#generateBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                stop:0 {ACCENT_HOVER}, stop:1 {ACCENT});
    color: #ffffff;
}}
QPushButton#ghostBtn {{
    background: transparent;
    border: 1px solid {BORDER};
    color: {MUTED_2};
}}
QPushButton#ghostBtn:hover {{ color: {TEXT}; border-color: {MUTED}; }}
QPushButton#outlineBtn {{
    background: transparent;
    border: 1px solid {ACCENT};
    color: {ACCENT_HOVER};
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 1px;
    border-radius: 11px;
    padding: 10px 22px;
}}
QPushButton#outlineBtn:hover {{
    background: rgba(128, 21, 21, 0.28);
    border-color: {ACCENT_HOVER};
    color: #ffffff;
}}
QPushButton#outlineBtn:disabled {{ color: #5A5142; border-color: {BORDER}; }}
QToolButton {{
    background: transparent;
    border: none;
    color: {MUTED};
    font-weight: 600;
    padding: 4px;
}}
QToolButton:hover {{ color: {TEXT}; }}

/* ---------- sloty kart ---------- */
QFrame#cardSlot {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#cardSlot:hover {{ border: 1px solid {GOLD}; }}
QFrame#cardSlot[state="assigned"] {{ border: 1px solid {GOLD}; }}
QFrame#cardSlot[state="queued"] {{ border: 1px solid {INFO}; }}
QFrame#cardSlot[state="done"] {{ border: 1px solid {GREEN}; }}
QFrame#cardSlot[state="error"] {{ border: 1px solid {RED}; }}
QFrame#cardSlot[drag="true"] {{ border: 2px solid {ACCENT}; }}
QLabel#slotChip {{
    background: rgba(15, 12, 7, 0.85);
    color: {TEXT};
    font-family: {SERIF};
    font-size: 15px;
    font-weight: bold;
    border-radius: 8px;
    padding: 2px 8px;
}}
QLabel#slotChip[red="true"] {{ color: {ACCENT_HOVER}; }}
QLabel#variantBadge {{
    background: {GOLD};
    color: #1A1408;
    font-size: 10px;
    font-weight: bold;
    border-radius: 7px;
    padding: 1px 6px;
}}
QLabel#slotGhost {{
    color: {MUTED};
    font-size: 11px;
    background: transparent;
}}
QLabel#slotState {{ border-radius: 2px; }}

/* ---------- pola / listy ---------- */
QListWidget, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox {{
    background: {SURFACE_INPUT};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px 9px;
    selection-background-color: {ACCENT};
    selection-color: {TEXT_BRIGHT};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
    border-color: {ACCENT};
}}
QLineEdit#searchEdit {{
    padding: 8px 12px;
    border-radius: 11px;
}}
QPlainTextEdit#logMono, QPlainTextEdit#promptPreview {{
    background: {BG_DEEP};
    color: {MUTED_2};
    font-family: {MONO};
    font-size: 11px;
    border-radius: 12px;
}}
QPlainTextEdit#styleEdit {{
    font-family: {MONO};
    font-size: 12px;
    color: {CREAM};
}}
QListWidget {{ border: none; background: transparent; }}
QListWidget::item {{ border-radius: 10px; padding: 4px; color: {MUTED_2}; }}
QListWidget::item:selected {{ background: rgba(198, 64, 46, 0.25); color: {TEXT}; }}
QListWidget::item:hover {{ background: {SURFACE_HOVER}; }}
QListWidget#queueList {{
    background: {BG_DEEP};
    border: 1px solid {BORDER};
    border-radius: 12px;
    font-family: {MONO};
    font-size: 11px;
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {MUTED};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: {ACCENT};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {SURFACE_HOVER};
    border: none;
    width: 18px;
}}
QSpinBox::up-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-bottom: 4px solid {MUTED};
}}
QSpinBox::down-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-top: 4px solid {MUTED};
}}
QCheckBox {{ spacing: 8px; color: {CREAM}; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 5px;
    background: {SURFACE_INPUT};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QRadioButton {{ spacing: 8px; color: {CREAM}; }}
QRadioButton::indicator {{
    width: 14px; height: 14px;
    border: 1px solid {BORDER};
    border-radius: 7px;
    background: {SURFACE_INPUT};
}}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5,
                                stop:0 {ACCENT}, stop:0.55 {ACCENT},
                                stop:0.65 {SURFACE_INPUT}, stop:1 {SURFACE_INPUT});
    border: 1px solid {ACCENT};
}}

/* ---------- podgląd / status ---------- */
QLabel#preview {{
    background: {BG_DEEP};
    border: 1px dashed {BORDER};
    border-radius: 12px;
    color: {MUTED};
}}
QWidget#statusBar {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QLabel#statusText {{ color: {MUTED_2}; font-size: 12px; }}
QProgressBar {{
    background: {SURFACE_INPUT};
    border: none;
    border-radius: 5px;
    max-height: 10px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                stop:0 {ACCENT_DEEP}, stop:1 {ACCENT_HOVER});
    border-radius: 5px;
}}
QLabel#bigPercent {{
    font-family: {SERIF};
    font-size: 34px;
    color: {TEXT_BRIGHT};
}}

/* ---------- toast ---------- */
QLabel#toast {{
    background: {SURFACE_HOVER};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-left: 3px solid {GOLD};
    border-radius: 10px;
    padding: 10px 16px;
    font-weight: 600;
}}
QLabel#toast[kind="ok"] {{ border-left: 3px solid {GREEN}; }}
QLabel#toast[kind="error"] {{ border-left: 3px solid {RED}; }}

/* ---------- suwaki / menu / splitter ---------- */
/* Nowoczesne, cienkie, dyskretne paski: uchwyt ledwo widoczny w spoczynku,
   akcentowany po najechaniu (QSS nie animuje szerokości, więc chowamy uchwyt
   kolorem — tor jest przezroczysty). */
QScrollBar:vertical {{ background: transparent; width: 7px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(122, 106, 84, 55);
    border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 7px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(122, 106, 84, 55);
    border-radius: 3px; min-width: 30px; }}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover {{
    background: {ACCENT}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QScrollArea {{ border: none; background: transparent; }}
QSplitter::handle {{ background: transparent; width: 6px; }}
QMenu {{
    background: {SURFACE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{ padding: 7px 18px; border-radius: 7px; }}
QMenu::item:selected {{ background: {ACCENT}; color: {TEXT_BRIGHT}; }}
QMenu::item:disabled {{ color: #5A5142; }}
QToolTip {{
    background: {SURFACE_HOVER}; color: {TEXT};
    border: 1px solid {BORDER}; border-radius: 6px; padding: 5px 8px;
}}
QMessageBox {{ background: {SURFACE}; }}
"""


def app_icon():
    """Ikona aplikacji (pasek tytułu / pasek zadań) — logo „A" w akcencie marki."""
    from PyQt6.QtCore import QRectF, Qt
    from PyQt6.QtGui import (
        QBrush, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap,
    )
    pm = QPixmap(64, 64)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 64, 64)
    gradient.setColorAt(0.0, QColor(ACCENT))
    gradient.setColorAt(1.0, QColor(ACCENT_DEEP))
    path = QPainterPath()
    path.addRoundedRect(QRectF(4, 4, 56, 56), 14, 14)
    painter.fillPath(path, QBrush(gradient))
    font = QFont("Georgia", 30)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(TEXT_BRIGHT))
    painter.drawText(QRectF(0, 2, 64, 62), Qt.AlignmentFlag.AlignCenter, "A")
    painter.end()
    return QIcon(pm)


def _load_ui_fonts() -> None:
    """Rejestruje fonty UI z assets/fonts/ui/ (jeśli są; inaczej fallbacki QSS)."""
    if not config.UI_FONTS_DIR.exists():
        return
    for path in sorted(config.UI_FONTS_DIR.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def apply(app: QApplication) -> None:
    """Nakłada fonty, QSS i ciemną paletę (dla natywnych elementów)."""
    _load_ui_fonts()
    app.setStyleSheet(QSS)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(BG))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Base, QColor(SURFACE_INPUT))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(SURFACE))
    palette.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Button, QColor(SURFACE_HOVER))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(TEXT_BRIGHT))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(SURFACE_HOVER))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    app.setPalette(palette)
