"""Biblioteki presetów stylu — trwałe foldery na dysku (Style/).

Zamiast jednego wspólnego „zestawu" mamy CZTERY niezależne biblioteki, po jednej
na komponent wyglądu talii:
  - postac     — stylizacja postaci (pop-out) ze zdjęcia,
  - styl_tla   — opis ornamentyki / szablonu kart,
  - tla_przodu — prompty teł PRZODU (czerwone/czarne) + 4 obrazy kart,
  - rewers     — opis + obraz rewersu (tyłu kart).

Każda kategoria to podfolder `Style/<kategoria>/`, a każdy preset to podfolder
z jego nazwą, np. `Style/postac/Domyślny/styl.txt`. Aktywny preset per kategoria
zapisywany jest w `Style/active.json` (globalny — przeżywa restart aplikacji).

Publiczne akcesory odczytu (`character_style`, `template_style`, `front_prompt`)
oraz stałe `DEFAULT_*` są zachowane, więc `app/core/prompts.py` działa bez zmian.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from app import config

# --- domyślne prompty (wartość, gdy pole presetu jest puste) ------------------

# UWAGA: ten tekst trafia do promptów OBU trybów (pop-out i FULL_AI), więc
# opisuje WYŁĄCZNIE styl rysunku i wnętrze symbolu — mechanikę nachodzenia na
# ramę (jak daleko postać wychodzi/nie wychodzi) definiują instrukcje trybu
# (prompts.DEFAULT_POPOUT_PROMPT / full_card_prompt). Poprzednia wersja miała
# tu własne „SLIGHT POP-OUT… ONLY SLIGHTLY" i zakaz dotykania kremu poza
# symbolem — tłumiły efekt pop-out mimo poprawnych instrukcji trybu.
DEFAULT_CHARACTER_STYLE = f"""\
CRITICAL TASK: Seamless inpainting. Transform the subjects and their immediate \
surroundings from the input photo into a stylized, full-color vector \
illustration. Do NOT output a raw photograph.
1. ART STYLE (STRICT):
- Clean, sharp, black outlines around all elements.
- Cell-shaded rendering for clothing, props and background: vibrant, flat, \
defined color planes, minimal gradients. FACES are the exception — render them \
with soft, smooth shading and fine detail to keep an exact likeness (never a \
few flat blocks).
- ACCURATE, REALISTIC face and body proportions: the same face shape, hairstyle \
and features as in the photo — no caricature, no exaggerated or "beautified" \
features, no changed head-to-body ratio. The people must be instantly \
recognizable.
- Preserve maximum likeness to the people (faces, poses, clothing details).
- The final look must resemble a crisp, modern graphic novel.
2. COMPOSITION:
- The suit symbol's colored fill and its ornate frame are ALREADY present and \
FINAL in the card you received — reproduce them exactly as given, without \
changing their shape, size or position. The colored fill ends exactly at the \
window contour: never bleed it over the frame or the surrounding ornaments.
- The subject stands on that existing backdrop inside the central suit symbol.
- How far the subject may or must cross the symbol's frame is defined by the \
composition instructions of the selected mode — follow THEM, not this section.
3. CARD SURROUNDINGS:
- DO NOT alter or blur the intricate etched scrollwork outside the central frame.
- Leave the corner shield plaques completely empty — no letters, numbers or \
suit pips anywhere.
"""

# Poprzednia wersja domyślnego stylu postaci — do jednorazowej migracji:
# presety, które mają ten tekst zapisany DOSŁOWNIE, wracają do pustego pliku
# (puste pole = aktualna wartość domyślna, patrz text()/set_text()).
# Uwaga: zawierała sprzeczność z prompts.NO_TEXT_SUFFIX (kazała zachować
# narożne litery/pipy, których na kartach nie ma — stempluje je compositor).
_LEGACY_CHARACTER_STYLE = """\
CRITICAL TASK: Seamless inpainting. Transform the subjects and their immediate \
surroundings from the input photo into a highly stylized, full-color vector \
illustration. Do NOT output a raw photograph.
1. ART STYLE (STRICT):
- Clean, sharp, black outlines around all elements.
- Strictly cell-shaded: use vibrant, flat, defined color planes only. ZERO soft gradients.
- Preserve maximum likeness to the people (faces, poses, clothing details).
- The final look must resemble a crisp, modern graphic novel.
2. COMPOSITION & POP-OUT EFFECT:
- The subject is placed inside the central suit symbol. The symbol's color MUST \
match the suit: RED for hearts/diamonds, BLACK for spades/clubs.
- SLIGHT POP-OUT: The subject's head, shoulders, or props MUST naturally overlap \
and ONLY SLIGHTLY break out of the thick border of the central symbol (using the \
corresponding red or black color) to create a 3D effect.
- INNER BACKGROUND: Convert the original photo's background into a simplified, \
uniform background matching the card's suit color (red for hearts/diamonds, black \
for spades/clubs) behind the subjects.
3. ABSOLUTE BOUNDARIES (DO NOT TOUCH):
- The subject MUST NOT cover, overwrite, or touch the vintage cream background \
outside the symbol.
- DO NOT alter or blur the intricate etched scrollwork outside the central frame.
- DO NOT modify the corner numbers, letters, or suit pips (A, K, J, etc.).
"""

DEFAULT_TEMPLATE_STYLE = f"""\
Precise, neo-ornamental engraving style (custom-deck engraving): ornaments MUST \
match the card's suit color (saturated dark red {config.ACCENT_HEX} for \
Hearts/Diamonds, or rich deep black for Spades/Clubs) on a vintage cream \
background. Rich and symmetric, full of intricate scrollwork, acanthus leaves and \
banknote-like engraving, as on high-end collector card decks. Lines clean, sharp \
and uniform.
"""

DEFAULT_FRONT_RED = f"""\
Generate a highly detailed, blank playing card front background. Vertical layout. \
Style: precise neo-ornamental engraving, vintage cream paper base, symmetrical, \
rich intricate scrollwork, and acanthus leaves along the borders. The artwork MUST \
be rendered entirely in saturated dark red ({config.ACCENT_HEX}) outlines. \
CRITICAL: The center of the card MUST feature a large, completely blank, vintage \
cream frame to serve as an empty canvas for placing subjects later. Absolutely NO \
patterns, shading, or lines inside this central window. Consistent graphic novel / \
collector card aesthetic. Output strictly the background design with no characters \
and no text.
"""

DEFAULT_FRONT_BLACK = """\
Generate a highly detailed, blank playing card front background. Vertical layout. \
Style: precise neo-ornamental engraving, vintage cream paper base, symmetrical, \
rich intricate scrollwork, and acanthus leaves along the borders. The artwork MUST \
be rendered entirely in deep black outlines. CRITICAL: The center of the card MUST \
feature a large, completely blank, vintage cream frame to serve as an empty canvas \
for placing subjects later. Absolutely NO patterns, shading, or lines inside this \
central window. Consistent graphic novel / collector card aesthetic. Output \
strictly the background design with no characters and no text.
"""

# --- definicja kategorii ------------------------------------------------------

CATEGORIES = config.STYLE_CATEGORIES   # ("postac","styl_tla","tla_przodu","rewers")

# Pola tekstowe (plik <field>.txt) i ich wartości domyślne, per kategoria.
_CATEGORY_FIELDS: dict[str, dict[str, str]] = {
    # sceneria_kolor "1" = tło/otoczenie ze zdjęcia malowane w oknie w
    # monochromatycznych odcieniach koloru karty zamiast płaskiego wypełnienia.
    # Domyślnie WŁĄCZONE (wnętrze symbolu nie ma być płaskie); checkbox w GUI
    # pozwala wrócić do płaskiego.
    "postac": {"styl": DEFAULT_CHARACTER_STYLE, "sceneria_kolor": "1"},
    "styl_tla": {"styl": DEFAULT_TEMPLATE_STYLE},
    # tryb_wlasny "1" = prompt presetu idzie do modelu DOSŁOWNIE, bez
    # wbudowanych dopisków programu (np. karty do planszówek)
    "tla_przodu": {"front_red": DEFAULT_FRONT_RED,
                   "front_black": DEFAULT_FRONT_BLACK,
                   "tryb_wlasny": "0"},
    "rewers": {"opis": "", "tryb_wlasny": "0"},
    # Typografia narożników (stemplowanie lokalne, nie AI) — liczby w %
    # wysokości tarczy, kolory hex; parsowanie w compositor.styl_z_presetu()
    "wartosci": {
        "czcionka": "",                       # nazwa pliku .ttf w folderze presetu
        "rozmiar_wartosci": "40",
        "rozmiar_symbolu": "32",
        "kolor_czerwony": config.ACCENT_HEX,
        "kolor_czarny": config.BLACK_HEX,
        "offset_x": "0",
        "offset_y": "0",
        "odstep": "42",
        # efekty stempla (0/puste = brak — pełna zgodność ze starymi presetami)
        "obwodka_grubosc": "0",               # % wysokości tarczy
        "obwodka_kolor": "",                  # pusty = krem (config.CREAM_HEX)
        "cien_przesuniecie": "0",             # % wysokości tarczy
        "cien_kolor": "",                     # pusty = czerń półprzezroczysta
    },
}

# Obrazy (plik <key>.png), per kategoria.
_CATEGORY_IMAGES: dict[str, tuple[str, ...]] = {
    "tla_przodu": ("kier", "karo", "pik", "trefl"),
    "rewers": ("rewers",),
}

# Czytelne etykiety kategorii (dla GUI).
CATEGORY_LABELS: dict[str, str] = {
    "postac": "styl postaci",
    "styl_tla": "styl tła",
    "tla_przodu": "tła przodu",
    "rewers": "rewers",
    "wartosci": "wartości narożne",
}

DEFAULT_PRESET_NAME = "Domyślny"

# stan: aktywny preset per kategoria (reszta czytana z dysku na bieżąco)
_active: dict[str, str] = {}


# --- ścieżki ------------------------------------------------------------------

def _cat_dir(cat: str) -> Path:
    return config.STYLE_ROOT / cat


def preset_dir(cat: str, name: str | None = None) -> Path:
    """Folder presetu. name=None → aktywny preset danej kategorii."""
    if name is None:
        name = active(cat)
    return _cat_dir(cat) / name


# --- gwarancja struktury ------------------------------------------------------

def _create_default_preset(cat: str) -> None:
    """Tworzy preset „Domyślny" z pustymi polami (puste = wartość domyślna)."""
    d = _cat_dir(cat) / DEFAULT_PRESET_NAME
    d.mkdir(parents=True, exist_ok=True)
    for field in _CATEGORY_FIELDS[cat]:
        f = d / f"{field}.txt"
        if not f.exists():
            f.write_text("", encoding="utf-8")


