"""Projektowanie pudełka na karty: parsowanie profesjonalnego wykrojnika
(dieline) + kompozycja grafiki AI na jego geometrii + eksport do druku.

Wykrojnik PNG (folder Style/Pudełka/) JEST geometrią — nie rekonstruujemy
paneli ani zakładek. Legenda kolorów w wykrojniku:
  ZIELONY  = spad (bleed)     — obrys obszaru druku (maska clipowania grafiki),
  NIEBIESKI= linia cięcia     — zostaje jako warstwa nadrukowana (proof),
  CZERWONY = bigowanie/zgięcie — jw.
Zielony obrys wyznacza obszar druku; jego bounding box = prostokąt „Design
area" w mm (z sidecara <nazwa>.json). Grafikę AI wciskamy w ten obszar i
przycinamy do wnętrza spadu (jak maska okna symbolu przy kartach), a linie
cięcia/big nakładamy opcjonalnie na wierzch. Eksport w dokładnym rozmiarze
fizycznym: mm→px przez eksport.formaty.mm_na_px (te same przeliczniki co
przy kartach). Cała logika offline — ZERO wywołań API.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app import config
from app.core.eksport.formaty import MM_NA_CAL, mm_na_px

PUDELKA_DIR = config.STYLE_ROOT / "Pudełka"

# Design area (mm) dołączonych wykrojników — odczytane z nagłówków „Dieline
# information" plików użytkownika. Klucz = nazwa pliku PNG. Pre-seed, żeby oba
# pokerowe wykrojniki działały od razu bez pytania o wymiary.
_PRESEED_DESIGN_MM: dict[str, tuple[float, float]] = {
    "pudełko standard-klapka-poker_64×24×89_mm-1.png": (188.2, 251.0),
    "pudelko-2czesciowe-poker_90×65×25_mm-1.png": (464.0, 201.0),
}

# Minimalna część pola największej składowej, żeby uznać obrys za „prawdziwy"
# (odsiewa szum); segmenty legendy odsiewa dodatkowo filtr proporcji.
_MIN_UDZIAL_POLA = 0.03
# Segment legendy to cienka pozioma kreska (aspect ratio ~15); prawdziwe
# obrysy wykrojnika są ~kwadratowe (0.75–1.2). Odrzucamy skrajnie wydłużone.
_MAX_ASPECT = 6.0
# Promień rozmycia tła-podkładu przy wpasowaniu bez przycinania (% krótszego
# boku kadru) — rozmyte przedłużenie grafiki wypełnia wolne miejsce, gdy
# proporcja obrazu ≠ proporcji kadru, więc nic nie trzeba obcinać.
_ROZMYCIE_TLA_PCT = 0.05
# Proporcje (szer/wys) wspierane przez image_config Gemini — do najblizszy_aspect.
_ASPECTY_GEMINI: dict[str, float] = {
    "1:1": 1.0, "2:3": 2 / 3, "3:2": 1.5, "3:4": 0.75, "4:3": 4 / 3,
    "4:5": 0.8, "5:4": 1.25, "9:16": 9 / 16, "16:9": 16 / 9, "21:9": 21 / 9,
}


@dataclass
class Wykrojnik:
    """Sparsowana geometria wykrojnika (wszystkie maski w natywnej
    rozdzielczości PNG, 0/255)."""
    path: Path
    obraz: Image.Image                 # oryginalny PNG (RGB)
    spad: np.ndarray                   # zielony obrys (spad)
    ciecie: np.ndarray                 # niebieskie linie cięcia
    big: np.ndarray                    # czerwone linie bigowania
    wypelnienie: np.ndarray            # wnętrze spadu = obszar druku
    bbox: tuple[int, int, int, int]    # (x, y, w, h) obszaru druku

    @property
    def proporcja(self) -> float:
        _, _, w, h = self.bbox
        return w / h if h else 0.0


# --- biblioteka ---------------------------------------------------------------

def wykrojniki() -> list[Path]:
    """Wszystkie wykrojniki PNG w bibliotece Style/Pudełka/ (posortowane)."""
    if not PUDELKA_DIR.exists():
        return []
    return sorted(p for p in PUDELKA_DIR.glob("*.png") if p.is_file())


def aktywny_wykrojnik() -> Path | None:
    """Wybrany wykrojnik z presetu „pudelko" (style_store.active_dieline);
    fallback = pierwszy z biblioteki. None = biblioteka pusta."""
    from app.core import style_store
    lista = wykrojniki()
    if not lista:
        return None
    wybrany = style_store.active_dieline()
    for p in lista:
        if p.name == wybrany:
            return p
    return lista[0]


def _sidecar(path: Path) -> Path:
    return path.with_suffix(".json")


def design_area_mm(path: Path) -> tuple[float, float] | None:
    """Wymiary „Design area" (mm) wykrojnika: z sidecara <nazwa>.json, a jak go
    brak — z pre-seedu dla dołączonych plików. None → trzeba dopytać
    użytkownika (dialog importu) i zapisać przez zapisz_design_area()."""
    sc = _sidecar(path)
    if sc.exists():
        try:
            data = json.loads(sc.read_text(encoding="utf-8"))
            w, h = data["design_area_mm"]
            return (float(w), float(h))
        except (OSError, ValueError, KeyError, TypeError):
            pass
    seed = _PRESEED_DESIGN_MM.get(path.name)
    if seed is not None:
        zapisz_design_area(path, seed)     # utrwal, żeby edycje były trwałe
        return seed
    return None


def zapisz_design_area(path: Path, design_mm: tuple[float, float],
                       model_id: str = "") -> None:
    """Zapisuje sidecar <nazwa>.json z wymiarami design area (mm)."""
    data: dict[str, object] = {
        "design_area_mm": [round(float(design_mm[0]), 2),
                           round(float(design_mm[1]), 2)]}
    if model_id:
        data["model_id"] = model_id
    try:
        _sidecar(path).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# --- parsowanie ---------------------------------------------------------------

def _maski_kolorow(a: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rozdziela linie wykrojnika po kolorze (progi zweryfikowane na plikach
    użytkownika). Zwraca (zielony, niebieski, czerwony) jako 0/255."""
    R, G, B = a[..., 0].astype(int), a[..., 1].astype(int), a[..., 2].astype(int)
    green = ((G > 120) & (R < 120) & (B < 120)).astype(np.uint8) * 255
    blue = ((B > 120) & (R < 120) & (G < 120)).astype(np.uint8) * 255
    red = ((R > 120) & (G < 90) & (B < 90)).astype(np.uint8) * 255
    return green, blue, red


