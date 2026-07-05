"""Nazwane style AI (zestawy promptów) — trwałe między uruchomieniami.

Jeden „styl" (slot) to KOMPLET wyglądu talii:
  - character   — stylizacja postaci (pop-out) ze zdjęcia,
  - template    — styl tła / szablonu kart,
  - front_red   — prompt tła PRZODU dla kolorów czerwonych (Kier, Karo),
  - front_black — prompt tła PRZODU dla kolorów czarnych (Pik, Trefl).

Sloty (i aktywny slot) trafiają do styles.json — globalne dla atelier, przeżywają
„Nową talię" i zmiany projektu. Wybór aktywnego slotu zmienia jednocześnie
wszystkie cztery prompty.
"""
from __future__ import annotations

import json

from app import config

# --- domyślne prompty (edytowalne w GUI, zapis do slotu) ---------------------

DEFAULT_CHARACTER_STYLE = """\
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
collector card aesthetic. Output strictly the background design with no characters, \
numbers, or suits.
"""

DEFAULT_FRONT_BLACK = """\
Generate a highly detailed, blank playing card front background. Vertical layout. \
Style: precise neo-ornamental engraving, vintage cream paper base, symmetrical, \
rich intricate scrollwork, and acanthus leaves along the borders. The artwork MUST \
be rendered entirely in deep black outlines. CRITICAL: The center of the card MUST \
feature a large, completely blank, vintage cream frame to serve as an empty canvas \
for placing subjects later. Absolutely NO patterns, shading, or lines inside this \
central window. Consistent graphic novel / collector card aesthetic. Output \
strictly the background design with no characters, numbers, or suits.
"""

# Pola slotu i ich domyślne wartości
FIELDS = ("character", "template", "front_red", "front_black")
_DEFAULTS: dict[str, str] = {
    "character": DEFAULT_CHARACTER_STYLE,
    "template": DEFAULT_TEMPLATE_STYLE,
    "front_red": DEFAULT_FRONT_RED,
    "front_black": DEFAULT_FRONT_BLACK,
}

DEFAULT_SLOT_NAME = "Styl 1 — domyślny"

# stan: nazwane sloty + wskaźnik aktywnego slotu
_slots: dict[str, dict[str, str]] = {}
_active: str = DEFAULT_SLOT_NAME


# --- budowanie / dostęp do slotów --------------------------------------------

def _default_slot() -> dict[str, str]:
    return dict(_DEFAULTS)


def _ensure() -> None:
    """Gwarantuje istnienie przynajmniej jednego slotu i poprawny wskaźnik."""
    global _active
    if not _slots:
        _slots[DEFAULT_SLOT_NAME] = _default_slot()
    if _active not in _slots:
        _active = next(iter(_slots))


def slot_names() -> list[str]:
    _ensure()
    return list(_slots.keys())


def active_slot() -> str:
    _ensure()
    return _active


def _current() -> dict[str, str]:
    _ensure()
    return _slots[_active]


def field(name: str) -> str:
    """Wartość pola aktywnego slotu (fallback do domyślnej)."""
    value = _current().get(name, "")
    return value if value.strip() else _DEFAULTS.get(name, "")


# --- akcesory zgodne z resztą kodu -------------------------------------------

def character_style() -> str:
    return field("character")


def template_style() -> str:
    return field("template")


def front_prompt(is_red: bool) -> str:
    return field("front_red" if is_red else "front_black")


# --- edycja aktywnego slotu ---------------------------------------------------

def set_style(kind: str, text: str) -> None:
    """Zapisuje pole aktywnego slotu. kind ∈ FIELDS.
    Pusty/domyślny tekst zeruje nadpisanie (wróci wartość domyślna)."""
    if kind not in FIELDS:
        return
    default = _DEFAULTS.get(kind, "").strip()
    _current()[kind] = "" if text.strip() in ("", default) else text
    save()


def reset(kind: str) -> str:
    """Przywraca pojedyncze pole aktywnego slotu do domyślnego; zwraca domyślny tekst."""
    if kind in FIELDS:
        _current()[kind] = ""
        save()
    return _DEFAULTS.get(kind, "")


def reset_slot() -> None:
    """Przywraca WSZYSTKIE pola aktywnego slotu do wartości domyślnych."""
    _slots[active_slot()] = _default_slot()
    save()


