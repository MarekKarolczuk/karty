"""Maski szablonów (OpenCV): centralny symbol (flood-fill) i narożne tarcze.

Klamp finalnej karty prowadzi maska_klampu(): rdzeń bezwarunkowy = OKNO
symbolu (maska centrum — tło modelu przycięte do konturu okna, rama
i ornamenty zawsze z szablonu → identyczny symbol na każdej karcie),
a ponad oknem adaptacyjna sylwetka postaci — z wyniku modelu zostaje to,
co ZNACZĄCO różni się od szablonu, jest spójne z oknem i dość duże
(postać „narzucona" na kartę bez limitu); tło, tarcze narożne i pas
bordiury zawsze wracają do szablonu. Maska pop-out (sylwetka symbolu
z wklęsłościami domkniętymi convex hullem + ring dylatacji ~60-90 px)
służy dziś degradacji guardraila i ścieżce inpaintingu Stability.
Maski szablonów są cache'owane w assets/masks/ (pliki wersjonowane
sufiksem _v{MASK_VERSION}); gdy flood-fill zawiedzie, wczytywana jest
maska statyczna z assets/masks/static/maska_<kolor>.png.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app import config

# Wersja algorytmu masek — podbicie unieważnia wszystkie cache na dysku
# (v8: nowa maska center_full — okno BEZ erozji, po którym wypełnia się kolor
# symbolu aż do konturu ramy (erodowany center zostawiał kremową szczelinę
# ~5 px — „biały ślad serca" w kolażu i po klampie); v7: wklęsłości sylwetki
# symbolu domknięte convex hullem przed dylatacją.
# Ring bez zmian ~60-90 px, tarcze narożne nadal twardo wyzerowane)
MASK_VERSION = 8

# Tolerancja flood-filla: PIL-owe thresh=90 to suma |diff| po kanałach,
# czyli ~30 na kanał w cv2 (FLOODFILL_FIXED_RANGE porównuje do seeda).
_FLOOD_DIFF = (30, 30, 30)

# Punkty startowe flood-filla dla narożnych tarcz (ułamki szer./wys. szablonu)
_TL_SEED = (0.175, 0.135)
_BR_SEED = (0.825, 0.865)

# Siatka sond wokół seeda tarczy (±3.5% w obu osiach) — tarcze na tłach z AI
# potrafią dryfować względem sztywnego punktu; pierwsza trafiona wygrywa
_SEED_OFFSETY = (0.0, -0.035, 0.035)

# Dozwolony rejon środka tarczy (ułamki w/h) — kandydat spoza swojej ćwiartki
# to leak flood-filla, nie tarcza
_TL_REJON = (0.0, 0.0, 0.45, 0.40)
_BR_REJON = (0.55, 0.60, 1.0, 1.0)

# Awaryjne ramki narożne, gdy flood-fill tarczy zawiedzie (leak / brak tarczy)
_TL_FALLBACK = (0.08, 0.05, 0.27, 0.21)
_BR_FALLBACK = (0.73, 0.79, 0.92, 0.95)

# Kalibracja klampu adaptacyjnego (maska_klampu) — wartości startowe do
# strojenia po testach live:
# próg |wynik − szablon| (maks. po kanałach): poniżej = „to samo tło";
# Gemini re-renderuje całą kartę, więc krem/grawer dryfują o kilkanaście
# jednostek — próg musi być wyżej, a wciąż niżej niż postać na kremie
# (38: granica skóra/krem — wyższe progi zostawiały dziury na jasnych twarzach)
KLAMP_PROG_ROZNICY = 38
# na PŁASKIM szablonie (czysty krem, tex_tpl < próg tekstury) poza ringiem
# próg obniżony: dryf kremu po re-renderze to ~kilkanaście jednostek, więc
# 27 ma zapas, a łapie jasne partie postaci (ubrania, skóra), które przy 38
# wracały szablonem — ucięte ramiona/kapelusze daleko od okna
KLAMP_PROG_PLASKI = 27
# detekcja teksturowa (kolor nie łapie skóry na kremowym ornamencie):
# rozmyty |Laplacian| szablonu POWYŻEJ progu = tam jest rysunek/ornament,
# a wyniku PONIŻEJ progu płaskości = ktoś zamalował go płaską farbą → postać
# (płaskość 14: rysy twarzy w cell-shadingu liczą się jako płaskie — ornament
# ma medianę ~69, próg 8 wycinał dziury dokładnie na oczach/brwiach → ghost)
KLAMP_TEKSTURA_PROG = 18.0
KLAMP_PLASKOSC_PROG = 14.0
# detekcja chromatyczna (kanał 3): inna BARWA przy podobnej jasności —
# jasna skóra na czystym kremie, której nie widzi ani kolor RGB-max
# (diff < próg), ani tekstura (szablon tam płaski). Niski próg tylko na
# płaskim szablonie (tex_tpl < KLAMP_TEKSTURA_PROG): na ornamencie dryf
# barwy re-renderu podmieniałby ramę na wersję modelu
KLAMP_PROG_CHROMA = 12.0
# chroma NA ORNAMENCIE z wyższym progiem: skóra/włosy mają barwę Lab wyraźnie
# inną niż różowo-czerwony grawer, a dryf barwy re-renderu ornamentu jest
# mały — bez tego kanału głowy malowane na ornamencie ginęły w klampie
# (A_kier_v54: pokrycie maski w rejonie głowy 10%); próg 2.3× wyższy niż na
# kremie trzyma dryf ornamentu poniżej detekcji
KLAMP_PROG_CHROMA_ORNAMENT = 28.0
# ring pewności: pas dylatacji okna, w którym próg kanału kolorowego jest
# obniżony (~60% bazowego) — tuż przy oknie wystająca postać jest niemal
# pewna; obniżka działa TYLKO na płaskim szablonie (jak wyżej — ochrona
# ornamentów ramy przed dryfem re-renderu)
# (72: dawne 48 nie pokrywało typowej głębokości wyjścia postaci — ring
# maski pop-out ma 60–90 px)
KLAMP_RING_PX = 72
KLAMP_PROG_RING = 23
# lite domknięcie sylwetki (MORPH_CLOSE po odsiewie artefaktów): mostkuje
# dziury detekcji na rysach twarzy i kanały w strefach słabej tekstury
# szablonu (do ~50 px) — wnętrze maski ma być binarne, częściowa maska +
# feather = półprzezroczysty ghost ornamentu i wyprane kolory
KLAMP_DOMKNIECIE_MIN_PX = 51
# anty-bleed: piksele wyniku w tym promieniu (na kanał) od koloru wypełnienia
# okna nie mogą udawać postaci na ramie — kształt symbolu ma zostać stały.
# Na kartach CZERWONYCH anty-bleed obejmuje też kanał kolorowy (cand1):
# model przerysowuje własne, WIĘKSZE serce i jego nadmiar poza oknem musi
# wrócić do szablonu (stały rozmiar symbolu). Na czarnych kartach kanał
# kolorowy zostaje bez anty-bleedu — kolor_tla ≈ czarne ubrania/włosy
# i strip ścinałby postacie
KLAMP_BLEED_TOL = 30
# rozpoznanie czerwonego wypełnienia: przewaga kanału R nad max(G,B)
# (#801515 → 107, #1A1414 → 6)
KLAMP_CZERWIEN_PRZEWAGA = 40
# maksymalna domykana dziura w sylwetce (ułamek pola karty): linie szablonu
# prześwitujące przez twarz są małe; większe prześwity (np. tło między ręką
# a ciałem) mają zostać szablonem (0.02 — po licie domkniętym close dziury
# bywają większe niż same linie)
KLAMP_MAKS_DZIURA = 0.02
# otwarcie morfologiczne kandydatów: usuwa cienkie krawędziowe szumy
# (subpikselowe przesunięcia linii graweru po re-renderze)
# (7 — 11 zjadało cienkie wystające elementy: palce, rondo kapelusza)
KLAMP_OTWARCIE_PX = 7
# mostek sylwetki: małe domknięcie kandydatów PO otwarciu, a PRZED filtrem
# spójności z oknem — niewykrywalne przesmyki (szyja/podbródek: skóra ≈
# ornament poniżej wszystkich progów) odcinały głowę od reszty sylwetki
# i filtr spójności kasował ją w całości (A_kier_v54: „bezgłowa" 4. osoba
# mimo 47% kandydatów w rejonie głowy); po otwarciu kandydaci są już bez
# cienkich szumów, więc mostek nie skleja śmieci z sylwetką
KLAMP_MOSTEK_PX = 31
# lekka dylatacja sylwetki przed featherem — domyka antyaliasowany kontur
# (3 — 5 + szeroki feather mieszały szablon z wynikiem → wyprane krawędzie)
KLAMP_DYLATACJA_PX = 3
# minimalne pole komponentu sylwetki (ułamek pola karty) — odsiewa łaty
# przemalowanej ramy symbolu, które przetrwały otwarcie; za duża wartość
# zjada drobne elementy pop-out (0.0008 — przy 0.0015 dłoń/rekwizyt ginęły)
KLAMP_MIN_POLE = 0.0008
# filtr resztek kolażu: komponent o wypełnieniu własnego bboxa >= 0.90
# i polu > 5% strefy poza oknem to prostokątna resztka zdjęcia (postacie
# mają nieregularny kontur, wypełnienie zwykle < 0.8) → wraca do szablonu
KLAMP_RESZTKA_WYPELNIENIE = 0.90
KLAMP_RESZTKA_MIN_UDZIAL = 0.05
# guardrail: większy udział sylwetki w strefie poza rdzeniem = model
# przemalował tło hurtem / zostawił prostokąt zdjęcia → degradacja do
# maski pop-out (hull+ring)
KLAMP_MAKS_UDZIAL = 0.35
# pas bordiury (ułamek szer./wys.) — krawędź karty zawsze z szablonu
KLAMP_BORDIURA = 0.05
# re-render graweru ≠ postać: gdzie szablon ma ornament (tex_tpl wysokie),
# a WYNIK też jest regionalnie teksturowany (tex_wyn > tego progu — model
# przerysował linie graweru, a nie zamalował je PŁASKĄ farbą postaci),
# przywracamy szablon. Bez tego dryf barwy/koloru re-renderu ornamentu wokół
# symbolu udaje sylwetkę → w kompozycie ląduje niedoskonały grawer modelu
# (ukośne szwy z bandingu dyfuzji + WIĘKSZY, podwójny kontur symbolu na
# kartach czarnych). Próg na skali rozmytego |Laplacian| (jak KLAMP_TEKSTURA_PROG):
# płaska farba postaci ma tex_wyn ≈ 0 « próg → sylwetka nad ornamentem przeżywa
KLAMP_ORNAMENT_KEEP_PROG = 20.0
# MASKA W KSZTAŁCIE SYMBOLU: sylwetka przeżywa tylko w oknie + WĄSKIM marginesie
# tej szerokości (px na skali config.TEMPLATE_STD_SZEROKOSC=1696). To NIE „pop-out
# na ramę", lecz mały zapas nad ornamentem — głowa może lekko wyjść nad wcięcie
# serca / górę symbolu, a wcięcia dostają luz (głowy nie cięte). Boki i tak
# przycina ochrona prostych linii (frame_lines_mask): okno jest ogromne (~87,9%
# szer.), na bokach kończy się ~18 px od bordiury, więc każdy szerszy ring zjadał
# boczną, prostą linię ramki (krzywe boki). 50 px huga symbol.
KLAMP_POPOUT_RING_PX = 50
# Ochrona prostych linii ramki: model re-renderuje całą kartę niedoskonale i
# proste linie falują. Wykrywamy DŁUGIE proste linie w szablonie (kierunkowe
# otwarcie morfologiczne) i zawsze przywracamy je z szablonu — nawet gdy leżą
# w ringu (boczna wewnętrzna ramka przy oknie). Ornament (krótkie łuki) nie
# przeżywa otwarcia. Progi: ciemność linii na kremie, minimalna długość odcinka
# (ułamek boku karty), dylatacja (grubość podwójnej linii + antyalias)
KLAMP_LINIA_CIEMNOSC_PROG = 150
KLAMP_LINIA_DL_ULAMEK = 1 / 6
KLAMP_LINIA_DYLATACJA_PX = 5

_cache: dict[Path, "TemplateMasks"] = {}
_popout_cache: dict[Path, Image.Image] = {}
_frame_cache: dict[Path, np.ndarray] = {}


class _MaskGenerationError(Exception):
    """Flood-fill nie wyznaczył sensownej maski symbolu (leak / pusty obszar)."""


@dataclass
class TemplateMasks:
    center: Image.Image                     # maska L: 255 = wnętrze symbolu
                                            # (erodowana — odsunięta od konturu)
    center_full: Image.Image                # okno BEZ erozji — wypełnienie
                                            # koloru symbolu sięga konturu ramy
    tl_box: tuple[int, int, int, int]       # bbox tarczy lewy-górny róg
    br_box: tuple[int, int, int, int]       # bbox tarczy prawy-dolny róg


def _read_bgr(path: Path) -> np.ndarray:
    """Wczytuje obraz przez imdecode — cv2.imread wywala się na polskich
    znakach i spacjach w ścieżkach na Windows."""
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Nie można wczytać szablonu: {path}")
    return img


def _flood_region(img: np.ndarray, seed: tuple[int, int]) -> np.ndarray:
    """Binarna maska (0/255) obszaru jednolitego koloru wokół punktu seed."""
    h, w = img.shape[:2]
    ff = np.zeros((h + 2, w + 2), np.uint8)
    flags = 8 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
    cv2.floodFill(img, ff, seed, (0, 0, 0),
                  loDiff=_FLOOD_DIFF, upDiff=_FLOOD_DIFF, flags=flags)
    return ff[1:-1, 1:-1]


def _center_region(img: np.ndarray) -> np.ndarray:
    """Wnętrze centralnego symbolu z sanity-checkami przeciw leakom."""
    h, w = img.shape[:2]
    region = _flood_region(img, (w // 2, h // 2))
    area = int(np.count_nonzero(region))
    if area == 0:
        raise _MaskGenerationError("flood-fill nie objął żadnego piksela")
    if not 0.04 * w * h < area < 0.55 * w * h:
        raise _MaskGenerationError(f"podejrzane pole symbolu: {area / (w * h):.3f}")
    ys, xs = np.nonzero(region)
    margin_x, margin_y = 0.04 * w, 0.04 * h
    if (xs.min() < margin_x or ys.min() < margin_y
            or xs.max() > w - margin_x or ys.max() > h - margin_y):
        raise _MaskGenerationError("flood-fill wyciekł do krawędzi karty")
    return region


def _static_center(template_path: Path, size: tuple[int, int]) -> np.ndarray:
    """Awaryjna maska statyczna assets/masks/static/maska_<kolor>.png."""
    stem = template_path.stem.lower()
    suit = next((s for s in ("kier", "karo", "pik", "trefl") if s in stem), None)
    static_path = config.MASKS_DIR / "static" / f"maska_{suit}.png" if suit else None
    if static_path is None or not static_path.exists():
        raise RuntimeError(
            f"Maska dla szablonu {template_path.name} nie powstała automatycznie "
            f"— dodaj plik {config.MASKS_DIR / 'static'}\\maska_{suit or '<kolor>'}.png "
            "(biały symbol na czarnym tle)"
        )
    data = np.fromfile(str(static_path), dtype=np.uint8)
    mask = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise RuntimeError(f"Nie można wczytać maski statycznej: {static_path}")
    mask = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST)
    return np.where(mask >= 128, 255, 0).astype(np.uint8)


def _kandydat_tarczy(img: np.ndarray, seed: tuple[int, int],
                     rejon: tuple[float, float, float, float]
                     ) -> tuple[int, int, int, int] | None:
    """Flood-fill od seeda + walidacja: tarcza to małe, zwarte pole, którego
    środek leży w oczekiwanym rejonie narożnym. None = kandydat odrzucony."""
    h, w = img.shape[:2]
    if not (0 <= seed[0] < w and 0 <= seed[1] < h):
        return None
    region = _flood_region(img, seed)
    area = int(np.count_nonzero(region))
    # Sanity: tarcza to małe, zwarte pole; leak na tło/margines = odrzucamy
    if not 0.002 * w * h < area < 0.06 * w * h:
        return None
    ys, xs = np.nonzero(region)
    x0, y0 = int(xs.min()), int(ys.min())
    x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
    if (x1 - x0) >= 0.30 * w or (y1 - y0) >= 0.30 * h:
        return None
    # Środek bboxa musi leżeć we właściwej ćwiartce — odcina leaki, które
    # przypadkiem spełniają kryterium pola
    cx, cy = (x0 + x1) / 2 / w, (y0 + y1) / 2 / h
    if not (rejon[0] <= cx <= rejon[2] and rejon[1] <= cy <= rejon[3]):
        return None
    return (x0, y0, x1, y1)


def _shield_box(img: np.ndarray, seed_rel: tuple[float, float],
                rejon: tuple[float, float, float, float],
                fallback_rel: tuple[float, float, float, float],
                opis: str) -> tuple[int, int, int, int]:
    """Bbox tarczy narożnej: siatka sond wokół seeda (tarcze na nowych tłach
    dryfują), pierwszy poprawny kandydat wygrywa; porażka = JAWNY log +
    awaryjna ramka o stałych proporcjach."""
    h, w = img.shape[:2]
    for dy in _SEED_OFFSETY:
        for dx in _SEED_OFFSETY:
            seed = (int((seed_rel[0] + dx) * w), int((seed_rel[1] + dy) * h))
            box = _kandydat_tarczy(img, seed, rejon)
            if box is not None:
                return box
    print(f"[maski] {opis}: flood-fill tarczy zawiódł — użyto awaryjnej "
          "ramki (stempel może nie trafić w narysowaną tarczę)")
    return (int(fallback_rel[0] * w), int(fallback_rel[1] * h),
            int(fallback_rel[2] * w), int(fallback_rel[3] * h))


def _cleanup_old_cache(stem: str) -> None:
    """Usuwa cache poprzednich wersji algorytmu masek (niewersjonowane i v2)."""
    for suffix in ("_center.png", "_boxes.txt", "_popout.png",
                   "_center_v2.png", "_boxes_v2.txt", "_popout_v2.png",
                   "_center_v3.png", "_boxes_v3.txt", "_popout_v3.png",
                   "_center_v4.png", "_boxes_v4.txt", "_popout_v4.png",
                   "_center_v5.png", "_boxes_v5.txt", "_popout_v5.png",
                   "_center_v6.png", "_boxes_v6.txt", "_popout_v6.png",
                   "_center_v7.png", "_boxes_v7.txt", "_popout_v7.png"):
        old = config.MASKS_DIR / f"{stem}{suffix}"
        old.unlink(missing_ok=True)


def get_masks(template_path: Path) -> TemplateMasks:
    template_path = Path(template_path)
    if template_path in _cache:
        return _cache[template_path]

    config.MASKS_DIR.mkdir(parents=True, exist_ok=True)
    stem = template_path.stem
    center_cache = config.MASKS_DIR / f"{stem}_center_v{MASK_VERSION}.png"
    full_cache = config.MASKS_DIR / f"{stem}_centerfull_v{MASK_VERSION}.png"
    meta_cache = config.MASKS_DIR / f"{stem}_boxes_v{MASK_VERSION}.txt"
    _cleanup_old_cache(stem)

    if center_cache.exists() and full_cache.exists() and meta_cache.exists() \
            and center_cache.stat().st_mtime >= template_path.stat().st_mtime:
        center = Image.open(center_cache).convert("L")
        center_full = Image.open(full_cache).convert("L")
        v = [int(x) for x in meta_cache.read_text().split()]
        masks = TemplateMasks(center, center_full,
                              (v[0], v[1], v[2], v[3]), (v[4], v[5], v[6], v[7]))
        _cache[template_path] = masks
        return masks

    img = _read_bgr(template_path)
    h, w = img.shape[:2]

    try:
        region = _center_region(img)
        print(f"[maski] {template_path.name}: maska symbolu z flood-filla")
    except _MaskGenerationError as exc:
        region = _static_center(template_path, (w, h))
        print(f"[maski] {template_path.name}: flood-fill zawiódł ({exc}) "
              "— użyto maski statycznej")

    # Domknięcie szumu graweru wewnątrz symbolu, potem erozja: odsuwamy się
    # od konturu ramy, żeby nie zamalować jej linii. Wersja SPRZED erozji
    # (center_full) służy wypełnianiu okna kolorem — fill musi sięgać konturu
    # (erodowana maska zostawiała kremową szczelinę ~5 px, „biały ślad").
    region = cv2.morphologyEx(
        region, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    center_full = Image.fromarray(region, mode="L")
    erode_px = max(3, w // 300)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * erode_px + 1, 2 * erode_px + 1))
    region = cv2.erode(region, kernel)
    center = Image.fromarray(region, mode="L")

    tl_box = _shield_box(img, _TL_SEED, _TL_REJON, _TL_FALLBACK,
                         f"{template_path.name} TL")
    br_box = _shield_box(img, _BR_SEED, _BR_REJON, _BR_FALLBACK,
                         f"{template_path.name} BR")

    center.save(center_cache)
    center_full.save(full_cache)
    meta_cache.write_text(" ".join(str(v) for v in [*tl_box, *br_box]))

    masks = TemplateMasks(center, center_full, tl_box, br_box)
    _cache[template_path] = masks
    return masks


def _hull_sylwetki(mask: np.ndarray) -> np.ndarray:
    """Domyka wklęsłości binarnej sylwetki (0/255) jej convex hullem —
    bez parametru wielkości jądra, niezależnie od głębokości wcięcia."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return mask
    hull = cv2.convexHull(np.vstack(contours))
    out = mask.copy()
    cv2.fillConvexPoly(out, hull, 255)
    return out