def _ensure() -> None:
    """Gwarantuje Style/ + podkatalogi kategorii, min. jeden preset i poprawny
    wskaźnik aktywnego presetu. Idempotentne, bez rekurencji."""
    for cat in CATEGORIES:
        d = _cat_dir(cat)
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        subdirs = [p for p in d.iterdir() if p.is_dir()]
        if not subdirs:
            _create_default_preset(cat)
            subdirs = [d / DEFAULT_PRESET_NAME]
        names = sorted(p.name for p in subdirs)
        if _active.get(cat) not in names:
            _active[cat] = names[0]


# --- lista / aktywny preset ---------------------------------------------------

def presets(cat: str) -> list[str]:
    _ensure()
    d = _cat_dir(cat)
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []


def active(cat: str) -> str:
    _ensure()
    names = presets(cat)
    cur = _active.get(cat)
    if cur in names:
        return cur
    return names[0] if names else DEFAULT_PRESET_NAME


def set_active(cat: str, name: str) -> None:
    if preset_dir(cat, name).is_dir():
        _active[cat] = name
        _save_active()


# --- teksty -------------------------------------------------------------------

def text(cat: str, field: str) -> str:
    """Wartość pola aktywnego presetu (puste → wartość domyślna)."""
    f = preset_dir(cat) / f"{field}.txt"
    try:
        value = f.read_text(encoding="utf-8")
    except OSError:
        value = ""
    return value if value.strip() else _CATEGORY_FIELDS.get(cat, {}).get(field, "")


