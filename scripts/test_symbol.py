"""Weryfikacja symbolu offline (zero API): sprawdza dwie własności finalnych kart
liczonych z zapisanych wyjść modelu (output/_raw/api/*.png):

  TEST 1 — LINIE PROSTE: proste linie ramki w kompozycie muszą pokrywać się z
    szablonem (model ich nie pofalował) i być geometrycznie proste (kąty ~0/90°).
  TEST 2 — TŁO NIENARUSZONE: poza symbolem i strefą pop-out kompozyt == szablon
    (rama, ornament, tło, tarcze — nie ruszone przez AI; „symbol nie rusza tła").
    AI zasłania symbol tylko wewnątrz/przy oknie. Poziom wypełnienia bazy = JEDEN
    odcień presetu.

Uruchomienie: python -m scripts.test_symbol [plik.png ...]
Bez argumentów bierze wszystkie karty z output/_raw/api/, grupuje po kolorze.
Nakładki (linie=czerwone, pas konturu=zielone) trafiają do TEST_OUT (domyślnie
output/symbol_test/). Kod wyjścia ≠ 0 przy dowolnym FAIL.

UWAGA: szablon i kolory brane z AKTYWNYCH presetów — jak w scripts.test_klamp.
"""
import os
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app import config
from app.core import compositor, masks, style_store
from app.core.models import Suit

style_store.load()

API_DIR = config.RAW_DIR / "api"
out_dir = Path(os.environ.get("TEST_OUT", config.OUTPUT_DIR / "symbol_test"))
out_dir.mkdir(parents=True, exist_ok=True)

# Progi zaliczenia (łagodny margines na pop-out postaci zasłaniający fragment linii)
IOU_MIN = 0.85            # zgodność wykrytych linii kompozytu z szablonem
PROSTE_MIN = 0.95         # odsetek długich odcinków w ±KAT_TOL od pionu/poziomu
KAT_TOL_DEG = 1.5
TLO_ZGODNOSC_MIN = 0.98   # min udział tła (poza symbolem) zgodnego z szablonem
LINIE_DIFF_MAX = 12       # max |kompozyt − szablon| na liniach (wracają z bazy)


def _kolor_z_nazwy(path: Path) -> Suit | None:
    czesci = path.stem.split("_")
    if len(czesci) < 2:
        return None
    try:
        return Suit.from_nazwa(czesci[1])
    except ValueError:
        return None


def _kompozyt(suit: Suit, plik: Path, styl) -> Image.Image | None:
    template = Image.open(suit.template_path).convert("RGB")
    wynik = Image.open(plik).convert("RGB")
    if wynik.size != template.size:
        wynik = wynik.resize(template.size, Image.Resampling.LANCZOS)
    kolor_hex = styl.kolor_czerwony if suit.is_red else styl.kolor_czarny
    kolor_tla = (int(kolor_hex[1:3], 16), int(kolor_hex[3:5], 16),
                 int(kolor_hex[5:7], 16))
    maska = masks.maska_klampu(wynik, template, suit.template_path,
                               kolor_tla=kolor_tla)
    baza = compositor.wypelnij_okno(template, suit)
    return Image.composite(wynik, baza, maska)


def _iou(a: np.ndarray, b: np.ndarray) -> float:
    inter = int(np.count_nonzero((a > 0) & (b > 0)))
    uni = int(np.count_nonzero((a > 0) | (b > 0)))
    return inter / uni if uni else 1.0


def _odsetek_prostych(lines_mask: np.ndarray, bok: int) -> tuple[float, int]:
    """Odsetek długich odcinków Hougha o kącie w ±KAT_TOL od pionu/poziomu."""
    segs = cv2.HoughLinesP(lines_mask, 1, np.pi / 180, threshold=80,
                           minLineLength=bok // 6, maxLineGap=bok // 40)
    if segs is None:
        return 1.0, 0
    proste = 0
    for x1, y1, x2, y2 in segs[:, 0]:
        kat = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1))) % 180.0
        odchyl = min(kat, abs(kat - 90.0), abs(kat - 180.0))
        if odchyl <= KAT_TOL_DEG:
            proste += 1
    return proste / len(segs), len(segs)


