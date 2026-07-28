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
    # oryginalne PDF-y z drukarni (źródło prawdy — patrz wykrojniki())
    "pudełko standard-klapka-poker_64×24×89_mm.pdf": (188.2, 251.0),
    "pudelko-2czesciowe-poker_90×65×25_mm.pdf": (464.0, 201.0),
}

# DPI rasteryzacji wektorowego wykrojnika PDF do parsowania/kompozycji. 300 =
# ten sam target co eksport, więc maski linii wychodzą 1:1 (bez skalowania).
_PDF_RASTER_DPI = 300
# Sufiks pliku-cache rastra PDF (wykluczany z listy wykrojników).
_RASTER_TAG = ".raster_"

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
    """Wykrojniki biblioteki Style/Pudełka/ (posortowane). Oryginalne PDF-y
    z drukarni są ŹRÓDŁEM PRAWDY; legacy PNG pokazujemy tylko, gdy nie mają
    odpowiadającego PDF-a. Pliki-cache rastra PDF (_RASTER_TAG) są pomijane."""
    if not PUDELKA_DIR.exists():
        return []
    pdfy = sorted(p for p in PUDELKA_DIR.glob("*.pdf") if p.is_file())
    bazy_pdf = {p.stem for p in pdfy}
    pngi: list[Path] = []
    for p in sorted(PUDELKA_DIR.glob("*.png")):
        if not p.is_file() or _RASTER_TAG in p.name:
            continue
        baza = p.stem[:-2] if p.stem.endswith("-1") else p.stem
        if baza in bazy_pdf:                       # legacy raster PDF-a → pomiń
            continue
        pngi.append(p)
    return pdfy + pngi


def _raster_z_pdf(path: Path, dpi: int = _PDF_RASTER_DPI) -> Path:
    """Rasteryzuje pierwszą stronę wektorowego wykrojnika PDF do PNG obok pliku
    (cache z mtime-guard) i zwraca ścieżkę rastra. Wymaga PyMuPDF (import fitz
    leniwy — narzędzia offline nie potrzebujące PDF-a działają bez zależności)."""
    cache = path.with_name(f"{path.stem}{_RASTER_TAG}{dpi}.png")
    if cache.exists() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache
    import fitz                                     # PyMuPDF
    doc = fitz.open(path)
    try:
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()
    img.save(cache)
    return cache


def zrodlo_rastra(path: Path) -> Path:
    """Ścieżka obrazu do parsowania: raster dla PDF, sam plik dla PNG."""
    return _raster_z_pdf(path) if path.suffix.lower() == ".pdf" else path


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
    """Parsuje wykrojnik (PDF rasteryzowany lub PNG): maski spad/cięcie/big +
    wnętrze spadu (obszar druku) + bbox obszaru druku (z pominięciem legendy
    nagłówka). `Wykrojnik.path` zostaje ORYGINALNY (PDF) — potrzebny eksportowi
    na wykrojnik drukarni; obraz to raster."""
    obraz = Image.open(zrodlo_rastra(path)).convert("RGB")
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


# --- deterministyczna kompozycja osób (tryb „osoby") --------------------------
# Chroma tła restylowanych portretów (model prosimy o pełne, płaskie #00FF00,
# potem wycinamy je progowaniem — bez modelu do mattingu).
CHROMA_HEX = "#00FF00"
_CHROMA_RGB = (0, 255, 0)
# Próg odległości RGB od chromy uznawany za tło (suma |Δ| po kanałach).
_CHROMA_PROG = 120
# Gdy wycinek pokrywa <5% lub >98% kadru, chroma jest nieczysta → traktuj obraz
# jako pełny prostokąt (fallback: postać na kafelce, układ/liczba zachowane).
_CHROMA_MIN, _CHROMA_MAX = 0.05, 0.98
# Minimalny udział pikseli zielonych, przy którym uznajemy, że model ZROBIŁ
# chroma-tło (wtedy wycinamy chromą). Poniżej → model narysował scenę → grabCut.
_CHROMA_TLO_MIN = 0.12