def set_text(cat: str, field: str, value: str) -> None:
    """Zapisuje pole aktywnego presetu. Pusty/domyślny tekst zeruje nadpisanie."""
    if field not in _CATEGORY_FIELDS.get(cat, {}):
        return
    default = _CATEGORY_FIELDS[cat][field].strip()
    d = preset_dir(cat)
    d.mkdir(parents=True, exist_ok=True)
    content = "" if value.strip() in ("", default) else value
    try:
        (d / f"{field}.txt").write_text(content, encoding="utf-8")
    except OSError:
        pass


def reset(cat: str, field: str) -> str:
    """Przywraca pole do domyślnego (zapisuje pustkę); zwraca domyślny tekst."""
    try:
        (preset_dir(cat) / f"{field}.txt").write_text("", encoding="utf-8")
    except OSError:
        pass
    return _CATEGORY_FIELDS.get(cat, {}).get(field, "")


def is_default(cat: str, field: str) -> bool:
    f = preset_dir(cat) / f"{field}.txt"
    try:
        return not f.read_text(encoding="utf-8").strip()
    except OSError:
        return True


# --- akcesory zgodne z resztą kodu (prompts.py) -------------------------------

def character_style() -> str:
    return text("postac", "styl")


def template_style() -> str:
    return text("styl_tla", "styl")


