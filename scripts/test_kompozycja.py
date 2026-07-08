"""Test offline (bez API): maski wszystkich szablonów, kompozycja próbnej karty
i asercje deterministycznego stemplowania narożników.

Uruchomienie: python -m scripts.test_kompozycja [sciezka_zdjecia]
Wynik trafia do katalogu podanego w zmiennej środowiskowej TEST_OUT (domyślnie output/).
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFont

from app import config
from app.core import compositor, masks
from app.core.models import CardSpec, Suit

out_dir = Path(os.environ.get("TEST_OUT", config.OUTPUT_DIR))
out_dir.mkdir(parents=True, exist_ok=True)

# 1. Maski wszystkich 4 szablonów + podglądy (czerwona nakładka = maska)
for suit in Suit:
    tpl = suit.template_path
    m = masks.get_masks(tpl)
    img = Image.open(tpl).convert("RGB")
    overlay = Image.new("RGB", img.size, (255, 0, 0))
    preview = Image.composite(overlay, img, m.center.point(lambda v: v // 2))
    d = preview.copy()
    from PIL import ImageDraw
    draw = ImageDraw.Draw(d)
    draw.rectangle(m.tl_box, outline=(0, 0, 255), width=8)
    draw.rectangle(m.br_box, outline=(0, 0, 255), width=8)
    d.thumbnail((600, 900))
    d.save(out_dir / f"maska_{suit.nazwa}.png")
    print(f"{suit.nazwa}: szablon={tpl.name}, maska bbox={m.center.getbbox()}, "
          f"tl={m.tl_box}, br={m.br_box}")

    # Maska pop-out (zielona nakładka): sylwetka symbolu + ring dylatacji,
    # zero prostokątów, czerń wszędzie indziej
    popout = masks.get_popout_mask(tpl)
    green = Image.new("RGB", img.size, (0, 200, 0))
    p = Image.composite(green, img, popout.point(lambda v: v // 2))
    p.thumbnail((600, 900))
    p.save(out_dir / f"maska_popout_{suit.nazwa}.png")
    dilate_px = round(img.width * 25 / 1500)
    print(f"  popout: bbox={popout.getbbox()}, ring~{max(20, min(30, dilate_px))}px")

    # ASERCJA (a): maska pop-out NIE obejmuje tarcz narożnych — inpainting
    # nigdy ich nie dotyka (narożniki stempluje wyłącznie compositor)
    for box in (m.tl_box, m.br_box):
        crop = popout.crop(box)
        assert crop.getbbox() is None, \
            f"{suit.nazwa}: maska pop-out wchodzi w tarczę {box}"

# 2. Kompozycja próbnej karty (surowe zdjęcie zamiast ilustracji AI)
photo = Path(sys.argv[1]) if len(sys.argv) > 1 else next(
    p for p in sorted(config.ZDJECIA_DIR.iterdir())
    if p.suffix.lower() in config.IMAGE_EXTS
)
for suit in (Suit.KIER, Suit.PIK):
    spec = CardSpec(value="K", suit=suit, photo_path=photo)
    card = compositor.compose_card(spec, Image.open(photo).convert("RGB"))
    small = card.copy()
    small.thumbnail((600, 900))
    small.save(out_dir / f"proba_K_{suit.nazwa}.png")
    print(f"Kompozycja K_{suit.nazwa}: OK, rozmiar={card.size}")

# 3. Asercje stemplowania narożników (zasada: AI nie rysuje tekstu)
for suit in (Suit.KIER, Suit.PIK):
    tpl = suit.template_path
    tmasks = masks.get_masks(tpl)
    template = Image.open(tpl).convert("RGB")
    spec = CardSpec(value="K", suit=suit)
    styl = compositor.styl_z_presetu()

    # (b) determinizm: dwa wywołania → identyczne piksele w tarczach
    a = compositor.stempluj_narozniki(template, spec, styl, tmasks)
    b = compositor.stempluj_narozniki(template, spec, styl, tmasks)
    for box in (tmasks.tl_box, tmasks.br_box):
        diff = ImageChops.difference(a.crop(box), b.crop(box))
        assert diff.getbbox() is None, \
            f"{suit.nazwa}: stemplowanie niedeterministyczne w tarczy {box}"

    # (c) identyczność narożników między dwiema RÓŻNYMI kartami tej samej
    # wartości i koloru (różne tło centrum nie może wpływać na tarcze)
    photo_card = compositor.compose_card(
        CardSpec(value="K", suit=suit, photo_path=photo),
        Image.open(photo).convert("RGB"),
    )
    for box in (tmasks.tl_box, tmasks.br_box):
        diff = ImageChops.difference(a.crop(box), photo_card.crop(box))
        assert diff.getbbox() is None, \
            f"{suit.nazwa}: narożnik {box} różni się między kartami tego samego koloru"
    print(f"Narożniki {suit.nazwa}: deterministyczne i identyczne między kartami")

# (d) font kart ma lining figures — „10" nie renderuje się jak „1o"
_font_path = config.find_serif_font()
_boxes = [ImageFont.truetype(str(_font_path), 64).getbbox(d) for d in "0123456789"]
_tops = [bx[1] for bx in _boxes]
_bottoms = [bx[3] for bx in _boxes]
assert max(_tops) - min(_tops) <= 5 and max(_bottoms) - min(_bottoms) <= 5, \
    f"font {_font_path.name} ma old-style figures (nierówne cyfry)"
print(f"Font kart: {_font_path.name} (lining figures OK)")
print("Test zakończony:", out_dir)