def _odfiltruj_legende(mask: np.ndarray) -> np.ndarray:
    """Usuwa segmenty legendy z nagłówka: cienkie, wydłużone kreski i drobny
    szum. Zostawia właściwe obrysy wykrojnika (mogą być 2+ dla pudełek
    wieloczęściowych)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if n <= 1:
        return mask
    prog = stats[1:, cv2.CC_STAT_AREA].max() * _MIN_UDZIAL_POLA
    keep = np.zeros_like(mask)
    for i in range(1, n):
        w, h, ar = (int(stats[i, cv2.CC_STAT_WIDTH]),
                    int(stats[i, cv2.CC_STAT_HEIGHT]),
                    int(stats[i, cv2.CC_STAT_AREA]))
        aspect = max(w, h) / max(1, min(w, h))
        if ar >= prog and aspect <= _MAX_ASPECT:
            keep[labels == i] = 255
    return keep


def _wnetrze_obrysow(outline: np.ndarray) -> np.ndarray:
    """Wypełnia wnętrze zamkniętych obrysów (flood-fill tła od rogu + inwersja
    dziur), z małą dylatacją/erozją domykającą drobne przerwy w cienkiej
    linii — jak fill-holes przy maskach okna symbolu."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    zamkniety = cv2.dilate(outline, k, iterations=1)
    h, w = zamkniety.shape
    ff = zamkniety.copy()
    maska = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(ff, maska, (0, 0), 255)          # tło osiągalne z rogu → 255
    dziury = cv2.bitwise_not(ff)                   # niedosięgnięte = wnętrze
    filled = cv2.bitwise_or(zamkniety, dziury)
    return cv2.erode(filled, k, iterations=1)


