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

# Twardy zakaz tekstu — doklejany na końcu KAŻDEGO promptu generującego przód
# karty lub tło. AI nie rysuje tekstu: wartości i symbole narożne stempluje
# deterministycznie compositor.stempluj_narozniki() PO odpowiedzi API.
NO_TEXT_SUFFIX = """\
ABSOLUTE: The output MUST contain NO text, NO letters, NO numbers, NO corner
pips, NO watermark, NO signature — anywhere in the image. Corner areas must
remain clean vintage cream background."""

# Twarde zabezpieczenie szablonu — wariant ŚCISŁY (ilustracja tylko wewnątrz
# ramy symbolu). Od iteracji 9 NIEUŻYWANY przez tryby kart (oba przeszły na
# TEMPLATE_GUARD_POPOUT — postać może przekraczać ramę); zostaje jako
# zabezpieczenie dla ewentualnych przyszłych promptów bez pop-outu.
TEMPLATE_GUARD = """\
TEMPLATE PRESERVATION (hard constraint): the card template you received is a
FINISHED background. Outside the central suit symbol it must stay PIXEL-
IDENTICAL: do not repaint, recolor, restyle, sharpen or "improve" the cream
paper, the outer border, any ornament or the corner shield plaques."""

# Wariant pop-out zabezpieczenia szablonu: najpierw afirmacja, że nachodzenie
# na ramę jest WYMAGANE i ma pierwszeństwo, dopiero potem zakaz przemalowania
# reszty — wersja zaczynająca od „PIXEL-IDENTICAL" z doklejonym wyjątkiem
# była czytana jako przewaga zakazu i model tłumił efekt do zera.
# Wierność tła wszędzie tam, gdzie postaci NIE ma, jest warunkiem działania
# klampu różnicowego (masks.maska_klampu): tło odtworzone ≠ szablon zostałoby
# uznane za sylwetkę albo utrącone guardrailem.
TEMPLATE_GUARD_POPOUT = """\
TEMPLATE PRESERVATION (hard constraint): the card template is a FINISHED
background. The pop-out overlap described above is REQUIRED and has
priority — where the subject crosses the suit frame it covers the frame
contour and may continue over the engraved background beyond it. EVERYWHERE
the subject does NOT stand the template must be reproduced PIXEL-IDENTICAL:
do not repaint, recolor, restyle, sharpen or "improve" the cream paper, the
outer border, any ornament or the corner shield plaques — and the subject
must never touch the corner shields or the card's outer border."""


# Blokada palety i charakteru rysunku — doklejana do KAŻDEGO promptu
# generującego przód karty, niezależnie od edytowalnych presetów stylu.
# Bez niej model dobiera inny odcień czerwieni/kremu na każdej karcie.
# UWAGA: paleta dotyczy WYŁĄCZNIE nowo malowanej treści — sformułowana jako
# ograniczenie, nie instrukcja przemalowania istniejących elementów karty
# (poprzednia wersja „symbol frame, ornaments, inner backdrop: exactly #hex"
# prowokowała model do redrawu tła). Funkcja (nie stała): czerwień/czerń
# pochodzą z aktywnego presetu „wartosci" (mutowalny w runtime).
def style_lock() -> str:
    from app.core import compositor
    styl = compositor.styl_z_presetu()
    # Technika rysunku spójna z poziomem kreskówki: przy poziomie 5 twarde
    # cell-shading jak dotąd; niżej zostaje tylko wymóg JEDNEJ spójnej
    # techniki (samą technikę definiuje cartoon_level_clause) — inaczej ten
    # blok wymuszałby płaskie plamy wbrew wybranemu realizmowi.
    if style_store.cartoon_level() >= 5:
        technika = ("flat cell-shaded color planes, medium saturation, "
                    "uniform black outline weight")
    else:
        technika = ("one consistent rendering technique and saturation "
                    "(follow the STYLIZATION LEVEL instructions)")
    return f"""\
MANDATORY DECK CONSISTENCY (identical on EVERY card of this deck):
- Any NEWLY painted content (the subject illustration and its immediate
  backdrop only) must keep to the fixed deck palette: cream {config.CREAM_HEX},
  dark red {styl.kolor_czerwony} for hearts/diamonds, deep black
  {styl.kolor_czarny} for spades/clubs. Never introduce other hues for card
  elements.
- Do NOT repaint existing card elements to match these colors — they already
  match; leave them exactly as they are.
- Subjects: {technika} — every card must look drawn by the same artist in one
  session (same palette, same line weight, same shading).
- The corner shield plaques must stay completely EMPTY — no letters, numbers
  or pips in them."""


