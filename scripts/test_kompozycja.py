"""Test offline (bez API): maski wszystkich szablonów, kompozycja próbnej karty
i asercje deterministycznego stemplowania narożników.

Uruchomienie: python -m scripts.test_kompozycja [sciezka_zdjecia]
Wynik trafia do katalogu podanego w zmiennej środowiskowej TEST_OUT (domyślnie output/).
"""
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

from app import config
from app.core import compositor, masks
from app.core.models import CardSpec, Suit

out_dir = Path(os.environ.get("TEST_OUT", config.OUTPUT_DIR))
out_dir.mkdir(parents=True, exist_ok=True)

# 1. Maski wszystkich 4 szablonów + podglądy (czerwona nakładka = maska)
for suit in Suit:
    if suit.czy_joker and not suit.available_templates():
        print(f"[pomijam] {suit.nazwa}: brak tła (opcjonalne)")
        continue
    tpl = suit.template_path
    m = masks.get_masks(tpl)
    img = Image.open(tpl).convert("RGB")
    overlay = Image.new("RGB", img.size, (255, 0, 0))
    preview = Image.composite(overlay, img, m.center.point(lambda v: v // 2))
    d = preview.copy()
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
    dilate_px = round(img.width * 80 / 1500)
    print(f"  popout: bbox={popout.getbbox()}, ring~{max(60, min(90, dilate_px))}px")

    # ASERCJA (a): maska pop-out NIE obejmuje tarcz narożnych — inpainting
    # nigdy ich nie dotyka (narożniki stempluje wyłącznie compositor)
    for box in (m.tl_box, m.br_box):
        crop = popout.crop(box)
        assert crop.getbbox() is None, \
            f"{suit.nazwa}: maska pop-out wchodzi w tarczę {box}"

    # ASERCJA (h): convex hull domyka wcięcie symbolu — dla kiera punkt w osi
    # środka tuż pod górną krawędzią bboxa symbolu (dawniej wcięcie serca = 0,
    # klamp ścinał głowy) musi leżeć w masce pop-out
    if suit is Suit.KIER:
        cb = m.center.getbbox()
        assert cb is not None, "kier: pusta maska centrum"
        cx_kier = (cb[0] + cb[2]) // 2
        y_kier = cb[1] + round(0.06 * (cb[3] - cb[1]))
        assert popout.getpixel((cx_kier, y_kier)) > 0, \
            "kier: wcięcie serca niedomknięte w masce pop-out"

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

# 2b. Kolaż pop-out: okno symbolu wypełnione DETERMINISTYCZNIE kolorem tła
# (czerwień kier / czerń pik z presetu „wartosci"), tarcze piksel-w-piksel
# z szablonu. Zoom 0.5 odsłania wypełnienie okna wokół prostokąta zdjęcia.
_styl = compositor.styl_z_presetu()


def _hex_rgb(h):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16))


for suit, oczekiwany in ((Suit.KIER, _hex_rgb(_styl.kolor_czerwony)),
                         (Suit.PIK, _hex_rgb(_styl.kolor_czarny))):
    tpl_img = Image.open(suit.template_path).convert("RGB")
    tm = masks.get_masks(suit.template_path)
    init = compositor.build_init_image(suit, photo, {"zoom": 0.5})
    cb = tm.center.getbbox()
    assert cb is not None
    bw_, bh_ = cb[2] - cb[0], cb[3] - cb[1]
    # punkt twardo w oknie (maska=255), a poza prostokątem zdjęcia (zoom 0.5
    # zajmuje środkowe 25-75% bboxa — sondy trzymają się lewych 6-18%)
    punkt = None
    for fy in (0.55, 0.45, 0.35, 0.65):
        for fx in (0.06, 0.10, 0.14, 0.18):
            x_probe = round(cb[0] + fx * bw_)
            y_probe = round(cb[1] + fy * bh_)
            if tm.center.getpixel((x_probe, y_probe)) == 255:
                punkt = (x_probe, y_probe)
                break
        if punkt is not None:
            break
    assert punkt is not None, f"{suit.nazwa}: nie znaleziono sondy w oknie"
    assert init.getpixel(punkt) == oczekiwany, \
        f"{suit.nazwa}: okno kolażu bez deterministycznego wypełnienia {punkt}"
    for box in (tm.tl_box, tm.br_box):
        d_t = ImageChops.difference(init.crop(box), tpl_img.crop(box))
        assert d_t.getbbox() is None, \
            f"{suit.nazwa}: tarcza {box} w kolażu różni się od szablonu"
    print(f"Kolaż {suit.nazwa}: wypełnienie okna {oczekiwany}, tarcze czyste")

