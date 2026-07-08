"""Składanie karty: kolaż init_image pod pop-out, wartości w rogach,
klasyczna kompozycja w masce (fallback) i zapis z DPI.

Szablon poza maską pozostaje pixel-perfect nienaruszony. ZASADA NADRZĘDNA:
AI nie rysuje tekstu — wartości i symbole narożne stempluje deterministycznie
stempluj_narozniki() PO odpowiedzi API, wg aktywnego presetu „wartosci".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app import config
from app.core import masks, style_store
from app.core.models import CardSpec, Suit

# Domyślna transformacja kadru (GUI: suwaki Zoom/X/Y)
DEFAULT_TRANSFORM = {"zoom": 1.0, "dx": 0.0, "dy": 0.0}

# Cache przeskalowanych szablonów/masek dla szybkiego podglądu w GUI
_scaled_cache: dict[tuple, tuple[Image.Image, Image.Image, tuple]] = {}

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


def _liczba(field: str, default: float) -> float:
    try:
        return float(style_store.text("wartosci", field).strip().replace(",", "."))
    except ValueError:
        return default


def _kolor(field: str, default: str) -> str:
    v = style_store.text("wartosci", field).strip()
    return v if re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


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
    )


def _corner_tile(box: tuple[int, int, int, int], spec: CardSpec,
                 styl: StylNaroznika) -> Image.Image:
    """Tarcza narożna: wartość i pod nią symbol koloru, w pionie."""
    w, h = box[2] - box[0], box[3] - box[1]
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    color = styl.kolor_czerwony if spec.suit.is_red else styl.kolor_czarny
    font_path = styl.czcionka or config.find_serif_font()

    value_font = _fit_text_size(spec.value, font_path,
                                int(h * styl.rozmiar_wartosci / 100), int(w * 0.82))
    symbol_font = _font(config.find_symbol_font(), int(h * styl.rozmiar_symbolu / 100))

    cx = w / 2 + w * styl.offset_x / 100
    value_y = h * 0.30 + h * styl.offset_y / 100
    symbol_y = value_y + h * styl.odstep / 100
    draw.text((cx, value_y), spec.value, font=value_font, fill=color, anchor="mm")
    draw.text((cx, symbol_y), spec.suit.symbol, font=symbol_font, fill=color, anchor="mm")
    return tile


def stempluj_narozniki(obraz: Image.Image, spec: CardSpec,
                       styl: StylNaroznika | None = None,
                       tmasks: masks.TemplateMasks | None = None) -> Image.Image:
    """Deterministyczna warstwa narożników: wartość + symbol w obu tarczach
    (dolna obrócona o 180°, jak na kartach). Czysta funkcja — to samo wejście
    daje identyczne piksele. Jedyne miejsce rysujące tekst na karcie."""
    if styl is None:
        styl = styl_z_presetu()
    if tmasks is None:
        tmasks = masks.get_masks(spec.suit.template_path)
    card = obraz.convert("RGBA")
    tl_tile = _corner_tile(tmasks.tl_box, spec, styl)
    br_tile = _corner_tile(tmasks.br_box, spec, styl).rotate(180)
    card.alpha_composite(tl_tile, (tmasks.tl_box[0], tmasks.tl_box[1]))
    card.alpha_composite(br_tile, (tmasks.br_box[0], tmasks.br_box[1]))
    return card.convert("RGB")


def draw_corners(card: Image.Image, spec: CardSpec,
                 tmasks: masks.TemplateMasks | None = None) -> Image.Image:
    """Zgodność ze starym API — deleguje do stempluj_narozniki()."""
    return stempluj_narozniki(card, spec, tmasks=tmasks)


def wyczysc_tarcze(img: Image.Image, template: Image.Image,
                   tmasks: masks.TemplateMasks) -> Image.Image:
    """Reset narożników: wkleja piksele czystego szablonu w bboxy tarcz
    (model potrafi coś tam narysować mimo zakazu w promptcie)."""
    img = img.copy()
    for box in (tmasks.tl_box, tmasks.br_box):
        img.paste(template.crop(box), (box[0], box[1]))
    return img


def _scaled_assets(template_path: Path, max_side: int) \
        -> tuple[Image.Image, Image.Image, tuple[int, int, int, int]]:
    """(szablon, maska pop-out, bbox centrum) przeskalowane do max_side."""
    template_path = Path(template_path)
    key = (str(template_path), max_side, template_path.stat().st_mtime,
           masks.MASK_VERSION)
    if key in _scaled_cache:
        return _scaled_cache[key]
    template = Image.open(template_path).convert("RGB")
    popout = masks.get_popout_mask(template_path)
    center_bbox = masks.get_masks(template_path).center.getbbox()
    if center_bbox is None:
        raise RuntimeError(f"Pusta maska centrum: {template_path.name}")
    if max_side and max(template.size) > max_side:
        ratio = max_side / max(template.size)
        new_size = (round(template.width * ratio), round(template.height * ratio))
        template = template.resize(new_size, Image.Resampling.LANCZOS)
        # BILINEAR + doclipowanie: LANCZOS daje ringing (niezerowe piksele)
        # poza maską, a poza nią musi zostać czysta czerń
        popout = popout.resize(new_size, Image.Resampling.BILINEAR)
        popout = popout.point(lambda v: 0 if v < 8 else v)
        center_bbox = tuple(round(v * ratio) for v in center_bbox)
    _scaled_cache[key] = (template, popout, center_bbox)
    return _scaled_cache[key]


def build_init_image(suit: Suit, photo_path: Path,
                     transform: dict | None = None,
                     max_side: int = 0) -> Image.Image:
    """Kolaż startowy pod pop-out: szablon + zdjęcie wkadrowane przez
    użytkownika (Zoom/X/Y), widoczne wyłącznie w poszerzonej masce.

    Zdjęcie NIE jest przycinane do sztywnego środka — kadr ustawia
    użytkownik, a maska sięga ponad ramę symbolu. max_side > 0 daje
    szybki, pomniejszony kolaż (podgląd w GUI / upload do API).
    """
    t = {**DEFAULT_TRANSFORM, **(transform or {})}
    template, popout, bbox = _scaled_assets(suit.template_path, max_side)
    bx0, by0, bx1, by1 = bbox
    bw, bh = bx1 - bx0, by1 - by0

    # Docelowy prostokąt zdjęcia: centrum symbolu + przesunięcie użytkownika
    target_w = max(24, round(bw * t["zoom"]))
    target_h = max(24, round(bh * t["zoom"]))
    cx = (bx0 + bx1) / 2 + t["dx"] * bw
    cy = (by0 + by1) / 2 + t["dy"] * bh

    photo = Image.open(photo_path)
    photo = ImageOps.exif_transpose(photo).convert("RGB")
    fitted = ImageOps.fit(photo, (target_w, target_h),
                          method=Image.Resampling.LANCZOS)

    layer = template.copy()
    layer.paste(fitted, (round(cx - target_w / 2), round(cy - target_h / 2)))
    return Image.composite(layer, template, popout)


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
