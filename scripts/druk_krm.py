"""CLI: masowe przygotowanie kart do druku w KRM (zero API, zero kredytów).

Bierze wszystkie obrazy z podanego katalogu i składa z nich JEDEN wielostronicowy
PDF w CMYK 300 DPI zgodny ze specyfikacją drukarni:

  * strona brutto = format netto + spad 3 mm z każdej strony (poker: 69 × 94 mm,
    815 × 1110 px przy 300 DPI), linia cięcia = netto (63 × 88 mm);
  * karta przeskalowana JEDNOLICIE (proporcja zachowana) tak, by zmieścić się
    w marginesie bezpieczeństwa 5 mm w głąb od linii cięcia — nie przekracza
    53 × 78 mm — i wyśrodkowana na stronie (8 mm od krawędzi pliku po bokach);
  * całe tło strony (spad + margines) zalane JEDNOLITYM kolorem pobranym
    z krawędzi karty: brak białych rogów, brak przezroczystości, brak masek
    zaokrąglających (płótno RGB → CMYK);
  * strona 1 = rewers, kolejne = awersy w porządku talii.

Cała robota graficzna idzie tym samym potokiem, co przycisk „Druk do KRM"
w panelu Eksport (ProcesorKRM → UkladPojedynczy → WyjsciePDF_CMYK), więc wynik
jest identyczny.

Uruchomienie:
    python -m scripts.druk_krm karty\\
    python -m scripts.druk_krm karty\\ -o output\\druk_krm.pdf --podbicie 4
    python -m scripts.druk_krm karty\\ --format tarot --rewers grafiki\\tyl.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from app import config
from app.core import exporter
from app.core.eksport import cmyk
from app.core.eksport.formaty import DPI_DRUKU, FormatKarty, formaty
from app.core.exporter import ExportJob
from app.core.models import JOKER_WARTOSC, Suit

# Stem pliku rozpoznawany jako rewers (dowolne rozszerzenie z IMAGE_EXTS).
_REWERS_STEM = "rewers"


def _klucz_talii(stem: str) -> tuple[int, int, int, str]:
    """Klucz sortowania: porządek TALII, nie alfabetu.

    Nazwa pliku w konwencji `<wartość>_<kolor>` (jak w `_deck_fronts` GUI, np.
    `A_kier`, `10_pik`, `JOKER_joker_czerwony`). Kolory w kolejności enuma
    `Suit`, wartości w kolejności `config.DEFAULT_VALUES`, jokery na końcu,
    nazwy nieparsowalne za nimi (alfabetycznie)."""
    kolory = Suit.kolory()
    wartosc, _, kolor = stem.partition("_")
    try:
        suit = Suit.from_nazwa(kolor.lower())
    except ValueError:
        return (2, 0, 0, stem.lower())
    if suit.czy_joker:
        return (1, Suit.jokery().index(suit), 0, stem.lower())
    wartosci = config.DEFAULT_VALUES
    idx_w = (wartosci.index(wartosc.upper()) if wartosc.upper() in wartosci
             else len(wartosci))
    return (0, kolory.index(suit), idx_w, stem.lower())


def _zbierz(katalog: Path, rewers_arg: Path | None,
            bez_rewersu: bool) -> tuple[list[tuple[str, Path | None]], Path | None]:
    """Awersy (posortowane porządkiem talii) + rewers z katalogu."""
    pliki = sorted(p for p in katalog.iterdir()
                   if p.is_file() and p.suffix.lower() in config.IMAGE_EXTS)
    rewers = rewers_arg
    awersy: list[Path] = []
    for p in pliki:
        if rewers_arg is None and p.stem.lower().startswith(_REWERS_STEM):
            rewers = p          # pierwszy „rewers*.ext" w katalogu
            continue
        awersy.append(p)
    if bez_rewersu:
        rewers = None
    awersy.sort(key=lambda p: _klucz_talii(p.stem))
    return [(p.stem, p) for p in awersy], rewers


def _wypisz_naglowek(fmt: FormatKarty, podbicie: int, ile_awersow: int,
                     rewers: Path | None) -> None:
    """Podsumowanie geometrii przed składaniem — to, co drukarnia weryfikuje."""
    w_mm, h_mm = fmt.mm_ze_spadem
    w_px, h_px = fmt.px_300dpi_ze_spadem
    r_mm, r_px = fmt.mm_ramki, fmt.px_ramki_300dpi
    profil = config.cmyk_profile_path()
    print(f"Format:     {fmt.etykieta}")
    print(f"Strona:     {w_mm:g} × {h_mm:g} mm ({w_px} × {h_px} px @ {DPI_DRUKU} DPI), "
          f"cięcie {fmt.szerokosc_mm:g} × {fmt.wysokosc_mm:g} mm")
    print(f"Karta:      maks. {r_mm[0]:g} × {r_mm[1]:g} mm ({r_px[0]} × {r_px[1]} px), "
          f"proporcja zachowana, wyśrodkowana")
    print(f"Podbicie:   {podbicie}" + (f"  ·  profil ICC: {profil.name}"
                                       if profil is not None else
                                       "  ·  bez profilu ICC (kolor niekalibrowany)"))
    print(f"Strony:     {ile_awersow + (1 if rewers else 0)} "
          f"({'rewers + ' if rewers else ''}{ile_awersow} awersów)")
    if rewers is not None:
        print(f"Rewers:     {rewers.name}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        prog="python -m scripts.druk_krm",
        description="Katalog obrazów kart → jeden PDF CMYK 300 DPI do druku w KRM.")
    ap.add_argument("katalog", type=Path, help="katalog z plikami kart")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="plik wyjściowy PDF (domyślnie <katalog>/druk_krm.pdf)")
    ap.add_argument("--podbicie", type=int, default=cmyk.SILA_DOMYSLNA,
                    choices=range(cmyk.SILA_MIN, cmyk.SILA_MAX + 1),
                    help=f"siła podbicia kolorów pod druk "
                         f"(1 = minimalne, {cmyk.SILA_DOMYSLNA} = domyślne, 5 = mocne)")
    ap.add_argument("--format", dest="format_karty", default=config.SELECTED_CARD_PRESET,
                    choices=sorted(config.CARD_PRESETS),
                    help="format karty (domyślnie wybrany w aplikacji)")
    ap.add_argument("--rewers", type=Path, default=None,
                    help="plik rewersu, gdy nie nazywa się rewers.* w katalogu")
    ap.add_argument("--bez-rewersu", dest="bez_rewersu", action="store_true",
                    help="pomiń stronę rewersu (same awersy)")
    args = ap.parse_args(argv)

    if not args.katalog.is_dir():
        print(f"BŁĄD: '{args.katalog}' nie jest katalogiem")
        return 2
    if args.rewers is not None and not args.rewers.is_file():
        print(f"BŁĄD: rewers '{args.rewers}' nie istnieje")
        return 2

    config.set_card_preset(args.format_karty)
    fmt = formaty()[args.format_karty]

    fronts, rewers = _zbierz(args.katalog, args.rewers, args.bez_rewersu)
    if not fronts:
        print(f"BŁĄD: brak plików obrazów w '{args.katalog}' "
              f"(obsługiwane: {', '.join(sorted(config.IMAGE_EXTS))})")
        return 1

    out = args.out or (args.katalog / "druk_krm.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)

    _wypisz_naglowek(fmt, args.podbicie, len(fronts), rewers)

    # Potok raportuje postęp z każdego etapu; układ (Etap B) zgłasza komplet
    # jednym tickiem, więc licznik pokazujemy dopiero od właściwego zapisu.
    stan = {"ostatni": 0}

    def postep(zrobione: int, razem: int) -> None:
        if zrobione >= razem and stan["ostatni"] == 0:
            return                      # komplet jednym tickiem = Etap B, nie zapis
        stan["ostatni"] = 0 if zrobione >= razem else zrobione
        print(f"\r  [{zrobione}/{razem}] składanie PDF-a…", end="", flush=True)

    exporter.run_export(
        ExportJob(kind="krm", out_path=out, fronts=fronts, back=rewers,
                  extra={"podbicie": args.podbicie}),
        progress=postep)
    print()

    rozmiar_mb = out.stat().st_size / (1024 * 1024)
    print(f"Zapisano:   {out}  ({rozmiar_mb:.1f} MB)")
    if JOKER_WARTOSC.lower() in " ".join(n.lower() for n, _p in fronts):
        print("Uwaga:      jokery trafiły na koniec talii — sprawdź kolejność stron.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