def _najwieksza_skladowa(maska: np.ndarray) -> np.ndarray:
    """Zostaw tylko NAJWIĘKSZĄ spójną składową maski 0/255 (jedna sylwetka).
    Gwarantuje jedną osobę na slot — druga postać dorysowana przez model jest
    odcinana."""
    n, lab, stats, _ = cv2.connectedComponentsWithStats(maska, connectivity=8)
    if n <= 2:                                       # tło + ≤1 obiekt = nic do cięcia
        return maska
    najw = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return np.where(lab == najw, 255, 0).astype(np.uint8)


def wytnij_na_chromie(img: Image.Image, *, prog: int = _CHROMA_PROG,
                      tylko_najwieksza: bool = True) -> Image.Image:
    """Wycina postać z jednolitego chroma-tła (#00FF00): piksele bliskie chromie
    → alfa 0. Otwarcie/domknięcie kasuje szum, feather wygładza krawędź. Zwraca
    RGBA. `tylko_najwieksza` (domyślnie) zostawia największą sylwetkę — twarda
    gwarancja JEDNEJ osoby na slot. Gdy chroma nieczysta (pokrycie skrajne) →
    obraz w całości nieprzezr. (fallback prostokątny)."""
    rgb = img.convert("RGB")
    a = np.asarray(rgb).astype(int)
    diff = np.abs(a - np.array(_CHROMA_RGB)).sum(axis=2)
    fg = (diff >= prog).astype(np.uint8) * 255       # nie-chroma = postać
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k)
    udzial = float(fg.mean()) / 255.0
    out = rgb.convert("RGBA")
    if udzial < _CHROMA_MIN or udzial > _CHROMA_MAX:  # brak czytelnej chromy
        return out
    if tylko_najwieksza:
        fg = _najwieksza_skladowa(fg)
    alpha = cv2.GaussianBlur(fg, (0, 0), 1.5)
    out.putalpha(Image.fromarray(alpha))
    return out


_HAAR_TWARZ = None


def _detektor_twarzy():
    """Kaskada Haar do wykrywania twarzy (lazy-cache) z zasobów OpenCV."""
    global _HAAR_TWARZ
    if _HAAR_TWARZ is None:
        _HAAR_TWARZ = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    return _HAAR_TWARZ


def wykadruj_twarz(img: Image.Image, margines: float = 0.6) -> Image.Image:
    """Przycina obraz do NAJWIĘKSZEJ wykrytej twarzy, poszerzonej o `margines`
    (włosy/broda/ramiona) — referencja restylingu skupia model na TWARZY, nie na
    tle i pozie. Brak wykrytej twarzy → zwraca oryginał (bez regresji)."""
    rgb = img.convert("RGB")
    a = np.asarray(rgb)
    gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    twarze = _detektor_twarzy().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
    if len(twarze) == 0:
        return rgb
    x, y, w, h = max(twarze, key=lambda f: int(f[2]) * int(f[3]))
    mx, my = int(w * margines), int(h * margines)
    x0, y0 = max(0, int(x) - mx), max(0, int(y) - my)
    x1 = min(a.shape[1], int(x) + int(w) + mx)
    y1 = min(a.shape[0], int(y) + int(h) + my)
    return rgb.crop((x0, y0, x1, y1))


def wytnij_osobe(img: Image.Image) -> Image.Image:
    """Wycina DOKŁADNIE JEDNĄ osobę z obrazu restylingu, NIEZALEŻNIE od tła.

    - Model zrobił zielone tło (chroma > _CHROMA_TLO_MIN) → `wytnij_na_chromie`.
    - Model narysował SCENĘ (brak zieleni) → grabCut wokół największej twarzy
      (lub środka kadru) → pierwszy plan → największa spójna składowa. NIE wkleja
      całej sceny (koniec „nałożonych zdjęć / dodatkowych postaci").
    Zawsze RGBA z jedną sylwetką."""
    rgb = img.convert("RGB")
    a = np.asarray(rgb)
    diff = np.abs(a.astype(int) - np.array(_CHROMA_RGB)).sum(axis=2)
    if float((diff < _CHROMA_PROG).mean()) > _CHROMA_TLO_MIN:
        return wytnij_na_chromie(rgb, tylko_najwieksza=True)

    h, w = a.shape[:2]
    gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    twarze = _detektor_twarzy().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))
    if len(twarze):
        fx, fy, fw, fh = max(twarze, key=lambda f: int(f[2]) * int(f[3]))
        cx = int(fx) + int(fw) // 2
        pw = min(w, int(fw * 3.2))
        rx = max(0, cx - pw // 2)
        rw = min(w - rx, pw)
        ry = max(0, int(fy) - int(fh * 0.8))
        rh = h - ry
    else:                                            # brak twarzy → środek kadru
        rx, ry = int(w * 0.15), int(h * 0.05)
        rw, rh = int(w * 0.7), int(h * 0.93)
    rect = (rx, ry, max(1, rw), max(1, rh))

    maska = np.zeros((h, w), np.uint8)
    bgr = cv2.cvtColor(a, cv2.COLOR_RGB2BGR)
    try:
        cv2.grabCut(bgr, maska, rect, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), 3, cv2.GC_INIT_WITH_RECT)
        fg = np.where((maska == cv2.GC_FGD) | (maska == cv2.GC_PR_FGD),
                      255, 0).astype(np.uint8)
    except Exception:
        fg = np.zeros((h, w), np.uint8)
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k)
    fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k)
    if fg.max() == 0:                                # grabCut nic nie dał → rect
        fg[ry:ry + rh, rx:rx + rw] = 255
    fg = _najwieksza_skladowa(fg)
    alpha = cv2.GaussianBlur(fg, (0, 0), 1.5)
    out = rgb.convert("RGBA")
    out.putalpha(Image.fromarray(alpha))
    return out


def osoby_z_folderu(folder: Path) -> list[list[Path]]:
    """Wykrywa osoby ze wskazanego folderu wg schematu „1 podfolder = 1 osoba".

    - Podfoldery zawierające obrazy → każdy podfolder to JEDNA osoba (jej zdjęcia,
      posortowane), liczba osób = liczba podfolderów.
    - Brak podfolderów z obrazami → luźne pliki obrazów = 1 plik/osoba
      (kompatybilność wstecz).
    Sort deterministyczny; puste/nieobsługiwane pomijane. Pusty wynik = brak
    użytecznych zdjęć."""
    d = Path(folder)
    if not folder or not d.is_dir():
        return []
    exts = (".jpg", ".jpeg", ".png", ".webp")
    def obrazy(kat: Path) -> list[Path]:
        return sorted(p for p in kat.iterdir()
                      if p.is_file() and p.suffix.lower() in exts)
    osoby: list[list[Path]] = []
    for sub in sorted(p for p in d.iterdir() if p.is_dir()):
        zdj = obrazy(sub)
        if zdj:
            osoby.append(zdj)
    if osoby:
        return osoby
    return [[p] for p in obrazy(d)]                  # fallback: 1 plik = 1 osoba


def _rozloz_rzad(warstwa: Image.Image, rzad: list[Image.Image],
                 W: int, y_dol: int) -> None:
    """Układa jeden rząd wycinków (RGBA) wyśrodkowany w szerokości W, kotwiczony
    dołem na y_dol; przy nadmiarze szerokości robi overlap (krok < szerokość)."""
    m = len(rzad)
    if m == 0:
        return
    margines = int(W * 0.03)
    dost = max(1, W - 2 * margines)
    suma_w = sum(im.width for im in rzad)
    luka = 0
    if m == 1:
        krok = 0
        start = (W - rzad[0].width) // 2
    elif suma_w <= dost:
        # mieszczą się bez nachodzenia — równy odstęp, wyśrodkowanie
        luka = (dost - suma_w) // (m - 1)
        krok = None                                   # znacznik: sekwencyjnie
        start = margines
    else:
        # overlap: równy krok środek-do-środka
        krok = (dost - rzad[-1].width) // (m - 1)
        start = margines
        luka = 0
    x = start
    for im in rzad:
        x = max(0, min(W - im.width, x))
        warstwa.alpha_composite(im, (x, max(0, y_dol - im.height)))
        x += (im.width + luka) if krok is None else krok


def zbuduj_scene_osob(wycinki: list[Image.Image], rozmiar: tuple[int, int],
                      tlo: Image.Image | str) -> Image.Image:
    """Deterministyczna scena okładki: tło (obraz cover-fit lub jednolity hex)
    + N postaci-wycinków ułożonych PO KOLEI (każdy dokładnie raz — gwarancja
    liczby i braku powtórzeń). Układ = SIATKA dobrana do proporcji panelu i N,
    tak by KAŻDA z N osób była widoczna (przy wielu osobach wiele rzędów, nie
    jeden zatłoczony). Postaci kotwiczone dołem swojego rzędu."""
    import math

    from PIL import ImageOps
    W, H = max(1, rozmiar[0]), max(1, rozmiar[1])
    if isinstance(tlo, Image.Image):
        base = ImageOps.fit(tlo.convert("RGB"), (W, H),
                            method=Image.Resampling.LANCZOS)
    else:
        base = Image.new("RGB", (W, H), tlo)
    n = len(wycinki)
    if n == 0:
        return base

    # kolumny proporcjonalne do proporcji panelu i N (0.55 ≈ proporcja biustu),
    # rzędy = tyle, by wszyscy się zmieścili
    kol = max(1, min(n, round(math.sqrt(max(1e-6, n * (W / H) / 0.55)))))
    rzedy = math.ceil(n / kol)
    cell_h = H / rzedy
    ph = max(1, int(cell_h * 0.9))                    # wysokość osoby w rzędzie

    skal: list[Image.Image] = []
    for im in wycinki:
        r = ph / max(1, im.height)
        skal.append(im.convert("RGBA").resize(
            (max(1, int(im.width * r)), ph), Image.Resampling.LANCZOS))

    warstwa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for r in range(rzedy):
        rzad = skal[r * kol:(r + 1) * kol]
        y_dol = int((r + 1) * cell_h - cell_h * 0.04)  # kotwica dołem pasa rzędu
        _rozloz_rzad(warstwa, rzad, W, y_dol)
    base = base.convert("RGBA")
    base.alpha_composite(warstwa)
    return base.convert("RGB")


def uloz_obok_siebie(wycinki: list[Image.Image], rozmiar: tuple[int, int],
                     *, tasuj: bool = True, tlo: str | None = None
                     ) -> Image.Image:
    """Postacie OBOK SIEBIE, jeden rząd, na neutralnym tle — wejście do
    AI-kompozycji sceny (model widzi wyraźnie N osobnych osób). `tasuj` = losowa
    kolejność (model ma je dopiero ustawić). Postacie skalowane do jednej
    wysokości, kotwiczone dołem, równe odstępy."""
    import random as _random

    W, H = max(1, rozmiar[0]), max(1, rozmiar[1])
    base = Image.new("RGB", (W, H), tlo or config.CREAM_HEX)
    items = list(wycinki)
    if tasuj:
        _random.shuffle(items)
    if not items:
        return base
    ph = max(1, int(H * 0.86))
    skal = [im.convert("RGBA").resize(
        (max(1, int(im.width * ph / max(1, im.height))), ph),
        Image.Resampling.LANCZOS) for im in items]
    warstwa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _rozloz_rzad(warstwa, skal, W, int(H * 0.97))
    base = base.convert("RGBA")
    base.alpha_composite(warstwa)
    return base.convert("RGB")


# --- magazyn zaakceptowanych postaci (tryb „Reżyser sceny") --------------------

def postacie_dir() -> Path:
    """Folder zaakceptowanych postaci aktywnego presetu pudełka (RGBA PNG)."""
    return box_glowny_proof().parent / "postacie"