def parsuj_wykrojnik(path: Path) -> Wykrojnik:
    """Parsuje wykrojnik PNG: maski spad/cięcie/big + wnętrze spadu (obszar
    druku) + bbox obszaru druku (z pominięciem legendy nagłówka)."""
    obraz = Image.open(path).convert("RGB")
    a = np.asarray(obraz)
    green, blue, red = _maski_kolorow(a)
    spad = _odfiltruj_legende(green)
    wypelnienie = _wnetrze_obrysow(spad)
    ys, xs = np.where(wypelnienie > 0)
    if len(xs) == 0:                               # awaryjnie: cały obraz
        bbox = (0, 0, obraz.width, obraz.height)
    else:
        bbox = (int(xs.min()), int(ys.min()),
                int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    return Wykrojnik(path=path, obraz=obraz, spad=spad, ciecie=blue, big=red,
                     wypelnienie=wypelnienie, bbox=bbox)


# --- kompozycja ---------------------------------------------------------------

def target_px(design_mm: tuple[float, float], dpi: int = 300) -> tuple[int, int]:
    """Dokładny rozmiar fizyczny obszaru druku w pikselach przy danym DPI."""
    return (mm_na_px(design_mm[0], dpi), mm_na_px(design_mm[1], dpi))


def _crop_resize(mask: np.ndarray, bbox: tuple[int, int, int, int],
                 target: tuple[int, int]) -> np.ndarray:
    x, y, w, h = bbox
    wyciety = mask[y:y + h, x:x + w]
    return cv2.resize(wyciety, target, interpolation=cv2.INTER_NEAREST)


def najblizszy_aspect(proporcja: float) -> str:
    """Najbliższa proporcja (szer/wys) wspierana przez image_config Gemini —
    twardy hint kadru dla modelu (np. 2.31 → „21:9", 0.72 → „3:4"). Model i tak
    nie honoruje proporcji z tekstu, a `image_config` owszem."""
    if not proporcja or proporcja <= 0:
        return "1:1"
    return min(_ASPECTY_GEMINI, key=lambda k: abs(_ASPECTY_GEMINI[k] - proporcja))


def _wpasuj_bez_uciecia(obraz: Image.Image,
                        target: tuple[int, int]) -> Image.Image:
    """Wpasowuje CAŁY obraz w `target` bez przycinania (contain, wyśrodkowany),
    a wolne miejsce wypełnia ROZMYTĄ, powiększoną wersją tego samego obrazu
    (cover + GaussianBlur) — nic nie ucięte, brak pustych pasów. Zwraca obraz
    dokładnie w rozmiarze `target`. Zastępuje ImageOps.fit (cover+crop), który
    obcinał grafikę pudełka przy proporcji obrazu ≠ proporcji kadru."""
    from PIL import ImageFilter, ImageOps
    rgb = obraz.convert("RGB")
    tw, th = max(1, target[0]), max(1, target[1])
    promien = max(1, round(min(tw, th) * _ROZMYCIE_TLA_PCT))
    baza = ImageOps.fit(rgb, (tw, th), method=Image.Resampling.LANCZOS)
    baza = baza.filter(ImageFilter.GaussianBlur(promien))
    wierzch = ImageOps.contain(rgb, (tw, th), method=Image.Resampling.LANCZOS)
    baza.paste(wierzch, ((tw - wierzch.width) // 2, (th - wierzch.height) // 2))
    return baza


def zloz_pudelko(scena: Image.Image, wykr: Wykrojnik,
                 design_mm: tuple[float, float], *, dpi: int = 300,
                 z_liniami: bool = True) -> Image.Image:
    """Składa grafikę pudełka: scenę AI wpasowuje w obszar druku BEZ obcinania
    (_wpasuj_bez_uciecia — cała grafika widoczna, wolne miejsce = rozmyte tło)
    i przycina do wnętrza spadu, poza spadem zostawia biel. z_liniami=True
    nakłada na wierzch linie cięcia (niebieski) i bigowania (czerwony) — proof
    do podglądu; False = czysty artwork (dla drukarni z osobną warstwą
    dieline). Wynik ma DOKŁADNY rozmiar fizyczny (design_mm @ dpi)."""
    target = target_px(design_mm, dpi)
    fill = _crop_resize(wykr.wypelnienie, wykr.bbox, target)

    plotno = Image.new("RGB", target, "white")
    scena_fit = _wpasuj_bez_uciecia(scena, target)
    plotno.paste(scena_fit, (0, 0), Image.fromarray(fill).convert("L"))

    if z_liniami:
        arr = np.asarray(plotno).copy()
        ciecie = _crop_resize(wykr.ciecie, wykr.bbox, target)
        big = _crop_resize(wykr.big, wykr.bbox, target)
        arr[ciecie > 0] = (0, 90, 220)      # niebieski — linia cięcia
        arr[big > 0] = (210, 40, 40)        # czerwony — bigowanie/zgięcie
        plotno = Image.fromarray(arr)
    return plotno


def dopasuj_wlasny(obraz: Image.Image, wykr: Wykrojnik,
                   design_mm: tuple[float, float], dpi: int = 300) -> Image.Image:
    """Wgrany własny projekt (płaski artwork) dopasowany do obszaru druku —
    jak zloz_pudelko, ale bez linii (użytkownik dostarcza gotową grafikę)."""
    return zloz_pudelko(obraz, wykr, design_mm, dpi=dpi, z_liniami=False)


# --- segmentacja na panele (tryb „osobne panele") ------------------------------

# dylatacja ścian (big∪cięcie) — rozdziela sąsiednie panele przy segmentacji
_SCIANA_DYL_PX = 9
# erozja masek paneli — odsuwa je od linii (żeby art nie właził na cięcie/big)
_PANEL_ERODE_PX = 5
# min. pole panelu względem największego (odsiewa klapki/szum)
_PANEL_MIN_UDZIAL = 0.04
# proporcja panelu uznawana za „twarz" (kartowy/prostokątny front/tył)
_TWARZ_ASPECT_MIN, _TWARZ_ASPECT_MAX = 0.4, 2.5
# twarz musi mieć pole ≥ tej części największego panelu (front/tył są duże;
# drobne prostokątne klapki NIE są twarzami)
_TWARZ_MIN_UDZIAL = 0.5
# bok musi mieć pole ≥ tej części największego (mniejsze panele = klapka/tint)
_BOK_MIN_UDZIAL = 0.12


@dataclass
class Panel:
    """Pojedynczy panel wykrojnika wykryty między liniami cięcia/bigowania."""
    maska: np.ndarray                  # 0/255, natywna rozdzielczość
    bbox: tuple[int, int, int, int]    # x, y, w, h
    rola: str                          # "przod"|"tyl"|"bok"|"klapka"
    pole: int
    cx: float
    cy: float

    @property
    def aspect(self) -> float:
        _, _, w, h = self.bbox
        return w / h if h else 0.0


def _przypisz_role(panele: list[Panel]) -> None:
    """Nadaje role po geometrii: największy panel kartowy = przód, kolejne
    kartowe = tył, wąskie/szerokie panele = boki, reszta = klapki."""
    maks = max(p.pole for p in panele)
    wg_pola = sorted(panele, key=lambda p: -p.pole)
    twarze = [p for p in wg_pola
              if p.pole >= maks * _TWARZ_MIN_UDZIAL
              and _TWARZ_ASPECT_MIN <= p.aspect <= _TWARZ_ASPECT_MAX]
    if twarze:
        twarze[0].rola = "przod"
        for p in twarze[1:]:
            p.rola = "tyl"
    for p in wg_pola:
        if (p.rola == "klapka" and p.pole >= maks * _BOK_MIN_UDZIAL
                and not (_TWARZ_ASPECT_MIN <= p.aspect <= _TWARZ_ASPECT_MAX)):
            p.rola = "bok"


def segmentuj_panele(wykr: Wykrojnik) -> list[Panel]:
    """Dzieli obszar druku na panele: ściany = big∪cięcie (dylatowane),
    panele = spójne składowe (wypełnienie & ~ściany), z odsianiem klapek i
    przypisaniem ról (przód/tył/bok/klapka)."""
    sciany = cv2.bitwise_or(wykr.big, wykr.ciecie)
    ks = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                   (_SCIANA_DYL_PX, _SCIANA_DYL_PX))
    sciany = cv2.dilate(sciany, ks, iterations=1)
    wnetrze = cv2.bitwise_and(wykr.wypelnienie, cv2.bitwise_not(sciany))
    ke = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                   (_PANEL_ERODE_PX, _PANEL_ERODE_PX))
    wnetrze = cv2.erode(wnetrze, ke, iterations=1)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(wnetrze,
                                                           connectivity=8)
    if n <= 1:
        return []
    maks = int(stats[1:, cv2.CC_STAT_AREA].max())
    panele: list[Panel] = []
    for i in range(1, n):
        pole = int(stats[i, cv2.CC_STAT_AREA])
        if pole < maks * _PANEL_MIN_UDZIAL:
            continue
        bbox = (int(stats[i, cv2.CC_STAT_LEFT]), int(stats[i, cv2.CC_STAT_TOP]),
                int(stats[i, cv2.CC_STAT_WIDTH]), int(stats[i, cv2.CC_STAT_HEIGHT]))
        maska = np.where(lab == i, 255, 0).astype(np.uint8)
        panele.append(Panel(maska=maska, bbox=bbox, rola="klapka", pole=pole,
                            cx=float(cent[i][0]), cy=float(cent[i][1])))
    _przypisz_role(panele)
    return panele


def liczba_twarzy(panele: list[Panel]) -> int:
    return sum(1 for p in panele if p.rola in ("przod", "tyl"))


def boki_rozmiary(wykr: Wykrojnik, design_mm: tuple[float, float],
                  dpi: int = 300) -> list[tuple[int, int]]:
    """Rozmiary docelowe (px) paneli-boków w TEJ SAMEJ kolejności, w jakiej
    zloz_pudelko_panele je składa — generator buduje pod nie wachlarze mini-kart
    do AI-restylingu (osobna scena/bok)."""
    target = target_px(design_mm, dpi)
    _, _, bw, bh = wykr.bbox
    sx, sy = target[0] / bw, target[1] / bh
    rozmiary: list[tuple[int, int]] = []
    for panel in segmentuj_panele(wykr):
        if panel.rola == "bok":
            _, _, pw, ph = panel.bbox
            rozmiary.append((max(1, int(pw * sx)), max(1, int(ph * sy))))
    return rozmiary


@lru_cache(maxsize=64)
def _karta_zrodlo(path_str: str, mtime: float, maks_px: int = 600) -> Image.Image:
    """Zdekodowana, POMNIEJSZONA (≤ maks_px) karta RGB — cache po (ścieżka,
    mtime). Boki renderują wachlarz z kilkunastu paneli × 2 przebiegi, więc bez
    cache ta sama karta byłaby dekodowana z pełnej rozdzielczości setki razy."""
    im = Image.open(path_str).convert("RGB")
    im.thumbnail((maks_px, maks_px), Image.Resampling.LANCZOS)
    return im


def wizualizacja_kart(karty: list[Path], rozmiar: tuple[int, int],
                      tlo: str | None = None) -> Image.Image:
    """Wachlarz miniatur PRAWDZIWYCH kart talii dla panelu bocznego („to, co
    jest w opakowaniu") — ZERO API. Układ kolumnowy dla wysokiego panelu,
    rzędowy dla szerokiego; karty lekko obrócone i nachodzące. Fallback: brak
    kart → jednolite tło w kolorze talii."""
    from PIL import ImageOps
    w, h = max(1, rozmiar[0]), max(1, rozmiar[1])
    out = Image.new("RGB", (w, h), tlo or config.CREAM_HEX)
    obrazy: list[Image.Image] = []
    for p in karty[:6]:
        try:
            obrazy.append(_karta_zrodlo(str(p), Path(p).stat().st_mtime))
        except (OSError, ValueError):
            continue
    if not obrazy:
        return out

    n = len(obrazy)
    pion = h >= w
    rw, rh = config.CARD_RATIO
    short = min(w, h)
    kw = max(1, int(short * 0.7))
    kh = max(1, int(kw * rh / rw))
    warstwa = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    for idx, im in enumerate(obrazy):
        mini = ImageOps.fit(im, (kw, kh),
                            method=Image.Resampling.LANCZOS).convert("RGBA")
        angle = -7 if idx % 2 else 7
        mini = mini.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC,
                           fillcolor=(0, 0, 0, 0))
        if pion:
            dostepne = max(0, h - mini.height)
            y = int(dostepne * idx / max(1, n - 1)) if n > 1 else dostepne // 2
            x = (w - mini.width) // 2
        else:
            dostepne = max(0, w - mini.width)
            x = int(dostepne * idx / max(1, n - 1)) if n > 1 else dostepne // 2
            y = (h - mini.height) // 2
        warstwa.alpha_composite(mini, (x, y))
    out.paste(warstwa, (0, 0), warstwa)
    return out


