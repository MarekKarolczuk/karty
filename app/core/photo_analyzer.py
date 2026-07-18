"""Auto-przydział zdjęć AI — analiza zdjęć i układanie propozycji talii.

AI (tani model tekstowo-wizyjny, config.ANALYSIS_MODEL) opisuje każde zdjęcie:
liczba osób, motywy, jakość i dopasowanie do motywów czterech kolorów
(edytowalnych w GUI). Z analiz czysty, deterministyczny algorytm układa
propozycję przypisań wg twardej reguły: liczba osób decyduje o wartości karty
(1 osoba → figury A/K/Q/J, 2–9 → odpowiadająca liczba, 10+ → dziesiątka),
a dopasowanie motywu wybiera kolor. Wyniki analiz są cache'owane na dysku
(config.ANALIZA_JSON) per plik (mtime+rozmiar) i per opisy motywów (hash),
żeby ponowne uruchomienia nie zużywały API.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from app import config

# Domyślne opisy motywów kolorów (edytowalne w GUI, zapisywane w projekt.json).
DOMYSLNE_MOTYWY: dict[str, str] = {
    "kier": "zdjęcia rodzinne, bliskie osoby, czułe i domowe momenty",
    "karo": "lato, wakacje, plaża, słońce, wyjazdy, łódki i woda",
    "pik": "zima, wieczorne i nocne kadry, elegancja",
    "trefl": "imprezy, zdjęcia grupowe, spotkania ze znajomymi, eventy",
}

# Nazwy wartości do budowania powodu propozycji (kopia z workspace_view.CARD_NAMES
# — importu stamtąd nie robimy: core nie może zależeć od gui).
_NAZWY_WARTOSCI = {"A": "As", "K": "Król", "Q": "Dama", "J": "Walet"}

# Kolejność kolorów przy remisie dopasowania (stała kolejność Suit).
_KOLORY = ("kier", "karo", "pik", "trefl")

# Priorytet wartości w grupie figur: najlepsze jakościowo zdjęcia solo → asy.
_FIGURY = ("A", "K", "Q", "J")


@dataclass
class AnalizaZdjecia:
    """Wynik analizy jednego zdjęcia (z AI albo z cache)."""
    sciezka: str
    liczba_osob: int                 # 0 = brak ludzi na zdjęciu
    motywy: list[str]                # tagi PL, np. ["lato", "plaża"]
    jakosc: int                      # 1–5 (5 = ostre, dobrze naświetlone)
    dopasowanie: dict[str, int]      # {"kier": 0–10, ...} — trafność per kolor
    opis: str                        # jedno zdanie PL (powód w podglądzie)


@dataclass
class Propozycja:
    """Jedna proponowana para karta↔zdjęcie."""
    klucz: str                       # "kier:A" — format MainWindow._key()
    sciezka: str
    powod: str                       # czytelne uzasadnienie PL


def _fake_api() -> bool:
    """Tryb testowy bez API (atrapa analizy) — jak generator._fake_api()."""
    return os.getenv("KARTY_FAKE_API", "") == "1"


# --- prompt analizy -------------------------------------------------------------

_PROMPT_ANALIZY = """\
You are analyzing a photo that will be assigned to a card in a custom
playing-card deck.
Return ONLY a single valid JSON object. No markdown fences, no commentary.

The deck has four suits with user-defined theme descriptions (in Polish):
- "kier" (hearts): {kier}
- "karo" (diamonds): {karo}
- "pik" (spades): {pik}
- "trefl" (clubs): {trefl}