# Wierność twarzy — doklejana do OBU promptów kart (nadrzędna nad edytowalnym
# stylem postaci). Testy live: twarze zbyt zniekształcone, niepodobne do zdjęcia
# — agresywny cell-shading spłaszczał rysy. Twarze są WYJĄTKIEM od płaskiego
# cieniowania: renderowane miękko i z detalem, reszta ilustracji zostaje
# stylizowana. Priorytet nad instrukcjami stylu, dlatego doklejane osobno.
FACE_FIDELITY = """\
FACE LIKENESS (highest priority): treat this as a PORTRAIT-likeness task. Each
person's face must be an accurate likeness of the SAME person in the reference
photo — keep the exact face shape, eye shape and spacing, nose, mouth, jawline,
eyebrows, facial hair and skin tone, so a viewer instantly recognizes that
specific individual. Render FACES with soft, smooth shading and enough fine
detail for a true likeness — faces are the EXCEPTION to the flat cell-shading:
never reduce a face to a few flat color blocks, never caricature, "beautify",
change age or alter proportions. Clothing, props and background may stay
cell-shaded."""


def face_fidelity_clause() -> str:
    return FACE_FIDELITY


# Klauzula siły poprawki (suwak „Siła poprawki" 1-5 w FixRegionDialog):
# 1-2 = zachowawczy retusz (zmień jak najmniej), 3 = brak klauzuli (status
# quo), 4-5 = wolna ręka w masce. Uzupełnia temperaturę wywołania
# (generator._FIX_TEMPERATURA) — prompt jest pewniejszą dźwignią.
_FIX_SILA = {
    1: """\
CHANGE STRENGTH: minimal touch-up — change as FEW pixels as possible inside
the masked region; preserve the existing composition, lines, colors and
shapes, and only fix the exact defect described above.""",
    2: """\
CHANGE STRENGTH: conservative — keep the existing composition and colors of
the masked region; adjust only what is necessary to fix the defect described
above.""",
    4: """\
CHANGE STRENGTH: strong — you may noticeably rework the masked region
(shapes, shading, details) as long as it satisfies the instruction and stays
consistent with the surrounding artwork.""",
    5: """\
CHANGE STRENGTH: free repaint — you may repaint the masked region from
scratch to best satisfy the instruction, keeping only the style, palette and
line weight of the surrounding artwork.""",
}


def fix_region_prompt(user_prompt: str, sila: int = 3) -> str:
    """Prompt korekcyjnego inpaintingu (lightbox → „Popraw selektywnie"):
    model dostaje kartę + maskę (drugi obraz, biały obszar = region do
    przerysowania) i instrukcję użytkownika DOSŁOWNIE; sila (1-5) dokleja
    klauzulę zachowawczości/swobody zmian. Twardą gwarancję nienaruszalności
    reszty karty daje generator (composite po masce + klamp), prompt jest
    tylko wsparciem."""
    sila_clause = _FIX_SILA.get(sila, "")
    return f"""\
You are given TWO images: (1) a playing-card illustration, (2) a MASK — the
WHITE area of the mask marks the ONLY region of the card you may repaint.
Redraw the card with the masked region corrected.

Required style: precise, multi-color vector-style illustration, cell-shaded,
consistent with the rest of the card.
{style_lock()}

Modification instruction for the masked region:
{user_prompt.strip()}

{sila_clause}

IMPORTANT: Focus exclusively on repairing the masked region according to the
instruction, blending seamlessly with the style, palette, lighting and line
weight of the surrounding artwork. Everything OUTSIDE the white mask area must
remain pixel-identical to the first image.

{NO_TEXT_SUFFIX}"""