def sciezka_postaci(i: int, nazwa: str = "") -> Path:
    """Ścieżka pliku postaci nr i (opcjonalnie z czytelnym sufiksem nazwy)."""
    slug = "".join(c for c in nazwa if c.isalnum() or c in "-_") [:24]
    stem = f"{i:02d}_{slug}" if slug else f"{i:02d}"
    return postacie_dir() / f"{stem}.png"


# --- segmentacja na panele (tryb „osobne panele") ------------------------------

# dylatacja ścian (big∪cięcie) — rozdziela sąsiednie panele przy segmentacji
_SCIANA_DYL_PX = 9
# erozja masek paneli — odsuwa je od linii (żeby art nie właził na cięcie/big)
_PANEL_ERODE_PX = 5
# min. pole panelu względem największego (odsiewa klapki/szum)
_PANEL_MIN_UDZIAL = 0.04
# dosunięcie panelu z powrotem DO linii zgięcia przy składaniu (cofa erozję
# panelu + połowę dylatacji ściany) — łączenia kończą się równo na liniach,
# bez brązowych szpar między panelami
_PANEL_DOSUN_PX = _SCIANA_DYL_PX + _PANEL_ERODE_PX + 2
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


def rozmiar_panelu(wykr: Wykrojnik, design_mm: tuple[float, float], rola: str,
                   dpi: int = 300) -> tuple[int, int] | None:
    """Rozmiar docelowy (px) PIERWSZEGO panelu danej roli („przod"/„tyl") —
    do budowy sceny osób w proporcji panelu (mniej docięcia przy cover-fit w
    zloz_pudelko_panele). None, gdy brak panelu tej roli."""
    target = target_px(design_mm, dpi)
    _, _, bw, bh = wykr.bbox
    sx, sy = target[0] / bw, target[1] / bh
    for panel in segmentuj_panele(wykr):
        if panel.rola == rola:
            _, _, pw, ph = panel.bbox
            return (max(1, int(pw * sx)), max(1, int(ph * sy)))
    return None


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
    rzędowy dla szerokiego; karty lekko obrócone i nachodzące.

    `tlo` (hex) → wynik RGB na jednolitym tle. `tlo=None` → wynik RGBA z
    PRZEZROCZYSTYM tłem (sam wachlarz) — do nałożenia na AI-tło pudełka.
    Fallback: brak kart → puste tło (jednolite lub przezroczyste)."""
    from PIL import ImageOps
    w, h = max(1, rozmiar[0]), max(1, rozmiar[1])
    if tlo is None:
        out: Image.Image = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    else:
        out = Image.new("RGB", (w, h), tlo)
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
    if out.mode == "RGBA":
        out.alpha_composite(warstwa)
    else:
        out.paste(warstwa, (0, 0), warstwa)
    return out


def zloz_pudelko_panele(obrazy: dict[str, Image.Image], wykr: Wykrojnik,
                        design_mm: tuple[float, float], *,
                        karty_boki: list[Path] | None = None,
                        boki_ai: list[Image.Image] | None = None,
                        tlo_boku: str | None = None,
                        tlo_ai: Image.Image | None = None,
                        dpi: int = 300, z_liniami: bool = True) -> Image.Image:
    """Składa pudełko z OSOBNYCH paneli, WYPEŁNIONYCH DO KRAWĘDZI (linii zgięcia).

    Baza spodu = `tlo_ai` (pełne tło AI, cover-fit) przez maskę wnętrza; gdy
    brak — fallback jednolity `tlo_boku`/krem. Każdy panel (przod/tyl/bok) jest
    dosuwany maską dylatowaną o `_PANEL_DOSUN_PX` z powrotem do linii zgięcia
    i wypełniany COVER-fit (ImageOps.fit), więc łączenia kończą się równo na
    liniach — bez brązowych szpar. Boki-wachlarz kładzione NA tło (RGBA), boki
    AI z `boki_ai`. z_liniami nakłada cienki proof cięcia/big na wierzch."""
    from PIL import ImageOps
    baza_hex = tlo_boku or config.CREAM_HEX
    target = target_px(design_mm, dpi)
    panele = segmentuj_panele(wykr)
    fill = _crop_resize(wykr.wypelnienie, wykr.bbox, target)
    fill_l = Image.fromarray(fill).convert("L")

    plotno = Image.new("RGB", target, "white")
    if tlo_ai is not None:
        baza = ImageOps.fit(tlo_ai.convert("RGB"), target,
                            method=Image.Resampling.LANCZOS)
    else:
        baza = Image.new("RGB", target, baza_hex)
    plotno.paste(baza, (0, 0), fill_l)

    x0, y0, bw, bh = wykr.bbox
    sx, sy = target[0] / bw, target[1] / bh
    kdos = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (_PANEL_DOSUN_PX, _PANEL_DOSUN_PX))
    bok_idx = 0
    for panel in panele:
        # maska dosunięta do linii zgięcia (cofa erozję + gap ściany)
        maska_full = cv2.dilate(panel.maska, kdos, iterations=1)
        mx, my, mw, mh = cv2.boundingRect(maska_full)
        tx, ty = int((mx - x0) * sx), int((my - y0) * sy)
        tpw, tph = max(1, int(mw * sx)), max(1, int(mh * sy))
        maska_bbox = maska_full[my:my + mh, mx:mx + mw]
        maska_t = Image.fromarray(
            cv2.resize(maska_bbox, (tpw, tph),
                       interpolation=cv2.INTER_NEAREST)).convert("L")
        if panel.rola == "bok" and not boki_ai:
            # wachlarz prawdziwych kart NA tle pudełka (bez kremowej łaty)
            fan = wizualizacja_kart(karty_boki or [], (tpw, tph), tlo=None)
            region = plotno.crop((tx, ty, tx + tpw, ty + tph)).convert("RGBA")
            region.alpha_composite(fan.convert("RGBA"))
            plotno.paste(region.convert("RGB"), (tx, ty), maska_t)
            bok_idx += 1
            continue
        if panel.rola == "bok" and boki_ai:
            art = ImageOps.fit(boki_ai[bok_idx % len(boki_ai)], (tpw, tph),
                               method=Image.Resampling.LANCZOS)
            bok_idx += 1
        else:
            obraz = obrazy.get(panel.rola)
            if obraz is None and panel.rola == "tyl":
                obraz = obrazy.get("przod")
            if obraz is None:
                continue                       # klapka → zostaje tło
            art = ImageOps.fit(obraz.convert("RGB"), (tpw, tph),
                               method=Image.Resampling.LANCZOS)
        plotno.paste(art, (tx, ty), maska_t)

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


def eksportuj_na_pdf_drukarni(artwork: Image.Image, dieline_pdf: Path,
                              out_path: Path) -> Path:
    """„Kopiuje" oryginalny wektorowy wykrojnik z drukarni i wstawia artwork
    (raw, BEZ linii) w prostokąt obszaru druku POD wektorowe linie — dokładnie
    plik drukarni z narzuconą grafiką. Wymaga PyMuPDF (fitz). `dieline_pdf` musi
    być PDF-em; dla PNG użyj eksportuj_pdf/eksportuj_pdf_cmyk."""
    import io

    import fitz

    wykr = parsuj_wykrojnik(dieline_pdf)
    x, y, w, h = wykr.bbox                            # px w rastrze @ _PDF_RASTER_DPI
    skala = 72.0 / _PDF_RASTER_DPI                    # px → punkty PDF
    doc = fitz.open(dieline_pdf)
    try:
        page = doc[0]
        rect = fitz.Rect(x * skala, y * skala,
                         (x + w) * skala, (y + h) * skala)
        buf = io.BytesIO()
        artwork.convert("RGB").save(buf, "JPEG", quality=92)   # lekki plik
        # overlay=False → grafika POD wektorowymi liniami wykrojnika (linie widoczne)
        page.insert_image(rect, stream=buf.getvalue(), overlay=False)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path))
    finally:
        doc.close()
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