# 2c. (t1) wypełnij_okno: fill sięga KONTURU ramy (center_full) — erodowana
# maska center zostawiała kremową szczelinę ~5 px („biały ślad" symbolu).
# Pierścień center_full−center musi być niepusty i w 100% w kolorze karty,
# a poza center_full baza == szablon piksel-w-piksel.
for suit, oczekiwany in ((Suit.KIER, _hex_rgb(_styl.kolor_czerwony)),
                         (Suit.PIK, _hex_rgb(_styl.kolor_czarny))):
    tpl_img = Image.open(suit.template_path).convert("RGB")
    tm = masks.get_masks(suit.template_path)
    baza = compositor.wypelnij_okno(tpl_img, suit)
    arr_full = np.array(tm.center_full, dtype=np.uint8) > 0
    arr_cen = np.array(tm.center, dtype=np.uint8) > 0
    ring = arr_full & ~arr_cen
    assert ring.any(), f"{suit.nazwa}: pusty pierścień center_full−center"
    arr_baza = np.asarray(baza)
    assert (arr_baza[ring] == np.array(oczekiwany, dtype=np.uint8)).all(), \
        f"{suit.nazwa}: wypełnienie okna nie sięga konturu (kremowa szczelina)"
    arr_tpl = np.asarray(tpl_img)
    assert (arr_baza[~arr_full] == arr_tpl[~arr_full]).all(), \
        f"{suit.nazwa}: wypelnij_okno zmieniło piksele poza oknem"
    print(f"(t1) {suit.nazwa}: fill sięga konturu, poza oknem szablon 1:1")

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

# 4. Klamp adaptacyjny v2 (generator._klamp_do_szablonu + masks.maska_klampu):
# rdzeń bezwarunkowy = OKNO symbolu (rama zawsze z szablonu — identyczny
# symbol na każdej karcie), sylwetka spójna z oknem przeżywa poza nim
# (otwarcie + filtr min. pola odsiewają przemalowaną ramę), tło, tarcze
# narożne i pas bordiury wracają piksel-w-piksel do szablonu. Hurtowe
# przemalowanie utrąca guardrail (degradacja do maski pop-out).
from app.core import generator

