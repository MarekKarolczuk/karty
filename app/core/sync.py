"""Synchronizacja offline między użytkownikami (pendrive, ZERO API, ZERO sieci).

Paczka to zwykły FOLDER, który przenosi się pendrivem. Zawiera dane (zdjęcia,
karty, style, pudełko) i stan (`projekt.json`), a NIE zawiera kodu ani kluczy
API. Dwa problemy, które ten moduł rozwiązuje:

1. `projekt.json` trzyma ścieżki ABSOLUTNE, a `MainWindow._load_project` po
   cichu wyrzuca wpisy, których plik nie istnieje — u kolegi zniknęłyby
   wszystkie przypisania. Dlatego w paczce ścieżki żyją jako TOKENY
   (`<ROOT>/zdjecia/foto.jpg`, `<ZEW>/…` dla zdjęć spoza folderu projektu)
   i są rozwijane do lokalnych dopiero przy imporcie.
2. Zwykłe „skopiuj i nadpisz" kasuje progres odbiorcy. Import tutaj jest
   ADDYTYWNY: nigdy nie usuwa i nie nadpisuje pliku o innej treści — kolidująca
   karta wchodzi jako NOWY WARIANT (`_vN`), kolidujący obraz jako
   `<nazwa> (od <autor>)`, a rozbieżności w `projekt.json` domyślnie
   rozstrzyga stan ODBIORCY (wersja z paczki ląduje w raporcie).

Idempotencja: `.sync/znane.json` (mapa sha1 → lokalna ścieżka) sprawia, że ten
sam plik przyniesiony ponownie — także pod inną nazwą — jest pomijany, więc
kolejne wymiany nie robią lawiny duplikatów „(od Marka) (od Marka)".
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator

from app import config

# Wersja formatu paczki — import odmawia pracy na nowszym formacie, zamiast
# cicho rozjechać dane.
FORMAT_PACZKI = 1

TOKEN_ROOT = "<ROOT>"
TOKEN_ZEW = "<ZEW>"

PROFILE = ("pelny", "roboczy", "lekki")

# Foldery danych wchodzące do paczki (profil pełny).
_FOLDERY_DANYCH = ("zdjecia", "Przypisane", "output", "Style")

# Pliki stanu: (ścieżka względem ROOT, nazwa w paczce). `Style/active.json`
# jedzie tylko informacyjnie (raport) — podmiana aktywnych presetów u odbiorcy
# byłaby nadpisaniem jego ustawień.
_PLIKI_STANU = (
    ("projekt.json", "projekt.json"),
    ("analiza_zdjec.json", "analiza_zdjec.json"),
    ("Style/active.json", "Style_active.json"),
)

# Nigdy do paczki: sekrety, cache i śmieci robocze.
_WYKLUCZONE_FRAGMENTY = (
    "/__pycache__/", "/.git/", "/.sync/", "/kopie_zapasowe/",
    "/assets/masks/",
    "/output/_raw/api/",          # 578 zrzutów debugowych dla scripts.test_klamp
)
_WYKLUCZONE_NAZWY = {
    ".env", ".env.example", "desktop.ini", "thumbs.db", ".ds_store",
    "_podglad_druku.png", "active.json",
}

# Klucze `projekt.json` niosące ścieżki — wymagają tokenizacji.
_KLUCZE_SCIEZEK_MAPA = ("assignments", "selections", "templates")
_KLUCZE_SCIEZEK_TEKST = ("import_folder",)

# Ustawienia UI: przy imporcie zostają odbiorcy, dochodzą tylko brakujące.
_KLUCZE_USTAWIEN = (
    "deck_name", "mode", "limit", "versions", "skip_done", "style_presets",
    "model", "card_preset", "back", "export", "box",
)

# Pliki definiujące SEMANTYKĘ presetu (pola tekstowe `<pole>.txt`, wskaźnik
# głównego wariantu pudełka, sygnatury normalizacji teł). Ich przemianowanie
# dałoby śmieć, którego program nie czyta — więc są wyłącznie addytywne:
# dochodzą, gdy brak, a przy różnicy trafiają do raportu.
_NAZWY_WSKAZNIKOW = {"glowna.txt", "_znormalizowane.json"}

_CARD_EXT = {".jpg", ".png"}
_RE_WARIANT = re.compile(r"^(?P<baza>.+?)(?:_v(?P<nr>\d+))?$")


# --- raport --------------------------------------------------------------------

@dataclass
class Raport:
    """Wynik importu (albo próby na sucho) — do pliku, konsoli i dialogu GUI."""
    autor: str = ""
    sucho: bool = False
    dodane: list[str] = field(default_factory=list)
    przemianowane: list[tuple[str, str]] = field(default_factory=list)
    pominiete: int = 0
    konflikty: list[str] = field(default_factory=list)
    ostrzezenia: list[str] = field(default_factory=list)

    @property
    def krotko(self) -> str:
        tryb = "PRÓBA (nic nie zapisano)" if self.sucho else "import"
        return (f"{tryb}: dodano {len(self.dodane)}, "
                f"przemianowano {len(self.przemianowane)}, "
                f"pominięto identycznych {self.pominiete}, "
                f"konfliktów projektu {len(self.konflikty)}")

    def tekst(self) -> str:
        linie = [
            f"Raport synchronizacji — {datetime.now():%Y-%m-%d %H:%M}",
            f"Autor paczki: {self.autor or '?'}",
            f"Tryb: {'PRÓBA NA SUCHO (żaden plik nie został zapisany)' if self.sucho else 'IMPORT'}",
            "",
            self.krotko,
        ]
        if self.ostrzezenia:
            linie += ["", "=== OSTRZEŻENIA ==="] + [f"! {o}" for o in self.ostrzezenia]
        if self.konflikty:
            linie += ["", "=== KONFLIKTY (zostawiono TWOJĄ wersję) ==="]
            linie += [f"- {k}" for k in self.konflikty]
        if self.przemianowane:
            linie += ["", "=== PRZEMIANOWANE (ta sama nazwa, inna treść) ==="]
            linie += [f"- {a}  ->  {b}" for a, b in self.przemianowane]
        if self.dodane:
            linie += ["", f"=== DODANE PLIKI ({len(self.dodane)}) ==="]
            linie += [f"+ {d}" for d in self.dodane]
        return "\n".join(linie) + "\n"


# --- narzędzia -----------------------------------------------------------------

def _root(root: Path | None) -> Path:
    """Folder projektu, na którym pracujemy (parametr = testy na mini-repo)."""
    return Path(root) if root is not None else config.ROOT


def sha1_pliku(path: Path, bufor: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while blok := f.read(bufor):
            h.update(blok)
    return h.hexdigest()


def _wykluczony(rel: str) -> bool:
    """rel = ścieżka względem ROOT w formie POSIX (bez wiodącego /)."""
    w_slashach = f"/{rel}"
    if any(frag in w_slashach for frag in _WYKLUCZONE_FRAGMENTY):
        return True
    return Path(rel).name.lower() in _WYKLUCZONE_NAZWY


def _dozwolony_w_profilu(rel: str, profil: str) -> bool:
    """Filtr rozmiaru paczki. `pelny` = wszystko; `roboczy` bez surowych wyjść
    AI i historii pudełka (~2,5 GB zamiast ~9 GB); `lekki` = same presety
    tekstowe i maski (kilkanaście MB, do szybkiej wymiany ustawień)."""
    if profil == "pelny":
        return True
    ciezkie = rel.startswith("output/_raw/") or "/historia/" in f"/{rel}"
    if profil == "roboczy":
        return not ciezkie
    # lekki
    if not rel.startswith("Style/"):
        return False
    return rel.endswith(".txt") or rel.endswith(".json") or "/maski/" in f"/{rel}"


def _pliki_danych(root: Path, profil: str) -> Iterator[tuple[Path, str]]:
    """(ścieżka absolutna, ścieżka względna POSIX) plików danych do paczki."""
    for folder in _FOLDERY_DANYCH:
        baza = root / folder
        if not baza.is_dir():
            continue
        for p in sorted(baza.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if _wykluczony(rel) or not _dozwolony_w_profilu(rel, profil):
                continue
            yield p, rel


def _klasa(rel: str) -> str:
    """„karta" (output/… → nowy wariant przy kolizji), „wskaznik" (pola presetu
    i wskaźniki — tylko addytywne) albo „zwykly" (kolizja → nazwa z autorem)."""
    p = Path(rel)
    if p.name in _NAZWY_WSKAZNIKOW:
        return "wskaznik"
    rodzic = p.parent.as_posix()
    if rodzic in ("output", "output/_raw") and p.suffix.lower() in _CARD_EXT:
        return "karta"
    # pole presetu: <pole>.txt bezpośrednio w folderze presetu Style/<kat>/<preset>/
    if (rel.startswith("Style/") and p.suffix.lower() == ".txt"
            and len(p.parts) == 4):
        return "wskaznik"
    return "zwykly"