def is_default(kind: str) -> bool:
    """Czy pole aktywnego slotu jest w wartości domyślnej."""
    if kind not in FIELDS:
        return True
    return not _current().get(kind, "").strip()


# --- zarządzanie slotami ------------------------------------------------------

def set_active_slot(name: str) -> None:
    global _active
    if name in _slots:
        _active = name
        save()


def _unique_name(base: str) -> str:
    if base not in _slots:
        return base
    i = 2
    while f"{base} ({i})" in _slots:
        i += 1
    return f"{base} ({i})"


def create_slot(name: str = "") -> str:
    """Tworzy nowy slot (kopia domyślnych), ustawia go aktywnym, zwraca nazwę."""
    global _active
    _ensure()
    base = name.strip() or f"Styl {len(_slots) + 1}"
    unique = _unique_name(base)
    _slots[unique] = _default_slot()
    _active = unique
    save()
    return unique


def duplicate_active(name: str = "") -> str:
    """Tworzy slot będący kopią AKTYWNEGO, ustawia go aktywnym, zwraca nazwę."""
    global _active
    _ensure()
    base = name.strip() or f"{_active} — kopia"
    unique = _unique_name(base)
    _slots[unique] = dict(_current())
    _active = unique
    save()
    return unique


def rename_slot(old: str, new: str) -> str:
    """Zmienia nazwę slotu (zachowuje kolejność). Zwraca ostateczną nazwę."""
    global _active
    new = new.strip()
    if old not in _slots or not new or new == old:
        return old
    unique = _unique_name(new)
    # odtwarzamy dict z zachowaniem kolejności, podmieniając klucz
    _slots_new = {
        (unique if key == old else key): value for key, value in _slots.items()
    }
    _slots.clear()
    _slots.update(_slots_new)
    if _active == old:
        _active = unique
    save()
    return unique


def delete_slot(name: str) -> None:
    """Usuwa slot (min. jeden musi zostać)."""
    global _active
    if name not in _slots or len(_slots) <= 1:
        return
    del _slots[name]
    if _active == name:
        _active = next(iter(_slots))
    save()


# --- eksport / import pojedynczego zestawu -----------------------------------

def export_slot(name: str = "") -> dict:
    """Zwraca zestaw (nazwa + prompty) do zapisania w pliku JSON."""
    _ensure()
    key = name if name in _slots else _active
    return {"name": key, "style": dict(_slots[key])}


def import_slot(data: dict) -> str:
    """Tworzy nowy slot z danych (format z export_slot lub sam dict pól),
    ustawia go aktywnym, zwraca nazwę."""
    global _active
    _ensure()
    payload = data.get("style") if isinstance(data.get("style"), dict) else data
    slot = _sanitize_slot(payload if isinstance(payload, dict) else {})
    base = str(data.get("name") or "Zaimportowany styl").strip() or "Zaimportowany styl"
    unique = _unique_name(base)
    _slots[unique] = slot
    _active = unique
    save()
    return unique


# --- zapis / odczyt -----------------------------------------------------------

def _sanitize_slot(data: dict) -> dict[str, str]:
    return {
        key: (str(data[key]) if isinstance(data.get(key), str) else "")
        for key in FIELDS
    }


def load() -> None:
    """Wczytuje sloty z styles.json (z migracją starego formatu)."""
    global _active
    _slots.clear()
    _active = DEFAULT_SLOT_NAME
    if not config.STYLES_JSON.exists():
        _ensure()
        return
    try:
        data = json.loads(config.STYLES_JSON.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        _ensure()
        return

    if isinstance(data.get("slots"), dict) and data["slots"]:
        for name, slot in data["slots"].items():
            if isinstance(slot, dict):
                _slots[str(name)] = _sanitize_slot(slot)
        active = data.get("active_slot")
        _active = active if isinstance(active, str) and active in _slots \
            else next(iter(_slots))
    else:
        # migracja starego formatu {character_preset, character_custom, template}
        slot = _default_slot()
        if isinstance(data.get("template"), str) and data["template"].strip():
            slot["template"] = data["template"]
        _slots[DEFAULT_SLOT_NAME] = slot
        _active = DEFAULT_SLOT_NAME
    _ensure()


def save() -> None:
    try:
        config.STYLES_JSON.write_text(
            json.dumps(
                {"active_slot": _active, "slots": _slots},
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass
