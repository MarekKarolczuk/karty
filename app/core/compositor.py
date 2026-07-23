"""Składanie karty: kolaż init_image pod pop-out (całe zdjęcie na szablonie),
wartości w rogach, klasyczna kompozycja w masce (fallback) i zapis z DPI.

O nienaruszalność szablonu na FINALNEJ karcie dba klamp adaptacyjny
(generator._klamp_do_szablonu + masks.maska_klampu). ZASADA NADRZĘDNA:
AI nie rysuje tekstu — wartości i symbole narożne stempluje deterministycznie
stempluj_narozniki() PO odpowiedzi API, wg aktywnego presetu „wartosci".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app import config
from app.core import masks, style_store
from app.core.models import CardSpec, Suit

# Domyślna transformacja kadru (GUI: suwaki Zoom/X/Y). Zoom 1.1 (nie 1.0) —
# subiekt wypełnia ~110% bboxa okna, mniej pustego płaskiego tła dookoła
# (model zostawiał małą sylwetkę pływającą w wielkim oknie „Domyślnego").
# Umiarkowanie, żeby nie ciąć szeroko fitowanych grup; suwaki GUI nadpisują.
DEFAULT_TRANSFORM = {"zoom": 1.1, "dx": 0.0, "dy": 0.0}

# Cache przeskalowanych szablonów/bboxów dla szybkiego podglądu w GUI
_scaled_cache: dict[tuple, tuple[Image.Image, Image.Image, tuple, tuple]] = {}

# Cache załadowanych czcionek (stemplowanie 52+ kart bez ponownego I/O)
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(path, size: int) -> ImageFont.FreeTypeFont:
    key = (str(path), size)
    if key not in _font_cache:
        _font_cache[key] = ImageFont.truetype(str(path), size)
    return _font_cache[key]


def _fit_text_size(text: str, font_path, start_size: int, max_width: int) -> ImageFont.FreeTypeFont:
    """Zmniejsza czcionkę, aż tekst zmieści się w zadanej szerokości (np. '10')."""
    size = start_size
    while size > 8:
        font = _font(font_path, size)
        if font.getbbox(text)[2] <= max_width:
            return font
        size -= 2
    return _font(font_path, 8)


# --- Typografia narożników (preset „wartosci") ---------------------------------

@dataclass(frozen=True)
class StylNaroznika:
    """Styl stemplowania narożników. Rozmiary/offsety w % wysokości (szerokości
    dla offset_x) tarczy narożnej — stabilne między rozdzielczościami szablonów."""
    czcionka: str = ""                       # ścieżka .ttf; pusta = find_serif_font()
    rozmiar_wartosci: float = 40.0
    rozmiar_symbolu: float = 32.0
    kolor_czerwony: str = config.ACCENT_HEX
    kolor_czarny: str = config.BLACK_HEX
    offset_x: float = 0.0
    offset_y: float = 0.0
    odstep: float = 42.0                     # wartość↔symbol (domyślnie 30% → 72%)
    # efekty stempla (0/puste = brak — rendering identyczny jak dawniej)
    obwodka_grubosc: float = 0.0             # % wysokości tarczy
    obwodka_kolor: str = ""                  # pusty = config.CREAM_HEX
    cien_przesuniecie: float = 0.0           # % wysokości tarczy (prawo-dół)
    cien_kolor: str = ""                     # pusty = czerń (stała alpha)


def _liczba(field: str, default: float) -> float:
    try:
        return float(style_store.text("wartosci", field).strip().replace(",", "."))
    except ValueError:
        return default


def _kolor(field: str, default: str) -> str:
    v = style_store.text("wartosci", field).strip()
    return v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def _rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    """Hex #RRGGBB → krotka RGBA (do półprzezroczystego cienia)."""
    return (int(hex_color[1:3], 16), int(hex_color[3:5], 16),
            int(hex_color[5:7], 16), alpha)


def styl_z_presetu() -> StylNaroznika:
    """StylNaroznika z aktywnego presetu „wartosci" (błędne pola → defaulty)."""
    czcionka = style_store.text("wartosci", "czcionka").strip()
    if czcionka:
        p = Path(czcionka)
        if not p.is_absolute():
            p = style_store.preset_dir("wartosci") / czcionka
        czcionka = str(p) if p.exists() else ""
    d = StylNaroznika()
    return StylNaroznika(
        czcionka=czcionka,
        rozmiar_wartosci=_liczba("rozmiar_wartosci", d.rozmiar_wartosci),
        rozmiar_symbolu=_liczba("rozmiar_symbolu", d.rozmiar_symbolu),
        kolor_czerwony=_kolor("kolor_czerwony", d.kolor_czerwony),
        kolor_czarny=_kolor("kolor_czarny", d.kolor_czarny),
        offset_x=_liczba("offset_x", d.offset_x),
        offset_y=_liczba("offset_y", d.offset_y),
        odstep=_liczba("odstep", d.odstep),
        obwodka_grubosc=_liczba("obwodka_grubosc", d.obwodka_grubosc),
        obwodka_kolor=_kolor("obwodka_kolor", d.obwodka_kolor),
        cien_przesuniecie=_liczba("cien_przesuniecie", d.cien_przesuniecie),
        cien_kolor=_kolor("cien_kolor", d.cien_kolor),
    )


def _corner_tile(box: tuple[int, int, int, int], spec: CardSpec,
                 styl: StylNaroznika) -> Image.Image:
    """Tarcza narożna: wartość i pod nią symbol koloru, w pionie.
    Joker: litery J-O-K-E-R jedna pod drugą, bez symbolu."""
    w, h = box[2] - box[0], box[3] - box[1]
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    color = styl.kolor_czerwony if spec.suit.is_red else styl.kolor_czarny
    font_path = styl.czcionka or config.find_serif_font()

    if spec.suit.czy_joker:
        return _corner_tile_joker(tile, draw, spec, styl, color, font_path, w, h)

    value_font = _fit_text_size(spec.value, font_path,
                                int(h * styl.rozmiar_wartosci / 100), int(w * 0.82))
    symbol_font = _font(config.find_symbol_font(), int(h * styl.rozmiar_symbolu / 100))

    cx = w / 2 + w * styl.offset_x / 100
    value_y = h * 0.30 + h * styl.offset_y / 100
    symbol_y = value_y + h * styl.odstep / 100

    # cień pod tekstem (przesunięty w prawo-dół, bez obwódki)
    if styl.cien_przesuniecie > 0:
        off = h * styl.cien_przesuniecie / 100
        shadow = _rgba(styl.cien_kolor or "#000000", 110)
        draw.text((cx + off, value_y + off), spec.value, font=value_font,
                  fill=shadow, anchor="mm")
        draw.text((cx + off, symbol_y + off), spec.suit.symbol,
                  font=symbol_font, fill=shadow, anchor="mm")

    # obwódka (kontur) — stroke_width=0 renderuje identycznie jak dawniej
    stroke_w = round(h * styl.obwodka_grubosc / 100)
    stroke_fill = styl.obwodka_kolor or config.CREAM_HEX
    draw.text((cx, value_y), spec.value, font=value_font, fill=color,
              anchor="mm", stroke_width=stroke_w, stroke_fill=stroke_fill)
    draw.text((cx, symbol_y), spec.suit.symbol, font=symbol_font, fill=color,
              anchor="mm", stroke_width=stroke_w, stroke_fill=stroke_fill)
    return tile


def _corner_tile_joker(tile: Image.Image, draw: ImageDraw.ImageDraw,
                       spec: CardSpec, styl: StylNaroznika, color: str,
                       font_path, w: int, h: int) -> Image.Image:
    """Pionowy napis J-O-K-E-R w tarczy: litery rozłożone równomiernie
    w pasie 12–88% wysokości, rozmiar ograniczony krokiem między literami
    (5 liter zawsze się mieści niezależnie od presetu)."""
    litery = list(spec.value)
    y0, y1 = h * 0.12, h * 0.88
    krok = (y1 - y0) / max(1, len(litery) - 1)
    size = min(int(h * styl.rozmiar_wartosci / 100), int(krok * 0.95))
    font = _fit_text_size("W", font_path, max(10, size), int(w * 0.82))

    cx = w / 2 + w * styl.offset_x / 100
    stroke_w = round(h * styl.obwodka_grubosc / 100)
    stroke_fill = styl.obwodka_kolor or config.CREAM_HEX
    for i, litera in enumerate(litery):
        y = y0 + i * krok + h * styl.offset_y / 100
        if styl.cien_przesuniecie > 0:
            off = h * styl.cien_przesuniecie / 100
            shadow = _rgba(styl.cien_kolor or "#000000", 110)
            draw.text((cx + off, y + off), litera, font=font,
                      fill=shadow, anchor="mm")
        draw.text((cx, y), litera, font=font, fill=color, anchor="mm",
                  stroke_width=stroke_w, stroke_fill=stroke_fill)
    return tile


def stempluj_narozniki(obraz: Image.Image, spec: CardSpec,
                       styl: StylNaroznika | None = None,
                       tmasks: masks.TemplateMasks | None = None) -> Image.Image:
    """Deterministyczna warstwa narożników: wartość + symbol w obu tarczach
    (dolna obrócona o 180°, jak na kartach). Czysta funkcja — to samo wejście
    daje identyczne piksele. Jedyne miejsce rysujące tekst na karcie.

    Przed stemplem tarcze są twardo czyszczone wklejką z czystego szablonu —
    dla świeżych kart (po klampie tła) to no-op, ale stare raw z FULL_AI
    (z pipami dorysowanymi przez model) „Przestempluj narożniki" naprawia
    bez API."""
    if styl is None:
        styl = styl_z_presetu()
    if tmasks is None:
        tmasks = masks.get_masks(spec.suit.template_path)
    card = obraz.convert("RGBA")
    try:
        template = Image.open(spec.suit.template_path).convert("RGBA")
    except (FileNotFoundError, OSError):
        template = None
    if template is not None and template.size == card.size:
        for box in (tmasks.tl_box, tmasks.br_box):
            card.paste(template.crop(box), (box[0], box[1]))
    tl_tile = _corner_tile(tmasks.tl_box, spec, styl)
    br_tile = _corner_tile(tmasks.br_box, spec, styl).rotate(180)
    card.alpha_composite(tl_tile, (tmasks.tl_box[0], tmasks.tl_box[1]))
    card.alpha_composite(br_tile, (tmasks.br_box[0], tmasks.br_box[1]))
    return card.convert("RGB")


def draw_corners(card: Image.Image, spec: CardSpec,
                 tmasks: masks.TemplateMasks | None = None) -> Image.Image:
    """Zgodność ze starym API — deleguje do stempluj_narozniki()."""
    return stempluj_narozniki(card, spec, tmasks=tmasks)


def wypelnij_okno(template: Image.Image, suit: Suit) -> Image.Image:
    """Szablon z oknem symbolu wypełnionym płasko kolorem karty (czerwień
    kier/karo, czerń pik/trefl — z presetu „wartosci") po masce center_full:
    wypełnienie sięga konturu ramy (erodowana maska center zostawiała kremową
    szczelinę — „biały ślad" symbolu). Wspólne dla kolażu pop-out, wejścia
    FULL_AI i bazy klampu — model i klamp widzą ten sam, finalny symbol."""
    tmasks = masks.get_masks(suit.template_path)
    styl = styl_z_presetu()
    kolor = styl.kolor_czerwony if suit.is_red else styl.kolor_czarny
    fill = Image.new("RGB", template.size, kolor)
    center_full = tmasks.center_full
    if center_full.size != template.size:
        center_full = center_full.resize(template.size,
                                         Image.Resampling.BILINEAR)
    return Image.composite(fill, template, center_full)


# Kolor adnotacji regionu poprawki — magenta nie występuje w palecie talii,
# więc model jednoznacznie widzi zaznaczenie (prompt zakazuje malowania nim)
_ZAZNACZENIE_KOLOR = (255, 0, 204)
_ZAZNACZENIE_ALFA = 115   # ~45% — treść pod tintem pozostaje czytelna


def zaznacz_region_poprawki(crop: Image.Image,
                            maska: Image.Image) -> Image.Image:
    """Crop z regionem poprawki ZAZNACZONYM wizualnie (półprzezroczysty
    magenta tint + kontur) — drugi obraz dla gemini_client.edit_region
    i podgląd „co zobaczy model" w FixRegionDialog (jedno źródło = podgląd
    identyczny z rzeczywistością). maska — L, biały = region poprawki,
    rozmiar cropa."""
    import numpy as np
    import cv2
    tint = Image.new("RGB", crop.size, _ZAZNACZENIE_KOLOR)
    alfa = maska.point(lambda v: _ZAZNACZENIE_ALFA if v > 0 else 0)
    zaznaczony = Image.composite(tint, crop, alfa)
    # gruby kontur maski — twarda granica regionu widoczna mimo tintu
    m = np.asarray(maska, np.uint8)
    kontur = cv2.morphologyEx(np.where(m > 0, 255, 0).astype(np.uint8),
                              cv2.MORPH_GRADIENT, np.ones((5, 5), np.uint8))
    return Image.composite(tint, zaznaczony,
                           Image.fromarray(kontur).convert("L"))


def wyczysc_tarcze(img: Image.Image, template: Image.Image,
                   tmasks: masks.TemplateMasks) -> Image.Image:
    """Reset narożników: wkleja piksele czystego szablonu w bboxy tarcz
    (model potrafi coś tam narysować mimo zakazu w promptcie)."""
    img = img.copy()
    for box in (tmasks.tl_box, tmasks.br_box):
        img.paste(template.crop(box), (box[0], box[1]))
    return img


def _scaled_assets(template_path: Path, max_side: int) \
        -> tuple[Image.Image, Image.Image, tuple[int, int, int, int],
                 tuple[tuple[int, int, int, int], tuple[int, int, int, int]]]:
    """(szablon, maska okna center_full, bbox okna, bboxy tarcz TL/BR)
    przeskalowane do max_side. Maska okna BEZ erozji — wypełnienie kolorem
    symbolu ma sięgać konturu ramy (kremowa szczelina = „biały ślad")."""
    template_path = Path(template_path)
    key = (str(template_path), max_side, template_path.stat().st_mtime,
           masks.MASK_VERSION)
    if key in _scaled_cache:
        return _scaled_cache[key]
    template = Image.open(template_path).convert("RGB")
    tmasks = masks.get_masks(template_path)
    center = tmasks.center_full
    center_bbox = center.getbbox()
    if center_bbox is None:
        raise RuntimeError(f"Pusta maska centrum: {template_path.name}")
    shield_boxes = (tmasks.tl_box, tmasks.br_box)
    if max_side and max(template.size) > max_side:
        ratio = max_side / max(template.size)
        new_size = (round(template.width * ratio), round(template.height * ratio))
        template = template.resize(new_size, Image.Resampling.LANCZOS)
        # BILINEAR + doclipowanie: LANCZOS daje ringing (niezerowe piksele)
        # poza maską, a wypełnienie okna nie może wyjść poza kontur
        center = center.resize(new_size, Image.Resampling.BILINEAR)
        center = center.point(lambda v: 0 if v < 8 else v)
        center_bbox = tuple(round(v * ratio) for v in center_bbox)
        shield_boxes = tuple(tuple(round(v * ratio) for v in box)
                             for box in shield_boxes)
    _scaled_cache[key] = (template, center, center_bbox, shield_boxes)
    return _scaled_cache[key]


def build_init_image(suit: Suit, photo_path: Path,
                     transform: dict | None = None,
                     max_side: int = 0) -> Image.Image:
    """Kolaż startowy pod pop-out: szablon z oknem symbolu wypełnionym
    DETERMINISTYCZNIE kolorem tła (czerwień kier/karo, czerń pik/trefl —
    z presetu „wartosci"), a na tym CAŁE zdjęcie (prostokąt) bez docinania
    maską. Model widzi finalny kształt symbolu (nie wymyśla własnego serca)
    i postać narzuconą na kartę do przerysowania; tło poza sylwetką i tak
    wraca z szablonu przez klamp adaptacyjny. Na wierzch wracają wycinki
    szablonu w tarczach narożnych — model zawsze widzi czyste tarcze.

    Kadr (Zoom/X/Y) ustawia użytkownik względem bboxa symbolu, jak dotąd.
    max_side > 0 daje szybki, pomniejszony kolaż (podgląd w GUI / upload).
    """
    t = {**DEFAULT_TRANSFORM, **(transform or {})}
    template, center, bbox, shield_boxes = _scaled_assets(
        suit.template_path, max_side)
    bx0, by0, bx1, by1 = bbox
    bw, bh = bx1 - bx0, by1 - by0

    # Deterministyczne tło okna: kolor symbolu dokładnie po kontur okna
    # szablonu — identyczny kształt na każdej karcie
    styl = styl_z_presetu()
    kolor = styl.kolor_czerwony if suit.is_red else styl.kolor_czarny
    fill = Image.new("RGB", template.size, kolor)
    layer = Image.composite(fill, template, center)

    # Docelowy prostokąt zdjęcia: centrum symbolu + przesunięcie użytkownika.
    # Zoom < 1 świadomie zmniejsza postać poniżej okna (widać więcej sceny);
    # obsługę „mniejszy niż okno" robi gałąź scenerii niżej.
    target_w = max(24, round(bw * t["zoom"]))
    target_h = max(24, round(bh * t["zoom"]))
    cx = (bx0 + bx1) / 2 + t["dx"] * bw
    cy = (by0 + by1) / 2 + t["dy"] * bh

    photo = Image.open(photo_path)
    photo = ImageOps.exif_transpose(photo).convert("RGB")

    # Kadr MNIEJSZY niż okno (zoom < 1): zamiast płaskiego koloru + twardego
    # prostokąta wypełnij OKNO rozmytym tłem zdjęcia — model dostaje scenerię
    # do domalowania na cały symbol, a ostra postać wtapia się w nie przez
    # feather (żadnej twardej krawędzi prostokąta). Przy zoomie ≥ 1 zdjęcie
    # i tak pokrywa okno — ta gałąź się nie uruchamia (zero zmian dla status quo).
    mniejszy = target_w < bw or target_h < bh
    if mniejszy:
        tlo = ImageOps.fit(photo, (bw, bh), method=Image.Resampling.LANCZOS,
                           centering=(0.5, 0.42))
        tlo = tlo.filter(ImageFilter.GaussianBlur(max(6, round(bw * 0.05))))
        bg = layer.copy()
        bg.paste(tlo, (bx0, by0))
        layer = Image.composite(bg, layer, center)   # rozmyta scena tylko w oknie

    # centering (0.5, 0.42): przy prawie kwadratowym bboxie okna portret
    # (kadr pionowy) fitowany symetrycznie ucinał głowę — bias ku górze
    # trzyma twarze w kadrze (jak compose_card_raw)
    fitted = ImageOps.fit(photo, (target_w, target_h),
                          method=Image.Resampling.LANCZOS,
                          centering=(0.5, 0.42))
    poz = (round(cx - target_w / 2), round(cy - target_h / 2))
    if mniejszy:
        margines = max(4, round(min(target_w, target_h) * 0.10))
        alfa = Image.new("L", (target_w, target_h), 0)
        ImageDraw.Draw(alfa).rectangle(
            (margines, margines, target_w - margines, target_h - margines),
            fill=255)
        alfa = alfa.filter(ImageFilter.GaussianBlur(margines))
        layer.paste(fitted, poz, alfa)
    else:
        layer.paste(fitted, poz)
    for box in shield_boxes:
        layer.paste(template.crop(box), (box[0], box[1]))
    return layer


