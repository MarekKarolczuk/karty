"""Maski szablonów (OpenCV): centralny symbol (flood-fill) i narożne tarcze.

Maska pop-out = wyłącznie sylwetka symbolu + dylatacja o grubość ramy
(~20-30 px). Wszystko poza nią jest czarne, więc inpainting nie może
naruszyć grawerowanego tła. Maski są cache'owane w assets/masks/
(pliki wersjonowane sufiksem _v{MASK_VERSION}); gdy flood-fill zawiedzie,
wczytywana jest maska statyczna z assets/masks/static/maska_<kolor>.png.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app import config

# Wersja algorytmu masek — podbicie unieważnia wszystkie cache na dysku
# (v3: narożniki stemplowane wyłącznie lokalnie — patrz compositor)
MASK_VERSION = 3

# Tolerancja flood-filla: PIL-owe thresh=90 to suma |diff| po kanałach,
# czyli ~30 na kanał w cv2 (FLOODFILL_FIXED_RANGE porównuje do seeda).
_FLOOD_DIFF = (30, 30, 30)

# Punkty startowe flood-filla dla narożnych tarcz (ułamki szer./wys. szablonu)
_TL_SEED = (0.175, 0.135)
_BR_SEED = (0.825, 0.865)

# Awaryjne ramki narożne, gdy flood-fill tarczy zawiedzie (leak / brak tarczy)
_TL_FALLBACK = (0.08, 0.05, 0.27, 0.21)
_BR_FALLBACK = (0.73, 0.79, 0.92, 0.95)

_cache: dict[Path, "TemplateMasks"] = {}
_popout_cache: dict[Path, Image.Image] = {}


class _MaskGenerationError(Exception):
    """Flood-fill nie wyznaczył sensownej maski symbolu (leak / pusty obszar)."""


@dataclass
class TemplateMasks:
    center: Image.Image                     # maska L: 255 = wnętrze symbolu
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


def _shield_box(img: np.ndarray, seed_rel: tuple[float, float],
                fallback_rel: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    h, w = img.shape[:2]
    seed = (int(seed_rel[0] * w), int(seed_rel[1] * h))
    region = _flood_region(img, seed)
    area = int(np.count_nonzero(region))
    # Sanity: tarcza to małe, zwarte pole; leak na tło/margines = odrzucamy
    if 0.002 * w * h < area < 0.06 * w * h:
        ys, xs = np.nonzero(region)
        x0, y0 = int(xs.min()), int(ys.min())
        x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
        if (x1 - x0) < 0.30 * w and (y1 - y0) < 0.30 * h:
            return (x0, y0, x1, y1)
    return (int(fallback_rel[0] * w), int(fallback_rel[1] * h),
            int(fallback_rel[2] * w), int(fallback_rel[3] * h))


def _cleanup_old_cache(stem: str) -> None:
    """Usuwa cache poprzednich wersji algorytmu masek (niewersjonowane i v2)."""
    for suffix in ("_center.png", "_boxes.txt", "_popout.png",
                   "_center_v2.png", "_boxes_v2.txt", "_popout_v2.png"):
        old = config.MASKS_DIR / f"{stem}{suffix}"
        old.unlink(missing_ok=True)


def get_masks(template_path: Path) -> TemplateMasks:
    template_path = Path(template_path)
    if template_path in _cache:
        return _cache[template_path]

    config.MASKS_DIR.mkdir(parents=True, exist_ok=True)
    stem = template_path.stem
    center_cache = config.MASKS_DIR / f"{stem}_center_v{MASK_VERSION}.png"
    meta_cache = config.MASKS_DIR / f"{stem}_boxes_v{MASK_VERSION}.txt"
    _cleanup_old_cache(stem)

    if center_cache.exists() and meta_cache.exists() \
            and center_cache.stat().st_mtime >= template_path.stat().st_mtime:
        center = Image.open(center_cache).convert("L")
        v = [int(x) for x in meta_cache.read_text().split()]
        masks = TemplateMasks(center, (v[0], v[1], v[2], v[3]), (v[4], v[5], v[6], v[7]))
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
    # od konturu ramy, żeby nie zamalować jej linii.
    region = cv2.morphologyEx(
        region, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    erode_px = max(3, w // 300)
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * erode_px + 1, 2 * erode_px + 1))
    region = cv2.erode(region, kernel)
    center = Image.fromarray(region, mode="L")

    tl_box = _shield_box(img, _TL_SEED, _TL_FALLBACK)
    br_box = _shield_box(img, _BR_SEED, _BR_FALLBACK)

    center.save(center_cache)
    meta_cache.write_text(" ".join(str(v) for v in [*tl_box, *br_box]))

    masks = TemplateMasks(center, tl_box, br_box)
    _cache[template_path] = masks
    return masks


def get_popout_mask(template_path: Path) -> Image.Image:
    """Maska pod inpainting pop-out: sylwetka symbolu + ring dylatacji
    o grubość ramy (~20-30 px), miękka krawędź TYLKO do wewnątrz.

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
    h, w = center.shape

    # 1) Ring: dylatacja o grubość czerwonej ramy symbolu (spec: 20-30 px)
    dilate_px = int(np.clip(round(w * 25 / 1500), 20, 30))
    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * dilate_px + 1, 2 * dilate_px + 1))
    dilated = cv2.dilate(center, kernel)

    # 2) Miękka krawędź wyłącznie do wewnątrz — na zewnątrz czysta czerń,
    #    żeby inpainting nie dostał ani piksela tła.
    soft = cv2.GaussianBlur(dilated, (0, 0), sigmaX=max(2, w // 400))
    mask_arr = np.where(dilated == 0, 0, soft).astype(np.uint8)

    # 3) Tarcze narożne twardo poza maską (obrona w głąb)
    for x0, y0, x1, y1 in (base.tl_box, base.br_box):
        mask_arr[y0:y1, x0:x1] = 0

    mask = Image.fromarray(mask_arr, mode="L")
    mask.save(cache_file)
    _popout_cache[template_path] = mask
    return mask
