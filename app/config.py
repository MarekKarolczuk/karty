"""Centralna konfiguracja: ścieżki, kolory, rozmiar karty, modele."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# --- Foldery (wg opis_pomyslu.md, dopasowane do istniejących nazw) ---
ZDJECIA_DIR = ROOT / "zdjecia"
TLA_DIR = ROOT / "tla_kart"          # LEGACY — tylko jednorazowa migracja do Style/
REFERENCJE_DIR = ROOT / "Przykladowe_karty_fajne_ale_nie_spojne"
OUTPUT_DIR = ROOT / "output"
RAW_DIR = OUTPUT_DIR / "_raw"        # surowe wyjście AI (PNG, bez narożników)
ASSETS_DIR = ROOT / "assets"
MASKS_DIR = ASSETS_DIR / "masks"
FONTS_DIR = ASSETS_DIR / "fonts"
UI_FONTS_DIR = FONTS_DIR / "ui"      # fonty interfejsu (NIE do rysowania kart!)
PROJEKT_JSON = ROOT / "projekt.json"
STYLES_JSON = ROOT / "styles.json"   # STARY format (migrowany do Style/)
ANALIZA_JSON = ROOT / "analiza_zdjec.json"   # cache analiz AI zdjęć (auto-przydział)
# Rewers i tła przodu żyją w folderach presetów: style_store.back_path()
# i style_store.front_dir() wskazują pliki AKTYWNYCH presetów.

# --- Biblioteki presetów stylu (foldery na dysku) ---
# Każda kategoria to podfolder Style/<kategoria>/, a każdy preset to podfolder
# z jego nazwą. Aktywny preset per kategoria zapisywany w Style/active.json.
STYLE_ROOT = ROOT / "Style"
STYLE_CATEGORIES = ("postac", "styl_tla", "tla_przodu", "rewers", "wartosci")
STYLE_ACTIVE_JSON = STYLE_ROOT / "active.json"

# --- API ---
# Klucze czytane ze zmiennych środowiskowych / .env (NIGDY nie hardcodowane —
# .env jest w .gitignore, więc nie trafia na repo).
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# Własny klucz do innego modelu AI (np. Claude / dowolny provider) — miejsce na
# klucz użytkownika zamiast sztywno wpisanego providera.
CUSTOM_API_KEY = os.getenv("CUSTOM_API_KEY", "")
# Zachowane dla zgodności (stability_client importuje tę stałą); puste = nieużywane.
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "")

# --- Vertex AI (Google Cloud) — alternatywa dla klucza z AI Studio ---
# USE_VERTEX=true → generacja idzie przez Vertex AI (billing GCP, np. 300$ z
# trialu), logowanie przez ADC (gcloud auth application-default login), BEZ
# klucza API. Wymaga GOOGLE_CLOUD_PROJECT i włączonego Vertex AI API.
USE_VERTEX = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() \
    in ("1", "true", "yes", "on")
GCP_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
# Region dotyczy tylko modeli regionalnych (np. gemini-2.5-flash-image). Modele
# global-only (Gemini 3 Image) wymuszają endpoint "global" niezależnie od tej
# wartości — patrz vertex_location_for() i pole "vertex_location" w MODELS.
GCP_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "").strip() or "us-central1"


def api_ready() -> bool:
    """Czy jest z czym wołać model: klucz AI Studio albo tryb Vertex + projekt."""
    return bool(GEMINI_API_KEY) or (USE_VERTEX and bool(GCP_PROJECT))


def active_provider_label() -> str:
    """Czytelna nazwa aktywnego źródła generacji (do paska tytułu / Ustawień).
    Pusty string, gdy nic nie jest skonfigurowane."""
    if USE_VERTEX and GCP_PROJECT:
        return f"Vertex AI · {GCP_PROJECT}"
    if GEMINI_API_KEY:
        return "Google AI Studio"
    return ""

# Rejestr modeli obrazowych (wybór w GUI). Stała lista — tylko modele
# generujące obrazy (Imagen 3/4 wyłączone przez Google VI 2026, nie dodawać).
MODELS: dict[str, dict] = {
    "gemini-3-pro-image": {
        "provider": "gemini",
        "label": "Gemini 3 Pro Image",
        "tier": "best",
        "vertex_location": "global",   # na Vertex serwowany tylko z "global"
    },
    "gemini-3.1-flash-image-preview": {
        "provider": "gemini",
        "label": "Gemini 3.1 Flash Image (Nano Banana 2)",
        "vertex_location": "global",   # rodzina gemini-3* jest global-only
    },
    "gemini-2.5-flash-image": {
        "provider": "gemini",
        "label": "Gemini 2.5 Flash Image",
        "vertex_location": None,       # honoruje GCP_LOCATION (regionalny)
    },
}
DEFAULT_MODEL = "gemini-3-pro-image"
SELECTED_MODEL = DEFAULT_MODEL   # nadpisywane z GUI / projekt.json

# Model TEKSTOWO-WIZYJNY do analizy zdjęć (auto-przydział) — celowo POZA MODELS
# (tam żyją wyłącznie modele obrazowe do pickera w GUI). Tani model multimodalny
# zwracający JSON. Regionalny: vertex_location_for() dla id spoza MODELS zwraca
# GCP_LOCATION (gdyby kiedyś zmienić na model rodziny gemini-3*, trzeba wymusić
# "global" — patrz pole "vertex_location" w MODELS).
ANALYSIS_MODEL = "gemini-2.5-flash"
ANALYSIS_TEMPERATURE = 0.1   # analiza ma być powtarzalna, nie kreatywna


def current_model() -> dict:
    return MODELS.get(SELECTED_MODEL, MODELS[DEFAULT_MODEL])


def vertex_location_for(model_id: str | None = None) -> str:
    """Region Vertex dla danego modelu: wymuszony (np. 'global' dla modeli
    global-only) albo region użytkownika z GCP_LOCATION."""
    model_id = model_id or SELECTED_MODEL
    forced = MODELS.get(model_id, {}).get("vertex_location")
    return forced or GCP_LOCATION

# --- Spójność stylistyczna (PRIORYTET KRYTYCZNY) ---
ACCENT_HEX = "#801515"           # wartości, znaki, ramki dla kolorów czerwonych
BLACK_HEX = "#1A1414"            # wartości dla pika i trefla
CREAM_HEX = "#F5EFE0"            # kremowe tło ilustracji (do kluczowania)

# --- Stabilizacja generacji (spójność talii) ---
GEN_TEMPERATURE = 0.3   # niska temperatura = powtarzalny styl między kartami
GEN_SEED = 12           # seed bazowy; wywołanie karty używa GEN_SEED + wariant

# --- Format karty (preset wybierany w Ustawieniach) ---
# klucz -> (etykieta, (szerokość mm, wysokość mm), DOKŁADNA proporcja pikseli)
# Proporcja pikseli to zredukowany stosunek calowego pierwowzoru formatu
# (poker 2.5×3.5″ = 5:7 itd.) — pliki teł/kart mają szer:wys równe jej co do
# piksela (wymóg drukarni/serwisów przyjmujących np. dokładnie 5:7); mm to
# zaokrąglony rozmiar WYDRUKU (eksport PDF).
CARD_PRESETS: dict[str, tuple[str, tuple[float, float], tuple[int, int]]] = {
    "poker": ("Standard Poker · 63 × 88 mm", (63.0, 88.0), (5, 7)),   # 2.5×3.5″
    "bridge": ("Bridge · 57 × 88 mm", (57.0, 88.0), (9, 14)),         # 2.25×3.5″
    "tarot": ("Tarot · 70 × 120 mm", (70.0, 120.0), (7, 12)),
    "mini": ("Mini · 44 × 63 mm", (44.0, 63.0), (7, 10)),             # 1.75×2.5″
}
SELECTED_CARD_PRESET = "poker"
CARD_MM = CARD_PRESETS[SELECTED_CARD_PRESET][1]
CARD_RATIO = CARD_PRESETS[SELECTED_CARD_PRESET][2]


def set_card_preset(key: str) -> None:
    """Zmienia globalny format karty (DPI eksportu liczy się z CARD_MM na żywo)."""
    global SELECTED_CARD_PRESET, CARD_MM, CARD_RATIO
    if key in CARD_PRESETS:
        SELECTED_CARD_PRESET = key
        CARD_MM = CARD_PRESETS[key][1]
        CARD_RATIO = CARD_PRESETS[key][2]


# Standardowa szerokość pliku tła (px) — jak domyślne tła; stałe pikselowe
# klampu (masks.KLAMP_*) są strojone pod tę skalę
TEMPLATE_STD_SZEROKOSC = 1696


def template_target_size() -> tuple[int, int]:
    """Docelowy rozmiar pliku tła: DOKŁADNA proporcja pikseli formatu
    (CARD_RATIO, np. 5:7 dla pokera) w skali najbliższej standardowej
    szerokości — wymiary to wielokrotności proporcji, więc szer/wys jest
    równe jej co do piksela (poker: 1695×2373). Liczone na żywo — preset
    formatu z Ustawień zmienia CARD_RATIO w sesji."""
    rw, rh = CARD_RATIO
    k = max(1, round(TEMPLATE_STD_SZEROKOSC / rw))
    return (rw * k, rh * k)

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


def _ma_rowne_cyfry(path: Path) -> bool:
    """Czy font ma cyfry o równej wysokości (lining figures)? Old-style
    figures (np. Georgia) renderują „10" jak „1o" — takie fonty odpadają."""
    try:
        from PIL import ImageFont
        boxes = [ImageFont.truetype(str(path), 64).getbbox(d)
                 for d in "0123456789"]
    except OSError:
        return False
    tops = [b[1] for b in boxes]
    bottoms = [b[3] for b in boxes]
    return max(tops) - min(tops) <= 5 and max(bottoms) - min(bottoms) <= 5


_serif_font_cache: Path | None = None


def find_serif_font() -> Path:
    """Czcionka serif do narożników kart — preferuje fonty z lining figures
    (równe cyfry); wynik cache'owany na czas procesu."""
    global _serif_font_cache
    if _serif_font_cache is not None:
        return _serif_font_cache
    existing = [c for c in SERIF_FONT_CANDIDATES if c.exists()]
    if not existing:
        raise FileNotFoundError(
            "Nie znaleziono czcionki serif. Umieść plik .ttf w assets/fonts/."
        )
    _serif_font_cache = next(
        (c for c in existing if _ma_rowne_cyfry(c)), existing[0]
    )
    return _serif_font_cache


def dpi_for_template(width_px: int, height_px: int) -> tuple[float, float]:
    """DPI, przy którym szablon wydrukuje się dokładnie w formacie CARD_MM."""
    mm_per_inch = 25.4
    return (
        width_px / (CARD_MM[0] / mm_per_inch),
        height_px / (CARD_MM[1] / mm_per_inch),
    )
