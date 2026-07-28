# Atelier Kart — generator personalizowanych kart do gry (AI)

Aplikacja desktopowa (PyQt6, Windows), która robi **prawdziwą talię kart ze zdjęć
konkretnych ludzi** — znajomych, rodziny, ekipy z pracy. Każda karta to jedna osoba
(albo grupa) wstawiona w ornamentowany szablon i przemalowana przez model Gemini,
plus pudełko na tę talię. Wyjście jest gotowe do wysłania do drukarni (PDF CMYK ze
spadem) albo do gry online (atlas Tabletop Simulator).

Wygląd całej talii żyje w **presetach na dysku** (`Style/`): styl postaci, tła przodu
per kolor, rewers, typografia narożników. Zmiana presetu zmienia talię, nie kod.

**Kluczowa zasada, która tłumaczy pół programu: AI nie rysuje tekstu.** Wartości
i symbole w narożnikach (A ♥, 10 ♠, …) stempluje lokalnie Pillow **po** odpowiedzi
modelu — dlatego są identyczne na każdej karcie, a zmiana czcionki nie wymaga ani
jednego wywołania API („♻ Przestempluj narożniki").

### Jak powstaje jedna karta

```
zdjęcie  →  kolaż na szablonie tła (okno symbolu wypełnione kolorem karty)
         →  Gemini stylizuje postać  (tryb Hybrydowy lub Pełne AI)
         →  KLAMP DO SZABLONU: rama, ornament, bordiura i tarcze narożne wracają
            z szablonu piksel w piksel; z odpowiedzi modelu zostaje sama postać
         →  stempel narożników (Pillow)
         →  output/<Wartość>_<kolor>.jpg   (+ bezstratny output/_raw/*.png)
```

Klamp to jedyna obrona, której model nie może zignorować — bez niego każda karta
miałaby lekko inną ramkę i inny symbol.

---

## Spis treści

1. [Szybki start](#szybki-start)
2. [Konfiguracja — klucz API albo Vertex AI](#konfiguracja--klucz-api-albo-vertex-ai)
3. [Czego repo NIE zawiera](#czego-repo-nie-zawiera)
4. [Przepływ pracy — od zera do talii](#przepływ-pracy--od-zera-do-talii)
5. [Widoki i opcje](#widoki-i-opcje)
6. [Eksport — co wybrać do czego](#eksport--co-wybrać-do-czego)
7. [CLI (bez GUI)](#cli-bez-gui)
8. [Struktura repo i pliki stanu](#struktura-repo-i-pliki-stanu)
9. [Problemy i FAQ](#problemy-i-faq)
10. [Dla agenta AI (Claude Code)](#dla-agenta-ai-claude-code)

---

## Szybki start

```powershell
git clone <repo>; cd karty_program
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env      # otwórz i wpisz GEMINI_API_KEY=...
python -m app.main
```

Jest też skrót `Uruchom Atelier Kart.bat` (odpala `pythonw -m app.main` bez konsoli).
Testowane na Pythonie 3.13 / Windows 11.

Kilka faktów, które oszczędzają czas:

- **Aplikacja startuje bez `.env`.** Klucz jest potrzebny dopiero przy pierwszej
  generacji — GUI, przypisania, eksport gotowych kart działają bez niego.
- **Generowanie obrazów w Gemini wymaga włączonych rozliczeń.** Na darmowym planie
  limit obrazów wynosi 0 i każda generacja padnie. Billing włącza się w projekcie
  na <https://aistudio.google.com/>.
- **Tryb testowy bez kredytów** — podmienia wszystkie wywołania API na atrapy,
  cały pipeline (kolejka, warianty, eksport) da się przeklikać za darmo:

  ```powershell
  $env:KARTY_FAKE_API = "1"; python -m app.main
  ```

---

## Konfiguracja — klucz API albo Vertex AI

Ustawienia czytane są z `.env` w katalogu repo (`app/config.py`). Te same pola można
wyklikać w widoku **Ustawienia i style** — przycisk „💾 Zapisz klucze" zapisuje je
z powrotem do `.env`.

| Zmienna | Domyślnie | Do czego |
|---|---|---|
| `GEMINI_API_KEY` | pusta | Klucz Google AI Studio. **Opcja A**, najprostsza. |
| `GOOGLE_GENAI_USE_VERTEXAI` | `false` | `true` przełącza na **opcję B** — Vertex AI (Google Cloud), logowanie ADC zamiast klucza. |
| `GOOGLE_CLOUD_PROJECT` | pusta | ID projektu GCP — wymagane przy Vertex. |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Region Vertex. Modele `gemini-3*` i tak jadą przez endpoint `global` (program ustawia to sam). |
| `CUSTOM_API_KEY` | pusta | Wolny slot na klucz innego dostawcy. **Generacja kart go nie używa** — jest tylko przechowywany. |
| `KARTY_FAKE_API` | brak | `1` = atrapy zamiast wywołań API (zero kosztów). |

Vertex AI (opcja B, np. gdy masz budżet z trialu GCP):

```powershell
gcloud auth application-default login     # ADC, bez klucza API
# w .env: GOOGLE_GENAI_USE_VERTEXAI=true, GOOGLE_CLOUD_PROJECT=<id-projektu>
```

### Modele

Rejestr modeli w `config.MODELS` to **ręcznie kuratorowana lista** (dynamiczne
odkrywanie zostało wycofane — wpuszczało modele, które nie generują obrazów).
Wybór w Ustawieniach:

| Model | Kiedy |
|---|---|
| `gemini-3.1-flash-image` | **Domyślny.** „Nano Banana 2" — szybki i tani, do przemiału całej talii. |
| `gemini-3-pro-image` | Najwyższa jakość ilustracji, wolniejszy i droższy. |
| `gemini-2.5-flash-image` | Najlepsza wierność detali przy inpaintingu (poprawki fragmentów). |

Analiza zdjęć (auto-przydział) używa osobnego, taniego modelu tekstowo-wizyjnego
`gemini-2.5-flash` — nie ma go na liście wyboru.

---

## Czego repo NIE zawiera

Po świeżym klonie program **wstaje i generuje karty**, ale kilku rzeczy nie ma
(są w `.gitignore` albo pochodzą od Ciebie):

| Czego brak | Skutek | Co zrobić |
|---|---|---|
| `.env` | Generacja rzuca „Brak GEMINI_API_KEY" | `Copy-Item .env.example .env` + klucz |
| Zdjęć (`zdjecia/`) | Nie ma co przypisywać | Widok **Galeria zdjęć** → Importuj (folder tworzy się sam) |
| Rewersu (`Style/rewers/<preset>/rewers.png`) | Eksport dwustronny, atlas TTS i KRM są niepełne | Widok **Style** → sekcja Rewers → „✨ Generuj rewers" (lub wgraj własny) |
| Wykrojników (`Style/Pudełka/`) | Widok **Pudełko** zgłosi błąd o pustej bibliotece | Wrzuć PDF wykrojnika od drukarni + sidecar `<nazwa>.json` z wymiarami obszaru druku w mm |
| Profilu ICC (`assets/icc/*.icc`) | CMYK liczony przybliżeniem, kolory niekalibrowane | Wrzuć `.icc` od swojej drukarni |
| `projekt.json`, `output/`, `analiza_zdjec.json`, `assets/masks/`, `.sync/` | — | Powstają same podczas pracy (to stan lokalny, poza repo) |

**W repo SĄ tła przodu** — `Style/tla_przodu/` z gotowymi presetami (`Domyślny`
z kompletem 4 kolorów, tłami jokerów i bibliotekami masek). Pozostałe kategorie
presetów (`postac`, `rewers`, `wartosci`, `pudelko`) program tworzy sam przy
pierwszym starcie jako pusty preset `Domyślny`, a **puste pole = wartość domyślna
wbudowana w kod**, więc prompty działają od razu.

---

## Przepływ pracy — od zera do talii

1. **Wrzuć zdjęcia** — widok *Galeria zdjęć*, przeciągnij pliki z Eksploratora
   (kopiują się do `zdjecia/`). Najlepiej działają wyraźne twarze i całe sylwetki.
2. **Przypisz zdjęcia do kart** — trzy drogi:
   - ręcznie: przeciągnij zdjęcie na slot w siatce talii (*Ekran roboczy*);
   - **📁 Przypisz z folderu** — zero API, decydują nazwy plików:
     `Kier_A.jpg`, `Pik_K.png`, `Trefl_10 Patryk K.jpg` (dopisek po spacji jest OK),
     `Joker_czerwony.jpg`, `Joker_czarny.jpg`. Aliasy: `D`→dama, `W`→walet;
   - **🪄 Auto-przydział AI** — model ogląda zdjęcia (ile osób, jaki motyw) i proponuje
     układ: liczba osób → wartość karty, motyw → kolor. Podgląd przed zatwierdzeniem.
3. **Ustaw wygląd talii** — widok *Style*: styl postaci, tła przodu (najlepiej
   „🎴 Generuj komplet (4 kolory)" — pierwsze tło kotwiczy resztę), rewers, typografia
   narożników.
4. **Dostrój kartę** — *Ekran roboczy*: kadr zdjęcia (zoom/pozycja, tylko w trybie
   Hybrydowym) i „Poziom kreskówki".
5. **⚡ Generuj talię** (Ctrl+G). Postęp, kolejka i log API są w dolnym drawerze
   („☰ Kolejka i log").
6. **Popraw, co wyszło źle** — ◀ ▶ przełącza warianty karty, „★ Ustaw jako główną"
   wybiera zwycięzcę, „🩹 Popraw" pozwala zamalować fragment i przerysować tylko jego.
7. **Eksportuj** — widok *Eksport* (druk lub paczka do gry), opcjonalnie *Pudełko*.

Wszystko zapisuje się samo do `projekt.json` (przypisania, kadry, ustawienia)
i do folderów `Style/` (presety; aktywne wybory w `Style/active.json`).

---

## Widoki i opcje

Sidebar ma 7 pozycji. Uwaga terminologiczna: **„Style"** (3) to wygląd talii,
**„Ustawienia i style"** (4) to klucze API, model i format — to dwa różne widoki.

### 0. ◈ Ekran roboczy

Główne miejsce pracy: pula zdjęć | siatka talii (albo szczegół wybranej karty) |
właściwości + panel generacji. Na dole wysuwany drawer z kolejką i logiem API.

| Opcja | Co robi |
|---|---|
| **◈ Hybrydowy / ✦ Pełne AI** | Hybrydowy: AI stylizuje **tylko zdjęcie**, wklejone na szablon — najbardziej powtarzalne, działa kadrowanie. Pełne AI: model komponuje całą kartę od zera (szablon dostaje z wypełnionym oknem), kadr nie ma wtedy znaczenia. |
| **Karty:** | Ile kart wygenerować w tej serii. **`0` = wszystkie przypisane.** |
| **Warianty na kartę:** | Ile wersji tej samej karty naraz (drugi i kolejne lądują jako `K_kier_v2.jpg`); wybór zwycięzcy później, w nawigatorze historii. |
| **Pomiń już gotowe karty** | Generuje tylko karty bez gotowego pliku — oszczędza kredyty przy dokańczaniu talii. |
| **Zoom** (30–250 %, domyślnie 110) | Kadr zdjęcia w oknie symbolu. Poniżej 100 % postać jest mniejsza niż okno — program dopełnia okno rozmytą sceną ze zdjęcia, żeby model dorysował tło zamiast zostawić prostokąt. |
| **Pozycja X / Y**, **↺ Wyśrodkuj kadr** | Przesunięcie kadru. Aktywne tylko w trybie Hybrydowym i tylko gdy karta ma zdjęcie. |
| **Poziom kreskówki** (1–5, domyślnie 5) | 5 = pełny cell-shading (komiks), 1 = blisko fotorealizmu. Dotyczy ubrań, rekwizytów i tła — **twarze zawsze zostają realistyczne**. Zapisuje się w presecie stylu postaci. |
| **▦ Podgląd maski** | Nakłada na podgląd strefę „pop-out" (gdzie postać może wyjść poza okno symbolu). Złota = maska narysowana ręcznie, akcentowa = wyliczona automatycznie. |
| **Combo presetu maski** | Który zestaw masek pop-out obowiązuje talię. „Maska automatyczna" = strefa liczona algorytmem. |
| **✎ Edytuj maskę** | Rysuje maskę pop-out **dla tej jednej karty** (nadpisuje maskę koloru). Zero API. |
| **📁 Przypisz z folderu** | Przypisania z nazw plików (patrz konwencja wyżej). Zero API. |
| **🪄 Auto-przydział AI** | Analiza zdjęć tanim modelem + propozycja przypisań; wyniki są cache'owane w `analiza_zdjec.json`, więc powtórka nie kosztuje. |
| **♻ Przestempluj narożniki** | Nanosi aktualną typografię narożników na **wszystkie już wygenerowane** karty (odtwarza je z `output/_raw/`). Zero API. |
| **◀ ▶ / ★ Ustaw jako główną** | Nawigacja po wariantach karty i wybór tego, który idzie do talii i eksportu. |
| **🩹 Popraw** | Selektywna poprawka pokazywanego wariantu — patrz niżej. |
| **⚡ Generuj talię** (Ctrl+G) / **⚡ Wygeneruj** | Cała seria / tylko bieżąca karta. |

**Selektywna poprawka (🩹)** — zamalowujesz pędzlem fragment karty i wybierasz tryb:

- **✨ Poprawa AI** — do modelu idzie *wycinek* karty (region + kontekst) w pełnej
  rozdzielczości, region zaznaczony na magenta, plus Twój prompt. Suwak **siły 1–5**:
  1–3 to retusz na bazie oryginału, 4 rozmywa region, 5 wymazuje go i każe malować
  od zera. Zdjęcie przypisane karcie jedzie jako referencja, więc da się odtworzyć
  ucięty element sceny.
- **⌫ Przywróć tło szablonu** — zamalowany obszar wraca piksel w piksel do szablonu.
  **Deterministycznie, bez API** — to lekarstwo na pokrzywione linie ramki
  i przestylizowany ornament.

Wynik zawsze ląduje jako **nowy wariant**; oryginał zostaje w historii.

### 1. ▣ Galeria zdjęć

Zdjęcia wejściowe z folderu `zdjecia/`. „＋ Importuj zdjęcia" albo drop plików
z Eksploratora (kolizje nazw dostają sufiks `_1`, `_2`…). Stąd przeciąga się zdjęcia
na sloty kart.

### 2. ▦ Talie

Podgląd całej talii i historia plików.

| Opcja | Co robi |
|---|---|
| **✎ Wartości** | Zmienia listę wartości talii — np. tylko A, K, Q, J, 10 (krótsza talia = mniej kart do wygenerowania). |
| **▦ Siatka / 🕓 Historia** | Siatka: karty per kolor, klik = lightbox z wariantami. Historia: wszystkie pliki z `output/` + backupy rewersu, po dacie. |
| **prawy przycisk na slocie** | Menu: usuń przypisanie albo skasuj wygenerowane pliki karty. |
| **♻ Przestempluj narożniki** | To samo co na Ekranie roboczym. |

Klik w kartę otwiera lightbox — tam też są akcje: ustaw jako główną, usuń, przestempluj, popraw selektywnie.

### 3. ❖ Style

Cztery **biblioteki presetów** zapisywane na dysku w `Style/<kategoria>/<preset>/`
(prompty jako `.txt`, obrazy jako `.png` — jedno źródło prawdy, bez kopii roboczych).
Każda ma pełny CRUD: ＋ Nowy, ⧉ Duplikuj, zmiana nazwy, zapis/wczytanie `.zip`, usuń.
Wybór presetu **od razu** staje się wyglądem talii.

**👤 Styl postaci (pop-out)** — opis techniki, palety i nastroju stylizacji.

| Opcja | Co robi |
|---|---|
| **🏔️ Tło w oknie w odcieniach koloru karty** | Gdy zdjęcie ma scenerię (góry, horyzont), model maluje ją w oknie symbolu za postacią — monochromatycznie, w odcieniach koloru karty. Wyłączone = płaskie wypełnienie. |
| **🎬 Wygeneruj podgląd** | Jedna przykładowa karta w bieżącym stylu, **nie trafia do talii**. |

**Tła przodu kart** — preset = 2 prompty (czerwone / czarne) + obrazy 4 kolorów.

| Opcja | Co robi |
|---|---|
| **🧩 Tryb własnego promptu** | Wyłącza wszystkie dopiski programu (kształt symbolu, tarcze narożne, zakaz tekstu, paleta). Prompt idzie do modelu **dosłownie** — do kart planszówkowych, które nie mają być kartami do pokera. |
| **🎨 Generuj tło przodu** | Tylko wybrany kolor. |
| **🎴 Generuj komplet (4 kolory)** | Kier → karo → pik → trefl; pierwsze tło kotwiczy pozostałe (wspólny seed + referencja) — tak powstaje spójna talia. |
| ↳ **razem z rewersem** | Po tłach generuje też rewers wg ustawień sekcji Rewers. |
| ↳ **razem z tłami Jokerów (★)** | Dwa dodatkowe tła z oknem w kształcie gwiazdy. Jokery są **opcjonalne** — bez nich talia ma 52 karty. |
| ↳ **czarny Joker = czarno-biała kopia czerwonego** | Oszczędza jedną generację: czarny joker powstaje jako grayscale kopia czerwonego. |
| **📁 Wgraj własne tło** | Własny obraz jako tło koloru, dopasowany do formatu bez API. Przy dużej różnicy proporcji program pyta: rozciągnąć całość czy dociąć brzegi. |
| **📐 Dopasuj istniejące tła do formatu** | Przelicza **wszystkie** tła presetu do wybranego formatu karty, licząc od zapisanych oryginałów (`zrodla/`) — tła docięte starszą wersją odzyskują pełną treść. Przydatne po zmianie formatu talii. |
| **Preset maski pop-out** + **✎ Edytuj maskę pop-out (kolor)** | Maska dla **całego koloru** (pojedynczą kartę nadpisuje się na Ekranie roboczym). Maski leżą w podfolderze presetu tła, więc wędrują razem z nim przy eksporcie `.zip`. |
| **Prompt tła + styl ornamentyki** | Osobne prompty dla czerwonych i czarnych + wspólny opis ornamentyki. Do promptu dokleja się twardy layout (centralne okno, bordiura…), chyba że włączony jest tryb własny. |

**Rewers (tył kart)** — wspólny dla całej talii.

| Opcja | Co robi |
|---|---|
| **📝 Generuj z opisu / 🖼 Generuj ze zdjęcia** | Tekst → obraz albo obraz → obraz (wtedy wybierasz zdjęcie źródłowe). |
| **Orientacja wzoru ▯/▭** | Pion albo poziom wzoru. |
| **Szybki styl rewersu** | Gotowe opisy do podstawienia w edytorze. |
| **🧩 Tryb własnego promptu** | Bez wbudowanych wymogów (symetria 180°, bordiura, zakaz tekstu). |

Poprzednie rewersy są archiwizowane (`rewers_stary_*.png`) i widoczne na liście backupów.

**🔤 Wartości narożne** — typografia stemplowana lokalnie.

| Opcja | Co robi |
|---|---|
| **Czcionka** | Wybór z wbudowanej biblioteki `assets/fonts/karty/`; wybrany plik jest **kopiowany do presetu**, więc preset (i jego `.zip`) jest samowystarczalny. Można też wskazać własny `.ttf`. |
| **Rozmiary / odstęp / offsety / obwódka / cień** | Wszystko w **% wysokości tarczy**, więc działa niezależnie od formatu karty. |
| **Kolory** | Osobno dla kier/karo i pik/trefl + obwódka i cień. Te dwa kolory zasilają też prompty AI — dzięki temu cała talia trzyma jedną paletę. |

Po każdej zmianie typografii wystarczy „♻ Przestempluj narożniki" — bez regeneracji.

### 4. ⚙ Ustawienia i style

| Opcja | Co robi |
|---|---|
| **Klucz API — Gemini** | `GEMINI_API_KEY` w `.env`. |
| **Własny klucz — inny model AI** | `CUSTOM_API_KEY`. Generacja kart go **nie używa** — to slot na przyszłość. |
| **Źródło generacji: AI Studio / Vertex AI** | Vertex wymaga billingu w GCP i `gcloud auth application-default login`; pola projektu i regionu aktywne tylko dla Vertexa. |
| **💾 Zapisz klucze (.env)** | Zapisuje wszystkie powyższe do `.env` i resetuje klienta API. |
| **⚡ Testuj połączenie** | Jedno lekkie żądanie listy modeli (grosze / nic nie kosztuje). |
| **✦ Model generujący obraz** | Patrz tabela modeli wyżej. |
| **⌗ Format talii** | `poker` 63×88, `bridge` 57×88, `tarot` 70×120, `mini` 44×63 mm. Zmiana formatu wymaga dopasowania teł („📐 Dopasuj istniejące tła"). |
| **📁 Foldery projektu** | Skróty do `zdjecia/`, `Style/`, `output/` i folderu referencji. |
| **{ } System prompt (podgląd)** | Podgląd tego, co realnie idzie do modelu (złożenie aktywnych presetów) + kopiowanie do schowka. Dobre do debugowania „dlaczego karta wyszła tak, a nie inaczej". |

**🔄 Synchronizacja (pendrive)** — przeniesienie całej pracy na drugi komputer bez
internetu i bez GitHuba. Paczka to zwykły folder.

| Opcja | Co robi |
|---|---|
| **Twoje imię** | Trafia do nazw plików przy kolizjach (`… (od Marka).png`). |
| **Zawartość: Pełna** | Dokładna kopia stanu — nawet kilka GB. |
| **Zawartość: Robocza** | Bez surowych PNG i historii pudełka. U odbiorcy nie zadziała „Przestempluj" ani selektywna poprawka **przywiezionych** kart. |
| **Zawartość: Przypisane** | Jak Robocza, ale z folderu zdjęć bierze **tylko zdjęcia realnie użyte w talii** (plus osoby pudełka), bez archiwum odrzutów i bez oryginałów teł z `zrodla/`. Zdjęcia przypisane spoza folderu projektu jadą jak zawsze. W tym projekcie: ~0,9 GB zamiast 2,2 GB (roboczy) i 6,5 GB (pełny). |
| **Zawartość: Lekka** | Same presety tekstowe i maski — kilkanaście MB. |
| **📤 Eksportuj paczkę** | Buduje folder `AtelierKart_paczka_<autor>_<data>` we wskazanym miejscu. |
| **🔍 Próbnie** | Próbny **import**: pokazuje, co weszłoby do Twojego projektu, nie zapisując ani jednego pliku. Rób to przed „Wczytaj paczkę". |
| **📥 Wczytaj paczkę** | **Import niczego nie kasuje.** Kolidująca karta wchodzi jako nowy wariant `_vN`, przy rozbieżnych przypisaniach domyślnie wygrywa wersja lokalna, `projekt.json` jest scalany per klucz (a nie podmieniany), przed zapisem powstaje kopia w `kopie_zapasowe/`. |

### 5. ⇲ Eksport

Patrz [osobna sekcja](#eksport--co-wybrać-do-czego) — tam jest ściąga, co wybrać.
Opcje wspólne:

| Opcja | Co robi |
|---|---|
| **Spad 3 mm** | Dokłada spad do pliku. Nieaktywne przy KRM i JKB — te mają geometrię narzuconą przez drukarnię. |
| **Znaczniki cięcia** | Linie cięcia na arkuszu. |
| **Strony rewersów (druk dwustronny)** | Dokłada strony z rewersem, z kolumnami odbitymi lustrzanie (żeby po obróceniu kartki trafiały w awersy). |
| **2 × 3 na stronę — margines drukarki** | Zamiast 3×3. Przy 3×3 ze spadem zostaje ~1,5 mm marginesu, którego część drukarek domowych nie zadrukuje. |
| **Podbicie kolorów (1–5)** | **Tylko dla wyjść CMYK.** Kompensuje węższy gamut druku: rozciągnięcie tonalne, gamma, kontrast, nasycenie, mikrokontrast. 1 = prawie bez ingerencji, 3 = domyślne, 5 = mocne. |
| **👁 Podgląd podbicia** | Składa PNG „przed \| po" na pierwszej gotowej karcie — nie trzeba renderować całego PDF-a, żeby ocenić ustawienie. |
| **Wersja lekka ≤ 4096 px** | Ogranicza rozdzielczość atlasu (starsze GPU nie łykają większych tekstur). |

Pasek u góry pokazuje gotowość („N/52 kart gotowych · brak rewersu") i informuje,
czy jest profil ICC.

### 6. ▧ Pudełko

Osobny potok: grafika AI z twarzami całej ekipy nałożona na **profesjonalny wykrojnik
(dieline) z drukarni**. Wykrojnik czytany jest z `Style/Pudełka/` — najlepiej
oryginalny PDF, bo tylko wtedy działa eksport „na wykrojnik drukarni". Kolory linii
mają znaczenie: zielony = spad, niebieski = cięcie, czerwony = bigowanie.

| Opcja | Co robi |
|---|---|
| **🧑 Osoby po kolei** (domyślny) | Każda osoba jest **osobno** przerabiana przez AI i wklejana na wygenerowane tło. Deterministyczne: dokładnie tyle postaci, ile osób, bez powtórek i „dorysowanych" ludzi. |
| **🖼 Jedna scena** | Jedna generacja całości. Ładniejsza kompozycja, ale model może pominąć albo powielić osoby. |
| **🧩 Osobne panele** | Przód i tył jako osobne sceny AI (spójne przez wspólny styl), boki = prawdziwe mini-karty Twojej talii. Wymaga wygenerowanych kart. |
| **📁 Wskaż folder osób** | Reguła: **1 podfolder = 1 osoba** (kilka zdjęć tej samej osoby = lepsze podobieństwo). Bez podfolderów: 1 plik = 1 osoba. |
| **🎬 Reżyser sceny** | Najpierw generuje same postacie i pokazuje je do akceptacji (dopisek + „🔄 Regeneruj" per osoba), dopiero potem AI komponuje z nich scenę. Zalecane przy większych ekipach. |
| **📂 Wznów postacie (Reżyser)** | Wczytuje postacie zapisane na dysku z przerwanej sesji — bez ponownego płacenia za generację. |
| **🧩 Tryb własnego promptu** | Bez dopisków programu (wraparound, wierność twarzy, zakaz tekstu). |
| **Eksportuj z liniami cięcia (proof)** | Włączone = plik z naniesionymi liniami do sprawdzenia. Wyłączone = czysty artwork dla drukarni. |
| **Eksport PNG / PDF / CMYK / na wykrojnik drukarni** | Ostatni wstawia grafikę **pod** wektorowe linie oryginalnego PDF-a od drukarni — to jest to, co się wysyła. Wymaga wykrojnika w PDF (i biblioteki PyMuPDF). |

Warianty działają jak przy kartach: ◀ ▶ + „✓ Ustaw jako główną", a „🩹 Popraw
selektywnie" otwiera ten sam dialog inpaintingu.

---

## Eksport — co wybrać do czego

| Wariant | Co wychodzi | Kiedy |
|---|---|---|
| **Arkusz PDF (A4)** | Karty na A4 (poker/bridge 3×3, tarot 2×2, mini 4×4), opcjonalny spad, znaczniki i strony rewersów | Druk domowy / ksero. **Drukuj w skali 100 %**, nie „dopasuj do strony". |
| **Pojedyncze pliki PNG** | Jeden PNG na kartę, 300 DPI RGB | Podgląd, archiwum, własny skład |
| **Pliki CMYK (TIFF)** | Jeden TIFF CMYK na kartę, spad 3 mm | Drukarnia, która chce pojedyncze pliki |
| **Druk do KRM (PDF CMYK)** | **Jeden** wielostronicowy PDF: strona = netto + spad, karta wyśrodkowana i wskalowana w margines bezpieczeństwa, tło zalane kolorem krawędzi (żadnych białych rogów), **strona 1 = rewers** | Drukarnia KRM. Geometria sztywna, dlatego spad i znaczniki są nieaktywne. |
| **Druk do JKB Print (2 × PDF CMYK)** | `<nazwa>_karty.pdf` + `<nazwa>_rewers.pdf`, strona = netto + spad 3 mm, grafika full-bleed | Drukarnia JKB Print |
| **PNG w ZIP** | 52 karty + rewers + `manifest.json` | Własny program, archiwum |
| **Arkusz-atlas (sprite 13×4)** | Jeden obraz, siatka 13×4 | Silniki gier, własne aplikacje |
| **Tabletop Simulator** | Atlas 10×7 + osobny rewers | Gra online w TTS |

Konwersja do CMYK nie idzie przez `Image.convert("CMYK")` (dawało `K = 0`
i wydruk „jak przez mgłę") — jest pełny GCR z limitem farby, a przy obecnym
profilu ICC dochodzi ImageCms z kompensacją czerni.

---

## CLI (bez GUI)

Wszystko uruchamiane z katalogu repo. **API zużywa tylko `generuj_karte`** — reszta
jest w 100 % offline.

```powershell
# jedna karta (API; joker: JOKER joker_czerwony)
python -m scripts.generuj_karte K kier "zdjecia\foto.jpg" hybrid
python -m scripts.generuj_karte K kier "zdjecia\foto.jpg" full_ai gemini-3-pro-image

# katalog gotowych obrazów -> jeden PDF CMYK do drukarni KRM (ten sam potok co GUI)
python -m scripts.druk_krm karty\ -o output\druk_krm.pdf --podbicie 4
python -m scripts.druk_krm karty\ --format poker --rewers Style\rewers\Domyślny\rewers.png

# synchronizacja przez pendrive
python -m scripts.sync_paczka eksport E:\paczka --autor Marek --profil roboczy --od-ostatniej
python -m scripts.sync_paczka eksport E:\paczka --autor Marek --profil przypisane
python -m scripts.sync_paczka import E:\AtelierKart_paczka_2026-07-28 --sucho

# testy / narzędzia diagnostyczne (offline)
python -m scripts.test_kompozycja      # maski szablonów + kompozycja próbnej karty
python -m scripts.test_klamp           # maska klampu na output/_raw/api/*.png + podglądy
python -m scripts.test_symbol          # asercje: proste linie ramki + nietknięty symbol
python -m scripts.test_eksport         # eksportery (pypdf opcjonalnie — bez niego 2 kontrole pominięte)
python -m scripts.test_sync            # niezmienniki synchronizacji na mini-repo w TEMP
```

Sanity check składni po zmianach w kodzie: `python -m compileall -q app scripts`.

> **Znany stan:** `test_kompozycja` przechodzi maski, kolaż i narożniki, ale kończy
> się FAIL-em na asercji „kandydat teksturowy nie uratował płaskiej plamy" — to
> otwarte strojenie heurystyki klampu, **nie objaw zepsutego klonu**. `test_symbol`,
> `test_eksport` i `test_sync` przechodzą w całości.

---

## Struktura repo i pliki stanu

```
app/
  api/gemini_client.py     jedyne wejście do API (generate_image + nakładki, retry z backoffem)
  core/
    generator.py           orkiestracja generacji (HYBRID / FULL_AI, tła, rewers, poprawki)
    masks.py               maski szablonu (flood-fill), maska klampu, maski użytkownika
    compositor.py          składanie karty + stempel narożników (Pillow)
    style_store.py         presety w Style/ — jedno źródło prawdy o wyglądzie
    prompts.py             wszystkie prompty i twarde dopiski layoutu
    photo_analyzer.py      analiza zdjęć + auto-przydział
    exporter.py + eksport/ potok eksportu (formaty -> układy -> wyjścia, CMYK/ICC)
    pudelko.py             wykrojniki, panele, kompozycja pudełka (offline)
    sync.py                paczki na pendrive (eksport/import, scalanie projekt.json)
  gui/                     motyw, sidebar, widoki (views/), dialogi, wątki robocze
scripts/                   CLI: generacja, druk KRM, synchronizacja, testy offline
Style/                     presety: postac/ tla_przodu/ rewers/ wartosci/ pudelko/ Pudełka/
assets/  fonts/ (ui + karty)   icc/ (profile CMYK)   masks/ (cache, generowany)
output/                    gotowe karty *.jpg  +  _raw/*.png (bezstratne, baza poprawek)
zdjecia/                   zdjęcia wejściowe
```

Pliki stanu (poza repo, tworzą się same):

| Plik | Co trzyma |
|---|---|
| `projekt.json` | Przypisania zdjęć, kadry, nazwa i wartości talii, wybrany model i format, ustawienia eksportu, pudełka i synchronizacji |
| `Style/active.json` | Który preset jest aktywny w każdej kategorii |
| `analiza_zdjec.json` | Cache analizy zdjęć (unieważniany po zmianie pliku lub motywów) |
| `assets/masks/` | Cache masek szablonów — można skasować, odbuduje się |
| `.sync/`, `kopie_zapasowe/` | Ślad wysłanych paczek i kopie `projekt.json` przed importem |

Architektura w szczegółach (dlaczego klamp wygląda tak, jak wygląda, jak działa
eksport, gdzie są pułapki) jest opisana w **`CLAUDE.md`**.

---

## Problemy i FAQ

**Generacja pada / „Brak GEMINI_API_KEY".** Sprawdź `.env`, a potem billing —
generowanie obrazów w Gemini nie działa na darmowym planie (limit 0). W Ustawieniach
jest „⚡ Testuj połączenie".

**Zmieniłem kod i nic się nie zmieniło.** PyQt nie przeładowuje modułów w locie —
**zrestartuj aplikację**, inaczej testujesz poprzednią wersję.

**Eksport mówi „brak rewersu".** Rewersu nie ma w repo — wygeneruj go w widoku Style
albo wgraj własny. Bez niego druk dwustronny, KRM i atlas TTS są niekompletne.

**Widok Pudełko zgłasza błąd o `Style/Pudełka/`.** Biblioteka wykrojników jest pusta —
wrzuć PDF od drukarni (plus `<nazwa>.json` z wymiarami obszaru druku w mm).

**Eksport PDF się wywala.** Brakuje `reportlab` (`pip install -r requirements.txt`).
Jeśli nie działa wykrojnik PDF ani eksport „na wykrojnik drukarni" — brakuje `PyMuPDF`.

**`python -m scripts.test_eksport` rzuca ImportError.** Ten skrypt wymaga `pypdf`,
którego nie ma w produkcyjnych zależnościach: `pip install pypdf`.

**Uruchamiam na Linuksie/macOS i leci `FileNotFoundError` o czcionce.**
`config.find_serif_font()` szuka `.ttf` bezpośrednio w `assets/fonts/`, a potem
w fontach Windows. Wrzuć dowolny serif `.ttf` do `assets/fonts/` albo ustaw czcionkę
w presecie „Wartości narożne" (kopiuje się wtedy do presetu).

**Wydruk wychodzi mętny, „jak przez mgłę".** To był objaw zerowego kanału K przy
naiwnej konwersji CMYK — dziś potok robi GCR z limitem farby. Jeśli mimo to jest
płasko, podnieś „Podbicie kolorów" i wrzuć profil ICC swojej drukarni do `assets/icc/`.

**Symbol koloru wychodzi inny na każdej karcie / ramka faluje.** Tak wygląda karta,
której nie domknął klamp. Najpierw sprawdź, czy tło jest znormalizowane
(„📐 Dopasuj istniejące tła do formatu"), a lokalne skrzywienia napraw poprawką
selektywną w trybie „⌫ Przywróć tło szablonu" (bez API).

**Import synchronizacji nadpisał mi pracę.** Nie nadpisuje — nigdy nie kasuje plików.
Kolidujące karty wchodzą jako nowe warianty `_vN`, a stan sprzed importu leży
w `kopie_zapasowe/`. Raport z importu zapisuje się jako `raport_sync_*.txt`.

---

## Dla agenta AI (Claude Code)

- **Architektura, niezmienniki i pułapki: `CLAUDE.md`.** Ten README opisuje program
  od strony użytkownika; `CLAUDE.md` mówi, dlaczego kod wygląda tak, jak wygląda.
- **Weryfikacja bez wydawania kredytów:**
  ```powershell
  python -m compileall -q app scripts            # sanity składni (nie ma lintera ani pytest)
  $env:KARTY_FAKE_API = "1"; python -m app.main  # atrapy zamiast API
  $env:QT_QPA_PLATFORM = "offscreen"             # smoke test GUI bez okna
  python -m scripts.test_kompozycja; python -m scripts.test_symbol; python -m scripts.test_sync
  ```
- **Po zmianie w `app/` trzeba zrestartować aplikację** — PyQt nie hot-reloaduje.
- **Czego nie ruszać:**
  - narożniki rysuje wyłącznie `compositor.stempluj_narozniki()` — nigdy nie każ ich
    generować modelowi (prompty kończą się `NO_TEXT_SUFFIX`);
  - `app/api/stability_client.py` to martwy provider, ale jego `abort_active()` /
    `reset_abort()` są **żywym mechanizmem anulowania** workerów;
  - `config.MODELS` to ręczna lista — modele Imagen zostały wyłączone przez Google,
    nie hardcoduj ich; nowy model = wpis w `MODELS` + opis w `MODEL_DESCRIPTIONS`;
  - w GUI: `widgets.SnapSlider`, `NoScrollComboBox`, `NoScrollSpinBox` zamiast surowych
    kontrolek Qt (kółko myszy nie może zmieniać wartości w scrollowanych panelach).
- **Nie commituj** `.env` ani `dane_do_api.md` (zawiera prawdziwe klucze; oba są
  w `.gitignore`).
