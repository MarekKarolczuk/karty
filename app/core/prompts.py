"""Prompty wg opis_pomyslu.md (sekcje 5-7).

Prompty są po angielsku (modele obrazowe reagują na nie precyzyjniej).
Części opisujące STYL (postać / tło) są edytowalne w GUI (style_store);
twarde wymogi layoutu (#801515, serif, pion, 63x88, maski) są doklejane
zawsze, niezależnie od edycji użytkownika.
"""
from app import config
from app.core import style_store

# Zachowane dla zgodności (domyślne wartości stylów)
CHARACTER_STYLE = style_store.DEFAULT_CHARACTER_STYLE
TEMPLATE_STYLE = style_store.DEFAULT_TEMPLATE_STYLE

# Twarde wymogi kompozycji dla stylizacji zdjęcia (tryb hybrydowy) —
# niezbędne dla masek kompozytora, nieedytowalne.
_CHARACTER_REQUIREMENTS = f"""\

Composition requirements (mandatory):
- Strictly vertical (portrait) composition.
- The characters fill the frame, centered.
- The background behind the characters must be a single flat, uniform cream
  color exactly {config.CREAM_HEX}, with no texture, no ornaments, no shadows.
- Do not add any text, borders, frames or card elements. Output only the
  stylized illustration of the people.
"""


def character_style() -> str:
    """Pełny prompt stylizacji zdjęcia: edytowalny styl + twarde wymogi."""
    return style_store.character_style().rstrip() + "\n" + _CHARACTER_REQUIREMENTS


def template_style() -> str:
    return style_store.template_style()


def full_card_prompt(value: str, suit_symbol: str, suit_name_en: str) -> str:
    return f"""\
The first image is a playing-card template in this style:
{style_store.template_style().rstrip()}
The central element is an ornate, bold suit-shaped frame with saturated fill.
The template must remain 100% UNTOUCHED outside the central suit frame and the
corner shields: do not redraw, move, recolor or alter any ornament, line or
border. Keep the exact resolution of the template image.

Task — seamless inpainting-style composition:
1. Take the people from the second image (the photo) and repaint them in this
   exact style:
{style_store.character_style().rstrip()}
2. Place that illustration ONLY inside the central {suit_name_en}-shaped frame
   of the template, strictly vertical, nicely filling the frame.
3. In the top-left corner shield draw the value "{value}" and below it the
   suit symbol "{suit_symbol}", stacked VERTICALLY, using a classic SERIF font,
   color exactly {config.ACCENT_HEX}. In the bottom-right corner shield draw
   the same value and symbol rotated 180 degrees (as on real playing cards).
4. Do not edit the background or ornaments of the template. Do not change the
   output resolution — it must match the template image exactly.
"""


SUIT_NAME_EN = {
    "kier": "heart",
    "karo": "diamond",
    "pik": "spade",
    "trefl": "club",
}


# Domyślny prompt bazowy dla teł PRZODU karty — zależny od koloru (czerwone/
# czarne). Bierze się z aktywnego slotu stylu (style_store), więc jest trwały
# i edytowalny per zestaw. Zachowana stała FRONT_BACKGROUND_PROMPT dla zgodności
# (fallback = wariant czerwony).
FRONT_BACKGROUND_PROMPT = style_store.DEFAULT_FRONT_RED


def front_background_prompt(suit) -> str:
    """Prompt tła przodu wg koloru karty (czerwone → front_red, czarne →
    front_black) z aktywnego slotu stylu."""
    return style_store.front_prompt(suit.is_red)


# --- Generowanie nowych szablonów tła ----------------------------------------

def template_generation_prompt(suit_name_en: str, is_red: bool) -> str:
    ornament_color = (
        f"saturated dark red ({config.ACCENT_HEX})" if is_red
        else "deep near-black ink (#1A1414)"
    )
    return f"""\
Generate a NEW empty playing-card template (card background), portrait
orientation with the exact aspect ratio 63:88 (standard poker size).

Style:
{style_store.template_style().rstrip()}
Primary ornament color for this card: {ornament_color}.

Mandatory layout (identical to the reference image if one is provided):
- A decorative outer border frame near the card edges.
- The central element: an ornate, bold {suit_name_en}-shaped frame with a
  clear contour; the INTERIOR of the {suit_name_en} must be a completely
  EMPTY, flat cream area (an illustration will be pasted there later).
- Two empty shield-shaped plaques: one in the top-left corner, one in the
  bottom-right corner (flat cream interiors, values will be added later).
- Absolutely NO letters, numbers, text or watermarks anywhere on the card.
"""