# Poziom przeróbki zdjęcia na kreskówkę (suwak na Ekranie roboczym, pole
# postac/poziom_kreskowki): 5 = pełna kreskówka — BRAK klauzuli (pełny styl
# presetu postaci, status quo); 4→1 stopniowo łagodzą stylizację ubrań,
# rekwizytów i tła w stronę fotorealizmu. Twarze ZAWSZE pod nadrzędną
# face_fidelity_clause — klauzula nie dotyka rysów.
_CARTOON_LEVELS = {
    4: """\
STYLIZATION LEVEL 4/5 (softened cartoon) — this OVERRIDES the rendering
technique in the subject style above (faces still follow FACE LIKENESS):
keep clean outlines, but soften the cell-shading — allow gentle gradients
and more color variation in clothing, props and the backdrop.""",
    3: """\
STYLIZATION LEVEL 3/5 (semi-realistic) — this OVERRIDES the rendering
technique in the subject style above (faces still follow FACE LIKENESS):
halfway between comic and photo — soft painterly light, thinner and less
prominent outlines, natural color transitions in clothing, props and the
backdrop instead of flat color planes.""",
    2: """\
STYLIZATION LEVEL 2/5 (painterly realism) — this OVERRIDES the rendering
technique in the subject style above (faces still follow FACE LIKENESS):
render clothing, props and the backdrop with realistic materials, soft
natural lighting and NO visible comic outlines — a detailed digital
painting, clearly not a cartoon.""",
    1: """\
STYLIZATION LEVEL 1/5 (near-photorealistic) — this OVERRIDES the rendering
technique in the subject style above (faces still follow FACE LIKENESS):
keep the subjects almost photographic — realistic skin, fabrics and
lighting with only the slightest illustrative cleanup; absolutely no comic
outlines and no flat color planes.""",
}


def cartoon_level_clause() -> str:
    """Klauzula poziomu kreskówki — pusty string przy poziomie 5 (pełna
    kreskówka = styl presetu bez modyfikacji)."""
    return _CARTOON_LEVELS.get(style_store.cartoon_level(), "")

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
    return (style_store.character_style().rstrip()
            + "\n" + _CHARACTER_REQUIREMENTS
            + "\n" + style_lock())


def template_style() -> str:
    return style_store.template_style()


# Nota o zdjęciu-referencji (tryb pop-out): w kolażu twarze są małe, więc
# model karykaturyzował rysy — osobne, pełnowymiarowe zdjęcie przywraca
# proporcje. Zdjęcie jest DRUGIM obrazem contents. liczba_osob (z cache
# analizy auto-przydziału; None = nieznana) wzmacnia instrukcję — przy
# grupach 4+ model gubił i zlewał osoby.
def photo_ref_note(liczba_osob: int | None = None) -> str:
    count = ""
    if liczba_osob and liczba_osob > 1:
        count = (f"\nThe photo shows exactly {liczba_osob} people — the"
                 f" illustration must contain exactly {liczba_osob} people.")
    return f"""\
PHOTO REFERENCE: the SECOND attached image is the ORIGINAL photo of the
subjects. Take the facial features, face shapes, hairstyles, expressions and
body proportions from THIS photo — the small photo inside the card collage
defines only the placement and crop. Draw EVERY person from the photo: the
same number of people, each with their own recognizable face and hairstyle —
never merge, drop or invent people. Every face must be FULLY visible: never
cropped by the suit frame, the window edge or the card border. Each drawn
person must look like the
corresponding person in this photo, with correct, undistorted proportions.
Also reproduce faithfully any distinctive object the people hold or interact
with (a boat with its sail, a sign, a bike, an instrument, a pet).{count}"""


# Twarda klauzula koloru i geometrii symbolu — doklejana do promptów OBU
# trybów kart. Naprawia dwie wady z testów live: (1) model wstawiał kolor
# PRZECIWNEGO koloru karty do okna (czarny na kierze), bo prompt nie znał
# koloru karty, a zdjęcie w kolażu zakrywało wypełnienie; (2) model
# przerysowywał WŁASNY, większy symbol. Funkcja (nie stała): hex pochodzi
# z aktywnego presetu „wartosci" (mutowalny w runtime).
def suit_fill_clause(suit) -> str:
    from app.core import compositor
    styl = compositor.styl_z_presetu()
    shape = SUIT_NAME_EN[suit.nazwa]
    if suit.is_red:
        fill = f"dark red (EXACTLY {styl.kolor_czerwony})"
        other = "black"
    else:
        fill = f"deep black (EXACTLY {styl.kolor_czarny})"
        other = "red"
    # W trybie scenerii wnętrze okna za postacią może zawierać uproszczone tło
    # w odcieniach koloru karty — łagodzimy „tylko postać zakrywa symbol"
    # (kolor/rozmiar/kształt/pozycja symbolu nadal twarde)
    cover = ("besides the subject, only a simplified backdrop painted in shades"
             " of this same suit color may sit inside the window behind the"
             " subject — nothing else"
             if style_store.scenery_suit_mode() else
             "the ONLY thing allowed to cover the symbol is the subject")
    return f"""\
THIS CARD'S SUIT (hard constraint): this is a {shape.upper()} card. The
central symbol's flat fill color is {fill} — NEVER swap it for the deck's
{other} or any other hue. The symbol's SIZE, SHAPE and POSITION are FINAL,
exactly as shown in the input image: never enlarge, shrink, move or redraw
it, and never spill its fill color beyond the frame contour — {cover}."""


