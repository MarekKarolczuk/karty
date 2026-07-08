# Atelier Kart — Generator Personalizowanych Kart do Gry (AI)

Aplikacja PyQt6 generująca spersonalizowane karty 63×88 mm z Twoich zdjęć,
z użyciem Gemini (Google AI Studio) lub Stability AI. Spójność stylu: kolor
`#801515`, czcionka serif, wartości w pionie, szablon tła nienaruszony.
Interfejs w stylu „Atelier" (ciemny, grawersko-vintage) — sidebar z 7 widokami.

## Uruchomienie

```powershell
pip install -r requirements.txt
python -m app.main
```

Klucze API trzymane są w pliku `.env` (`GEMINI_API_KEY=...`,
`STABILITY_API_KEY=...`) — można je też wpisać w widoku **Ustawienia**
(zapis do `.env` + test połączenia z saldem kredytów Stability).

> ⚠️ **Wymagany billing**: generowanie obrazów w Gemini API nie działa na
> darmowym planie (limit 0). Włącz rozliczenia dla projektu na
> https://aistudio.google.com/ (model `gemini-2.5-flash-image`).

> 💡 **Tryb testowy bez kredytów**: `KARTY_FAKE_API=1 python -m app.main`
> podmienia wywołania API na atrapy — cały pipeline GUI (kolejka, animacje,
> eksport) można przeklikać za darmo.

## Widoki (sidebar)

1. **Pracownia** — pula zdjęć z szukajką, duży podgląd z efektem „transformacji
   AI", właściwości karty, spójność stylu + wybór/generowanie tła per kolor,
   film-strip całej talii ze statusami.
2. **Talia** — siatka slotów per kolor ♥♦♠♣ (liczniki przypisań), **✎ Wartości**
   zmienia listę wartości. Klik = przypisz wybrane zdjęcie, przeciąganie działa,
   prawy przycisk = usuń przypisanie / wygenerowane pliki.
3. **Generowanie** — tryb (**Hybrydowy** / **Pełne AI**), wybór modelu,
   **Karty:** limit serii, **Wersje:** warianty (`K_kier_v2.jpg`), podgląd na
   żywo ze smugą skanującą, **kolejka**, pauza/wznowienie i **LOG API**.
4. **Galeria** — gotowe karty z `output/`; klik obraca kartę na rewers (flip).
5. **Eksport** — generowanie **rewersu** (AI, wspólny dla talii, zapis do
   folderu aktywnego presetu `Style/rewers/<preset>/rewers.png`) oraz:
   - **Do druku (IRL)**: arkusz PDF A4 (3×3 lub 2×3), karty dokładnie
     63×88 mm @300 DPI, opcjonalny spad 3 mm i znaczniki cięcia, strony
     rewersów pod druk dwustronny — drukuj w skali 100%;
   - **Do gry/programu**: ZIP z PNG + `manifest.json`, atlas
     **Tabletop Simulator 10×7** (ostatnie pole = rewers), sprite-sheet 13×4,
     opcja „lekka ≤4096 px".
6. **Style** — cztery biblioteki presetów (styl postaci, styl tła, tła przodu,
   rewers) z pełnym CRUD i zapisem na dysku w `Style/<kategoria>/<preset>/`
   (prompty jako `.txt`, obrazy jako `.png` — jedno źródło prawdy, bez kopii).
   Twarde wymogi layoutu doklejane zawsze.
7. **Ustawienia** — klucze API, test połączenia, foldery projektu, reguły
   spójności.

Przypisania, wybrane tła, nazwa talii i ustawienia zapisują się automatycznie
do `projekt.json`; presety stylu do folderów `Style/` (aktywne wybory
w `Style/active.json`).

## CLI (bez GUI)

```powershell
# pojedyncza karta
python -m scripts.generuj_karte K kier "zdjecia\moje.jpg" hybrid
# test masek i kompozycji bez wywołań API
python -m scripts.test_kompozycja
# offline test eksporterów (PDF/ZIP/atlas)
python -m scripts.test_eksport
# jednorazowa ekstrakcja fontów UI z bundla designu (wymaga fonttools+brotli)
python -m scripts.wyciagnij_fonty
```

## Struktura

- `app/api/` — klienci Gemini i Stability (obrazy, retry)
- `app/core/` — prompty + edytowalne style (`style_store`), maski szablonów
  (flood-fill, cache w `assets/masks/`), kompozytor Pillow, orkiestracja,
  eksporter (PDF/ZIP/atlas)
- `app/gui/` — motyw „Atelier" (`theme.py`), animacje (`animations.py`),
  sidebar, widoki w `app/gui/views/`, wątki robocze
- `assets/fonts/ui/` — fonty interfejsu (Archivo, Cormorant Garamond,
  JetBrains Mono) wydobyte z designu; **nie** są używane do rysowania kart
- `Design/` — oryginalny design HTML (źródło wyglądu)
- `Style/` — biblioteki presetów stylu: `postac/`, `styl_tla/`, `tla_przodu/`
  (szablony tła kart), `rewers/` (rewers + backupy); `zdjecia/` — zdjęcia
  wejściowe, `output/` — gotowe karty `[Wartość]_[kolor].jpg`