def zloz_pudelko_panele(obrazy: dict[str, Image.Image], wykr: Wykrojnik,
                        design_mm: tuple[float, float], *,
                        karty_boki: list[Path] | None = None,
                        boki_ai: list[Image.Image] | None = None,
                        tlo_boku: str | None = None,
                        dpi: int = 300, z_liniami: bool = True) -> Image.Image:
    """Składa pudełko z OSOBNYCH paneli: każda rola (przod/tyl) dostaje swój
    obraz wpasowany BEZ obcinania (_wpasuj_bez_uciecia) w bbox swojego panelu
    i przycięty do jego maski — bez rozciągania przez linie zgięć. Boki: gdy
    podane `boki_ai` (AI-restyling wachlarza mini-kart) — kolejne obrazy per
    bok; inaczej `wizualizacja_kart` z `karty_boki` na jednolitym tle
    `tlo_boku`. `tlo_boku` (hex) barwi też bazę spadu/klapek — cały spód
    pudełka jeden kolor (koniec białych/czarnych łat). z_liniami nakłada
    cięcie/big (proof)."""
    baza_hex = tlo_boku or config.CREAM_HEX
    target = target_px(design_mm, dpi)
    panele = segmentuj_panele(wykr)
    fill = _crop_resize(wykr.wypelnienie, wykr.bbox, target)

    plotno = Image.new("RGB", target, "white")
    tint = Image.new("RGB", target, baza_hex)
    plotno.paste(tint, (0, 0), Image.fromarray(fill).convert("L"))

    x0, y0, bw, bh = wykr.bbox
    sx, sy = target[0] / bw, target[1] / bh
    bok_idx = 0
    for panel in panele:
        px, py, pw, ph = panel.bbox
        tx, ty = int((px - x0) * sx), int((py - y0) * sy)
        tpw, tph = max(1, int(pw * sx)), max(1, int(ph * sy))
        if panel.rola == "bok":
            if boki_ai:
                art = _wpasuj_bez_uciecia(boki_ai[bok_idx % len(boki_ai)],
                                          (tpw, tph))
            else:
                art = wizualizacja_kart(karty_boki or [], (tpw, tph),
                                        tlo=baza_hex)
            bok_idx += 1
        else:
            obraz = obrazy.get(panel.rola)
            if obraz is None and panel.rola == "tyl":
                obraz = obrazy.get("przod")
            if obraz is None:
                continue                       # klapka → zostaje tint
            art = _wpasuj_bez_uciecia(obraz, (tpw, tph))
        maska_bbox = panel.maska[py:py + ph, px:px + pw]
        maska_t = cv2.resize(maska_bbox, (tpw, tph),
                             interpolation=cv2.INTER_NEAREST)
        plotno.paste(art, (tx, ty), Image.fromarray(maska_t).convert("L"))

    if z_liniami:
        arr = np.asarray(plotno).copy()
        ciecie = _crop_resize(wykr.ciecie, wykr.bbox, target)
        big = _crop_resize(wykr.big, wykr.bbox, target)
        arr[ciecie > 0] = (0, 90, 220)
        arr[big > 0] = (210, 40, 40)
        plotno = Image.fromarray(arr)
    return plotno


