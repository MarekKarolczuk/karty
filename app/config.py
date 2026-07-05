"""Centralna konfiguracja: ścieżki, kolory, rozmiar karty, modele."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Foldery (wg opis_pomyslu.md, dopasowane do istniejących nazw) ---
ZDJECIA_DIR = ROOT / "zdjecia"
TLA_DIR = ROOT / "tla_kart"
REFERENCJE_DIR = ROOT / "Przykladowe_karty_fajne_ale_nie_spojne"
OUTPUT_DIR = ROOT / "output"
ASSETS_DIR = ROOT / "assets"
MASKS_DIR = ASSETS_DIR / "masks"
FONTS_DIR = ASSETS_DIR / "fonts"
UI_FONTS_DIR = FONTS_DIR / "ui"      # fonty interfejsu (NIE do rysowania kart!)
PROJEKT_JSON = ROOT / "projekt.json"
STYLES_JSON = ROOT / "styles.json"   # edytowalne style AI (globalne)
BACK_PATH = TLA_DIR / "rewers.png"   # wspólny rewers talii

# --- API ---
# Klucze czytane ze zmiennych środowiskowych / .env (NIGDY nie hardcodowane —
# .env jest w .gitignore, więc nie trafia na repo).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Własny klucz do innego modelu AI (np. Claude / dowolny provider) — miejsce na
# klucz użytkownika zamiast sztywno wpisanego providera.
CUSTOM_API_KEY = os.getenv("CUSTOM_API_KEY", "")
# Zachowane dla zgodności (stability_client importuje tę stałą); puste = nieużywane.
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "")

# Rejestr dostępnych modeli obrazowych (wybór w GUI). Obecnie tylko Gemini —
# generuje całą stylizację (pop-out i pełne AI). provider: "gemini".
MODELS: dict[str, dict] = {
    "gemini-3-pro-image": {
        "provider": "gemini",
        "label": "Gemini 3 Pro Image",
        "tier": "best",
    },
    "gemini-2.5-flash-image": {
        "provider": "gemini",
        "label": "Gemini 2.5 Flash Image",
    },
}
DEFAULT_MODEL = "gemini-3-pro-image"
SELECTED_MODEL = DEFAULT_MODEL   # nadpisywane z GUI / projekt.json


def current_model() -> dict:
    return MODELS.get(SELECTED_MODEL, MODELS[DEFAULT_MODEL])

# --- Spójność stylistyczna (PRIORYTET KRYTYCZNY) ---
ACCENT_HEX = "#801515"           # wartości, znaki, ramki dla kolorów czerwonych
BLACK_HEX = "#1A1414"            # wartości dla pika i trefla
CREAM_HEX = "#F5EFE0"            # kremowe tło ilustracji (do kluczowania)

# --- Format karty (preset wybierany w Ustawieniach) ---
# klucz -> (etykieta, (szerokość mm, wysokość mm))
CARD_PRESETS: dict[str, tuple[str, tuple[float, float]]] = {
    "poker": ("Standard Poker · 63 × 88 mm", (63.0, 88.0)),
    "bridge": ("Bridge · 57 × 88 mm", (57.0, 88.0)),
    "tarot": ("Tarot · 70 × 120 mm", (70.0, 120.0)),
    "mini": ("Mini · 44 × 63 mm", (44.0, 63.0)),
}
SELECTED_CARD_PRESET = "poker"
CARD_MM = CARD_PRESETS[SELECTED_CARD_PRESET][1]


def set_card_preset(key: str) -> None:
    """Zmienia globalny format karty (DPI eksportu liczy się z CARD_MM na żywo)."""
    global SELECTED_CARD_PRESET, CARD_MM
    if key in CARD_PRESETS:
        SELECTED_CARD_PRESET = key
        CARD_MM = CARD_PRESETS[key][1]

# Rozszerzenia plików traktowane jako obrazy
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Domyślne wartości talii (edytowalne w GUI)
DEFAULT_VALUES = ["A", "K", "Q", "J", "10", "9", "8", "7", "6", "5", "4", "3", "2"]

# Wybrane przez użytkownika tła per kolor: {"kier": "ścieżka", ...}
# (ustawiane z GUI, zapisywane w projekt.json)
TEMPLATE_OVERRIDES: dict[str, str] = {}

# Kandydaci na czcionkę serif: najpierw dołączone, potem systemowe Windows
SERIF_FONT_CANDIDATES = [
    *(sorted(FONTS_DIR.glob("*.ttf")) if FONTS_DIR.exists() else []),
    Path(r"C:\Windows\Fonts\georgiab.ttf"),   # Georgia Bold
    Path(r"C:\Windows\Fonts\georgia.ttf"),
    Path(r"C:\Windows\Fonts\timesbd.ttf"),    # Times New Roman Bold
    Path(r"C:\Windows\Fonts\times.ttf"),
]


# Czcionka na symbole ♥♦♣♠ (Georgia/Times ich nie mają)
SYMBOL_FONT_CANDIDATES = [
    Path(r"C:\Windows\Fonts\seguisym.ttf"),   # Segoe UI Symbol
    Path(r"C:\Windows\Fonts\segoeui.ttf"),
    Path(r"C:\Windows\Fonts\arial.ttf"),
]


def find_symbol_font() -> Path:
    for candidate in SYMBOL_FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    return find_serif_font()


def find_serif_font() -> Path:
    for candidate in SERIF_FONT_CANDIDATES:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Nie znaleziono czcionki serif. Umieść plik .ttf w assets/fonts/."
    )


def dpi_for_template(width_px: int, height_px: int) -> tuple[float, float]:
    """DPI, przy którym szablon wydrukuje się dokładnie w formacie CARD_MM."""
    mm_per_inch = 25.4
    return (
        width_px / (CARD_MM[0] / mm_per_inch),
        height_px / (CARD_MM[1] / mm_per_inch),
    )
