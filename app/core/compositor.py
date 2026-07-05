"""Składanie karty: kolaż init_image pod pop-out, wartości w rogach,
klasyczna kompozycja w masce (fallback) i zapis z DPI.

Szablon poza maską pozostaje pixel-perfect nienaruszony; wartości narożne
zawsze rysujemy lokalnie (spójność: serif, pion, #801515).
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app import config
from app.core import masks
from app.core.models import CardSpec, Suit

# Domyślna transformacja kadru (GUI: suwaki Zoom/X/Y)
DEFAULT_TRANSFORM = {"zoom": 1.0, "dx": 0.0, "dy": 0.0}

# Cache przeskalowanych szablonów/masek dla szybkiego podglądu w GUI
_scaled_cache: dict[tuple, tuple[Image.Image, Image.Image, tuple]] = {}


def _font(path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _fit_text_size(text: str, font_path, start_size: int, max_width: int) -> ImageFont.FreeTypeFont:
    """Zmniejsza czcionkę, aż tekst zmieści się w zadanej szerokości (np. '10')."""
    size = start_size
    while size > 8:
        font = _font(font_path, size)
        if font.getbbox(text)[2] <= max_width:
            return font
        size -= 2
    return _font(font_path, 8)


def _corner_tile(box: tuple[int, int, int, int], spec: CardSpec) -> Image.Image:
    """Tarcza narożna: wartość i pod nią symbol koloru, w pionie, serif."""
    w, h = box[2] - box[0], box[3] - box[1]
    tile = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tile)
    color = spec.suit.value_color

    value_font = _fit_text_size(spec.value, config.find_serif_font(),
                                int(h * 0.40), int(w * 0.82))
    symbol_font = _font(config.find_symbol_font(), int(h * 0.32))

    draw.text((w / 2, h * 0.30), spec.value, font=value_font, fill=color, anchor="mm")
    draw.text((w / 2, h * 0.72), spec.suit.symbol, font=symbol_font, fill=color, anchor="mm")
    return tile


def draw_corners(card: Image.Image, spec: CardSpec,
                 tmasks: masks.TemplateMasks | None = None) -> Image.Image:
    """Wartości w narożnych tarczach (dolna obrócona o 180°, jak na kartach)."""
    if tmasks is None:
        tmasks = masks.get_masks(spec.suit.template_path)
    card = card.convert("RGBA")
    tl_tile = _corner_tile(tmasks.tl_box, spec)
    br_tile = _corner_tile(tmasks.br_box, spec).rotate(180)
    card.alpha_composite(tl_tile, (tmasks.tl_box[0], tmasks.tl_box[1]))
    card.alpha_composite(br_tile, (tmasks.br_box[0], tmasks.br_box[1]))
    return card.convert("RGB")


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


def compose_card(spec: CardSpec, illustration: Image.Image) -> Image.Image:
    template = Image.open(spec.suit.template_path).convert("RGB")
    tmasks = masks.get_masks(spec.suit.template_path)

    # 1. Ilustracja wklejona wyłącznie przez maskę centralnego symbolu
    bbox = tmasks.center.getbbox()
    if bbox is None:
        raise RuntimeError(f"Pusta maska centrum dla szablonu {spec.suit.template_path.name}")
    bw, bh = bbox[2] - bbox[0], bbox[3] - bbox[1]
    fitted = ImageOps.fit(illustration.convert("RGB"), (bw, bh),
                          method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
    layer = template.copy()
    layer.paste(fitted, (bbox[0], bbox[1]))
    card = Image.composite(layer, template, tmasks.center)

    # 2. Wartości w narożnych tarczach
    return draw_corners(card, spec, tmasks)


def save_card(card: Image.Image, spec: CardSpec, expected_size: tuple[int, int]) -> None:
    """Zapis z wymuszeniem rozdzielczości szablonu i DPI dla druku 63x88 mm."""
    if card.size != expected_size:
        card = card.resize(expected_size, Image.Resampling.LANCZOS)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    dpi = config.dpi_for_template(*expected_size)
    card.save(spec.output_path, "JPEG", quality=95,
              dpi=(round(dpi[0]), round(dpi[1])))