def _window_backdrop_clause(suit) -> str:
    """Zawartość okna ZA postacią: płaskie wypełnienie (domyślnie) albo — gdy
    włączony tryb scenerii (style_store.scenery_suit_mode) — uproszczona
    sceneria zdjęcia malowana WYŁĄCZNIE w odcieniach koloru karty. Doklejane
    do promptów OBU trybów kart. Wnętrze okna to rdzeń bezwarunkowy klampu
    (masks.maska_klampu), więc ta treść przeżywa kompozycję bez zmian w klampie.
    Funkcja (nie stała): hex koloru z aktywnego presetu „wartosci"."""
    from app.core import compositor
    styl = compositor.styl_z_presetu()
    shape = SUIT_NAME_EN[suit.nazwa]
    hex_fill = styl.kolor_czerwony if suit.is_red else styl.kolor_czarny
    if style_store.scenery_suit_mode():
        return f"""\
WINDOW BACKDROP — SUIT-COLOR BACKGROUND: behind the subject, INSIDE the {shape}
window, PAINT the photo's BACKGROUND and surroundings — the setting, scenery,
room, objects and context behind the people, not just the people — as a
simplified backdrop that FILLS the window (it must NOT stay a flat empty color).
Render this backdrop ENTIRELY in shades of the suit color: the main shapes
EXACTLY the fill color {hex_fill}, shadows a darker shade of that SAME hue,
highlights a lighter shade, and NO other colors at all. Keep it low-detail and
low-contrast so the {shape} symbol stays clearly recognizable. The subject stays
in FULL natural color on top of it. Do NOT reproduce the background in its
natural photographic colors, and never let it spill outside the window onto the
frame or the card — outside the window the template is reproduced exactly."""
    return f"""\
WINDOW BACKDROP — FLAT FILL: the flat suit-color fill ({hex_fill}) is the ONLY
backdrop inside the {shape} window; the subject (in full color) stands directly
on the clean, flat fill, which must stay visible around the subject. NEVER
paint the photo's scenery — sky, water, grass, ground, floor, walls, interiors
— anywhere on the card, inside or outside the window. Scenery is NOT part of
the subject."""


def _full_card_size_clause(liczba_osob: int | None) -> str:
    """Punkt kompozycji FULL_AI: pojedyncze osoby → duży kadr popiersia;
    grupy 3+ → grupa wypełnia SZEROKOŚĆ okna, każda twarz rozpoznawalna
    (kadr popiersia dla grupy ścieśniał osoby i gubił twarze)."""
    if liczba_osob is not None and liczba_osob >= 3:
        return f"""\
The GROUP must be LARGE: together the people fill about 90-95% of the
   window's width, arranged so that EVERY face is clearly visible and
   recognizable — never a small group floating in the middle of the window
   with wide margins around it, and no one standing out on the frame or on
   the card away from the window."""
    return """\
The subject must be LARGE: about
   90-95% of the window's height (bust/portrait crop), the head close to the
   top of the window or slightly overlapping its notch — never a small figure
   floating in the middle of the window with wide margins around it, and never
   standing out on the frame or on the card away from the window."""