for suit in (Suit.KIER, Suit.PIK):
    tpl = suit.template_path
    template = Image.open(tpl).convert("RGB")
    popout = masks.get_popout_mask(tpl)
    _tm = masks.get_masks(tpl)
    center, center_full = _tm.center, _tm.center_full
    spec = CardSpec(value="K", suit=suit)
    black = Image.new("RGB", template.size, (0, 0, 0))
    pb = popout.getbbox()
    assert pb is not None, f"{suit.nazwa}: pusta maska pop-out"
    px0, py0, px1, py1 = pb
    cx = (px0 + px1) // 2
    # Od v8 baza klampu poza sylwetką to szablon z oknem wypełnionym kolorem
    # karty aż do konturu (center_full) — asercje „nic poza sylwetką się nie
    # zmieniło" wykluczają całe okno center_full, nie erodowany center
    bin_full = center_full.point(lambda v: 255 if v > 0 else 0)

    # (e) blob „postaci" nachodzący na okno i wystający ~200 px ponad ring
    # musi przetrwać klamp w całości (out-of-bounds bez limitu)
    blob = (cx - 140, py0 - 200, cx + 140, py0 + 300)
    fake_wynik = template.copy()
    ImageDraw.Draw(fake_wynik).ellipse(blob, fill=(0, 128, 255))
    clamped = generator._klamp_do_szablonu(fake_wynik, spec)
    assert clamped.getpixel((cx, py0 - 100)) == (0, 128, 255), \
        f"{suit.nazwa}: klamp ściął sylwetkę wystającą ponad ring"
    # poza sylwetką (margines na feather+domknięcie) i oknem: zero różnic
    # z szablonem
    exclusion = bin_full.copy()
    m140 = 140
    ImageDraw.Draw(exclusion).ellipse(
        (blob[0] - m140, blob[1] - m140, blob[2] + m140, blob[3] + m140),
        fill=255)
    diff = ImageChops.difference(clamped, template)
    outside = Image.composite(black, diff, exclusion)
    assert outside.getbbox() is None, \
        f"{suit.nazwa}: klamp przepuścił zmiany tła poza sylwetką"

    # (e2) „przemalowana rama": cienkie linie w paśmie ramy + mała plama przy
    # oknie → wszystko wraca do szablonu (otwarcie tnie linie, filtr min. pola
    # tnie plamę); wynik == szablon poza oknem. Plama skalowana do 0.7×
    # KLAMP_MIN_POLE (kontrakt v4: 0.0008 pola karty — mniejsze płaty
    # przemalowanej ramy giną, większe elementy to już rekwizyt, test (r))
    cb = center.getbbox()
    assert cb is not None
    fake_rama = template.copy()
    dr = ImageDraw.Draw(fake_rama)
    for off in (18, 36, 54):
        dr.line([(cb[0] - off, cb[1]), (cb[0] - off, cb[3])],
                fill=(0, 128, 255), width=3)
    _pole_plamy = 0.7 * masks.KLAMP_MIN_POLE * template.width * template.height
    _rx = max(8, round((2 * _pole_plamy / np.pi) ** 0.5))
    _ry = max(4, _rx // 2)
    _y_mid = (cb[1] + cb[3]) // 2
    dr.ellipse((cb[0] - _rx, _y_mid - _ry, cb[0] + _rx, _y_mid + _ry),
               fill=(0, 128, 255))
    clamped3 = generator._klamp_do_szablonu(fake_rama, spec)
    diff3 = ImageChops.difference(clamped3, template)
    outside3 = Image.composite(black, diff3, bin_full)
    assert outside3.getbbox() is None, \
        f"{suit.nazwa}: klamp przepuścił przemalowaną ramę / małą plamę"

    if suit is Suit.KIER:
        cx_w = (cb[0] + cb[2]) // 2

        # (t) detekcja teksturowa: PŁASKA plama w kolorze zbliżonym do kremu
        # (poniżej progu kolorowego) zamalowująca ornament nad wcięciem —
        # regresja v33 (ścięta twarz); od v3 ratuje ją kandydat teksturowy
        krem_crop = template.crop((template.width // 2 - 20, 10,
                                   template.width // 2 + 20, 40))
        krem = tuple(
            sorted(krem_crop.getdata(band=b))[len(krem_crop.getdata()) // 2]
            for b in range(3))
        skora = (max(0, krem[0] - 20), max(0, krem[1] - 15), max(0, krem[2] - 25))
        fake_t = template.copy()
        ImageDraw.Draw(fake_t).rectangle(
            (cx_w - 90, cb[1] - 90, cx_w + 90, cb[1] + 90), fill=skora)
        clamped_t = generator._klamp_do_szablonu(fake_t, spec)
        # Lita maska (v6): wnętrze plamy ma wyjść niemal 1:1 (feather tylko
        # na krawędzi); bez kandydata teksturowego różnica wynosiłaby pełne
        # |krem−skora| (~20-25)
        px_t = clamped_t.getpixel((cx_w, cb[1] - 40))
        assert all(abs(a - b) <= 4 for a, b in zip(px_t, skora)), \
            f"kier: kandydat teksturowy nie uratował płaskiej plamy ({px_t} vs {skora})"

        # (g2) regresja ghostingu: plama skóropodobna z „rysami twarzy"
        # (cienkie ciemne linie → lokalnie wysoka tekstura wyniku) — sonda
        # MIĘDZY liniami musi być ≈ kolorowi plamy, nie blendem z ornamentem
        fake_g = template.copy()
        dg = ImageDraw.Draw(fake_g)
        dg.rectangle((cx_w - 90, cb[1] - 90, cx_w + 90, cb[1] + 90), fill=skora)
        for y_l in (cb[1] - 60, cb[1] - 40, cb[1] - 20):
            dg.line([(cx_w - 70, y_l), (cx_w + 70, y_l)],
                    fill=(60, 40, 30), width=4)
        clamped_g = generator._klamp_do_szablonu(fake_g, spec)
        for probe_g in ((cx_w, cb[1] - 50), (cx_w, cb[1] - 30)):
            px_g = clamped_g.getpixel(probe_g)
            assert all(abs(a - b) <= 4 for a, b in zip(px_g, skora)), \
                f"kier: ghost ornamentu między rysami twarzy ({px_g} vs {skora})"

        # (h) domykanie dziur: gruby pierścień nachodzący na okno, wewnątrz
        # subtelna zmiana PONIŻEJ progu — środek musi pochodzić z WYNIKU
        # (dziura domknięta), nie z szablonu (regresja „ptaszka" na czole v34)
        fake_h = template.copy()
        frag_box = (cx_w - 55, cb[1] - 32, cx_w + 55, cb[1] + 72)
        frag = template.crop(frag_box).point(lambda v: max(0, v - 12))
        fake_h.paste(frag, frag_box[:2])
        ImageDraw.Draw(fake_h).ellipse(
            (cx_w - 100, cb[1] - 60, cx_w + 100, cb[1] + 100),
            outline=(0, 128, 255), width=40)
        clamped_h = generator._klamp_do_szablonu(fake_h, spec)
        probe_h = (cx_w, cb[1] - 10)
        assert fake_h.getpixel(probe_h) != template.getpixel(probe_h), \
            "kier: sonda dziury trafiła w niezmieniony piksel (popraw test)"
        assert clamped_h.getpixel(probe_h) == fake_h.getpixel(probe_h), \
            "kier: dziura w sylwetce niedomknięta (szablon prześwituje)"

        # --- klamp v4: drobne elementy, resztki kolażu, kanał chroma ---
        w_t, h_t = template.size
        arr_center = np.array(center.point(lambda v: 255 if v > 0 else 0),
                              dtype=np.uint8)

        # Kotwica testów: NAJSZERSZY punkt okna (kontur == cb[0]) — wszędzie
        # indziej kontur leży na prawo, więc kształty doklejone w tym punkcie
        # mają przewidywalne pole poza oknem niezależnie od krzywizny serca
        kol_lewa = np.nonzero(arr_center[:, cb[0]])[0]
        assert kol_lewa.size, "kier: kolumna cb[0] bez pikseli maski centrum"
        y_star = int(kol_lewa[kol_lewa.size // 2])
        xl = cb[0]

        # (r) drobny rekwizyt: kółko przy oknie o polu ~1.35× NOWEGO progu
        # min. pola (poniżej starego 0.0015 — przedtem ginęło) musi przeżyć
        min_pole_px = masks.KLAMP_MIN_POLE * w_t * h_t
        r_rekw = int(round(np.sqrt(1.35 * min_pole_px / (0.804 * np.pi))))
        fake_r = template.copy()
        ImageDraw.Draw(fake_r).ellipse(
            (xl - 12 - r_rekw, y_star - r_rekw,
             xl - 12 + r_rekw, y_star + r_rekw), fill=(0, 128, 255))
        clamped_r = generator._klamp_do_szablonu(fake_r, spec)
        probe_r = (xl - 12 - r_rekw // 2, y_star)
        assert clamped_r.getpixel(probe_r) == (0, 128, 255), \
            f"kier: drobny rekwizyt (r={r_rekw}px) ścięty przez klamp"

        # (rk) resztka kolażu: duży prostokąt (fill bboxa ~1) nachodzący na
        # okno — filtr prostokątnych resztek MUSI zwrócić go do szablonu
        rk_w, rk_h = round(0.40 * w_t), round(0.18 * h_t)
        fake_rk = template.copy()
        ImageDraw.Draw(fake_rk).rectangle(
            (xl + 20 - rk_w, y_star - rk_h // 2,
             xl + 20, y_star + rk_h // 2), fill=(0, 128, 255))
        clamped_rk = generator._klamp_do_szablonu(fake_rk, spec)
        probe_rk = (max(10, xl - round(0.15 * w_t)), y_star)
        assert clamped_rk.getpixel(probe_rk) == template.getpixel(probe_rk), \
            "kier: prostokątna resztka kolażu przeszła przez klamp"

        # (ch) kanał chromatyczny — SYNTETYCZNY szablon (realne szablony są
        # grawerowane niemal wszędzie, więc płaskiego kremu nie da się na
        # nich wiarygodnie znaleźć): czysty krem + elipsa-rama + dwie tarcze.
        # Plama o INNEJ BARWIE, ale różnicy RGB poniżej progu kolorowego,
        # sięgająca daleko poza ring pewności — łapie ją wyłącznie chroma.
        import cv2

        krem_ch = tuple(int(config.CREAM_HEX[i:i + 2], 16) for i in (1, 3, 5))
        synt = Image.new("RGB", (900, 1260), krem_ch)
        ds = ImageDraw.Draw(synt)
        ds.ellipse((250, 380, 650, 880), outline=(128, 21, 21), width=18)
        ds.rectangle((80, 70, 200, 230), outline=(128, 21, 21), width=8)
        ds.rectangle((700, 1030, 820, 1190), outline=(128, 21, 21), width=8)
        synt_path = out_dir / "synt_szablon_chroma.png"
        synt.save(synt_path)

        kolor_ch = (max(0, krem_ch[0] - 22), max(0, krem_ch[1] - 6),
                    min(255, krem_ch[2] + 28))
        # sanity konstrukcji: poniżej progu RGB, powyżej progu chroma
        assert max(abs(a - b) for a, b in zip(kolor_ch, krem_ch)) \
            <= masks.KLAMP_PROG_ROZNICY, "test (ch): kolor ponad progiem RGB"
        para = np.array([[krem_ch, kolor_ch]], dtype=np.uint8)
        lab_para = cv2.cvtColor(para, cv2.COLOR_RGB2Lab).astype(np.float32)
        chroma_para = np.hypot(lab_para[0, 0, 1] - lab_para[0, 1, 1],
                               lab_para[0, 0, 2] - lab_para[0, 1, 2])
        assert chroma_para > masks.KLAMP_PROG_CHROMA, \
            f"test (ch): za mała różnica chroma ({chroma_para:.1f})"

        # plama nachodzi na okno (spójność z rdzeniem) i sięga 190 px w lewo
        # — daleko poza ring pewności (KLAMP_RING_PX), gdzie obowiązuje pełny
        # próg RGB i tylko kanał chroma może ją uratować
        wynik_ch = synt.copy()
        ImageDraw.Draw(wynik_ch).rectangle((60, 580, 290, 680), fill=kolor_ch)
        maska_ch = masks.maska_klampu(wynik_ch, synt, synt_path,
                                      kolor_tla=(128, 21, 21))
        clamped_ch = Image.composite(wynik_ch, synt, maska_ch)
        probe_ch = (120, 630)
        px_ch = clamped_ch.getpixel(probe_ch)
        assert all(abs(a - b) <= 4 for a, b in zip(px_ch, kolor_ch)), \
            (f"kier: kanał chroma nie uratował jasnej plamy na kremie "
             f"({px_ch} vs {kolor_ch})")

        # (t2) „większe serce": model rozlał kolor wypełnienia ~80 px poza
        # okno (przerysowany, powiększony symbol) — anty-bleed kanału
        # kolorowego na kartach CZERWONYCH musi zwrócić nadmiar do szablonu
        # (stały rozmiar symbolu; na czarnych reguła celowo wyłączona —
        # kolor_tla ≈ ubrania/włosy postaci)
        kolor_kier = _hex_rgb(_styl.kolor_czerwony)
        arr_full_k = np.array(bin_full, dtype=np.uint8)
        k80 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (161, 161))
        dil80 = cv2.dilate(arr_full_k, k80) > 0
        fake_serce = np.asarray(template).copy()
        fake_serce[dil80] = kolor_kier
        clamped_s = generator._klamp_do_szablonu(
            Image.fromarray(fake_serce), spec)
        diff_s = ImageChops.difference(clamped_s, template)
        outside_s = Image.composite(black, diff_s, bin_full)
        assert outside_s.getbbox() is None, \
            "kier: powiększone serce (fill poza oknem) przeszło przez klamp"

        # (t3) domknięcie na UNII extra|core: pasmo w kolorze ≈ krem
        # (niewykrywalne żadnym kanałem) PRZYLEGAJĄCE do granicy okna,
        # otoczone sylwetką — stare domknięcie samego `extra` nie
        # mostkowało go (maska otwarta od strony okna) i przez postać
        # przebijał „duch" konturu szablonu (K_kier_v13); po domknięciu
        # na unii pasmo ma pochodzić z WYNIKU. Szablon syntetyczny z (ch):
        # okno-elipsa (250,380,650,880), lewa krawędź przy x≈250-258.
        pasmo = tuple(max(0, c - 8) for c in krem_ch)
        wynik_t3 = synt.copy()
        dt3 = ImageDraw.Draw(wynik_t3)
        dt3.rectangle((60, 560, 400, 700), fill=(0, 128, 255))
        dt3.rectangle((210, 560, 250, 640), fill=pasmo)
        maska_t3 = masks.maska_klampu(wynik_t3, synt, synt_path,
                                      kolor_tla=(128, 21, 21))
        clamped_t3 = Image.composite(wynik_t3, synt, maska_t3)
        probe_t3 = (230, 610)
        px_t3 = clamped_t3.getpixel(probe_t3)
        assert all(abs(a - b) <= 4 for a, b in zip(px_t3, pasmo)), \
            (f"kier: pasmo przy granicy okna niedomknięte — duch konturu "
             f"({px_t3} vs {pasmo})")

    # (e3) wynik identyczny z szablonem → poza oknem klamp niczego nie
    # zmienia (wewnątrz okna baza v8 maluje wypełnienie kolorem karty —
    # to celowe, sprawdza test (t1))
    clamped4 = generator._klamp_do_szablonu(template.copy(), spec)
    diff4 = ImageChops.difference(clamped4, template)
    outside4 = Image.composite(black, diff4, bin_full)
    assert outside4.getbbox() is None, \
        f"{suit.nazwa}: klamp zmienił tło poza oknem symbolu"

    # (f) guardrail: jednolite przemalowanie całej karty → degradacja do
    # maski pop-out (POZA nią szablon, WEWNĄTRZ treść modelu przeżywa)
    clamped2 = generator._klamp_do_szablonu(
        Image.new("RGB", template.size, (0, 128, 255)), spec)
    bin_core = popout.point(lambda v: 255 if v > 0 else 0)
    diff2 = ImageChops.difference(clamped2, template)
    outside2 = Image.composite(black, diff2, bin_core)
    assert outside2.getbbox() is None, \
        f"{suit.nazwa}: guardrail nie zdegradował klampu do maski pop-out"
    inside2 = Image.composite(diff2, black, bin_core)
    assert inside2.getbbox() is not None, \
        f"{suit.nazwa}: klamp zabił treść wewnątrz symbolu"
    print(f"Klamp adaptacyjny v4 {suit.nazwa}: sylwetka przeżyła (kolor+"
          "tekstura+chroma), drobny rekwizyt ocalony, resztka kolażu i rama "
          "z szablonu, dziury domknięte, guardrail działa")

# (g) tarcze wykryte flood-fillem, nie z awaryjnych ramek (dla dostarczonych
# szablonów detekcja MUSI trafiać; log „[maski] … awaryjnej ramki" = regresja)
for suit in Suit:
    if suit.czy_joker and not suit.available_templates():
        continue
    tpl = suit.template_path
    m = masks.get_masks(tpl)
    w, h = Image.open(tpl).size
    tl_fb = (int(masks._TL_FALLBACK[0] * w), int(masks._TL_FALLBACK[1] * h),
             int(masks._TL_FALLBACK[2] * w), int(masks._TL_FALLBACK[3] * h))
    br_fb = (int(masks._BR_FALLBACK[0] * w), int(masks._BR_FALLBACK[1] * h),
             int(masks._BR_FALLBACK[2] * w), int(masks._BR_FALLBACK[3] * h))
    assert m.tl_box != tl_fb, f"{suit.nazwa}: tarcza TL z awaryjnej ramki"
    assert m.br_box != br_fb, f"{suit.nazwa}: tarcza BR z awaryjnej ramki"
print("Tarcze: wszystkie z flood-filla (bez awaryjnych ramek)")

# (d) font kart ma lining figures — „10" nie renderuje się jak „1o"
_font_path = config.find_serif_font()
_boxes = [ImageFont.truetype(str(_font_path), 64).getbbox(d) for d in "0123456789"]
_tops = [bx[1] for bx in _boxes]
_bottoms = [bx[3] for bx in _boxes]
assert max(_tops) - min(_tops) <= 5 and max(_bottoms) - min(_bottoms) <= 5, \
    f"font {_font_path.name} ma old-style figures (nierówne cyfry)"
print(f"Font kart: {_font_path.name} (lining figures OK)")
print("Test zakończony:", out_dir)