def montaz_portretow(paths, *, komorka: int = 460, maks: int = 12,
                     kolumny: int | None = None) -> Image.Image:
    """Siatka-montaż (contact sheet) portretów: JEDEN obraz zamiast kilkunastu
    osobnych referencji (lekki request do modelu, a twarze wciąż czytelne).
    Komórki z biasem ku górze (twarze), cienkie ramki i odstępy — model czyta
    odrębne osoby. Bierze pierwsze `maks` ścieżek."""
    import math

    obrazy: list[Image.Image] = []
    for p in list(paths)[:maks]:
        try:
            obrazy.append(ImageOps.exif_transpose(Image.open(p)).convert("RGB"))
        except (OSError, ValueError):
            continue
    if not obrazy:
        return Image.new("RGB", (komorka, komorka), config.CREAM_HEX)

    n = len(obrazy)
    kol = kolumny or max(1, math.ceil(math.sqrt(n)))
    wier = math.ceil(n / kol)
    kw = komorka
    kh = round(komorka * 1.15)          # komórka lekko pionowa (portrety)
    odstep = max(4, komorka // 40)
    plotno = Image.new("RGB",
                       (kol * kw + (kol + 1) * odstep,
                        wier * kh + (wier + 1) * odstep), config.CREAM_HEX)
    draw = ImageDraw.Draw(plotno)
    for i, im in enumerate(obrazy):
        r, c = divmod(i, kol)
        x = odstep + c * (kw + odstep)
        y = odstep + r * (kh + odstep)
        mini = ImageOps.fit(im, (kw, kh), method=Image.Resampling.LANCZOS,
                            centering=(0.5, 0.35))
        plotno.paste(mini, (x, y))
        draw.rectangle((x, y, x + kw - 1, y + kh - 1),
                       outline=(60, 60, 60), width=max(1, komorka // 115))
    return plotno


def compose_card_raw(spec: CardSpec, illustration: Image.Image) -> Image.Image:
    """Klasyczna kompozycja BEZ narożników: ilustracja wklejona wyłącznie
    przez maskę centralnego symbolu."""
    template = Image.open(spec.suit.template_path).convert("RGB")
    tmasks = masks.get_masks(spec.suit.template_path)
    bbox = tmasks.center.getbbox()
    if bbox is None:
        raise RuntimeError(f"Pusta maska centrum dla szablonu {spec.suit.template_path.name}")
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    fitted = ImageOps.fit(illustration.convert("RGB"), (bw, bh),
                          method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    layer = template.copy()
    layer.paste(fitted, (bbox[0], bbox[1]))
    return Image.composite(layer, template, tmasks.center)


def compose_card(spec: CardSpec, illustration: Image.Image) -> Image.Image:
    return stempluj_narozniki(compose_card_raw(spec, illustration), spec)


def save_raw(img: Image.Image, spec: CardSpec, expected_size: tuple[int, int]) -> None:
    """Surowe wyjście AI (bez narożników) do output/_raw/ — bezstratny PNG,
    źródło do przestemplowania narożników bez wywołań API."""
    if img.size != expected_size:
        img = img.resize(expected_size, Image.Resampling.LANCZOS)
    spec.raw_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(spec.raw_path, "PNG")


def save_card(card: Image.Image, spec: CardSpec, expected_size: tuple[int, int]) -> None:
    """Zapis z wymuszeniem rozdzielczości szablonu i DPI dla druku 63x88 mm."""
    if card.size != expected_size:
        card = card.resize(expected_size, Image.Resampling.LANCZOS)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dpi = config.dpi_for_template(*expected_size)
    card.save(spec.output_path, "JPEG", quality=95,
              dpi=(round(dpi[0]), round(dpi[1])))