def front_prompt(is_red: bool) -> str:
    return text("tla_przodu", "front_red" if is_red else "front_black")


def front_custom_mode() -> bool:
    """Tryb własnego promptu teł przodu: prompt presetu idzie do modelu
    dosłownie, bez dopisków layoutu (kształt symbolu, tarcze, zakaz tekstu)."""
    return text("tla_przodu", "tryb_wlasny").strip() == "1"


def scenery_suit_mode() -> bool:
    """Sceneria zdjęcia (góry, horyzont) malowana w oknie symbolu w
    monochromatycznych odcieniach koloru karty zamiast płaskiego wypełnienia."""
    return text("postac", "sceneria_kolor").strip() == "1"


def back_text() -> str:
    return text("rewers", "opis")


def back_custom_mode() -> bool:
    """Tryb własnego promptu rewersu: opis presetu idzie do modelu dosłownie,
    bez twardych wymogów (symetria 180°, bordiura, zakaz tekstu)."""
    return text("rewers", "tryb_wlasny").strip() == "1"


# --- obrazy -------------------------------------------------------------------

def image_path(cat: str, key: str, name: str | None = None) -> Path:
    return preset_dir(cat, name) / f"{key}.png"


def save_image(cat: str, key: str, image) -> Path:
    """Zapisuje obraz (PIL.Image) do folderu aktywnego presetu jako <key>.png."""
    d = preset_dir(cat)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{key}.png"
    image.save(path)
    return path


def save_font_file(cat: str, src: Path) -> str:
    """Kopiuje plik czcionki (.ttf/.otf) do folderu AKTYWNEGO presetu.
    Zwraca nazwę pliku (zapisywaną w polu tekstowym presetu) — CRUD i eksport
    zip kopiują cały folder, więc czcionka wędruje razem z presetem."""
    d = preset_dir(cat)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / Path(src).name
    shutil.copy2(src, dest)
    return dest.name


def back_path() -> Path:
    """Plik rewersu talii = rewers.png w folderze AKTYWNEGO presetu rewersu.
    Jedyne źródło prawdy — silnik, eksport i GUI czytają stąd."""
    return preset_dir("rewers") / "rewers.png"


def front_dir() -> Path:
    """Folder AKTYWNEGO presetu teł przodu — tu żyją obrazy szablonów."""
    return preset_dir("tla_przodu")


# --- zarządzanie presetami ----------------------------------------------------

def _sanitize_name(name: str) -> str:
    name = (name or "").strip()
    return "".join(c for c in name if c not in '\\/:*?"<>|').strip()


def _unique_name(cat: str, base: str) -> str:
    existing = set(presets(cat))
    if base not in existing:
        return base
    i = 2
    while f"{base} ({i})" in existing:
        i += 1
    return f"{base} ({i})"


def create(cat: str, name: str = "") -> str:
    """Tworzy nowy preset (puste pola = domyślne), ustawia aktywnym, zwraca nazwę."""
    _ensure()
    base = _sanitize_name(name) or f"Styl {len(presets(cat)) + 1}"
    unique = _unique_name(cat, base)
    d = _cat_dir(cat) / unique
    d.mkdir(parents=True, exist_ok=True)
    for field in _CATEGORY_FIELDS[cat]:
        (d / f"{field}.txt").write_text("", encoding="utf-8")
    _active[cat] = unique
    _save_active()
    return unique


def duplicate(cat: str, name: str = "") -> str:
    """Kopiuje aktywny preset (teksty + obrazy), ustawia aktywnym, zwraca nazwę."""
    _ensure()
    src = preset_dir(cat)
    base = _sanitize_name(name) or f"{active(cat)} — kopia"
    unique = _unique_name(cat, base)
    dst = _cat_dir(cat) / unique
    try:
        shutil.copytree(src, dst)
    except OSError:
        dst.mkdir(parents=True, exist_ok=True)
    _active[cat] = unique
    _save_active()
    return unique