pliki = ([Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1
         else sorted(API_DIR.glob("*.png")))
if not pliki:
    sys.exit(f"Brak plików — wygeneruj karty (wyjścia modelu trafiają do {API_DIR})")

styl = compositor.styl_z_presetu()
wg_koloru: dict[str, list[Path]] = defaultdict(list)
for p in pliki:
    s = _kolor_z_nazwy(p)
    if s is None:
        print(f"[pomijam] {p.name}: nazwa nie pasuje do wzorca wartość_kolor")
        continue
    wg_koloru[s.nazwa].append(p)

any_fail = False
for nazwa, karty in sorted(wg_koloru.items()):
    suit = Suit.from_nazwa(nazwa)
    template = Image.open(suit.template_path).convert("RGB")
    tpl_arr = np.asarray(template, dtype=np.int16)
    tpl_bgr = cv2.cvtColor(np.asarray(template), cv2.COLOR_RGB2BGR)
    baza_arr = np.asarray(compositor.wypelnij_okno(template, suit), dtype=np.int16)
    tmasks = masks.get_masks(suit.template_path)
    core_full = np.array(tmasks.center_full) > 0
    h, w = tpl_arr.shape[:2]
    # TŁO NIENARUSZONE: obszar POZA symbolem i strefą pop-out kompozyt musi ==
    # szablon (rama/ornament/tło nie ruszone przez AI). Pomijamy pas NAD symbolem
    # (tam głowy pop-out legalnie zasłaniają ornament — to zamierzone; prostość
    # górnej ramki weryfikuje TEST 1) oraz tarcze (stempel wartości).
    r_poza = max(20, round(w * (masks.KLAMP_POPOUT_RING_V_PX + 20)
                           / config.TEMPLATE_STD_SZEROKOSC))
    poza_symbol = cv2.dilate(core_full.astype(np.uint8) * 255,
                             cv2.getStructuringElement(
                                 cv2.MORPH_ELLIPSE, (2 * r_poza + 1, 2 * r_poza + 1)))
    poza_symbol = poza_symbol == 0
    sy0 = int(np.nonzero(core_full.any(axis=1))[0].min())
    poza_symbol[:sy0, :] = False   # nad symbolem: pop-out głów (zamierzone)
    for x0, y0, x1, y1 in (tmasks.tl_box, tmasks.br_box):
        poza_symbol[y0:y1, x0:x1] = False   # tarcze: tam ląduje stempel wartości
    fill_hex = styl.kolor_czerwony if suit.is_red else styl.kolor_czarny
    fill_rgb = np.array([int(fill_hex[i:i + 2], 16) for i in (1, 3, 5)], np.int16)

    # Pas GÓRA/DÓŁ do testu LINII — poziome linie ramki są tu z dala od symbolu
    # (środek) i postaci (w oknie); boczne pionowe linie leżą tuż przy szerokim
    # symbolu i nie da się ich odseparować, więc testujemy poziome. Tarcze
    # narożne (proste krawędzie) wykluczone.
    ramka = np.zeros((h, w), bool)
    ramka[:int(0.15 * h), :] = True
    ramka[int(0.85 * h):, :] = True
    for x0, y0, x1, y1 in (tmasks.tl_box, tmasks.br_box):
        ramka[y0:y1, x0:x1] = False
    lines_tpl_r = masks._wykryj_proste_linie(tpl_bgr) & (ramka.astype(np.uint8) * 255)

    # POZIOM WYPEŁNIENIA (per kolor): baza wypełnia okno JEDNYM płaskim odcieniem
    # = tyle samo na każdej karcie; sprawdzamy że to dokładnie kolor presetu.
    fill_vals = baza_arr[core_full]
    fill_odc = len(np.unique(fill_vals.reshape(-1, 3), axis=0)) if len(fill_vals) else 0
    fill_ok = fill_odc == 1 and int(np.abs(fill_vals[0] - fill_rgb).max()) <= 1
    any_fail |= not fill_ok
    print(f"\n=== {nazwa.upper()} ({len(karty)} kart) === "
          f"wypełnienie: {fill_odc} odcień [{'OK' if fill_ok else 'FAIL'}]")

    for plik in karty:
        comp = _kompozyt(suit, plik, styl)
        comp_arr = np.asarray(comp, dtype=np.int16)
        comp_bgr = cv2.cvtColor(np.asarray(comp), cv2.COLOR_RGB2BGR)

        # TEST 1 — linie proste (poziome linie ramki góra/dół). Kryterium PASS:
        # kompozyt na pikselach linii szablonu == szablon (linie wracają z bazy =
        # są proste jak w szablonie). IoU/Hough tylko INFO — wykrywanie linii na
        # kompozycie łapie też ornament rogów i wystające rekwizyty postaci
        # (szablon sam nie osiąga 100% osiowości), więc nie nadają się na próg.
        lines_comp_r = masks._wykryj_proste_linie(comp_bgr) & (ramka.astype(np.uint8) * 255)
        iou = _iou(lines_comp_r, lines_tpl_r)
        odsetek, n_seg = _odsetek_prostych(lines_comp_r, min(h, w))
        linie_diff = int(np.abs(comp_arr - tpl_arr)[lines_tpl_r > 0].max()) \
            if np.any(lines_tpl_r) else 0
        t1 = linie_diff <= LINIE_DIFF_MAX

        # TEST 2 — TŁO NIENARUSZONE: poza symbolem i strefą pop-out kompozyt ==
        # szablon (rama/ornament/tło nie ruszone przez AI). AI zasłania symbol
        # tylko wewnątrz/przy oknie.
        roznica_tla = np.abs(comp_arr - tpl_arr).max(axis=2)[poza_symbol]
        udzial = float((roznica_tla <= 2).mean()) if roznica_tla.size else 1.0
        t2 = udzial >= TLO_ZGODNOSC_MIN

        any_fail |= not (t1 and t2)
        status = "PASS" if (t1 and t2) else "FAIL"
        print(f"  {plik.name:<22} [{status}]  linie: IoU={iou:.3f} "
              f"proste={odsetek:.0%}({n_seg}) diff={linie_diff} | "
              f"tło nietknięte={udzial:.1%}")

        # nakładka do oceny wzrokowej (linie=czerwone, strefa tła=zielone)
        ov = np.asarray(comp).copy()
        ov[lines_comp_r > 0] = [255, 0, 0]
        ov[poza_symbol] = (0.6 * ov[poza_symbol]
                           + np.array([0, 100, 0])).astype(np.uint8)
        mala = Image.fromarray(ov)
        mala.thumbnail((700, 1000))
        mala.save(out_dir / f"{plik.stem}_symbol.png")

print(f"\n{'— WSZYSTKO PASS —' if not any_fail else '!!! SĄ BŁĘDY (FAIL) !!!'}"
      f"  (nakładki: {out_dir})")
sys.exit(1 if any_fail else 0)
