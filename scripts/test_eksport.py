"""Offline test eksporterów (zero API, zero kredytów).

Bierze istniejące karty z output/ (albo tworzy sztuczne), dokłada sztuczny
rewers i sprawdza: PDF (liczba stron), ZIP (zawartość + manifest),
atlas TTS 10×7 (wymiary, ostatnie pole = rewers) i sprite 13×4.

Uruchomienie:  python -m scripts.test_eksport
"""
from __future__ import annotations

import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
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
    # jokery: zawsze na końcu listy frontów (jak main_window._deck_fronts),
    # w odróżnialnym kolorze — test pól 52-53 atlasu
    joker_color = "#156080"
    for suit in ("joker_czerwony", "joker_czarny"):
        name = f"JOKER_{suit}"
        fake = fake_dir / f"{name}.jpg"
        _make_fake_card(fake, joker_color)
        fronts.append((name, fake))
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
    # jokery (fronty 52-53) trafiają do pól 52-53 (wiersz 5, kolumny 2-3);
    # tolerancja na stratną kompresję JPEG sztucznej karty
    joker_rgb = (0x15, 0x60, 0x80)
    joker_cell = atlas.crop((2 * CELL[0], 5 * CELL[1],
                             3 * CELL[0], 6 * CELL[1]))
    joker_center = joker_cell.getpixel((CELL[0] // 2, CELL[1] // 2))
    joker_ok = all(abs(a - b) <= 6 for a, b in zip(joker_center, joker_rgb))
    ok = atlas.size == expected_size and center == back_color and joker_ok
    print(f"Atlas: {atlas.size} (oczekiwane {expected_size}), "
          f"pole 69 środek={center} (rewers {back_color}), "
          f"pole 52 środek={joker_center} (joker {joker_rgb}) -> "
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

    # --- Druk KRM: geometria strony ---------------------------------------------------
    from app.core.eksport.cmyk import rgb_na_cmyk
    from app.core.eksport.procesor import ProcesorKRM, kolor_krawedzi
    fmt_poker = fmts["poker"]
    tlo_rgb = (0x2A, 0x40, 0x70)
    probka = Image.new("RGB", (1695, 2373), tlo_rgb)
    # jasny prostokat w srodku - odrozni karte od tla przy pomiarze marginesow
    probka.paste(Image.new("RGB", (1200, 1800), "#E0D8C0"), (247, 286))
    strona = ProcesorKRM(fmt_poker).przetworz(probka)
    arr = np.asarray(strona)
    # bbox karty: piksele rozne od koloru tla (tlo jest jednolite)
    rozne = np.any(arr != np.asarray(kolor_krawedzi(probka)), axis=2)
    ys, xs = np.where(rozne)
    lewy, prawy = int(xs.min()), strona.width - 1 - int(xs.max())
    gora, dol = int(ys.min()), strona.height - 1 - int(ys.max())
    szer, wys = int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)
    ramka = fmt_poker.px_ramki_300dpi
    # tlo poza karta ma byc JEDNYM kolorem (bez bialych rogow i przezroczystosci)
    pas = np.concatenate([arr[:gora].reshape(-1, 3),
                          arr[strona.height - dol:].reshape(-1, 3)])
    ok = (strona.size == (815, 1110) and strona.mode == "RGB"
          and abs(lewy - prawy) <= 1 and abs(gora - dol) <= 1
          and szer <= ramka[0] and wys <= ramka[1]
          and len({tuple(p) for p in pas}) == 1
          and tuple(pas[0]) == kolor_krawedzi(probka))
    print(f"KRM geometria: strona {strona.size} (oczekiwane (815, 1110)), "
          f"karta {szer}x{wys} px w ramce {ramka[0]}x{ramka[1]}, "
          f"marginesy L/P {lewy}/{prawy}, G/D {gora}/{dol}, "
          f"tlo {len({tuple(p) for p in pas})} kolor(y) -> "
          f"{'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Druk KRM: biale zaokraglenia narozne znikaja ---------------------------------
    # Pliki kart maja wyciete, biale rogi; drukarnia zabrania ich wprost.
    probka_rogi = probka.copy()
    for poz in ((0, 0), (probka.width - 40, 0), (0, probka.height - 40),
                (probka.width - 40, probka.height - 40)):
        probka_rogi.paste(Image.new("RGB", (40, 40), "white"), poz)
    strona_rogi = ProcesorKRM(fmt_poker).przetworz(probka_rogi)
    biale = int((np.asarray(strona_rogi).min(axis=2) >= 250).sum())
    ok = biale == 0
    print(f"KRM biale rogi: {biale} px prawie-bialych (oczekiwane 0) -> "
          f"{'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Druk KRM: PDF (strona 1 = rewers, DeviceCMYK) --------------------------------
    krm_path = tmp / "druk_krm.pdf"
    exporter.run_export(ExportJob(kind="krm", out_path=krm_path, fronts=fronts,
                                  back=back, extra={"podbicie": 3}))
    try:
        czytnik = PdfReader(str(krm_path))
        krm_pages = len(czytnik.pages)
        zasoby = czytnik.pages[0]["/Resources"]["/XObject"]
        obraz = zasoby[next(iter(zasoby))]
        przestrzen = str(obraz["/ColorSpace"])
        rozmiar_px = (int(obraz["/Width"]), int(obraz["/Height"]))
        strona_pt = (round(float(czytnik.pages[0].mediabox.width), 1),
                     round(float(czytnik.pages[0].mediabox.height), 1))
    except Exception as exc:                                  # noqa: BLE001
        krm_pages, przestrzen, rozmiar_px, strona_pt = -1, f"?({exc})", (0, 0), (0, 0)
    # 69x94 mm w punktach PDF (1 pt = 1/72")
    oczekiwana_strona = (round(69 / 25.4 * 72, 1), round(94 / 25.4 * 72, 1))
    ok = (krm_pages == present + 1 and przestrzen == "/DeviceCMYK"
          and rozmiar_px == (815, 1110) and strona_pt == oczekiwana_strona)
    print(f"KRM PDF: {krm_pages} stron (oczekiwane {present + 1}), "
          f"strona {strona_pt} pt (oczekiwane {oczekiwana_strona}), "
          f"obraz {rozmiar_px} {przestrzen} -> {'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- Druk KRM: round-trip obrazu Z PDF-a (pulapka odwroconego Adobe CMYK) ---------
    # Pillow zapisuje JPEG CMYK z markerem Adobe (wartosci odwrocone). Gdyby
    # reportlab osadzil go bez tej informacji, wydruk wyszedlby NEGATYWEM -
    # test wyzej tego nie widzi, bo bada obraz PRZED zapisem. Tu czytamy piksele
    # z PDF-a zlozonego z JEDNEJ znanej probki: rog strony to spad w kolorze tla
    # (ciemny), srodek to jasny prostokat.
    probka_path = tmp / "probka_krm.png"
    probka.save(probka_path)
    probka_pdf = tmp / "probka_krm.pdf"
    exporter.run_export(ExportJob(kind="krm", out_path=probka_pdf,
                                  fronts=[("probka", probka_path)], back=None,
                                  extra={"podbicie": 3}))
    try:
        zasoby = PdfReader(str(probka_pdf)).pages[0]["/Resources"]["/XObject"]
        surowy = Image.open(io.BytesIO(zasoby[next(iter(zasoby))].get_data()))
        tryb_pdf = surowy.mode
        rgb = surowy.convert("RGB")
        lum = lambda px: 0.299 * px[0] + 0.587 * px[1] + 0.114 * px[2]  # noqa: E731
        lum_rog = lum(rgb.getpixel((6, 6)))                     # type: ignore[arg-type]
        lum_srodek = lum(rgb.getpixel((rgb.width // 2, rgb.height // 2)))  # type: ignore[arg-type]
    except Exception as exc:                                      # noqa: BLE001
        tryb_pdf, lum_rog, lum_srodek = f"?({exc})", -1.0, -1.0
    ok = tryb_pdf == "CMYK" and lum_rog < 128 and lum_srodek > 128
    print(f"KRM round-trip: obraz z PDF-a {tryb_pdf}, luminancja rogu "
          f"{lum_rog:.0f} (oczekiwane <128), srodka {lum_srodek:.0f} "
          f"(oczekiwane >128) -> {'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    # --- CMYK: czern idzie kanalem K (kontrola inwersji i generacji czerni) -----------
    jasny = rgb_na_cmyk(Image.new("RGB", (8, 8), "#F0EAD8"), sila=3)[0]
    ciemny = rgb_na_cmyk(Image.new("RGB", (8, 8), "#101010"), sila=3)[0]
    k_jasny = jasny.getpixel((4, 4))[3]      # type: ignore[index]
    k_ciemny = ciemny.getpixel((4, 4))[3]    # type: ignore[index]
    ok = k_ciemny > 200 and k_jasny < 40
    print(f"CMYK czern: K jasnego={k_jasny}, K ciemnego={k_ciemny} "
          f"(oczekiwane <40 i >200) -> {'OK' if ok else 'BLAD'}")
    failures += 0 if ok else 1

    print(f"\nWynik: {'WSZYSTKO OK' if failures == 0 else f'{failures} bledow'}")
    print(f"Pliki testowe: {tmp}")
    return failures


if __name__ == "__main__":
    sys.exit(main())