# --- eksport ------------------------------------------------------------------

def eksportuj_png(obraz: Image.Image, out_path: Path,
                  design_mm: tuple[float, float]) -> Path:
    """Zapis PNG z metadanymi DPI tak, by wydruk miał dokładnie design_mm."""
    dpi = (obraz.width / (design_mm[0] / MM_NA_CAL),
           obraz.height / (design_mm[1] / MM_NA_CAL))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    obraz.save(out_path, "PNG", dpi=dpi)
    return out_path


def eksportuj_pdf_cmyk(obraz: Image.Image, out_path: Path,
                       design_mm: tuple[float, float], *,
                       nasycenie: float | None = None) -> Path:
    """Zapis PDF w CMYK (strona = rozmiar wykrojnika) z podbiciem nasycenia
    (kompensuje węższy gamut CMYK — kolory żywe jak w RGB) i osadzonym profilem
    ICC, gdy dostępny. Grafika CMYK jako JPEG q92 (wzór eksportuj_pdf)."""
    import io

    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    from app.core.eksport.cmyk import NASYCENIE_DRUKU, rgb_na_cmyk

    nas = NASYCENIE_DRUKU if nasycenie is None else nasycenie
    cmyk, icc = rgb_na_cmyk(obraz.convert("RGB"), nasycenie=nas)
    pt = (design_mm[0] / MM_NA_CAL * 72.0, design_mm[1] / MM_NA_CAL * 72.0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = pdf_canvas.Canvas(str(out_path), pagesize=pt)
    c.setTitle(f"Atelier Kart — pudełko CMYK {out_path.stem}")
    buf = io.BytesIO()
    zapis: dict = {"quality": 92}
    if icc is not None:
        zapis["icc_profile"] = icc
    cmyk.save(buf, "JPEG", **zapis)
    buf.seek(0)
    c.drawImage(ImageReader(buf), 0, 0, width=pt[0], height=pt[1])
    c.showPage()
    c.save()
    return out_path


def eksportuj_pdf(obraz: Image.Image, out_path: Path,
                  design_mm: tuple[float, float]) -> Path:
    """Zapis PDF o stronie w rozmiarze wykrojnika (mm→punkty), grafika osadzona
    1:1 jako JPEG q92 (wzór eksport.wyjscia.WyjsciePDF, ale pagesize =
    rozmiar pudełka, nie A4)."""
    import io

    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdf_canvas

    pt = (design_mm[0] / MM_NA_CAL * 72.0, design_mm[1] / MM_NA_CAL * 72.0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = pdf_canvas.Canvas(str(out_path), pagesize=pt)
    c.setTitle(f"Atelier Kart — pudełko {out_path.stem}")
    buf = io.BytesIO()
    obraz.convert("RGB").save(buf, "JPEG", quality=92)
    buf.seek(0)
    c.drawImage(ImageReader(buf), 0, 0, width=pt[0], height=pt[1])
    c.showPage()
    c.save()
    return out_path


# --- historia wariantów --------------------------------------------------------
# Każda generacja/import/poprawka tworzy WARIANT (para plików raw+proof) w
# Style/pudelko/<preset>/historia/. „Główny" wariant jest kopiowany do stałych
# ścieżek roboczych (box_glowny_raw/box_glowny_proof), których używa reszta
# potoku (podgląd, eksport, poprawka) — dzięki temu przełączanie wariantu jest
# zwykłym skopiowaniem, bez zmian w innych modułach.

def box_glowny_raw() -> Path:
    """Surowy artwork GŁÓWNEGO wariantu (bez linii) — baza eksportu/poprawek."""
    from app.core import style_store
    return config.RAW_DIR / f"pudelko_{style_store.active('pudelko')}.png"


def box_glowny_proof() -> Path:
    """Proof (z liniami) GŁÓWNEGO wariantu — podgląd talii."""
    from app.core import style_store
    return style_store.box_path()


def _historia_dir() -> Path:
    return box_glowny_proof().parent / "historia"


def sciezki_wariantu(stamp: str) -> tuple[Path, Path]:
    """(raw, proof) plików wariantu o danym stempelu."""
    d = _historia_dir()
    return d / f"{stamp}_raw.png", d / f"{stamp}_proof.png"


def warianty_pudelka() -> list[str]:
    """Stemple wariantów pudełka, od NAJNOWSZEGO."""
    d = _historia_dir()
    if not d.exists():
        return []
    stamps = sorted((p.name[:-len("_proof.png")] for p in d.glob("*_proof.png")),
                    reverse=True)
    return stamps


def glowny_stamp() -> str | None:
    """Stempel aktualnie głównego wariantu (z historia/glowna.txt)."""
    f = _historia_dir() / "glowna.txt"
    try:
        stamp = f.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return stamp or None


def _unikalny_stamp(d: Path) -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base, i = stamp, 1
    while (d / f"{stamp}_proof.png").exists():
        i += 1
        stamp = f"{base}_{i}"
    return stamp


def ustaw_glowny_wariant(stamp: str) -> Path:
    """Ustawia wariant jako główny: kopiuje jego pliki do ścieżek roboczych
    (raw/proof) i zapisuje wskaźnik. Zwraca proof główny."""
    raw_h, proof_h = sciezki_wariantu(stamp)
    if not (raw_h.exists() and proof_h.exists()):
        raise FileNotFoundError(f"Brak wariantu pudełka {stamp}")
    graw, gproof = box_glowny_raw(), box_glowny_proof()
    graw.parent.mkdir(parents=True, exist_ok=True)
    gproof.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(raw_h, graw)
    shutil.copyfile(proof_h, gproof)
    (_historia_dir() / "glowna.txt").write_text(stamp, encoding="utf-8")
    return gproof


def _seed_z_glownego() -> None:
    """Przy pustej historii, a istniejącym GŁÓWNYM pliku (pudełko sprzed
    wprowadzenia historii) — archiwizuje go jako pierwszy wariant, by nie
    przepadł przy pierwszym nowym zapisie."""
    gproof = box_glowny_proof()
    if warianty_pudelka() or not gproof.exists():
        return
    stamp = datetime.fromtimestamp(gproof.stat().st_mtime).strftime(
        "%Y%m%d_%H%M%S")
    raw_h, proof_h = sciezki_wariantu(stamp)
    shutil.copyfile(gproof, proof_h)
    graw = box_glowny_raw()
    shutil.copyfile(graw if graw.exists() else gproof, raw_h)


def zapisz_wariant_pudelka(raw: Image.Image, proof: Image.Image) -> Path:
    """Zapisuje NOWY wariant do historii i ustawia go jako główny. Zwraca
    proof główny (podgląd). Przy pustej historii archiwizuje wcześniejszy
    główny plik, by nie przepadł."""
    d = _historia_dir()
    d.mkdir(parents=True, exist_ok=True)
    _seed_z_glownego()
    stamp = _unikalny_stamp(d)
    raw_h, proof_h = sciezki_wariantu(stamp)
    raw.save(raw_h)
    proof.save(proof_h)
    return ustaw_glowny_wariant(stamp)
