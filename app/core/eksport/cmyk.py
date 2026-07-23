"""Konwersja RGB → CMYK dla eksportu do druku + podbicie kolorów.

Dwa problemy, które ten moduł rozwiązuje:

1. **„Wydruk jak przez mgłę"** — bez profilu ICC Pillow konwertuje `RGB → CMYK`
   wzorem `C = 255 − R` i zostawia **K = 0 na całym obrazie**: czernie i cienie
   drukują się brudną mieszanką CMY zamiast czarnym atramentem. Zastępuje to
   `_cmyk_gcr()` z pełną generacją czerni (GCR) i limitem TAC.
2. **Węższy gamut CMYK** zjada nasycenie i mikrokontrast. Przed konwersją idzie
   więc pre-press w RGB (`przygotuj_do_druku`) sterowany jedną siłą 1-5.

Gdy w `assets/icc/` leży profil drukarni, konwersja idzie przez zarządzanie
kolorem (intent relative colorimetric + kompensacja punktu czerni — perceptual
zostawiał czerń szarą), a bajty profilu wracają razem z obrazem do osadzenia
w pliku (JPEG/TIFF).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageCms, ImageEnhance, ImageFilter, ImageOps

from app import config

# Profil sRGB budujemy raz — źródło konwersji dla obrazów bez własnego profilu.
_SRGB = ImageCms.createProfile("sRGB")

# Domyślna siła podbicia (suwak „Podbicie kolorów" w panelu Eksport).
SILA_DOMYSLNA = 3
SILA_MIN, SILA_MAX = 1, 5

# Maksymalne pokrycie farbą (Total Area Coverage) dla papieru powlekanego —
# suma CMYK ponad tę wartość rozmaka i brudzi druk.
TAC_MAX = 3.0     # 300 %

# Zgodność wstecz: pudelko.py woła rgb_na_cmyk(nasycenie=NASYCENIE_DRUKU).
NASYCENIE_DRUKU = 1.2


@dataclass(frozen=True)
class ProfilDruku:
    """Jeden poziom suwaka. Kolejność stosowania = kolejność pól."""
    cutoff: float        # % pikseli obcinanych przy rozciąganiu tonalnym
    gamma: float         # < 1 pogłębia półcienie
    kontrast: float
    saturacja: float
    wyostrzenie: int     # procent UnsharpMask (0 = pomiń)


# Poziom 3 odpowiada dotychczasowemu zachowaniu (saturacja 1.2) wzbogaconemu
# o rozciągnięcie tonalne — to on jest domyślny.
_PROFILE: dict[int, ProfilDruku] = {
    1: ProfilDruku(0.0, 1.00, 1.00, 1.05, 0),
    2: ProfilDruku(0.1, 0.98, 1.04, 1.12, 30),
    3: ProfilDruku(0.2, 0.96, 1.08, 1.20, 55),
    4: ProfilDruku(0.4, 0.94, 1.14, 1.30, 80),
    5: ProfilDruku(0.6, 0.92, 1.20, 1.42, 110),
}


def profil(sila: int) -> ProfilDruku:
    return _PROFILE[max(SILA_MIN, min(SILA_MAX, int(sila)))]


def przygotuj_do_druku(img: Image.Image,
                       sila: int = SILA_DOMYSLNA) -> Image.Image:
    """Pre-press w RGB: rozciągnięcie zakresu tonalnego → gamma → kontrast →
    nasycenie → mikrokontrast. Zwraca NOWY obraz RGB.

    Rozciągnięcie tonalne jest tu najważniejsze: karty z AI rzadko mają pełną
    czerń i biel, a druk dodatkowo je ściska — stąd wrażenie mgły. `preserve_tone`
    liczy je na luminancji, więc kremowe tła nie zmieniają barwy."""
    p = profil(sila)
    out = img.convert("RGB")
    if p.cutoff > 0:
        out = ImageOps.autocontrast(out, cutoff=p.cutoff, preserve_tone=True)
    if p.gamma != 1.0:
        lut = [round(255 * (i / 255) ** p.gamma) for i in range(256)]
        out = out.point(lut * 3)
    if p.kontrast != 1.0:
        out = ImageEnhance.Contrast(out).enhance(p.kontrast)
    if p.saturacja != 1.0:
        out = ImageEnhance.Color(out).enhance(p.saturacja)
    if p.wyostrzenie:
        out = out.filter(ImageFilter.UnsharpMask(
            radius=max(1.0, min(out.size) / 800), percent=p.wyostrzenie,
            threshold=3))
    return out


def _cmyk_gcr(img: Image.Image) -> Image.Image:
    """RGB → CMYK z pełną generacją czerni i limitem pokrycia farbą.

    Zamiennik `Image.convert("CMYK")`, które daje K = 0: tam każda szarość jest
    mieszanką trzech farb (drukarsko: nieostro, brudno, drogo). Tu neutralna
    składowa wędruje w całości do kanału K, a CMY zostaje tylko na barwę.
    Konwencja Pillow: 255 = pełne krycie farbą."""
    rgb = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    cmy = 1.0 - rgb
    k = cmy.min(axis=2)
    reszta = np.clip(1.0 - k, 1e-6, None)
    cmy = (cmy - k[..., None]) / reszta[..., None]

    # limit TAC — nadmiar ścinamy z CMY, K zostaje (to on niesie kontrast)
    suma = cmy.sum(axis=2) + k
    nadmiar = suma > TAC_MAX
    if nadmiar.any():
        wolne = np.clip(TAC_MAX - k, 0.0, None)
        skala = np.divide(wolne, np.clip(cmy.sum(axis=2), 1e-6, None))
        cmy[nadmiar] *= skala[nadmiar][..., None]

    kanaly = np.concatenate([cmy, k[..., None]], axis=2)
    return Image.fromarray(
        np.clip(kanaly * 255.0 + 0.5, 0, 255).astype(np.uint8), mode="CMYK")


def rgb_na_cmyk(img: Image.Image, nasycenie: float = 1.0,
                sila: int | None = None) -> tuple[Image.Image, bytes | None]:
    """Zwraca (obraz CMYK, bajty profilu ICC | None).

    `sila` (1-5) włącza pełny pre-press `przygotuj_do_druku` i ma pierwszeństwo
    przed starszym parametrem `nasycenie` (samo podbicie barw), który zostaje
    dla `pudelko.py`.

    Z profilem ICC → konwersja z zarządzaniem kolorem (relative colorimetric +
    kompensacja punktu czerni) i bajty profilu do osadzenia. Bez profilu →
    `_cmyk_gcr` (kolor niekalibrowany, ale z uczciwą czernią)."""
    if img.mode != "RGB":
        img = img.convert("RGB")
    if sila is not None:
        img = przygotuj_do_druku(img, sila)
    elif nasycenie != 1.0:
        img = ImageEnhance.Color(img).enhance(nasycenie)

    profil_icc = config.cmyk_profile_path()
    if profil_icc is not None:
        try:
            cmyk_profile = ImageCms.getOpenProfile(str(profil_icc))
            wynik = ImageCms.profileToProfile(
                img, _SRGB, cmyk_profile, outputMode="CMYK",
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                flags=ImageCms.Flags.BLACKPOINTCOMPENSATION
                | ImageCms.Flags.HIGHRESPRECALC,
            )
            if wynik is not None:
                return wynik, cmyk_profile.tobytes()
        except (ImageCms.PyCMSError, OSError):
            pass   # zły/uszkodzony profil → fallback poniżej

    return _cmyk_gcr(img), None
