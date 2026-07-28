"""Weryfikacja synchronizacji offline (zero API, zero sieci, na mini-repo w TEMP).

Buduje dwa sztuczne foldery projektu — „Marek" (autor paczki) i „Kolega"
(odbiorca z WŁASNYM progresem) — eksportuje paczkę i importuje ją, a potem
sprawdza twarde niezmienniki, na których stoi cała funkcja:

  TEST 1 — NIC NIE GINIE: żaden plik odbiorcy nie zniknął ani nie zmienił treści.
  TEST 2 — KOLIZJA KARTY = NOWY WARIANT: karta o tej samej nazwie i innej treści
    wchodzi jako `_vN`, a para awers+raw dostaje TEN SAM numer.
  TEST 3 — ŚCIEŻKI DZIAŁAJĄ: wszystkie przypisania i wybory w projekt.json
    wskazują na ISTNIEJĄCE pliki lokalne (regresja: absolutne ścieżki autora).
  TEST 4 — ZDJĘCIE SPOZA PROJEKTU: plik z folderu poza ROOT dojechał do
    `zdjecia/_zewnetrzne/` i jest podpięty pod właściwą kartę.
  TEST 5 — IDEMPOTENCJA: powtórny import tej samej paczki nic nie zmienia.
  TEST 6 — BEZ SEKRETÓW: w paczce nie ma `.env` ani cache `assets/masks/`.
  TEST 7 — MÓJ STAN WYGRYWA: rozbieżne przypisanie zostaje odbiorcy i ląduje
    w konfliktach raportu.

Uruchomienie: python -m scripts.test_sync
Kod wyjścia ≠ 0 przy dowolnym FAIL.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

from app.core import sync

wyniki: list[tuple[str, bool, str]] = []


def sprawdz(nazwa: str, warunek: bool, detal: str = "") -> None:
    wyniki.append((nazwa, bool(warunek), detal))


def _zapisz(path: Path, tresc: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(tresc, str):
        path.write_text(tresc, encoding="utf-8")
    else:
        path.write_bytes(tresc)
    return path


def _migawka(root: Path) -> dict[str, str]:
    """sha1 wszystkich plików repo — do porównania „przed/po"."""
    return {p.relative_to(root).as_posix(): sync.sha1_pliku(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def _projekt(root: Path) -> dict:
    return json.loads((root / "projekt.json").read_text(encoding="utf-8"))


def zbuduj_marka(root: Path, zewnetrzne: Path) -> None:
    """Repo autora: 2 karty (jedna z wariantem), zdjęcie w projekcie, zdjęcie
    SPOZA projektu, preset tła z maską i polem tekstowym."""
    foto = _zapisz(root / "zdjecia" / "Patryk.jpg", b"FOTO-PATRYK-MAREK")
    zew = _zapisz(zewnetrzne / "Kier_8.jpg", b"FOTO-SPOZA-PROJEKTU")
    _zapisz(root / "output" / "A_kier.jpg", b"KARTA-A-KIER-MAREK")
    _zapisz(root / "output" / "_raw" / "A_kier.png", b"RAW-A-KIER-MAREK")
    _zapisz(root / "output" / "K_pik.jpg", b"KARTA-K-PIK-MAREK")
    _zapisz(root / "output" / "_raw" / "K_pik.png", b"RAW-K-PIK-MAREK")
    _zapisz(root / "output" / "_raw" / "api" / "A_kier.png", b"DEBUG-NIE-PAKOWAC")
    _zapisz(root / "Style" / "tla_przodu" / "Domyślny" / "kier.png", b"TLO-KIER-MAREK")
    _zapisz(root / "Style" / "tla_przodu" / "Domyślny" / "styl.txt",
            "ornament w stylu art deco, wersja Marka")
    _zapisz(root / "Style" / "tla_przodu" / "Domyślny" / "maski" / "maska 1"
            / "kier.png", b"MASKA-KIER-MAREK")
    _zapisz(root / "Style" / "active.json",
            json.dumps({"tla_przodu": "Domyślny"}, ensure_ascii=False))
    _zapisz(root / ".env", "GEMINI_API_KEY=sekret-marka")
    _zapisz(root / "assets" / "masks" / "cache_kier.png", b"CACHE-DO-POMINIECIA")
    _zapisz(root / "analiza_zdjec.json",
            json.dumps({"zdjecie_marka": {"osoby": 2}}, ensure_ascii=False))
    _zapisz(root / "projekt.json", json.dumps({
        "deck_name": "Talia Marka",
        "values": ["A", "K", "8"],
        "assignments": {"kier:A": str(foto), "kier:8": str(zew)},
        "transforms": {"kier:A": {"zoom": 1.1, "dx": 0.0, "dy": 0.0}},
        "selections": {"kier:A": str(root / "output" / "A_kier.jpg")},
        "templates": {"kier": str(root / "Style" / "tla_przodu" / "Domyślny"
                                  / "kier.png")},
        "model": "gemini-3-pro-image",
        "import_folder": str(zewnetrzne),
    }, ensure_ascii=False, indent=2), )


def zbuduj_kolege(root: Path) -> None:
    """Repo odbiorcy: WŁASNA wersja tej samej karty i tego samego pola presetu
    oraz własne przypisanie dla kier:A — wszystko to musi przeżyć import."""
    foto = _zapisz(root / "zdjecia" / "Wlasne.jpg", b"FOTO-KOLEGI")
    _zapisz(root / "output" / "A_kier.jpg", b"KARTA-A-KIER-KOLEGI")
    _zapisz(root / "output" / "_raw" / "A_kier.png", b"RAW-A-KIER-KOLEGI")
    _zapisz(root / "Style" / "tla_przodu" / "Domyślny" / "styl.txt",
            "ornament kolegi — inny tekst")
    _zapisz(root / "projekt.json", json.dumps({
        "deck_name": "Talia kolegi",
        "values": ["A", "K", "8"],
        "assignments": {"kier:A": str(foto)},
        "selections": {"kier:A": str(root / "output" / "A_kier.jpg")},
        "model": "gemini-3-pro-image",
    }, ensure_ascii=False, indent=2))


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="atelier_sync_test_"))
    try:
        marek = tmp / "repo_marek"
        kolega = tmp / "repo_kolega"
        zewnetrzne = tmp / "wybor zdjec"
        pendrive = tmp / "pendrive"
        pendrive.mkdir(parents=True)
        zbuduj_marka(marek, zewnetrzne)
        zbuduj_kolege(kolega)

        paczka = sync.eksportuj(pendrive, "Marek", root=marek, profil="pelny")
        w_paczce = {p.relative_to(paczka).as_posix()
                    for p in paczka.rglob("*") if p.is_file()}

        # TEST 6 — bez sekretów i cache
        sprawdz("TEST 6 — bez .env i cache masek w paczce",
                not any(".env" in s or "assets/masks" in s for s in w_paczce),
                f"{sorted(s for s in w_paczce if '.env' in s or 'masks' in s)}")
        sprawdz("TEST 6b — bez zrzutów debugowych output/_raw/api",
                not any("_raw/api" in s for s in w_paczce))
        sprawdz("TEST 6c — zdjęcie spoza ROOT dołączone do paczki",
                any(s.startswith("dane/_zewnetrzne/") for s in w_paczce),
                f"{sorted(s for s in w_paczce if '_zewnetrzne' in s)}")

        przed = _migawka(kolega)
        raport = sync.importuj(paczka, root=kolega)
        po = _migawka(kolega)

        # TEST 1 — nic nie ginie
        zgubione = [rel for rel in przed if rel not in po]
        zmienione = [rel for rel in przed
                     if rel in po and po[rel] != przed[rel]
                     and rel not in ("projekt.json", "analiza_zdjec.json")]
        sprawdz("TEST 1 — żaden plik odbiorcy nie zniknął", not zgubione,
                f"zgubione: {zgubione}")
        sprawdz("TEST 1b — żaden plik odbiorcy nie zmienił treści",
                not zmienione, f"zmienione: {zmienione}")

        # TEST 2 — kolizja karty → nowy wariant, para awers+raw zgodna
        warianty = sorted(p.name for p in (kolega / "output").glob("A_kier*.jpg"))
        raw_warianty = sorted(p.name for p in
                              (kolega / "output" / "_raw").glob("A_kier*.png"))
        nowy_jpg = [n for n in warianty if n != "A_kier.jpg"]
        nowy_raw = [n for n in raw_warianty if n != "A_kier.png"]
        sprawdz("TEST 2 — kolidująca karta weszła jako nowy wariant",
                len(nowy_jpg) == 1 and nowy_jpg[0].startswith("A_kier_v"),
                f"awersy: {warianty}")
        sprawdz("TEST 2b — raw dostał TEN SAM numer wariantu",
                len(nowy_raw) == 1
                and Path(nowy_raw[0]).stem == Path(nowy_jpg[0]).stem
                if nowy_jpg and nowy_raw else False,
                f"jpg: {nowy_jpg}, raw: {nowy_raw}")
        sprawdz("TEST 2c — treść wariantu to karta autora",
                bool(nowy_jpg) and (kolega / "output" / nowy_jpg[0]).read_bytes()
                == b"KARTA-A-KIER-MAREK")
        sprawdz("TEST 2d — karta odbiorcy nietknięta",
                (kolega / "output" / "A_kier.jpg").read_bytes()
                == b"KARTA-A-KIER-KOLEGI")

        # TEST 3 — ścieżki w projekcie działają lokalnie
        proj = _projekt(kolega)
        martwe = [f"{k}[{kk}]={vv}"
                  for k in ("assignments", "selections", "templates")
                  for kk, vv in (proj.get(k) or {}).items()
                  if not Path(vv).exists()]
        sprawdz("TEST 3 — wszystkie ścieżki w projekt.json istnieją",
                not martwe, f"martwe: {martwe}")
        sprawdz("TEST 3b — doszła karta kier:8 od autora",
                "kier:8" in (proj.get("assignments") or {}))

        # TEST 4 — zdjęcie spoza projektu
        zew_pliki = list((kolega / "zdjecia" / "_zewnetrzne").glob("*.jpg")) \
            if (kolega / "zdjecia" / "_zewnetrzne").is_dir() else []
        przypisane_zew = (proj.get("assignments") or {}).get("kier:8", "")
        sprawdz("TEST 4 — zdjęcie spoza ROOT trafiło do zdjecia/_zewnetrzne",
                len(zew_pliki) == 1
                and zew_pliki[0].read_bytes() == b"FOTO-SPOZA-PROJEKTU",
                f"{[p.name for p in zew_pliki]}")
        sprawdz("TEST 4b — kier:8 wskazuje na to zdjęcie",
                bool(przypisane_zew) and Path(przypisane_zew).exists()
                and "_zewnetrzne" in przypisane_zew.replace("\\", "/"),
                przypisane_zew)

        # TEST 7 — mój stan wygrywa przy rozbieżności
        sprawdz("TEST 7 — przypisanie odbiorcy dla kier:A zachowane",
                (proj.get("assignments") or {}).get("kier:A", "").endswith(
                    "Wlasne.jpg"),
                (proj.get("assignments") or {}).get("kier:A", ""))
        sprawdz("TEST 7b — konflikt zgłoszony w raporcie",
                any("kier:A" in k for k in raport.konflikty),
                f"{raport.konflikty}")
        sprawdz("TEST 7c — konflikt pola presetu (styl.txt) zgłoszony",
                any("styl.txt" in k for k in raport.konflikty))
        sprawdz("TEST 7d — pole presetu odbiorcy nietknięte",
                (kolega / "Style" / "tla_przodu" / "Domyślny" / "styl.txt")
                .read_text(encoding="utf-8") == "ornament kolegi — inny tekst")
        sprawdz("TEST 7e — nazwa talii odbiorcy nietknięta",
                proj.get("deck_name") == "Talia kolegi")

        # TEST 5 — idempotencja
        przed2 = _migawka(kolega)
        raport2 = sync.importuj(paczka, root=kolega)
        po2 = _migawka(kolega)
        rozne = [rel for rel in set(przed2) | set(po2)
                 if przed2.get(rel) != po2.get(rel)
                 and not rel.startswith("kopie_zapasowe/")
                 and not rel.startswith(".sync/")]
        sprawdz("TEST 5 — powtórny import nie zmienia plików", not rozne,
                f"różnice: {rozne}")
        sprawdz("TEST 5b — powtórny import nic nie dodaje",
                not raport2.dodane and not raport2.przemianowane,
                f"dodane: {raport2.dodane}, przemianowane: {raport2.przemianowane}")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("Weryfikacja synchronizacji (mini-repo w TEMP, zero API)\n")
    for nazwa, ok, detal in wyniki:
        print(f"  [{'PASS' if ok else 'FAIL'}]  {nazwa}"
              + (f"\n           {detal}" if detal and not ok else ""))
    zle = sum(1 for _, ok, _ in wyniki if not ok)
    print(f"\n{'— WSZYSTKO PASS —' if not zle else f'!!! {zle} FAIL !!!'}"
          f"  ({len(wyniki)} sprawdzeń)")
    return 1 if zle else 0


if __name__ == "__main__":
    sys.exit(main())