Analyze the attached photo and return exactly this JSON structure:
{{
  "people_count": <integer - number of clearly visible people; 0 if none>,
  "themes": [<2 to 5 short lowercase Polish tags describing setting/mood,
              e.g. "lato", "plaza", "impreza", "lodka", "zima", "rodzina">],
  "quality": <integer 1-5; 5 = sharp, well lit, good composition;
              1 = blurry or dark>,
  "suit_scores": {{"kier": <0-10>, "karo": <0-10>, "pik": <0-10>,
                   "trefl": <0-10>}},
  "description": "<one short sentence in Polish describing the photo>"
}}
"suit_scores" must express how well the photo's content and mood match EACH
suit theme description above (10 = perfect match). Scores are independent of
each other.
"""


# --- cache na dysku (config.ANALIZA_JSON) ---------------------------------------

def motywy_hash(motywy: dict[str, str]) -> str:
    """Hash opisów motywów — zmiana opisów unieważnia wpis cache (dopasowanie
    per kolor zależy od opisów). Hash per wpis, nie globalny: powrót do starych
    opisów nie gubi wcześniejszych analiz."""
    tekst = "|".join(f"{k}={motywy.get(k, '')}" for k in _KOLORY)
    return hashlib.md5(tekst.encode("utf-8")).hexdigest()[:12]


def _wczytaj_cache() -> dict:
    if not config.ANALIZA_JSON.exists():
        return {"wersja": 1, "zdjecia": {}}
    try:
        data = json.loads(config.ANALIZA_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"wersja": 1, "zdjecia": {}}
    if not isinstance(data, dict) or not isinstance(data.get("zdjecia"), dict):
        return {"wersja": 1, "zdjecia": {}}
    return data


def _zapisz_cache(data: dict) -> None:
    try:
        config.ANALIZA_JSON.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass


def z_cache(path: Path, motywy: dict[str, str]) -> AnalizaZdjecia | None:
    """Analiza z cache, jeśli plik się nie zmienił (mtime+rozmiar) i opisy
    motywów są te same (hash). None = trzeba analizować przez API."""
    wpis = _wczytaj_cache()["zdjecia"].get(str(path))
    if not isinstance(wpis, dict):
        return None
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    if wpis.get("mtime") != stat.st_mtime or wpis.get("size") != stat.st_size:
        return None
    if wpis.get("motywy_hash") != motywy_hash(motywy):
        return None
    analiza = wpis.get("analiza")
    if not isinstance(analiza, dict):
        return None
    try:
        return _analiza_z_dict(str(path), analiza)
    except (ValueError, TypeError, KeyError):
        return None


def liczba_osob_z_cache(path) -> int | None:
    """Liczba osób na zdjęciu z cache analizy (auto-przydział) — zero API.
    Waliduje TYLKO mtime+rozmiar; motywy_hash jest ignorowany, bo liczba
    osób nie zależy od opisów motywów kolorów. None = brak ważnego wpisu
    (generator wtedy używa generycznej instrukcji w promptach)."""
    if path is None:
        return None
    wpis = _wczytaj_cache()["zdjecia"].get(str(path))
    if not isinstance(wpis, dict):
        return None
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    if wpis.get("mtime") != stat.st_mtime or wpis.get("size") != stat.st_size:
        return None
    analiza = wpis.get("analiza")
    if not isinstance(analiza, dict):
        return None
    try:
        n = int(analiza.get("liczba_osob"))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def policz_cache_hits(paths: list, motywy: dict[str, str]) -> int:
    """Ile z podanych zdjęć ma ważny wpis w cache — do estymaty „K wywołań
    API" w dialogu PRZED startem (jedno wczytanie pliku cache)."""
    zdjecia = _wczytaj_cache()["zdjecia"]
    mhash = motywy_hash(motywy)
    hits = 0
    for p in paths:
        wpis = zdjecia.get(str(p))
        if not isinstance(wpis, dict) or wpis.get("motywy_hash") != mhash:
            continue
        try:
            stat = Path(p).stat()
        except OSError:
            continue
        if wpis.get("mtime") == stat.st_mtime and wpis.get("size") == stat.st_size:
            hits += 1
    return hits


def dopisz_cache(path: Path, motywy: dict[str, str],
                 analiza: AnalizaZdjecia) -> None:
    """Dopisuje jedną analizę do cache na dysku (wołane po każdym zdjęciu —
    anulowanie serii nie marnuje wykonanych analiz)."""
    try:
        stat = Path(path).stat()
    except OSError:
        return
    data = _wczytaj_cache()
    data["zdjecia"][str(path)] = {
        "mtime": stat.st_mtime,
        "size": stat.st_size,
        "motywy_hash": motywy_hash(motywy),
        "analiza": {
            "liczba_osob": analiza.liczba_osob,
            "motywy": analiza.motywy,
            "jakosc": analiza.jakosc,
            "dopasowanie": analiza.dopasowanie,
            "opis": analiza.opis,
        },
    }
    _zapisz_cache(data)


# --- analiza jednego zdjęcia ----------------------------------------------------

def _clamp(value, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return lo


def _analiza_z_dict(sciezka: str, dane: dict) -> AnalizaZdjecia:
    """Buduje AnalizaZdjecia z surowego dicta (JSON modelu albo cache),
    z walidacją typów i clampowaniem zakresów."""
    surowe_dopasowanie = dane.get("dopasowanie") or dane.get("suit_scores") or {}
    if not isinstance(surowe_dopasowanie, dict):
        surowe_dopasowanie = {}
    dopasowanie = {k: _clamp(surowe_dopasowanie.get(k, 0), 0, 10)
                   for k in _KOLORY}
    motywy_raw = dane.get("motywy") or dane.get("themes") or []
    motywy = [str(m) for m in motywy_raw if str(m).strip()] \
        if isinstance(motywy_raw, list) else []
    liczba = dane.get("liczba_osob", dane.get("people_count"))
    return AnalizaZdjecia(
        sciezka=sciezka,
        liczba_osob=_clamp(liczba, 0, 99),
        motywy=motywy[:5],
        jakosc=_clamp(dane.get("jakosc", dane.get("quality", 3)), 1, 5),
        dopasowanie=dopasowanie,
        opis=str(dane.get("opis", dane.get("description", ""))).strip(),
    )


def _parsuj_json(tekst: str) -> dict:
    """Zdejmowanie ewentualnych płotków ```json``` i parsowanie do dicta."""
    tekst = tekst.strip()
    if tekst.startswith("```"):
        tekst = tekst.split("\n", 1)[-1] if "\n" in tekst else ""
        if tekst.rstrip().endswith("```"):
            tekst = tekst.rstrip()[:-3]
    dane = json.loads(tekst)
    if not isinstance(dane, dict):
        raise ValueError(f"Model zwrócił {type(dane).__name__} zamiast obiektu JSON")
    return dane


def _fake_analiza(path: Path) -> AnalizaZdjecia:
    """Deterministyczna atrapa (KARTY_FAKE_API=1) — z md5 nazwy pliku, żeby
    testy algorytmu były powtarzalne. Obejmuje przypadek 0 osób."""
    time.sleep(0.05)
    h = hashlib.md5(Path(path).name.encode("utf-8")).digest()
    liczba_osob = h[0] % 5                     # 0–4
    jakosc = h[1] % 5 + 1                      # 1–5
    dopasowanie = {k: h[2 + i] % 11 for i, k in enumerate(_KOLORY)}
    tagi = ["lato", "zima", "impreza", "rodzina", "łódka", "wieczór"]
    motywy = [tagi[h[6] % len(tagi)], tagi[h[7] % len(tagi)]]
    return AnalizaZdjecia(
        sciezka=str(path),
        liczba_osob=liczba_osob,
        motywy=sorted(set(motywy)),
        jakosc=jakosc,
        dopasowanie=dopasowanie,
        opis=f"Atrapa analizy zdjęcia {Path(path).name}.",
    )


def analizuj_zdjecie(path: Path, motywy: dict[str, str]) -> AnalizaZdjecia:
    """Analizuje jedno zdjęcie przez Gemini (albo atrapę w trybie testowym).
    Nie dotyka cache — zapis robi wywołujący (worker) po sukcesie.
    Błąd parsowania JSON → ValueError (zdjęcie zostaje pominięte)."""
    if _fake_api():
        return _fake_analiza(path)
    from app.api import gemini_client
    prompt = _PROMPT_ANALIZY.format(
        **{k: motywy.get(k) or DOMYSLNE_MOTYWY[k] for k in _KOLORY}
    )
    # 768 px wystarcza do liczenia osób i motywu — mniej tokenów niż 1024
    odpowiedz = gemini_client.generate_text(
        [prompt, gemini_client._load_photo(path, max_side=768)]
    )
    try:
        dane = _parsuj_json(odpowiedz)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(
            f"Niepoprawny JSON analizy: {exc} (odpowiedź: {odpowiedz[:200]!r})"
        ) from exc
    return _analiza_z_dict(str(path), dane)


# --- algorytm układania propozycji ----------------------------------------------

def wartosci_dla_osob(n: int, wartosci_talii: list[str]) -> list[str]:
    """Twarda reguła wartości wg liczby osób: 1 → figury (A, K, Q, J),
    2–9 → odpowiadająca liczba, 10+ → "10", 0 → brak dopasowania.
    Zwraca tylko wartości obecne w aktualnej (edytowalnej) liście wartości
    talii, w kolejności priorytetu."""
    if n == 1:
        return [v for v in _FIGURY if v in wartosci_talii]
    if 2 <= n <= 9:
        return [str(n)] if str(n) in wartosci_talii else []
    if n >= 10:
        return ["10"] if "10" in wartosci_talii else []
    return []


def nazwa_wartosci(value: str) -> str:
    return _NAZWY_WARTOSCI.get(value, value)


def _powod(analiza: AnalizaZdjecia, value: str, kolor: str) -> str:
    osoby = ("1 osoba" if analiza.liczba_osob == 1
             else f"{analiza.liczba_osob} osób"
             if analiza.liczba_osob >= 5
             else f"{analiza.liczba_osob} osoby")
    czesci = [f"{osoby} → {nazwa_wartosci(value)}"]
    if analiza.motywy:
        czesci.append(f"motywy: {', '.join(analiza.motywy)}"
                      f" → {kolor} ({analiza.dopasowanie.get(kolor, 0)}/10)")
    else:
        czesci.append(f"{kolor} ({analiza.dopasowanie.get(kolor, 0)}/10)")
    czesci.append(f"jakość {analiza.jakosc}/5")
    if analiza.opis:
        czesci.append(analiza.opis)
    return " · ".join(czesci)


def uloz_propozycje(
    analizy: list[AnalizaZdjecia],
    wartosci_talii: list[str],
    przypisania: dict[str, str],
    nadpisz: bool,
) -> tuple[list[Propozycja], list[str], list[str]]:
    """Układa propozycję przypisań (zachłannie, deterministycznie).

    Zwraca (propozycje, karty_bez_kandydata, nieuzyte_zdjecia):
    - cele: wszystkie karty talii, a przy nadpisz=False tylko bez przypisania;
    - pula: przy nadpisz=False tylko zdjęcia nieużyte w przypisaniach;
    - zdjęcia bez ludzi (0 osób) nigdy nie są przypisywane;
    - w grupie wartości zdjęcia idą od najlepszej jakości, każde bierze wolną
      kartę z najwyższym dopasowaniem koloru (remis: priorytet A>K>Q>J
      i stała kolejność kolorów).
    Reguła liczby osób jest TWARDA — brak kandydata zostawia kartę pustą.
    """
    # karty-cele
    zajete = set() if nadpisz else set(przypisania)
    wolne: set[tuple[str, str]] = {
        (kolor, v) for kolor in _KOLORY for v in wartosci_talii
        if f"{kolor}:{v}" not in zajete
    }

    # pula zdjęć
    uzyte_sciezki = set() if nadpisz else set(przypisania.values())
    nieuzyte: list[str] = []
    pula: list[AnalizaZdjecia] = []
    for analiza in analizy:
        if analiza.sciezka in uzyte_sciezki:
            continue
        if analiza.liczba_osob <= 0:
            nieuzyte.append(analiza.sciezka)
            continue
        pula.append(analiza)

    # grupowanie po dozwolonych wartościach + sortowanie po jakości
    pula.sort(key=lambda a: (-a.jakosc, Path(a.sciezka).name.lower()))

    propozycje: list[Propozycja] = []
    for analiza in pula:
        dozwolone = wartosci_dla_osob(analiza.liczba_osob, wartosci_talii)
        kandydaci = [
            (kolor, v) for v in dozwolone for kolor in _KOLORY
            if (kolor, v) in wolne
        ]
        if not kandydaci:
            nieuzyte.append(analiza.sciezka)
            continue
        # najwyższe dopasowanie koloru; remis: priorytet wartości (kolejność
        # w `dozwolone`), potem stała kolejność kolorów
        kolor, value = max(
            kandydaci,
            key=lambda kv: (analiza.dopasowanie.get(kv[0], 0),
                            -dozwolone.index(kv[1]),
                            -_KOLORY.index(kv[0])),
        )
        wolne.discard((kolor, value))
        propozycje.append(Propozycja(
            klucz=f"{kolor}:{value}",
            sciezka=analiza.sciezka,
            powod=_powod(analiza, value, kolor),
        ))

    karty_bez_kandydata = sorted(
        f"{kolor}:{v}" for kolor, v in wolne
    )
    return propozycje, karty_bez_kandydata, nieuzyte


# --- import przypisań z nazw plików folderu ---------------------------------------

# Rozszerzenia zdjęć honorowane przy imporcie z folderu (case-insensitive).
_IMPORT_ROZSZERZENIA = {".jpg", ".jpeg", ".png"}

# Aliasy wartości w nazwach plików: polskie oznaczenia figur → kody programu.
_ALIASY_WARTOSCI = {"D": "Q", "W": "J"}


@dataclass(frozen=True)
class ImportPrzypisan:
    """Wynik parsowania folderu ze zdjęciami nazwanymi `<Kolor>_<Wartość>.<ext>`."""
    przypisania: dict[str, str]        # klucz "kolor:wartość" → ścieżka pliku
    pominiete: list[tuple[str, str]]   # (nazwa pliku, powód pominięcia)


def _klucz_ze_stemu(stem: str, wartosci_talii: list[str]) -> tuple[str | None, str]:
    """Mapuje stem nazwy pliku na klucz karty ("kolor:wartość") albo (None, powód).

    Konwencja: `Kier_A`, `Trefl_10 dowolny dopisek`, `Joker_czerwony`;
    wielkość liter bez znaczenia, dama jako D lub Q, walet jako W lub J.
    """
    from app.core.models import JOKER_WARTOSC

    tekst = stem.strip().lower()
    if tekst.startswith("joker"):
        reszta = tekst[len("joker"):].lstrip("_ ").split()
        odmiana = reszta[0] if reszta else ""
        if odmiana.startswith("czerwon"):
            return f"joker_czerwony:{JOKER_WARTOSC}", ""
        if odmiana.startswith("czarn"):
            return f"joker_czarny:{JOKER_WARTOSC}", ""
        return None, "niejednoznaczny joker (oczekiwano Joker_czerwony/Joker_czarny)"

    czesci = tekst.split("_", 1)
    if len(czesci) != 2 or czesci[0] not in _KOLORY:
        return None, "nazwa nie zaczyna się od koloru (Kier/Karo/Pik/Trefl/Joker)"
    kolor = czesci[0]
    # wartość = pierwszy człon reszty do spacji ("10 patryk k" → "10")
    token = czesci[1].strip().split()
    wartosc = token[0].upper() if token else ""
    wartosc = _ALIASY_WARTOSCI.get(wartosc, wartosc)
    if wartosc not in wartosci_talii:
        return None, f"nieznana wartość karty: {wartosc or '(brak)'}"
    return f"{kolor}:{wartosc}", ""


def przypisania_z_folderu(folder: Path,
                          wartosci_talii: list[str]) -> ImportPrzypisan:
    """Buduje przypisania kart ze zdjęć w folderze wg konwencji nazw
    `<Kolor>_<Wartość>.<ext>` (np. `Kier_A.jpg`, `Trefl_10 opis.jpg`,
    `Joker_czerwony.jpg`). Czysta funkcja, zero API.

    Przy dwóch plikach na tę samą kartę wygrywa pierwszy alfabetycznie,
    pozostałe trafiają do `pominiete` z powodem.
    """
    przypisania: dict[str, str] = {}
    pominiete: list[tuple[str, str]] = []
    pliki = sorted(
        (p for p in Path(folder).iterdir()
         if p.is_file() and p.suffix.lower() in _IMPORT_ROZSZERZENIA),
        key=lambda p: p.name.lower(),
    )
    for plik in pliki:
        klucz, powod = _klucz_ze_stemu(plik.stem, wartosci_talii)
        if klucz is None:
            pominiete.append((plik.name, powod))
            continue
        if klucz in przypisania:
            zajety = Path(przypisania[klucz]).name
            pominiete.append((plik.name, f"karta {klucz} już zajęta przez {zajety}"))
            continue
        przypisania[klucz] = str(plik)
    return ImportPrzypisan(przypisania=przypisania, pominiete=pominiete)