def _wolna_nazwa(cel: Path, autor: str) -> Path:
    """`foto.jpg` → `foto (od Marek).jpg`, a przy kolejnej kolizji `… 2`."""
    znacznik = f" (od {autor})" if autor else " (z paczki)"
    kandydat = cel.with_name(f"{cel.stem}{znacznik}{cel.suffix}")
    i = 2
    while kandydat.exists():
        kandydat = cel.with_name(f"{cel.stem}{znacznik} {i}{cel.suffix}")
        i += 1
    return kandydat


def _rozbij_wariant(stem: str) -> tuple[str, int]:
    m = _RE_WARIANT.match(stem)
    if not m:
        return stem, 1
    return m.group("baza"), int(m.group("nr") or 1)


def _nazwa_wariantu(baza: str, nr: int, suffix: str) -> str:
    return f"{baza}{'' if nr <= 1 else f'_v{nr}'}{suffix}"


def _najwyzszy_wariant(root: Path, baza: str) -> int:
    """Najwyższy zajęty numer wariantu karty — liczony z output/ ORAZ
    output/_raw/, żeby nowy numer był wolny po obu stronach pary jpg+png
    (wzorzec `generator.nastepny_wariant`, tu bez zależności od generatora)."""
    najw = 0
    for folder, wzor in ((root / "output", f"{baza}*.jpg"),
                         (root / "output" / "_raw", f"{baza}*.png")):
        if not folder.is_dir():
            continue
        for p in folder.glob(wzor):
            b, nr = _rozbij_wariant(p.stem)
            if b == baza:
                najw = max(najw, nr)
    return najw