def rename(cat: str, old: str, new: str) -> str:
    """Zmienia nazwę presetu (folderu). Zwraca ostateczną nazwę."""
    new = _sanitize_name(new)
    src = _cat_dir(cat) / old
    if not new or new == old or not src.is_dir():
        return old
    unique = _unique_name(cat, new)
    dst = _cat_dir(cat) / unique
    try:
        src.rename(dst)
    except OSError:
        return old
    if _active.get(cat) == old:
        _active[cat] = unique
        _save_active()
    return unique


def delete(cat: str, name: str) -> None:
    """Usuwa preset (min. jeden musi zostać)."""
    if len(presets(cat)) <= 1:
        return
    d = _cat_dir(cat) / name
    if d.is_dir():
        shutil.rmtree(d, ignore_errors=True)
    if _active.get(cat) == name:
        remaining = presets(cat)
        _active[cat] = remaining[0] if remaining else DEFAULT_PRESET_NAME
        _save_active()


def reset_active(cat: str) -> None:
    """Przywraca wszystkie pola aktywnego presetu do domyślnych (czyści teksty)."""
    for field in _CATEGORY_FIELDS[cat]:
        reset(cat, field)


# --- eksport / import presetu do pliku (Zapisz / Wczytaj) ---------------------

def export_preset(cat: str, dest_path: str, name: str | None = None) -> None:
    """Pakuje folder presetu (teksty + obrazy) do pliku ZIP."""
    name = name or active(cat)
    src = preset_dir(cat, name)
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("_meta.json", json.dumps({"category": cat, "name": name},
                                              ensure_ascii=False))
        if src.is_dir():
            for f in sorted(src.iterdir()):
                if f.is_file():
                    zf.write(f, f.name)


def import_preset(cat: str, zip_path: str) -> str:
    """Wczytuje preset z pliku ZIP jako nowy preset kategorii; zwraca nazwę."""
    _ensure()
    with zipfile.ZipFile(zip_path) as zf:
        meta = {}
        try:
            meta = json.loads(zf.read("_meta.json").decode("utf-8"))
        except (KeyError, json.JSONDecodeError, UnicodeDecodeError):
            pass
        base = _sanitize_name(str(meta.get("name") or Path(zip_path).stem)) \
            or "Zaimportowany"
        unique = _unique_name(cat, base)
        dst = _cat_dir(cat) / unique
        dst.mkdir(parents=True, exist_ok=True)
        for member in zf.namelist():
            if member == "_meta.json" or member.endswith("/"):
                continue
            target = dst / Path(member).name   # tylko nazwa pliku (bez ścieżek)
            try:
                with zf.open(member) as srcf, open(target, "wb") as out:
                    out.write(srcf.read())
            except OSError:
                pass
    _active[cat] = unique
    _save_active()
    return unique


# --- zapis / odczyt aktywnych wskaźników --------------------------------------