def get_popout_mask(template_path: Path) -> Image.Image:
    """Maska pod inpainting pop-out: sylwetka symbolu + ring dylatacji
    ~3× grubości ramy (~60-90 px — wyraźne wychodzenie postaci poza symbol),
    miękka krawędź TYLKO do wewnątrz.

    Żadnych prostokątów — poza ringiem maska jest czysto czarna, więc
    grawerowane tło i narożne tarcze pozostają nietykalne dla API
    (wartości rysujemy lokalnie po powrocie z API).
    """
    template_path = Path(template_path)
    if template_path in _popout_cache:
        return _popout_cache[template_path]

    config.MASKS_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = config.MASKS_DIR / f"{template_path.stem}_popout_v{MASK_VERSION}.png"
    if cache_file.exists() \
            and cache_file.stat().st_mtime >= template_path.stat().st_mtime:
        mask = Image.open(cache_file).convert("L")
        _popout_cache[template_path] = mask
        return mask

    base = get_masks(template_path)
    center = np.array(base.center, dtype=np.uint8)
    w = center.shape[1]

    # 1) Domknięcie wklęsłości sylwetki convex hullem — wcięcie serca i rowki
    # trefla przestają wycinać zatoki w masce (głowy rysowane nad wcięciem
    # nie są ścinane). Hull dotyczy WYŁĄCZNIE maski pop-out; center zostaje
    # dokładny (stemplowanie, kompozycja klasyczna).
    closed = _hull_sylwetki(center)

    # 2) Ring: dylatacja ~3× grubości ramy symbolu (60-90 px) — postać może
    # WYRAŹNIE wyjść ponad kontur ramy (pop-out), klamp tego nie cofnie
    dilate_px = int(np.clip(round(w * 80 / 1500), 60, 90))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
    dilated = cv2.dilate(closed, kernel)

    # 3) Miękka krawędź wyłącznie do wewnątrz — na zewnątrz czysta czerń,
    #    żeby inpainting nie dostał ani piksela tła.
    soft = cv2.GaussianBlur(dilated, (0, 0), sigmaX=max(2, w // 400))
    mask_arr = np.where(dilated == 0, 0, soft).astype(np.uint8)

    # 4) Tarcze narożne twardo poza maską (obrona w głąb)
    for x0, y0, x1, y1 in (base.tl_box, base.br_box):
        mask_arr[y0:y1, x0:x1] = 0

    mask = Image.fromarray(mask_arr, mode="L")
    mask.save(cache_file)
    _popout_cache[template_path] = mask
    return mask


def frame_lines_mask(template_path: Path) -> np.ndarray:
    """Maska (0/255) DŁUGICH prostych linii szablonu (rama zewnętrzna/wewnętrzna
    i inne proste kreski) — te ZAWSZE wracają z szablonu w klampie, bo model
    re-renderuje je pofalowane. Kierunkowe otwarcie morfologiczne ciemnych
    pikseli: pionowe/poziome jądro długości ~ułamek boku karty zostawia tylko
    długie proste odcinki; krzywy ornament (krótkie łuki) znika. Cache w
    assets/masks/{stem}_frame_v{MASK_VERSION}.png (jak get_popout_mask)."""
    template_path = Path(template_path)
    if template_path in _frame_cache:
        return _frame_cache[template_path]

    config.MASKS_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = config.MASKS_DIR / f"{template_path.stem}_frame_v{MASK_VERSION}.png"
    if cache_file.exists() \
            and cache_file.stat().st_mtime >= template_path.stat().st_mtime:
        arr = np.array(Image.open(cache_file).convert("L"))
        _frame_cache[template_path] = arr
        return arr

    img = _read_bgr(template_path)
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    dark = (gray < KLAMP_LINIA_CIEMNOSC_PROG).astype(np.uint8) * 255

    len_v = max(31, int(h * KLAMP_LINIA_DL_ULAMEK) | 1)
    len_h = max(31, int(w * KLAMP_LINIA_DL_ULAMEK) | 1)
    k_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, len_v))
    k_h = cv2.getStructuringElement(cv2.MORPH_RECT, (len_h, 1))
    vert = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k_v)
    horiz = cv2.morphologyEx(dark, cv2.MORPH_OPEN, k_h)
    lines = cv2.bitwise_or(vert, horiz)

    dyl = max(1, round(w * KLAMP_LINIA_DYLATACJA_PX / config.TEMPLATE_STD_SZEROKOSC))
    k_d = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dyl + 1, 2 * dyl + 1))
    lines = cv2.dilate(lines, k_d)

    Image.fromarray(lines, mode="L").save(cache_file)
    _frame_cache[template_path] = lines
    return lines