# --- Pop-out ("out of bounds") -------------------------------------------------
# Główny prompt trybu pop-out: postać MUSI wychodzić poza centralną ramę
# symbolu. Model dostaje kolaż (szablon + wkadrowane zdjęcie) jako init_image.

DEFAULT_POPOUT_PROMPT = """\
Transform the subject from the input image into a highly detailed, colorful
vector illustration (cell-shaded, clean black outlines). The subject MUST
perfectly blend with the existing playing card design. CRITICAL INSTRUCTION:
Create a 3D pop-out effect. The subject's head, arms, or props may extend
only SLIGHTLY beyond the central suit frame (heart/diamond/spade/club
border) — just past its contour line, never reaching the card's ornaments
or edges. Do not confine the subject strictly inside the white center.
Match the lighting and maintain the pristine, neo-ornamental vintage style
of the card. Do not alter anything outside the central suit frame: the
engraved background, outer border and corner shields must stay untouched."""


def popout_prompt() -> str:
    """Prompt pop-out: instrukcje mechaniki + wybrany preset stylu postaci
    (Ustawienia i style) jako doprecyzowanie wyglądu."""
    return (DEFAULT_POPOUT_PROMPT
            + "\n\nSubject style details:\n"
            + style_store.character_style().strip())


# --- Rewers (tył karty) --------------------------------------------------------

# Predefiniowane style rewersu (zakładka „Rewersy"): klucz -> (etykieta PL,
# opis stylu dla modelu; None = użytkownik wpisuje własny opis).
BACK_PRESETS: dict[str, tuple[str, str | None]] = {
    "klasyczny": (
        "Klasyczny ornament",
        f"Dense, rich classic engraving scrollwork in saturated dark red "
        f"({config.ACCENT_HEX}) on a cream background — acanthus leaves, "
        "banknote-like guilloche, as on high-end collector card decks.",
    ),
    "stylizowany": (
        "Stylizowany",
        f"Bold, modern art-deco stylization: strong symmetric shapes, fans "
        f"and sunburst motifs in saturated dark red ({config.ACCENT_HEX}) "
        "with thin cream accents; elegant, contemporary, poster-like.",
    ),
    "geometryczny": (
        "Geometryczny",
        f"Perfectly regular geometric lattice: interlocking diamonds and "
        f"knots in saturated dark red ({config.ACCENT_HEX}) on cream, "
        "precise thin linework, mathematical repetition edge to edge.",
    ),
    "monogram": (
        "Monogram / medalion",
        f"A single central ornamental medallion with mirrored flourishes in "
        f"saturated dark red ({config.ACCENT_HEX}) on cream, framed by a "
        "delicate engraved wreath; calm margins, jewel-like detail.",
    ),
    "custom": ("Własny opis", None),
}


def back_generation_prompt(preset: str = "klasyczny", custom_text: str = "",
                           orientation: str = "portrait",
                           from_photo: bool = False) -> str:
    """Prompt rewersu: styl z presetu (lub własny opis) + twarde wymogi
    (symetria 180°, bordiura, bez tekstu). Orientacja steruje proporcjami."""
    style_text = BACK_PRESETS.get(preset, BACK_PRESETS["klasyczny"])[1]
    if style_text is None:
        style_text = custom_text.strip() or style_store.template_style().rstrip()

    if orientation == "landscape":
        aspect = ("landscape orientation with the exact aspect ratio 88:63 "
                  "(a standard poker card rotated 90 degrees)")
    else:
        aspect = ("portrait orientation with the exact aspect ratio 63:88 "
                  "(standard poker size)")

    photo_block = ""
    if from_photo:
        photo_block = (
            "\nUse the provided photo as the design source: transform its "
            "subject, silhouettes and dominant shapes into a decorative, "
            "fully ornamental pattern — do NOT reproduce the photo "
            "literally, no photographic textures.\n"
        )

    return f"""\
Generate the BACK of a playing card (card back design), {aspect}.

Style:
{style_text}
{photo_block}
Mandatory requirements:
- The design must be PERFECTLY SYMMETRIC under a 180-degree rotation
  (identical when the card is upside down), like real playing-card backs.
- A decorative border frame near the card edges with a thin cream margin
  outside it (safe for printing).
- Rich ornament with no large empty areas.
- Absolutely NO letters, numbers, text, faces or watermarks.
"""