def _save_active() -> None:
    try:
        config.STYLE_ROOT.mkdir(parents=True, exist_ok=True)
        config.STYLE_ACTIVE_JSON.write_text(
            json.dumps(_active, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def _load_active() -> None:
    _active.clear()
    if not config.STYLE_ACTIVE_JSON.exists():
        return
    try:
        data = json.loads(config.STYLE_ACTIVE_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if isinstance(data, dict):
        for cat in CATEGORIES:
            if isinstance(data.get(cat), str):
                _active[cat] = data[cat]


# --- migracja starych danych --------------------------------------------------

def _copy_as_png(src: Path, dst: Path) -> None:
    """Kopiuje obraz do PNG (konwersja, bo szablony bywają .jpg)."""
    from PIL import Image
    Image.open(src).convert("RGB").save(dst)


def _read_old_active_slot() -> dict:
    """Pola aktywnego slotu ze starego styles.json (jeśli istnieje)."""
    if not config.STYLES_JSON.exists():
        return {}
    try:
        data = json.loads(config.STYLES_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    slots = data.get("slots")
    if not isinstance(slots, dict) or not slots:
        return {}
    name = data.get("active_slot")
    slot = slots.get(name) if name in slots else next(iter(slots.values()))
    return slot if isinstance(slot, dict) else {}


def _rmdir_quiet(d: Path) -> None:
    shutil.rmtree(d, ignore_errors=True)


def _merge_loose_images(src_dir: Path, cat: str) -> None:
    """Zbiera luźne obrazy z legacy-folderu do presetu Domyślny danej kategorii."""
    dst = preset_dir(cat, DEFAULT_PRESET_NAME)
    dst.mkdir(parents=True, exist_ok=True)
    if cat == "tla_przodu":
        for suit in _CATEGORY_IMAGES["tla_przodu"]:
            target = dst / f"{suit}.png"
            if target.exists():
                continue
            match = next(
                (p for p in sorted(src_dir.iterdir())
                 if p.is_file() and p.suffix.lower() in config.IMAGE_EXTS
                 and suit in p.stem.lower()),
                None,
            )
            if match:
                try:
                    _copy_as_png(match, target)
                except (OSError, ValueError):
                    pass
    elif cat == "rewers":
        target = dst / "rewers.png"
        match = src_dir / "rewers.png"
        if not target.exists() and match.exists():
            try:
                _copy_as_png(match, target)
            except (OSError, ValueError):
                pass


def _migrate_user_folders() -> None:
    """Porządkuje foldery utworzone ręcznie przez użytkownika w Style/."""
    root = config.STYLE_ROOT
    # 1) „Syle postaci" (literówka) → postac: przenieś podfoldery-presety
    legacy_pc = root / "Syle postaci"
    if legacy_pc.is_dir():
        for sub in legacy_pc.iterdir():
            if sub.is_dir():
                target = root / "postac" / sub.name
                if not target.exists():
                    try:
                        sub.rename(target)
                    except OSError:
                        pass
        _rmdir_quiet(legacy_pc)
    # 2) tla_kart (luźne obrazy) → tla_przodu/Domyślny
    legacy_front = root / "tla_kart"
    if legacy_front.is_dir():
        _merge_loose_images(legacy_front, "tla_przodu")
        _rmdir_quiet(legacy_front)
    # 3) tyl_kart → rewers/Domyślny
    legacy_back = root / "tyl_kart"
    if legacy_back.is_dir():
        _merge_loose_images(legacy_back, "rewers")
        _rmdir_quiet(legacy_back)


def _seed_default_texts() -> None:
    """Przenosi teksty ze starego styles.json do presetu Domyślny (gdy pusty)."""
    slot = _read_old_active_slot()
    if not slot:
        return
    mapping = {
        ("postac", "styl"): slot.get("character"),
        ("styl_tla", "styl"): slot.get("template"),
        ("tla_przodu", "front_red"): slot.get("front_red"),
        ("tla_przodu", "front_black"): slot.get("front_black"),
    }
    for (cat, field), value in mapping.items():
        if not (isinstance(value, str) and value.strip()):
            continue
        f = preset_dir(cat, DEFAULT_PRESET_NAME) / f"{field}.txt"
        try:
            if not f.exists() or not f.read_text(encoding="utf-8").strip():
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(value, encoding="utf-8")
        except OSError:
            pass


def _migrate_working_set() -> None:
    """Jednorazowo wchłania stary roboczy zestaw tla_kart/ do presetów Domyślny
    i usuwa go — obrazy żyją WYŁĄCZNIE w folderach presetów (bez duplikatów)."""
    legacy = config.TLA_DIR
    if not legacy.is_dir():
        return
    # tła przodu (kier/karo/pik/trefl) i rewers.png → presety Domyślny
    _merge_loose_images(legacy, "tla_przodu")
    _merge_loose_images(legacy, "rewers")
    # backupy starych rewersów → folder presetu Domyślny rewersu
    rdst = preset_dir("rewers", DEFAULT_PRESET_NAME)
    rdst.mkdir(parents=True, exist_ok=True)
    for backup in sorted(legacy.glob("rewers_stary_*.png")):
        target = rdst / backup.name
        if not target.exists():
            try:
                backup.rename(target)
            except OSError:
                pass
    _rmdir_quiet(legacy)


def _migrate_character_defaults() -> None:
    """Presety postaci ze STARYM domyślnym stylem zapisanym dosłownie wracają
    do pustego pliku (= aktualna wartość domyślna). Presety edytowane ręcznie
    zostają nietknięte."""
    d = _cat_dir("postac")
    if not d.is_dir():
        return
    for preset in d.iterdir():
        f = preset / "styl.txt"
        if not (preset.is_dir() and f.is_file()):
            continue
        try:
            if f.read_text(encoding="utf-8").strip() \
                    == _LEGACY_CHARACTER_STYLE.strip():
                f.write_text("", encoding="utf-8")
        except OSError:
            continue


def load() -> None:
    """Inicjalizacja przy starcie: struktura folderów + migracja starych danych."""
    _load_active()
    _ensure()
    _migrate_user_folders()
    _seed_default_texts()
    _migrate_working_set()
    _migrate_character_defaults()
    _ensure()