def full_card_prompt(suit, liczba_osob: int | None = None) -> str:
    """Prompt trybu FULL_AI — kompozycja POP-OUT (jak tryb hybrydowy):
    postać narzucona na symbol może przekraczać kontur ramy i wchodzić na
    tło karty (poprzednia wersja tłoczyła postać W oknie — źródło ucinanych
    twarzy), a symbol (rozmiar/kształt/pozycja/kolor) jest FINALNY — szablon
    idzie do modelu z oknem już wypełnionym kolorem karty (generator).
    liczba_osob (z cache analizy auto-przydziału, None = nieznana) przełącza
    klauzulę kompozycji na wariant grupowy i dokleja twardą liczbę osób."""
    shape = SUIT_NAME_EN[suit.nazwa]
    cartoon = cartoon_level_clause()
    cartoon_block = (cartoon + "\n\n") if cartoon else ""
    count = ""
    if liczba_osob and liczba_osob > 1:
        count = (f" The photo shows exactly {liczba_osob} people — the"
                 f" illustration must contain exactly {liczba_osob} people,"
                 " each with their own recognizable face and the whole head"
                 " visible (no face may be cropped); never merge, drop"
                 " or invent people.")
    return f"""\
The first image is a playing-card template in this style:
{style_store.template_style().rstrip()}
The central element is an ornate, bold {shape}-shaped frame whose interior
is ALREADY filled with the final flat suit color.
Keep the exact resolution of the template image.

Task — bold 3D pop-out ("out of bounds") composition:
1. Take the people from the second image (the photo) AND any distinctive
   object they hold or interact with (a boat with its sail, a sign, a bike,
   an instrument, a pet) and repaint them in this exact style:
{style_store.character_style().rstrip()}{count}
2. Place that illustration standing INSIDE the central {shape} window,
   strictly vertical, filling the window; wherever the people do not stand
   inside the window, the window backdrop (described below) must show.
3. The subject FILLS the {shape} window. It may lightly step out: where
   they meet, the frame's contour passes BEHIND the subject's body, and a
   head, shoulder or held prop may cross the window's edge into the narrow
   band right next to it. But the subject must STAY at the window — it must
   NOT walk out onto the open engraved frame, and no person may stand on the
   ornament or on the card away from the window. EVERY face must be FULLY
   visible — never cropped by the frame, the window edge or the card border;
   if the subject does not fit, crop it a little at the bottom rather than
   scattering people onto the frame. Keep a clear empty margin from the
   card's outer border and never touch the corner shield plaques.
   {_full_card_size_clause(liczba_osob)}
4. The suit symbol must stay recognizable — the subject crosses the frame
   but never covers the window completely.

{_window_backdrop_clause(suit)}

{suit_fill_clause(suit)}

{cartoon_block}\
{style_lock()}

{face_fidelity_clause()}

{TEMPLATE_GUARD_POPOUT}

{NO_TEXT_SUFFIX}
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


def _front_ornament(suit) -> str:
    """Kolor ornamentu centralnej ramy wg koloru karty (paleta z presetu
    „wartosci" — jedna paleta dla AI-ornamentów i stemplowanych narożników)."""
    from app.core import compositor
    styl = compositor.styl_z_presetu()
    return (f"saturated dark red (exactly {styl.kolor_czerwony})" if suit.is_red
            else f"deep black (exactly {styl.kolor_czarny})")


def front_layout_suffix(suit) -> str:
    """Twarde wymogi layoutu tła przodu — doklejane do edytowalnego promptu
    bazowego (poza trybem własnym): centralna rama w kształcie symbolu KOLORU
    karty (kier → serce, pik → wino itd.) oraz puste tarcze na wartości
    WYŁĄCZNIE w lewym górnym i prawym dolnym rogu (wartości A/K/10 i pipy
    stempluje potem compositor, nie AI) + zakaz tekstu."""
    shape = SUIT_NAME_EN[suit.nazwa]
    return f"""\
Mandatory layout for this {shape} card:
- The central blank cream window MUST be shaped as ONE large, ornate {shape}
  symbol with a bold {_front_ornament(suit)} contour; the INTERIOR of the
  {shape} stays a completely EMPTY, flat cream (exactly {config.CREAM_HEX})
  area (an illustration will be pasted there later).
- Exactly TWO empty shield-shaped plaques for the corner indices: one in the
  TOP-LEFT corner and one in the BOTTOM-RIGHT corner (flat cream interiors —
  the card value like A, K or 10 and the {shape} pip are stamped there later
  by the program). NO plaques, pips or suit symbols in the other two corners
  or anywhere else on the card.

{NO_TEXT_SUFFIX}"""


def front_background_prompt(suit, base: str | None = None) -> str:
    """Pełny prompt POJEDYNCZEGO tła przodu: edytowalna baza per kolor
    (czerwone → front_red, czarne → front_black; `base` pozwala podać tekst
    z edytora GUI) + twardy layout (kształt symbolu koloru, tarcze TL/BR,
    zakaz tekstu). Tryb własny presetu → baza idzie do modelu DOSŁOWNIE."""
    base = (base or style_store.front_prompt(suit.is_red)).rstrip()
    if style_store.front_custom_mode():
        return base
    return base + "\n\n" + front_layout_suffix(suit)


def front_set_prompt(suit, with_reference: bool) -> str:
    """Prompt tła w trybie KOMPLETU (4 kolory jednym stylem): edytowalna baza
    per czerwone/czarne + przy referencji instrukcja dopasowania do INNEGO
    koloru tego samego zestawu + twardy layout (kształt symbolu, tarcze TL/BR,
    zakaz tekstu). Tryb własny presetu → bez dopisków layoutu, przy referencji
    zostaje tylko krótka informacja, że załączony obraz to inna karta zestawu."""
    custom = style_store.front_custom_mode()
    prompt = style_store.front_prompt(suit.is_red).rstrip()
    if with_reference:
        if custom:
            prompt += (
                "\nThe attached reference image is ANOTHER CARD of the SAME"
                " deck set — reproduce its style, palette and composition"
                " EXACTLY."
            )
        else:
            shape = SUIT_NAME_EN[suit.nazwa]
            prompt += (
                "\nThe attached reference image is ANOTHER SUIT of the SAME"
                " deck set — reproduce its engraving style, border layout,"
                " palette, line weight and composition EXACTLY; change ONLY"
                f" the central symbol shape (to a {shape}) and the ornament"
                f" color (to {_front_ornament(suit)})."
            )
    if custom:
        return prompt
    return prompt + "\n\n" + front_layout_suffix(suit)


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
  EMPTY, flat cream (exactly {config.CREAM_HEX}) area (an illustration will
  be pasted there later).
- Exactly TWO empty shield-shaped plaques: one in the TOP-LEFT corner, one in
  the BOTTOM-RIGHT corner (flat cream interiors — the card value and suit pip
  are stamped there later by the program). NO plaques, pips or suit symbols
  in the other two corners.

{NO_TEXT_SUFFIX}
"""


# --- Pop-out ("out of bounds") -------------------------------------------------
# Główny prompt trybu pop-out: postać MUSI wychodzić poza centralną ramę
# symbolu. Model dostaje kolaż (szablon + CAŁE zdjęcie położone prostokątem
# na karcie) jako init_image — prostokąt fotografii to tymczasowe rusztowanie:
# model ma wyciąć z niego postać, ODTWORZYĆ pod nim tło karty i narysować
# postać wychodzącą z okna symbolu śmiało na kartę (twardy klamp adaptacyjny
# przywraca szablon wszędzie tam, gdzie postaci nie ma). Restrykcje szablonu
# żyją wyłącznie w TEMPLATE_GUARD_POPOUT (bez dublowania tutaj).

DEFAULT_POPOUT_PROMPT = """\
Transform the subject from the photo into a highly detailed, colorful
vector illustration (cell-shaded, clean black outlines) that blends
perfectly with the existing playing card design.

The SUBJECT means the people from the photo AND any distinctive object they
hold, ride or interact with (a boat with its sail, a sign, a bike, an
instrument, a pet) — repaint those objects in the same illustration style;
they belong to the subject and may cross the frame with it. Do NOT reduce
the subject to the people alone.

IMPORTANT — the input collage is NOT the target composition: the whole
photo was pasted onto the card as a plain rectangle. That rectangle is
temporary scaffolding. Extract ONLY the subject from it, DELETE the photo's
own rectangular background completely, and repaint the card background
(cream paper, engraved ornaments, suit frame) exactly as the template looks
wherever the photo rectangle covered it and the subject does not stand.

The suit symbol's colored fill visible in the collage is ALREADY FINAL:
reproduce its shape, size and position exactly — do not redraw the symbol,
do not change its contour, and never bleed the fill over the ornate frame.
Props the subject holds, rides or wears (a bike, skis, a mast, a mask,
handlebars) ARE part of the subject and stay in full color. The backdrop
inside the window (behind the subject) is defined separately below.

MAIN GOAL — the subject FILLS the suit-symbol window, with a light 3D
pop-out at its edge:
- The subject stands INSIDE the suit-symbol window and fills it; where the
  body meets the window edge, the frame's contour passes BEHIND the body.
- A head, shoulder, elbow, hand or held prop may lightly cross the window's
  contour into the NARROW band right next to it — but the subject must STAY
  at the window. Do NOT let anyone reach out onto the open engraved frame,
  and NO person may stand on the ornament or on the card away from the
  window. Keep a clear EMPTY margin from the card's outer border and never
  touch the corner shield plaques.
- Fill the window: no small subject floating in the middle with a wide empty
  flat-fill margin around it, and no people scattered onto the frame.
- EVERY person from the photo must fit in the picture with their WHOLE head
  visible: no face may be cropped by the frame, the window edge or the
  card edge.
- The suit symbol must stay recognizable: the subject fills the window but
  never covers it completely.
- Never treat the frame as a porthole or a clipping window — do not crop,
  fade or cut the subject at the frame edge, and never leave any straight
  photo edge visible.
Match the lighting and maintain the pristine, neo-ornamental vintage style
of the card."""

# Przypomnienie na SAM KONIEC promptu pop-out (tuż przed NO_TEXT_SUFFIX):
# model czyta restrykcje (guard + zakaz tekstu) jako ostatnie i instrukcja
# pop-out z początku promptu ginie — krótka repryza przywraca jej wagę.
# Funkcja (nie stała): środkowe zdanie o tle okna zależy od trybu scenerii.
def popout_reminder() -> str:
    if style_store.scenery_suit_mode():
        backdrop = ("Equally WRONG: any leftover straight photo edge, or the"
                    " scenery in its natural photographic colors — inside the"
                    " window the backdrop is a simplified scenery painted ONLY"
                    " in shades of the suit color, everywhere else the card's"
                    " own background.")
    else:
        backdrop = ("Equally WRONG: any leftover straight photo edge or photo"
                    " scenery (sky, water, grass, ground) — inside the window"
                    " the flat suit-color fill must show around the subject,"
                    " everywhere else the card's own background.")
    return f"""\
FINAL CHECK — MOST IMPORTANT: the subject must FILL the suit window, with a
head/shoulder/prop lightly crossing the window's edge into the band right
next to it. WRONG: a subject or person standing out on the ornate frame or
on the card away from the window (they must stay at the window). WRONG: a
small subject floating in the middle of the window with a wide empty
flat-fill margin around it. {backdrop} Also WRONG: any face cropped or
missing, or anything touching the card's outer border."""


def popout_prompt(suit, photo_ref: bool = False,
                  liczba_osob: int | None = None) -> str:
    """Prompt pop-out: instrukcje mechaniki + twardy kolor/geometria symbolu
    (suit_fill_clause — model nie zna koloru karty z kolażu, bo zdjęcie
    zakrywa wypełnienie okna) + wybrany preset stylu postaci (Ustawienia
    i style) jako doprecyzowanie wyglądu. photo_ref=True dokleja notę
    o oryginalnym zdjęciu (drugi załączony obraz — wierność twarzy
    i rekwizytów); liczba_osob wzmacnia notę twardą liczbą osób."""
    photo_note = ("\n\n" + photo_ref_note(liczba_osob)) if photo_ref else ""
    cartoon = cartoon_level_clause()
    return (DEFAULT_POPOUT_PROMPT
            + "\n\n" + _window_backdrop_clause(suit)
            + "\n\n" + suit_fill_clause(suit)
            + "\n\nSubject style details:\n"
            + style_store.character_style().strip()
            + (("\n\n" + cartoon) if cartoon else "")
            + "\n\n" + style_lock()
            + photo_note
            + "\n\n" + face_fidelity_clause()
            + "\n\n" + TEMPLATE_GUARD_POPOUT
            + "\n\n" + popout_reminder()
            + "\n\n" + NO_TEXT_SUFFIX)


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
    (symetria 180°, bordiura, bez tekstu). Orientacja steruje proporcjami.
    Tryb własny presetu rewersu → opis idzie do modelu DOSŁOWNIE."""
    if style_store.back_custom_mode():
        own = (custom_text or "").strip() or style_store.back_text().strip()
        if own:
            return own
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
