"""Strojenie klampu offline (zero API): przelicza maskę klampu dla zapisanych
wyjść modelu SPRZED klampu (output/_raw/api/*.png) i zapisuje podglądy:
nakładkę sylwetki (zielone = przeżywa klamp), finalny composite po klampie
i diff „co klamp cofnął" (czerwone = wróciło do szablonu).

Uruchomienie: python -m scripts.test_klamp [plik.png ...]
Bez argumentów przetwarza wszystkie PNG z output/_raw/api/.
Wyniki trafiają do katalogu ze zmiennej TEST_OUT (domyślnie output/klamp_test/).

UWAGA: szablon i kolory brane są z AKTYWNYCH presetów — jeśli preset teł lub
„wartosci" zmienił się od wygenerowania karty, maska nie odda stanu z generacji.
"""
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from app import config
from app.core import compositor, masks, style_store
from app.core.models import Suit

# Bez load() wskaźniki aktywnych presetów (Style/active.json) nie są wczytane
# i skrypt cicho analizowałby preset „Domyślny" zamiast aktywnego
style_store.load()

API_DIR = config.RAW_DIR / "api"
out_dir = Path(os.environ.get("TEST_OUT", config.OUTPUT_DIR / "klamp_test"))
out_dir.mkdir(parents=True, exist_ok=True)


def _kolor_z_nazwy(path: Path) -> Suit | None:
    """Kolor karty ze stemu pliku (wzorzec CardSpec.raw_name: K_kier_v2)."""
    czesci = path.stem.split("_")
    if len(czesci) < 2:
        return None
    try:
        return Suit.from_nazwa(czesci[1])
    except ValueError:
        return None


pliki = ([Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1
         else sorted(API_DIR.glob("*.png")))
if not pliki:
    sys.exit("Brak plików do analizy — najpierw wygeneruj karty "
             f"(wyjścia modelu sprzed klampu trafiają do {API_DIR})")

styl = compositor.styl_z_presetu()
for plik in pliki:
    suit = _kolor_z_nazwy(plik)
    if suit is None:
        print(f"[pomijam] {plik.name}: nazwa nie pasuje do wzorca "
              "wartość_kolor[_vN].png")
        continue
    template = Image.open(suit.template_path).convert("RGB")
    wynik = Image.open(plik).convert("RGB")
    if wynik.size != template.size:
        wynik = wynik.resize(template.size, Image.Resampling.LANCZOS)
    kolor_hex = styl.kolor_czerwony if suit.is_red else styl.kolor_czarny
    kolor_tla = (int(kolor_hex[1:3], 16), int(kolor_hex[3:5], 16),
                 int(kolor_hex[5:7], 16))
    maska = masks.maska_klampu(wynik, template, suit.template_path,
                               kolor_tla=kolor_tla)
    composite = Image.composite(wynik, template, maska)

    # (1) nakładka maski na wyniku modelu — zielone przeżywa klamp
    zielony = Image.new("RGB", wynik.size, (0, 200, 0))
    overlay = Image.composite(zielony, wynik, maska.point(lambda v: v // 2))

    # (2) diff „co klamp cofnął": wynik modelu ≠ composite → wróciło do
    # szablonu — czerwona nakładka na wyniku modelu (tu widać ucięcia)
    w_arr = np.asarray(wynik, dtype=np.int16)
    c_arr = np.asarray(composite, dtype=np.int16)
    cofniete = ((np.abs(w_arr - c_arr).max(axis=2) > 12)
                .astype(np.uint8) * 255)
    czerwony = Image.new("RGB", wynik.size, (255, 0, 0))
    m_cof = Image.fromarray(cofniete).point(lambda v: v // 2)
    diff = Image.composite(czerwony, wynik, m_cof)

    for nazwa, obraz in (("maska", overlay), ("final", composite),
                         ("cofniete", diff)):
        mala = obraz.copy()
        mala.thumbnail((700, 1000))
        mala.save(out_dir / f"{plik.stem}_{nazwa}.png")
    udzial = np.count_nonzero(cofniete) / cofniete.size
    print(f"{plik.name}: maska bbox={maska.getbbox()}, "
          f"cofnięte {udzial:.1%} pikseli -> {out_dir}")
