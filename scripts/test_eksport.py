"""Offline test eksporterów (zero API, zero kredytów).

Bierze istniejące karty z output/ (albo tworzy sztuczne), dokłada sztuczny
rewers i sprawdza: PDF (liczba stron), ZIP (zawartość + manifest),
atlas TTS 10×7 (wymiary, ostatnie pole = rewers) i sprite 13×4.

Uruchomienie:  python -m scripts.test_eksport
"""
from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image

from app import config
from app.core import exporter
from app.core.exporter import CELL, ExportJob


def _make_fake_card(path: Path, color: str) -> None:
    Image.new("RGB", (744, 1039), color).save(path, quality=90)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    tmp = Path(tempfile.mkdtemp(prefix="karty_eksport_"))
    print(f"Katalog testowy: {tmp}")

    # --- dane wejściowe: prawdziwe karty z output/ + sztuczne uzupełnienie -------
    real = sorted(config.OUTPUT_DIR.glob("*.jpg")) \
        if config.OUTPUT_DIR.exists() else []
    fronts: list[tuple[str, Path | None]] = []
    values = config.DEFAULT_VALUES
    fake_dir = tmp / "fake_cards"
    fake_dir.mkdir()
    i = 0
    for suit in ("kier", "karo", "pik", "trefl"):
        for value in values:
            name = f"{value}_{suit}"
            existing = config.OUTPUT_DIR / f"{name}.jpg"
            if existing.exists():
                fronts.append((name, existing))
            elif i % 3 == 0:   # co trzecia brakująca zostaje None (test braków)
                fronts.append((name, None))
            else:
                fake = fake_dir / f"{name}.jpg"
                _make_fake_card(fake, "#F5EFE0" if i % 2 else "#801515")
                fronts.append((name, fake))
            i += 1
    back = tmp / "rewers.png"
    Image.new("RGB", (744, 1039), "#3A0A0A").save(back)
    present = sum(1 for _n, p in fronts if p is not None)
    print(f"Kart w teście: {present}/{len(fronts)} "
          f"(w tym prawdziwych z output/: {len(real)})")

    failures = 0

    # --- PDF ----------------------------------------------------------------------
    pdf_path = tmp / "arkusz.pdf"
    job = ExportJob(kind="pdf", out_path=pdf_path, fronts=fronts, back=back,
                    columns=3, bleed=True, marks=True, backs=True)
    exporter.run_export(job)
    from pypdf import PdfReader   # opcjonalny — jeśli brak, liczymy inaczej
    try:
        pages = len(PdfReader(str(pdf_path)).pages)
    except Exception:
        pages = -1
    expected_pages = -(-present // 9) * 2   # fronty + rewersy
    ok = pdf_path.exists() and pdf_path.stat().st_size > 10_000
    if pages >= 0:
        ok = ok and pages == expected_pages
        print(f"PDF: {pages} stron (oczekiwane {expected_pages}), "
              f"{pdf_path.stat().st_size // 1024} KB -> "
              f"{'OK' if ok else 'BLAD'}")
    else:
        print(f"PDF: zapisany, {pdf_path.stat().st_size // 1024} KB (pypdf brak "
              f"— pominięto licznik stron) -> {'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- ZIP ----------------------------------------------------------------------
    zip_path = tmp / "talia.zip"
    exporter.run_export(ExportJob(kind="zip", out_path=zip_path,
                                  fronts=fronts, back=back))
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        manifest = json.loads(archive.read("manifest.json"))
    ok = ("rewers.png" in names
          and len([n for n in names if n.endswith(".png")]) == present + 1
          and len(manifest["cards"]) == present
          and len(manifest["missing"]) == len(fronts) - present)
    print(f"ZIP: {len(names)} plików, manifest cards={len(manifest['cards'])}, "
          f"missing={len(manifest['missing'])} -> {'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Atlas TTS 10×7 --------------------------------------------------------------
    atlas_path = tmp / "atlas.png"
    exporter.run_export(ExportJob(kind="atlas", out_path=atlas_path,
                                  fronts=fronts, back=back))
    atlas = Image.open(atlas_path)
    expected_size = (10 * CELL[0], 7 * CELL[1])
    last_cell = atlas.crop((9 * CELL[0], 6 * CELL[1],
                            10 * CELL[0], 7 * CELL[1]))
    back_color = (0x3A, 0x0A, 0x0A)
    center = last_cell.getpixel((CELL[0] // 2, CELL[1] // 2))
    ok = atlas.size == expected_size and center == back_color
    print(f"Atlas: {atlas.size} (oczekiwane {expected_size}), "
          f"pole 69 środek={center} (rewers {back_color}) -> "
          f"{'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Sprite 13×4 ------------------------------------------------------------------
    sprite_path = tmp / "sprite.png"
    exporter.run_export(ExportJob(kind="sprite", out_path=sprite_path,
                                  fronts=fronts, back=back, small_atlas=True))
    sprite = Image.open(sprite_path)
    from app.core.exporter import CELL_SMALL
    expected_size = (13 * CELL_SMALL[0], 4 * CELL_SMALL[1])
    ok = sprite.size == expected_size
    print(f"Sprite: {sprite.size} (oczekiwane {expected_size}) -> "
          f"{'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Potok A4: dynamiczna siatka per format --------------------------------------
    from app.core.eksport import UkladA4, formaty
    fmts = formaty()
    oczekiwane_siatki = {"poker": (3, 3), "bridge": (3, 3),
                         "tarot": (2, 2), "mini": (4, 4)}
    ok = True
    for klucz, siatka in oczekiwane_siatki.items():
        uklad = UkladA4(fmts[klucz], spad=True)
        if (uklad.kolumny, uklad.wiersze) != siatka:
            ok = False
        print(f"Siatka A4 {klucz}: {uklad.kolumny}x{uklad.wiersze} "
              f"(oczekiwane {siatka[0]}x{siatka[1]}) -> "
              f"{'OK' if (uklad.kolumny, uklad.wiersze) == siatka else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Potok A4: lustro duplexu (kolumny odbite, rzad bez zmian) --------------------
    poker = UkladA4(fmts["poker"], spad=True)   # 3x3
    ok = (poker.pozycja_rewersu(0) == poker.pozycja_komorki(2)      # 0 <-> 2
          and poker.pozycja_rewersu(2) == poker.pozycja_komorki(0)
          and poker.pozycja_rewersu(4) == poker.pozycja_komorki(4)  # srodek
          and poker.pozycja_rewersu(3) == poker.pozycja_komorki(5))  # rzad 2
    print(f"Duplex: rewers idx0->kol2, idx4->srodek, idx3->idx5 -> "
          f"{'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Potok A4: strony tarota (2x2 -> 4/strone, duplex przeplatany) ----------------
    tarot_karty = [(f"k{i}", Image.new("RGB", (350, 600), "#801515"))
                   for i in range(5)]
    wynik = UkladA4(fmts["tarot"], spad=True).uloz(
        tarot_karty, Image.new("RGB", (350, 600), "#3A0A0A"))
    ok = (len(wynik.plotna) == 4          # 5 kart po 4/strone = 2 x (awers+rewers)
          and wynik.plotna[0].size == (2480, 3508)
          and wynik.nazwy[:2] == ["strona_01_awersy", "strona_01_rewersy"])
    print(f"Tarot: {len(wynik.plotna)} plocien (oczekiwane 4), "
          f"strona {wynik.plotna[0].size} (oczekiwane (2480, 3508)) -> "
          f"{'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    print(f"\nWynik: {'WSZYSTKO OK' if failures == 0 else f'{failures} bledow'}")
    print(f"Pliki testowe: {tmp}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
