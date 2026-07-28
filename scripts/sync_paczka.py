"""CLI: synchronizacja projektu między komputerami przez pendrive (ZERO API).

Paczka to folder z danymi i stanem talii — bez kodu i bez kluczy API. Import
jest ADDYTYWNY: nic nie kasuje i nie nadpisuje cudzej pracy (kolidująca karta
wchodzi jako nowy wariant `_vN`, inne pliki jako „nazwa (od <autor>)", a przy
rozbieżnościach w `projekt.json` domyślnie zostaje wersja odbiorcy).

Uruchomienie:
    # u siebie — spakuj stan na pendrive (E:\\)
    python -m scripts.sync_paczka eksport E:\\ --autor Marek
    python -m scripts.sync_paczka eksport E:\\ --autor Marek --profil roboczy
    python -m scripts.sync_paczka eksport E:\\ --autor Marek --od-ostatniej

    # u kolegi — najpierw PRÓBNIE, potem naprawdę
    python -m scripts.sync_paczka import "E:\\AtelierKart_paczka_Marek_20260728_1830" --sucho
    python -m scripts.sync_paczka import "E:\\AtelierKart_paczka_Marek_20260728_1830"

Profile: `pelny` (wszystko, ~9 GB), `roboczy` (bez output/_raw i historii
pudełka, ~2,5 GB — uwaga: bez _raw u odbiorcy nie zadziała „Przestempluj" ani
selektywna poprawka na przywiezionych kartach), `lekki` (same presety tekstowe
i maski, kilkanaście MB).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from app import config
from app.core import sync


def _postep(etykieta: str):
    """Prosty pasek postępu w jednej linii (kopiowanie 9 GB trwa)."""
    stan = {"ostatni": -1}

    def cb(i: int, n: int) -> None:
        proc = int(i * 100 / max(1, n))
        if proc != stan["ostatni"]:
            stan["ostatni"] = proc
            print(f"\r{etykieta}: {proc:3d}%  ({i}/{n})", end="", flush=True)
    return cb


def _eksport(args) -> int:
    cel = Path(args.katalog)
    if not cel.is_dir():
        print(f"BŁĄD: nie ma katalogu docelowego {cel}", file=sys.stderr)
        return 2
    print(f"Pakuję stan z {config.ROOT}\n  profil: {args.profil}"
          f"{'  (tylko nowe pliki)' if args.od_ostatniej else ''}")
    paczka = sync.eksportuj(cel, args.autor, profil=args.profil,
                            tylko_nowe=args.od_ostatniej,
                            postep=_postep("Kopiuję"))
    manifest = sync.podsumowanie_paczki(paczka)
    print(f"\nGotowe: {paczka}")
    print(f"  plików: {len(manifest.get('pliki', []))}")
    print("  Przenieś CAŁY ten folder na pendrive i daj koledze — instrukcja "
          "dla niego jest w CZYTAJ_MNIE.txt.")
    return 0


def _import(args) -> int:
    zrodlo = Path(args.paczka)
    if not zrodlo.is_dir():
        print(f"BŁĄD: nie ma folderu paczki {zrodlo}", file=sys.stderr)
        return 2
    manifest = sync.podsumowanie_paczki(zrodlo)
    if not manifest:
        print(f"BŁĄD: {zrodlo} nie wygląda na paczkę Atelier Kart "
              f"(brak manifest.json)", file=sys.stderr)
        return 2
    print(f"Paczka: autor {manifest.get('autor', '?')}, "
          f"{manifest.get('utworzono', '?')}, profil {manifest.get('profil', '?')}, "
          f"plików {len(manifest.get('pliki', []))}")
    if args.sucho:
        print("TRYB PRÓBNY — żaden plik nie zostanie zapisany.\n")

    try:
        raport = sync.importuj(zrodlo, przypisania=args.przypisania,
                               sucho=args.sucho, postep=_postep("Scalam"))
    except ValueError as exc:
        print(f"\nBŁĄD: {exc}", file=sys.stderr)
        return 1

    print(f"\n\n{raport.krotko}")
    for ostrzezenie in raport.ostrzezenia:
        print(f"  ! {ostrzezenie}")
    for konflikt in raport.konflikty[:10]:
        print(f"  ~ {konflikt}")
    if len(raport.konflikty) > 10:
        print(f"  ~ …i {len(raport.konflikty) - 10} dalszych konfliktów")

    plik = config.ROOT / f"raport_sync_{datetime.now():%Y%m%d_%H%M%S}.txt"
    plik.write_text(raport.tekst(), encoding="utf-8")
    print(f"\nPełny raport: {plik}")
    if not args.sucho:
        print("Uruchom program ponownie, żeby zobaczyć zmiany "
              "(PyQt nie przeładowuje stanu w locie).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.sync_paczka",
        description="Synchronizacja projektu przez pendrive (bez sieci i API).")
    pod = parser.add_subparsers(dest="komenda", required=True)

    p_eks = pod.add_parser("eksport", help="spakuj swój stan do folderu paczki")
    p_eks.add_argument("katalog", help="gdzie utworzyć paczkę (np. E:\\)")
    p_eks.add_argument("--autor", default="", help="Twoje imię — trafia do nazw "
                       "plików przy kolizjach u odbiorcy")
    p_eks.add_argument("--profil", default="pelny", choices=sync.PROFILE)
    p_eks.add_argument("--od-ostatniej", action="store_true", dest="od_ostatniej",
                       help="tylko pliki niewysłane wcześniej do tego odbiorcy")
    p_eks.set_defaults(func=_eksport)

    p_imp = pod.add_parser("import", help="wczytaj paczkę od kolegi")
    p_imp.add_argument("paczka", help="folder paczki (AtelierKart_paczka_…)")
    p_imp.add_argument("--przypisania", default="moje", choices=("moje", "ich"),
                       help="kto wygrywa przy rozbieżności w projekt.json "
                            "(domyślnie Twoja wersja)")
    p_imp.add_argument("--sucho", action="store_true",
                       help="tylko raport, bez zapisywania czegokolwiek")
    p_imp.set_defaults(func=_import)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
