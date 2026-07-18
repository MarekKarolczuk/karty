"""CLI: generowanie pojedynczej karty przez API.

Uruchomienie:
    python -m scripts.generuj_karte <wartość> <kolor> <zdjęcie> [hybrid|full_ai] [model]
Przykład:
    python -m scripts.generuj_karte K kier "zdjecia/x.jpg" hybrid stability-ultra
Joker (wartość JOKER, kolory joker_czerwony / joker_czarny):
    python -m scripts.generuj_karte JOKER joker_czerwony "zdjecia/x.jpg" hybrid
Dostępne modele: patrz app/config.py (MODELS).
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from app import config
from app.core import style_store
from app.core.generator import generate_card
from app.core.models import CardSpec, GenMode, Suit

style_store.load()   # własne style AI (styles.json), jeśli zapisane w GUI

if len(sys.argv) < 4:
    print(__doc__)
    sys.exit(1)

value, suit_name, photo = sys.argv[1], sys.argv[2], Path(sys.argv[3])
mode = GenMode(sys.argv[4]) if len(sys.argv) > 4 else GenMode.HYBRID
if len(sys.argv) > 5:
    if sys.argv[5] not in config.MODELS:
        print(f"Nieznany model '{sys.argv[5]}'. Dostępne: {', '.join(config.MODELS)}")
        sys.exit(1)
    config.SELECTED_MODEL = sys.argv[5]

spec = CardSpec(value=value, suit=Suit.from_nazwa(suit_name), photo_path=photo, mode=mode)
print(f"Generuję {spec.label} ({mode.value}, {config.current_model()['label']}) "
      f"ze zdjęcia {photo.name}...")
out = generate_card(spec)
print(f"Zapisano: {out}")