# --- indeks znanych treści (.sync/znane.json) ----------------------------------

def _sync_dir(root: Path) -> Path:
    return root / ".sync"


def _wczytaj_json(path: Path) -> dict:
    try:
        dane = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dane if isinstance(dane, dict) else {}


def _zapisz_json(path: Path, dane: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dane, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def _znane(root: Path) -> dict[str, str]:
    return _wczytaj_json(_sync_dir(root) / "znane.json")


# --- tokenizacja ścieżek -------------------------------------------------------

def token_ze_sciezki(sciezka: str | Path, root: Path,
                     zewnetrzne: dict[str, Path] | None = None) -> str:
    """Ścieżka lokalna → token przenośny. Plik spoza folderu projektu jest
    rejestrowany w `zewnetrzne` (nazwa w paczce → źródło), żeby eksport mógł go
    dołożyć — inaczej u odbiorcy przypisanie wskazywałoby w próżnię."""
    p = Path(str(sciezka))
    try:
        return f"{TOKEN_ROOT}/{p.resolve().relative_to(root.resolve()).as_posix()}"
    except (ValueError, OSError):
        pass
    if not p.exists() or zewnetrzne is None:
        return str(sciezka)                 # nie ruszamy — raport to zgłosi
    try:
        skrot = sha1_pliku(p)[:8]
    except OSError:
        return str(sciezka)
    nazwa = f"{skrot}_{p.name}"
    zewnetrzne[nazwa] = p
    return f"{TOKEN_ZEW}/{nazwa}"


def sciezka_z_tokenu(token: str, root: Path,
                     mapa: dict[str, Path] | None = None) -> Path | None:
    """Token → lokalna ścieżka u odbiorcy (uwzględnia przemianowania z importu).
    None = ścieżki nie da się odtworzyć (plik nie przyszedł w paczce)."""
    if not isinstance(token, str) or not token:
        return None
    if mapa and token in mapa:
        return mapa[token]
    if token.startswith(f"{TOKEN_ROOT}/"):
        return root / token[len(TOKEN_ROOT) + 1:]
    if token.startswith(f"{TOKEN_ZEW}/"):
        return root / "zdjecia" / "_zewnetrzne" / token[len(TOKEN_ZEW) + 1:]
    return None


def _tokenizuj_projekt(dane: dict, root: Path,
                       zewnetrzne: dict[str, Path]) -> dict:
    """Kopia `projekt.json` ze ścieżkami zamienionymi na tokeny."""
    out = json.loads(json.dumps(dane, ensure_ascii=False))
    for klucz in _KLUCZE_SCIEZEK_MAPA:
        mapa = out.get(klucz)
        if isinstance(mapa, dict):
            out[klucz] = {k: token_ze_sciezki(v, root, zewnetrzne)
                          for k, v in mapa.items() if isinstance(v, str)}
    for klucz in _KLUCZE_SCIEZEK_TEKST:
        if isinstance(out.get(klucz), str) and out[klucz]:
            out[klucz] = token_ze_sciezki(out[klucz], root, zewnetrzne)
    box = out.get("box")
    if isinstance(box, dict) and isinstance(box.get("osobne_folder"), str) \
            and box["osobne_folder"]:
        # folder osób może być poza ROOT, ale to KATALOG — kopiujemy tylko token
        # w formie <ROOT>/… gdy da się, inaczej zostaje ścieżka autora (raport)
        box["osobne_folder"] = token_ze_sciezki(box["osobne_folder"], root, None)
    return out


# --- eksport -------------------------------------------------------------------

_CZYTAJ_MNIE = """ATELIER KART — paczka synchronizacyjna
=======================================
Autor: {autor}
Data:  {data}
Profil: {profil}   |   plików: {ile}   |   rozmiar: {rozmiar}

Co to jest: dane i stan talii (zdjęcia, karty, style, pudełko, projekt.json).
NIE ma tu kodu programu ani kluczy API (.env zostaje u autora).

Jak wczytać u siebie (w folderze programu):

    python -m scripts.sync_paczka import "{sciezka}" --sucho    # podgląd, nic nie zapisuje
    python -m scripts.sync_paczka import "{sciezka}"            # właściwy import

albo w programie: Ustawienia -> SYNCHRONIZACJA (pendrive) -> Wczytaj paczkę.

Import NIC NIE KASUJE i nic nie nadpisuje: karty o tej samej nazwie i innej
treści wchodzą jako nowe warianty (_vN), pozostałe pliki jako
"nazwa (od {autor})", a przy rozbieżnościach w projekt.json zostaje TWOJA
wersja (wersja autora ląduje w raporcie).
"""


def eksportuj(cel: Path, autor: str, *, root: Path | None = None,
              profil: str = "pelny", tylko_nowe: bool = False,
              postep: Callable[[int, int], None] | None = None) -> Path:
    """Buduje folder paczki w `cel` i zwraca jego ścieżkę.

    `tylko_nowe` = eksport przyrostowy: pomija pliki, których sha1 już wysłano
    do tego odbiorcy (`.sync/wyslane_<autor>.json`) — druga i kolejna wymiana
    to zwykle kilkaset MB zamiast kilku GB.
    """
    if profil not in PROFILE:
        raise ValueError(f"Nieznany profil paczki: {profil}")
    r = _root(root)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    bezpieczny_autor = re.sub(r"[^\w\- ]", "", autor).strip() or "uzytkownik"
    paczka = Path(cel) / f"AtelierKart_paczka_{bezpieczny_autor}_{stamp}"
    paczka.mkdir(parents=True, exist_ok=True)

    wyslane_path = _sync_dir(r) / f"wyslane_{bezpieczny_autor}.json"
    wyslane = set(_wczytaj_json(wyslane_path).get("sha1", [])) if tylko_nowe else set()

    # 1) zdjęcia spoza ROOT wskazane w projekt.json — muszą pojechać razem
    projekt = _wczytaj_json(r / "projekt.json")
    zewnetrzne: dict[str, Path] = {}
    projekt_tok = _tokenizuj_projekt(projekt, r, zewnetrzne) if projekt else {}

    # 2) lista plików danych
    pliki = list(_pliki_danych(r, profil))
    razem = len(pliki) + len(zewnetrzne)
    manifest_pliki: list[dict] = []
    wyslane_nowe: set[str] = set()
    bajty = 0

    def _kopiuj(zrodlo: Path, w_paczce: str, i: int) -> None:
        nonlocal bajty
        try:
            skrot = sha1_pliku(zrodlo)
        except OSError:
            return
        if skrot in wyslane:
            return
        docelowy = paczka / w_paczce
        docelowy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(zrodlo, docelowy)
        rozmiar = docelowy.stat().st_size
        bajty += rozmiar
        manifest_pliki.append({"sciezka": w_paczce, "sha1": skrot,
                               "rozmiar": rozmiar})
        wyslane_nowe.add(skrot)
        if postep:
            postep(i, razem)

    for i, (p, rel) in enumerate(pliki, 1):
        _kopiuj(p, f"dane/{rel}", i)
    for i, (nazwa, zrodlo) in enumerate(sorted(zewnetrzne.items()),
                                        len(pliki) + 1):
        _kopiuj(zrodlo, f"dane/_zewnetrzne/{nazwa}", i)

    # 3) stan (ścieżki jako tokeny)
    (paczka / "stan").mkdir(exist_ok=True)
    if projekt_tok:
        _zapisz_json(paczka / "stan" / "projekt.json", projekt_tok)
    for rel, nazwa in _PLIKI_STANU:
        if rel == "projekt.json":
            continue                      # zapisany wyżej, w wersji z tokenami
        src = r / rel
        if src.exists():
            shutil.copy2(src, paczka / "stan" / nazwa)

    # 4) manifest + instrukcja
    _zapisz_json(paczka / "manifest.json", {
        "format": FORMAT_PACZKI,
        "autor": autor,
        "utworzono": datetime.now().isoformat(timespec="seconds"),
        "profil": profil,
        "przyrostowa": bool(tylko_nowe),
        "pliki": manifest_pliki,
    })
    (paczka / "CZYTAJ_MNIE.txt").write_text(_CZYTAJ_MNIE.format(
        autor=autor or "?", data=f"{datetime.now():%Y-%m-%d %H:%M}",
        profil=profil, ile=len(manifest_pliki), rozmiar=_ludzko(bajty),
        sciezka=paczka), encoding="utf-8")

    # 5) pamięć wysyłek (do trybu przyrostowego)
    _zapisz_json(wyslane_path,
                 {"sha1": sorted(wyslane | wyslane_nowe),
                  "ostatnia": datetime.now().isoformat(timespec="seconds")})
    return paczka


def _ludzko(bajty: int) -> str:
    x = float(bajty)
    for jedn in ("B", "KB", "MB", "GB"):
        if x < 1024 or jedn == "GB":
            return f"{x:.1f} {jedn}"
        x /= 1024
    return f"{x:.1f} GB"


# --- import --------------------------------------------------------------------

def podsumowanie_paczki(zrodlo: Path) -> dict:
    """Manifest paczki (autor, data, profil, liczba plików) — do podglądu w GUI
    przed importem. Pusty słownik = to nie jest paczka."""
    dane = _wczytaj_json(Path(zrodlo) / "manifest.json")
    if not dane.get("pliki") and "format" not in dane:
        return {}
    return dane


def importuj(zrodlo: Path, *, root: Path | None = None,
             przypisania: str = "moje", sucho: bool = False,
             postep: Callable[[int, int], None] | None = None) -> Raport:
    """Scala paczkę z lokalnym stanem. NIGDY nie usuwa i nie nadpisuje plików
    o innej treści. `przypisania="ich"` odwraca priorytet w `projekt.json`.
    `sucho=True` = pełny raport bez zapisu czegokolwiek."""
    r = _root(root)
    p = Path(zrodlo)
    manifest = podsumowanie_paczki(p)
    if not manifest:
        raise ValueError(f"To nie jest paczka Atelier Kart: {p}")
    if int(manifest.get("format", 0)) > FORMAT_PACZKI:
        raise ValueError(
            f"Paczka ma nowszy format ({manifest['format']}) niż ten program "
            f"(obsługuje {FORMAT_PACZKI}) — zaktualizuj program u siebie.")

    autor = str(manifest.get("autor") or "")
    rap = Raport(autor=autor, sucho=sucho)
    znane = _znane(r)
    # token w paczce -> lokalna ścieżka (uwzględnia przemianowania)
    mapa_tokenow: dict[str, Path] = {}
    nowe_znane: dict[str, str] = {}
    # co powstanie u odbiorcy (ścieżka -> sha1); liczy się także w trybie sucho,
    # więc próba na sucho daje ten sam raport co prawdziwy import
    zaplanowane: dict[str, str] = {}

    wpisy = list(manifest.get("pliki", []))
    karty = [w for w in wpisy if _klasa(_rel_z_paczki(w["sciezka"])) == "karta"]
    reszta = [w for w in wpisy if _klasa(_rel_z_paczki(w["sciezka"])) != "karta"]
    razem = len(wpisy)
    licznik = 0

    # 1) KARTY — para jpg+png musi dostać TEN SAM numer wariantu, więc numery
    # przydzielamy grupowo, zanim cokolwiek skopiujemy.
    plan = _plan_kart(r, karty, znane)
    for wpis in karty:
        licznik += 1
        rel = _rel_z_paczki(wpis["sciezka"])
        decyzja = plan.get(rel)
        if decyzja is None:
            rap.pominiete += 1
            znany = znane.get(wpis["sha1"])
            mapa_tokenow[f"{TOKEN_ROOT}/{rel}"] = (
                Path(znany) if znany and Path(znany).exists() else r / rel)
        else:
            _wykonaj_kopie(p / wpis["sciezka"], decyzja, rel, wpis["sha1"],
                           rap, sucho, nowe_znane, zaplanowane,
                           przemianowany=decyzja.name != Path(rel).name)
            mapa_tokenow[f"{TOKEN_ROOT}/{rel}"] = decyzja
        if postep:
            postep(licznik, razem)

    # 2) POZOSTAŁE PLIKI
    for wpis in reszta:
        licznik += 1
        rel = _rel_z_paczki(wpis["sciezka"])
        cel = _cel_lokalny(r, rel)
        skrot = wpis["sha1"]
        znany = znane.get(skrot)
        if znany and Path(znany).exists():
            # ten sam plik już u nas jest (choćby pod inną nazwą) — cisza
            rap.pominiete += 1
            mapa_tokenow[f"{TOKEN_ROOT}/{rel}"] = Path(znany)
        elif not cel.exists():
            _wykonaj_kopie(p / wpis["sciezka"], cel, rel, skrot, rap, sucho,
                           nowe_znane, zaplanowane)
            mapa_tokenow[f"{TOKEN_ROOT}/{rel}"] = cel
        elif _bezpieczny_sha1(cel) == skrot:
            rap.pominiete += 1
            mapa_tokenow[f"{TOKEN_ROOT}/{rel}"] = cel
        elif _klasa(rel) == "wskaznik":
            # pole presetu / wskaźnik: przemianowanie dałoby plik, którego
            # program nie czyta — zostawiamy Twoją wersję i pokazujemy różnicę
            rap.konflikty.append(
                _opis_konfliktu_wskaznika(p / wpis["sciezka"], rel))
            mapa_tokenow[f"{TOKEN_ROOT}/{rel}"] = cel
        else:
            nowy = _wolna_nazwa(cel, autor)
            _wykonaj_kopie(p / wpis["sciezka"], nowy, rel, skrot, rap, sucho,
                           nowe_znane, zaplanowane, przemianowany=True)
            mapa_tokenow[f"{TOKEN_ROOT}/{rel}"] = nowy
        if postep:
            postep(licznik, razem)

    # 3) tokeny <ZEW> → zdjecia/_zewnetrzne/
    for wpis in wpisy:
        rel = _rel_z_paczki(wpis["sciezka"])
        if rel.startswith("_zewnetrzne/"):
            nazwa = rel.split("/", 1)[1]
            mapa_tokenow[f"{TOKEN_ZEW}/{nazwa}"] = \
                mapa_tokenow.get(f"{TOKEN_ROOT}/{rel}", r / "zdjecia"
                                 / "_zewnetrzne" / nazwa)

    # 4) analiza_zdjec.json — cache analiz AI, scalany addytywnie (klucze,
    # których nie mamy), żeby kolega nie płacił drugi raz za te same zdjęcia
    _scal_analize(r, p, rap, sucho)

    # 5) projekt.json
    _scal_projekt(r, p, mapa_tokenow, autor, przypisania, rap, sucho,
                  zaplanowane)

    if not sucho and nowe_znane:
        znane.update(nowe_znane)
        _zapisz_json(_sync_dir(r) / "znane.json", znane)
    return rap


def _rel_z_paczki(sciezka_w_paczce: str) -> str:
    """`dane/output/A_kier.jpg` → `output/A_kier.jpg`."""
    return sciezka_w_paczce.split("/", 1)[1] if "/" in sciezka_w_paczce \
        else sciezka_w_paczce


def _cel_lokalny(root: Path, rel: str) -> Path:
    """Docelowa ścieżka u odbiorcy; zdjęcia spoza ROOT lądują trwale
    w `zdjecia/_zewnetrzne/`, żeby przypisania miały do czego wskazywać."""
    if rel.startswith("_zewnetrzne/"):
        return root / "zdjecia" / "_zewnetrzne" / rel.split("/", 1)[1]
    return root / rel


def _ta_sama_tresc(a: Path, b: Path, zaplanowane: dict[str, str]) -> bool:
    """Czy dwie ścieżki wskazują plik o IDENTYCZNEJ treści. Ratuje przed
    fałszywymi konfliktami: to samo zdjęcie leży u autora poza projektem,
    a u odbiorcy w `zdjecia/_zewnetrzne/` pod nazwą z hashem. `b` może jeszcze
    nie istnieć (tryb sucho) — wtedy sha1 bierzemy z manifestu paczki."""
    if not a.is_file():
        return False
    skrot_b = zaplanowane.get(str(b)) or (_bezpieczny_sha1(b) if b.is_file()
                                          else "")
    return skrot_b != "" and _bezpieczny_sha1(a) == skrot_b


def _bezpieczny_sha1(p: Path) -> str:
    try:
        return sha1_pliku(p)
    except OSError:
        return ""


def _wykonaj_kopie(zrodlo: Path, cel: Path, rel: str, skrot: str, rap: Raport,
                   sucho: bool, nowe_znane: dict[str, str],
                   zaplanowane: dict[str, str],
                   przemianowany: bool = False) -> None:
    # przy próbie na sucho nic nie kopiujemy, ale zapamiętujemy CO by powstało —
    # inaczej scalanie projektu uznałoby każdy przywieziony plik za „nie dojechał"
    zaplanowane[str(cel)] = skrot
    if przemianowany:
        rap.przemianowane.append((rel, str(cel.name)))
    else:
        rap.dodane.append(rel)
    nowe_znane[skrot] = str(cel)
    if sucho:
        return
    if not zrodlo.exists():
        rap.ostrzezenia.append(f"Brak pliku w paczce: {zrodlo.name}")
        return
    cel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(zrodlo, cel)


def _plan_kart(root: Path, karty: list[dict],
               znane: dict[str, str]) -> dict[str, Path | None]:
    """Dla każdej karty z paczki: docelowa ścieżka albo None (pomiń).

    Grupujemy po (baza, wariant), bo `output/A_kier_v7.jpg` i lustrzany
    `output/_raw/A_kier_v7.png` MUSZĄ dostać ten sam nowy numer — inaczej
    „przestempluj" i selektywna poprawka straciłyby swoją bazę raw.
    """
    grupy: dict[tuple[str, int], list[dict]] = {}
    for wpis in karty:
        rel = _rel_z_paczki(wpis["sciezka"])
        baza, nr = _rozbij_wariant(Path(rel).stem)
        grupy.setdefault((baza, nr), []).append(wpis)

    plan: dict[str, Path | None] = {}
    zajete: dict[str, int] = {}          # baza -> najwyższy przydzielony numer
    for (baza, nr), wpisy in sorted(grupy.items()):
        kolizja = False
        for wpis in wpisy:
            rel = _rel_z_paczki(wpis["sciezka"])
            cel = root / rel
            znany = znane.get(wpis["sha1"])
            if znany and Path(znany).exists():
                continue                  # już mamy tę treść
            if cel.exists() and _bezpieczny_sha1(cel) == wpis["sha1"]:
                continue                  # identyczna karta
            if cel.exists():
                kolizja = True            # ta sama nazwa, INNA treść
        if kolizja:
            szczyt = max(zajete.get(baza, 0), _najwyzszy_wariant(root, baza))
            nowy_nr = szczyt + 1
            zajete[baza] = nowy_nr
        else:
            nowy_nr = nr
        for wpis in wpisy:
            rel = _rel_z_paczki(wpis["sciezka"])
            cel = root / rel
            znany = znane.get(wpis["sha1"])
            if (znany and Path(znany).exists()) or (
                    cel.exists() and _bezpieczny_sha1(cel) == wpis["sha1"]):
                plan[rel] = None
                continue
            p = Path(rel)
            plan[rel] = (root / p.parent
                         / _nazwa_wariantu(baza, nowy_nr, p.suffix))
    return plan


def _opis_konfliktu_wskaznika(w_paczce: Path, rel: str) -> str:
    """Konflikt pola presetu — do raportu wchodzi TREŚĆ autora (pola są krótkie,
    więc da się ją przekleić ręcznie zamiast zgadywać, co się różni)."""
    opis = f"{rel} — zostawiono Twoją wersję"
    if w_paczce.suffix.lower() == ".txt":
        try:
            tresc = w_paczce.read_text(encoding="utf-8").strip()
        except OSError:
            return opis
        if tresc:
            skrot = tresc if len(tresc) <= 400 else tresc[:400] + "…"
            return f"{opis}; wersja autora:\n      {skrot}"
    return opis


def _scal_analize(root: Path, paczka: Path, rap: Raport, sucho: bool) -> None:
    """Cache analiz zdjęć: dokładamy tylko wpisy, których nie mamy (klucz =
    ścieżka pliku u autora, więc bezużyteczne wpisy odsiewa sam photo_analyzer
    przy niezgodnym mtime/rozmiarze — nic nie psujemy, a część analiz przechodzi)."""
    src = paczka / "stan" / "analiza_zdjec.json"
    if not src.exists():
        return
    ich = _wczytaj_json(src)
    if not ich:
        return
    cel = root / "analiza_zdjec.json"
    moje = _wczytaj_json(cel)
    nowe = {k: v for k, v in ich.items() if k not in moje}
    if not nowe:
        return
    rap.dodane.append(f"analiza_zdjec.json (+{len(nowe)} wpisów cache)")
    if not sucho:
        moje.update(nowe)
        _zapisz_json(cel, moje)


def _scal_projekt(root: Path, paczka: Path, mapa: dict[str, Path], autor: str,
                  przypisania: str, rap: Raport, sucho: bool,
                  zaplanowane: dict[str, str]) -> None:
    """Scalanie `projekt.json` PER KLUCZ. Domyślnie wygrywa stan odbiorcy —
    rozbieżności idą do raportu i do `projekt_od_<autor>.json`."""
    src = paczka / "stan" / "projekt.json"
    if not src.exists():
        return
    ich = _wczytaj_json(src)
    if not ich:
        return
    cel = root / "projekt.json"
    moje = _wczytaj_json(cel)
    ich_lokalnie = _rozwin_projekt(ich, root, mapa)
    ich_wygrywa = przypisania == "ich"

    # --- assignments / transforms / selections (per karta) ---
    for klucz in ("assignments", "selections"):
        ich_mapa = ich_lokalnie.get(klucz) or {}
        moja_mapa = dict(moje.get(klucz) or {})
        for karta, sciezka in ich_mapa.items():
            if not sciezka or not (Path(sciezka).exists()
                                   or sciezka in zaplanowane):
                rap.ostrzezenia.append(
                    f"{klucz}[{karta}]: pliku nie ma w paczce ani u Ciebie "
                    f"({Path(sciezka).name if sciezka else '—'}) — pominięto")
                continue
            if karta not in moja_mapa:
                moja_mapa[karta] = sciezka
                rap.dodane.append(f"projekt.json {klucz}[{karta}]")
            elif moja_mapa[karta] != sciezka:
                if _ta_sama_tresc(Path(moja_mapa[karta]), Path(sciezka),
                                  zaplanowane):
                    continue          # ten sam plik pod inną nazwą — nie konflikt
                if ich_wygrywa:
                    moja_mapa[karta] = sciezka
                    rap.dodane.append(f"projekt.json {klucz}[{karta}] (z paczki)")
                else:
                    rap.konflikty.append(
                        f"{klucz}[{karta}]: Twoje „{Path(moja_mapa[karta]).name}"
                        f"\" vs autora „{Path(sciezka).name}\"")
        moje[klucz] = moja_mapa

    # kadrowanie ma sens tylko przy przypisaniu, które faktycznie weszło
    ich_tr = ich_lokalnie.get("transforms") or {}
    moje_tr = dict(moje.get("transforms") or {})
    for karta, tr in ich_tr.items():
        if karta not in moje_tr and karta in (moje.get("assignments") or {}):
            moje_tr[karta] = tr
    moje["transforms"] = moje_tr

    # --- wartości talii: różnica = realny rozjazd slotów, tylko ostrzegamy ---
    if ich.get("values") and moje.get("values") and \
            list(ich["values"]) != list(moje["values"]):
        rap.ostrzezenia.append(
            f"Inna lista wartości talii — Twoja: {moje['values']}, "
            f"autora: {ich['values']}. Zostawiono Twoją (inne wartości = inne "
            f"sloty; wyrównajcie ją ręcznie przez „✎ Wartości\").")
    elif ich.get("values") and not moje.get("values"):
        moje["values"] = ich["values"]

    # --- ustawienia UI: zostają Twoje, dochodzą brakujące ---
    for klucz in _KLUCZE_USTAWIEN:
        if klucz in ich and klucz not in moje:
            moje[klucz] = ich[klucz]

    # --- tła per kolor: tylko dla kolorów, dla których nic nie masz ---
    ich_tpl = ich_lokalnie.get("templates") or {}
    moje_tpl = dict(moje.get("templates") or {})
    for suit, sciezka in ich_tpl.items():
        if suit not in moje_tpl and sciezka and (Path(sciezka).exists()
                                                 or sciezka in zaplanowane):
            moje_tpl[suit] = sciezka
    moje["templates"] = moje_tpl

    # --- motywy auto-przydziału: uzupełnienie brakujących kolorów ---
    ich_motywy = ((ich.get("auto_przydzial") or {}).get("motywy")) or {}
    if ich_motywy:
        blok = moje.setdefault("auto_przydzial", {})
        motywy = dict(blok.get("motywy") or {})
        for kolor, tekst in ich_motywy.items():
            motywy.setdefault(kolor, tekst)
        blok["motywy"] = motywy

    if sucho:
        return
    # kopia zapasowa PRZED zapisem — cofnięcie importu to skopiowanie pliku
    if cel.exists():
        kopie = root / "kopie_zapasowe"
        kopie.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cel, kopie / f"projekt_{datetime.now():%Y%m%d_%H%M%S}.json")
    _zapisz_json(cel, moje)
    if rap.konflikty:
        # pełny stan autora (już z lokalnymi ścieżkami) do ręcznego podejrzenia
        _zapisz_json(root / f"projekt_od_{autor or 'autora'}.json", ich_lokalnie)


def _rozwin_projekt(ich: dict, root: Path, mapa: dict[str, Path]) -> dict:
    """Kopia projektu z paczki z tokenami zamienionymi na LOKALNE ścieżki."""
    out = json.loads(json.dumps(ich, ensure_ascii=False))
    for klucz in _KLUCZE_SCIEZEK_MAPA:
        m = out.get(klucz)
        if isinstance(m, dict):
            rozwiniete = {}
            for k, v in m.items():
                p = sciezka_z_tokenu(v, root, mapa)
                if p is not None:
                    rozwiniete[k] = str(p)
            out[klucz] = rozwiniete
    for klucz in _KLUCZE_SCIEZEK_TEKST:
        p = sciezka_z_tokenu(out.get(klucz, ""), root, mapa)
        out[klucz] = str(p) if p is not None else ""
    box = out.get("box")
    if isinstance(box, dict):
        p = sciezka_z_tokenu(box.get("osobne_folder", ""), root, mapa)
        if p is not None:
            box["osobne_folder"] = str(p)
    return out