def maska_klampu(wynik: Image.Image, template: Image.Image,
                 template_path: Path,
                 kolor_tla: tuple[int, int, int] | None = None) -> Image.Image:
    """Adaptacyjna maska klampu: rdzeń bezwarunkowy = OKNO symbolu (maska
    centrum, miękka krawędź do wewnątrz) — tło namalowane przez model jest
    przycinane dokładnie do konturu okna szablonu, a rama i ornamenty wokół
    okna wracają piksel-w-piksel z szablonu (identyczny symbol na każdej
    karcie). Ponad oknem przeżywa SYLWETKA postaci, wykrywana trzema drogami:
    (1) kolor — wynik znacząco różni się od szablonu (progi schodkowe: ring
    pewności przy oknie < płaski krem < ornament), (2) tekstura — szablon ma tam
    rysunek, a wynik płaską farbę (skóra na kremowym ornamencie, której kolor
    nie łapie), (3) chroma — inna barwa przy podobnej jasności na czystym
    kremie (jasne partie postaci poza ornamentem). Po odsianiu szumu
    (otwarcie + minimalne pole komponentu + filtr prostokątnych resztek
    kolażu) zostają komponenty spójne z oknem, a prześwity szablonu wewnątrz
    sylwetki (linie przez twarz) domyka wypełnianie małych dziur. Tarcze
    narożne i pas bordiury zawsze wracają do szablonu.

    kolor_tla — kolor wypełnienia okna z kolażu (anty-bleed: płaskie rozlanie
    tego koloru na ramę nie może udawać postaci).

    Guardrail: gdy „sylwetka" pokrywa większość strefy poza oknem (model
    przemalował tło hurtem albo zostawił prostokąt zdjęcia z kolażu),
    degradujemy do maski pop-out (symbol z hullem + ring — zachowanie
    z iteracji 3, bez sylwetki).
    """
    base = get_masks(template_path)
    w, h = template.size
    center = np.array(base.center, dtype=np.uint8)
    # Miękka krawędź rdzenia wyłącznie do wewnątrz okna (jak w masce pop-out)
    soft = cv2.GaussianBlur(center, (0, 0), sigmaX=max(2, w // 400))
    core = np.where(center == 0, 0, soft).astype(np.uint8)
    core_bin = np.where(center > 0, 255, 0).astype(np.uint8)

    # Strefa rozszerzona: cała karta bez tarcz narożnych i pasa bordiury.
    # allowed_full trzyma pełną strefę (do progów udziału guardraila/resztek —
    # znaczenie „część całej strefy poza oknem"), a bramkowanie kandydatów
    # zawężamy do OKNA + RINGU: poza ringiem rama/ornament zawsze z szablonu.
    allowed_full = np.full((h, w), 255, np.uint8)
    bx, by = round(w * KLAMP_BORDIURA), round(h * KLAMP_BORDIURA)
    allowed_full[:by, :] = 0
    allowed_full[h - by:, :] = 0
    allowed_full[:, :bx] = 0
    allowed_full[:, w - bx:] = 0
    for x0, y0, x1, y1 in (base.tl_box, base.br_box):
        allowed_full[y0:y1, x0:x1] = 0
    # Maska w kształcie symbolu: sylwetka przeżywa w oknie + wąskim marginesie,
    # a proste linie ramki (frame_lines) ZAWSZE wracają z szablonu (boki przy
    # oknie, wewnętrzna ramka) — nawet gdyby margines je objął
    ring_px = max(20, round(w * KLAMP_POPOUT_RING_PX / config.TEMPLATE_STD_SZEROKOSC))
    ring_kernel_popout = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * ring_px + 1, 2 * ring_px + 1))
    okno_ring = cv2.dilate(core_bin, ring_kernel_popout)
    frame_lines = frame_lines_mask(template_path)
    if frame_lines.shape != (h, w):
        frame_lines = cv2.resize(frame_lines, (w, h),
                                 interpolation=cv2.INTER_NEAREST)
    allowed = cv2.bitwise_and(allowed_full, okno_ring)
    allowed = cv2.bitwise_and(allowed, cv2.bitwise_not(frame_lines))

    wyn_rgb = np.asarray(wynik.convert("RGB"), dtype=np.int16)
    tpl_rgb = np.asarray(template.convert("RGB"), dtype=np.int16)
    diff = np.abs(wyn_rgb - tpl_rgb).max(axis=2)

    # Tekstura SZABLONU rozmyta (sygnał regionalny „tu jest ornament");
    # płaskość WYNIKU surowa, lokalna — rozmycie rozlewało teksturę rysów
    # twarzy (brwi/nos) na ±10-15 px i wycinało z kandydata szerokie kanały,
    # których nie mostkowało nawet lite domknięcie (ghost między rysami)
    sigma_tex = max(3.0, w / 500)
    tex_tpl = cv2.GaussianBlur(
        np.abs(cv2.Laplacian(cv2.cvtColor(tpl_rgb.astype(np.uint8),
                                          cv2.COLOR_RGB2GRAY),
                             cv2.CV_16S, ksize=3)).astype(np.float32),
        (0, 0), sigmaX=sigma_tex)
    lap_wyn = np.abs(cv2.Laplacian(cv2.cvtColor(wyn_rgb.astype(np.uint8),
                                                cv2.COLOR_RGB2GRAY),
                                   cv2.CV_16S, ksize=3)).astype(np.float32)
    # Tekstura WYNIKU rozmyta tym samym jądrem co tex_tpl — sygnał REGIONALNY
    # „tu wynik ma linie" (re-render ornamentu) vs „płaska farba" (postać);
    # per-pikselowe lap_wyn dawało łatkowatą maskę na cienkich liniach ramki
    tex_wyn = cv2.GaussianBlur(lap_wyn, (0, 0), sigmaX=sigma_tex)
    tpl_plaski = tex_tpl < KLAMP_TEKSTURA_PROG   # czysty krem bez ornamentu

    # Kandydaci (1) kolorowi: znacząca różnica od szablonu (maks. po RGB).
    # W ringu pewności (pas dylatacji okna) próg obniżony — tuż przy oknie
    # wystająca postać jest niemal pewna; obniżka tylko na PŁASKIM szablonie,
    # żeby dryf re-renderu ornamentów ramy nie podmieniał ich na wersję modelu
    ring_kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * KLAMP_RING_PX + 1, 2 * KLAMP_RING_PX + 1))
    ring = (cv2.dilate(core_bin, ring_kernel) > 0) & (core_bin == 0)
    # Schodki progu: ring-płaski 23 / płaski 27 / ornament 38 — na czystym
    # kremie postać odstaje słabiej niż od rysunku, więc próg może być niższy
    prog = np.where(ring & tpl_plaski, KLAMP_PROG_RING,
                    np.where(tpl_plaski, KLAMP_PROG_PLASKI,
                             KLAMP_PROG_ROZNICY))
    cand = np.where(diff > prog, 255, 0).astype(np.uint8)

    # Kandydaci (2) teksturowi: szablon ma rysunek, wynik płaską farbę —
    # postać zamalowała ornament kolorem zbliżonym do szablonu (jasna skóra
    # na kremie), czego różnica kolorów nie widzi.
    cand2 = (tex_tpl > KLAMP_TEKSTURA_PROG) & (lap_wyn < KLAMP_PLASKOSC_PROG)

    # Kandydaci (3) chromatyczni: inna BARWA przy podobnej jasności — na
    # CZYSTYM kremie niski próg (jasne partie postaci poza ornamentem,
    # których nie widzi ani kanał (1), ani (2)); na ORNAMENCIE wyższy próg
    # (skóra/włosy vs różowy grawer — bez tego głowy malowane na ornamencie
    # ginęły; wyższy próg trzyma dryf barwy re-renderu poniżej detekcji)
    lab_wyn = cv2.cvtColor(wyn_rgb.astype(np.uint8),
                           cv2.COLOR_RGB2Lab).astype(np.float32)
    lab_tpl = cv2.cvtColor(tpl_rgb.astype(np.uint8),
                           cv2.COLOR_RGB2Lab).astype(np.float32)
    chroma = np.hypot(lab_wyn[..., 1] - lab_tpl[..., 1],
                      lab_wyn[..., 2] - lab_tpl[..., 2])
    cand3 = np.where(tpl_plaski, chroma > KLAMP_PROG_CHROMA,
                     chroma > KLAMP_PROG_CHROMA_ORNAMENT)

    # Re-render ornamentu ≠ postać: gdzie szablon ma grawer, a wynik NADAL
    # jest teksturowany (model przerysował linie, nie zamalował ich płaską
    # farbą), przywróć szablon — dryf barwy/koloru samego re-renderu graweru
    # nie może udawać sylwetki. Chroni gęsty ornament wokół symbolu (szwy
    # bandingu + podwójny kontur na czarnych kartach), a płaska farba postaci
    # (lap_wyn < KLAMP_PLASKOSC_PROG « KLAMP_ORNAMENT_KEEP_PROG) przeżywa.
    ornament_rerender = (tex_tpl > KLAMP_TEKSTURA_PROG) \
        & (tex_wyn > KLAMP_ORNAMENT_KEEP_PROG)
    cand[ornament_rerender] = 0
    cand2 &= ~ornament_rerender
    cand3 &= ~ornament_rerender

    if kolor_tla is not None:
        # Anty-bleed: rozlanie koloru tła okna na ramę/krem nie jest postacią
        blisko_tla = np.abs(
            wyn_rgb - np.array(kolor_tla, dtype=np.int16)
        ).max(axis=2) <= KLAMP_BLEED_TOL
        cand2 &= ~blisko_tla
        cand3 &= ~blisko_tla
        # Na kartach CZERWONYCH anty-bleed obejmuje też kanał kolorowy:
        # nadmiar przerysowanego, WIĘKSZEGO serca (płaska czerwień poza
        # oknem) wraca do szablonu — rozmiar symbolu jest stały. Na czarnych
        # kolor_tla ≈ ubrania/włosy postaci, więc kanał kolorowy zostaje
        if kolor_tla[0] - max(kolor_tla[1], kolor_tla[2]) \
                >= KLAMP_CZERWIEN_PRZEWAGA:
            cand[blisko_tla] = 0
    cand = cv2.bitwise_or(
        cand, np.where(cand2 | cand3, 255, 0).astype(np.uint8))
    cand = cv2.bitwise_and(cand, allowed)

    # Otwarcie: cienkie krawędziowe szumy graweru (re-render przesuwa linie
    # o pojedyncze piksele) znikają, zwarte plamy postaci zostają
    k_open = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (KLAMP_OTWARCIE_PX, KLAMP_OTWARCIE_PX))
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, k_open)

    # Mostek: małe domknięcie kandydatów — niewykrywalne przesmyki (szyja:
    # skóra ≈ ornament) odcinały głowę od sylwetki, a filtr spójności niżej
    # kasował ją jako plamę „luzem"
    k_most = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (KLAMP_MOSTEK_PX, KLAMP_MOSTEK_PX))
    cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, k_most)
    cand = cv2.bitwise_and(cand, allowed)

    # Tylko komponenty spójne z OKNEM — plamy „luzem" na tle to artefakty
    union = cv2.bitwise_or(cand, core_bin)
    _, labels = cv2.connectedComponents((union > 0).astype(np.uint8),
                                        connectivity=8)
    core_labels = np.unique(labels[core_bin > 0])
    core_labels = core_labels[core_labels != 0]
    component = np.isin(labels, core_labels)
    extra = np.where(component & (core_bin == 0), 255, 0).astype(np.uint8)
    extra = cv2.bitwise_and(extra, allowed)

    # Filtr minimalnego pola: łaty przemalowanej ramy, które przetrwały
    # otwarcie, są małe; sylwetka postaci (głowa, ramiona) o rząd większa.
    # Filtr resztek kolażu: duży komponent szczelnie wypełniający własny
    # bbox to prostokątna resztka zdjęcia (postać ma nieregularny kontur)
    zone = int(np.count_nonzero((allowed_full > 0) & (core_bin == 0)))
    min_pole = KLAMP_MIN_POLE * w * h
    n_comp, lab2, stats, _ = cv2.connectedComponentsWithStats(
        (extra > 0).astype(np.uint8), connectivity=8)
    for i in range(1, n_comp):
        pole = stats[i, cv2.CC_STAT_AREA]
        if pole < min_pole:
            extra[lab2 == i] = 0
            continue
        bbox_pole = stats[i, cv2.CC_STAT_WIDTH] * stats[i, cv2.CC_STAT_HEIGHT]
        if (pole > KLAMP_RESZTKA_MIN_UDZIAL * zone
                and pole >= KLAMP_RESZTKA_WYPELNIENIE * bbox_pole):
            print("[maski] klamp adaptacyjny: prostokątny komponent "
                  f"({pole}px, wypełnienie {pole / bbox_pole:.2f}) wygląda "
                  "na resztkę kolażu — wraca do szablonu")
            extra[lab2 == i] = 0

    # Guardrail przed hurtowym przemalowaniem tła / resztkami kolażu
    if zone == 0 or np.count_nonzero(extra) > KLAMP_MAKS_UDZIAL * zone:
        print("[maski] klamp adaptacyjny: sylwetka pokrywa zbyt dużą część "
              "karty — degradacja do maski pop-out (symbol+ring)")
        return get_popout_mask(template_path)

    # LITE domknięcie sylwetki dużym jądrem: mostkuje dziury detekcji na
    # rysach twarzy (brwi/nos — lokalnie nie-płaskie i w kolorze kremu);
    # artefakty są już odfiltrowane (otwarcie + min. pole), więc duże jądro
    # nie skleja śmieci. Wnętrze maski musi wyjść binarne — częściowa maska
    # po featherze daje półprzezroczysty ghost ornamentu i wyprane kolory.
    # Domknięcie liczone na UNII extra|core: pasma kremowego konturu szablonu
    # przylegające do granicy okna (skóra≈krem, diff < progu) mają maskę
    # tylko z jednej strony — close samego `extra` ich nie mostkował i przez
    # postacie przebijał serc-kształtny „duch" konturu (K_kier_v13)
    close_px = max(KLAMP_DOMKNIECIE_MIN_PX, w // 40) | 1
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                        (close_px, close_px))
    unia = cv2.morphologyEx(cv2.bitwise_or(extra, core_bin),
                            cv2.MORPH_CLOSE, k_close)
    # Domknięte piksele tylko w SĄSIEDZTWIE wykrytej sylwetki: close unii
    # wypełnia też wklęsłości samego okna (wcięcie serca) bez żadnej
    # detekcji obok — tam ma zostać szablon/wypełnienie, nie treść modelu
    k_blisko = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                         (2 * close_px + 1, 2 * close_px + 1))
    blisko_sylwetki = cv2.dilate(extra, k_blisko)
    extra = cv2.bitwise_and(
        unia, cv2.bitwise_and(cv2.bitwise_not(core_bin), blisko_sylwetki))

    # Domykanie dziur: linie/ornament szablonu prześwitujące przez postać
    # (np. kontur wcięcia na czole) są OTOCZONE maską — flood-fill negatywu
    # od rogu karty znajduje prawdziwe tło, reszta to dziury; domykamy tylko
    # małe (duże prześwity, np. tło między ręką a ciałem, zostają szablonem)
    pelna = cv2.bitwise_or(extra, core_bin)
    tlo = np.where(pelna > 0, 0, 255).astype(np.uint8)
    ff = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(tlo, ff, (0, 0), 0)
    if np.any(tlo):
        n_dz, lab_dz, stats_dz, _ = cv2.connectedComponentsWithStats(
            (tlo > 0).astype(np.uint8), connectivity=8)
        maks_dziura = KLAMP_MAKS_DZIURA * w * h
        for i in range(1, n_dz):
            if stats_dz[i, cv2.CC_STAT_AREA] <= maks_dziura:
                extra[lab_dz == i] = 255

    # Lekka dylatacja (antyaliasowany kontur postaci) i wąski feather
    # krawędzi (w//800 — szerszy mieszał szablon z wynikiem na obwodzie
    # sylwetki → wyprane kolory wystających części)
    k_dil = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * KLAMP_DYLATACJA_PX + 1,
                            2 * KLAMP_DYLATACJA_PX + 1))
    extra = cv2.dilate(extra, k_dil)
    extra = cv2.GaussianBlur(extra, (0, 0), sigmaX=max(2, w // 800))
    extra = cv2.bitwise_and(extra, allowed)

    return Image.fromarray(np.maximum(core, extra), mode="L")
