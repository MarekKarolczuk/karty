# Projekt: Generator Personalizowanych Kart do Gry (AI-Powered)

## 1. Koncepcja i Cel Projektu
Aplikacja z graficznym interfejsem użytkownika (GUI) do zautomatyzowanego generowania spersonalizowanych kart do gry. Program wykorzystuje API Google AI Studio do transformacji dostarczonych zdjęć na wektorowe ilustracje i płynnego wklejania ich (inpainting) w przygotowane szablony kart, zachowując bezwzględną spójność stylistyczną całej talii.

## 2. Kluczowe Wymagania Techniczne
* **Silnik AI:** Google AI Studio API (obsługa inpaintingu / image-to-image).
* **Rozmiar Karty:** Rygorystycznie utrzymywany format **63 x 88 mm** (standard pokerowy). Skrypt nie może zmieniać rozdzielczości wyjściowej szablonów.
* **Nazewnictwo Plików:** Automatyczny zapis wygenerowanych kart według schematu `[Wartość]_[Kolor]` (np. `A_karo.jpg`, `K_kier.jpg`, `J_pik.jpg`).
* **Zarządzanie Zadaniami:** GUI pozwalające użytkownikowi w prosty sposób sparować plik ze zdjęciem wejściowym z konkretną kartą (np. "przypisz `tomek.jpg` do Króla Pik").

## 3. Struktura Katalogów
Aplikacja musi opierać się na następującej strukturze folderów:
* `/zdjecia/` – Zbiór surowych zdjęć użytkownika (input).
* `/tlo/` – Zbiór przygotowanych, pustych szablonów kart (tła, ramki). Pliki z tego folderu są nienaruszalne przez skrypt poza obszarem maski.
* `/przykladowe_karty_fajne/` – Folder referencyjny ze stylami (dla modeli wizyjnych / podpowiedzi).
* `/output/` – Folder docelowy na wygenerowane karty.

## 4. Interfejs Użytkownika (GUI)
Interfejs musi być prosty i intuicyjny, realizujący następujący przepływ pracy (flow):
1. **Wybór Szablonu:** Użytkownik wybiera plik tła z folderu `/tlo/`.
2. **Mapowanie Zdjęć:** Lista rozwijana lub system "przeciągnij i upuść", gdzie użytkownik przypisuje zdjęcie z folderu `/zdjecia/` do konkretnej karty.
3. **Parametry:** Pola tekstowe do zdefiniowania "Wartości" (np. A, K, Q, J, 10).
4. **Generuj:** Przycisk uruchamiający wywołanie do API Google.

---

## 5. ⚠️ SPÓJNOŚĆ STYLISTYCZNA (PRIORYTET KRYTYCZNY) ⚠️
Najważniejszym założeniem projektu jest absolutna powtarzalność wizualna. Skrypt generujący prompt do API musi wymuszać następujące twarde zasady:
* **Kolorystyka:** Główny odcień czerwieni (wartości, znaki, ramki, detale tła) musi bezwzględnie oscylować wokół kodu HEX **`#801515`**.
* **Czcionka (Typografia):** Wartości w narożnikach muszą być wygenerowane klasyczną czcionką szeryfową (**`serif font`**).
* **Formatowanie Tekstu:** Wartość (np. "K") i znak (np. "♥") pod spodem muszą znajdować się w pionie.

## 6. Wytyczne dla Modelu AI (Do osadzenia w kodzie jako System Prompt)
Poniższe definicje muszą być przekazywane do Google AI Studio w celu wymuszenia odpowiedniego stylu inpaintingu.

**Styl Tła i Wypełnienia Karty (Szablon - Nie do edycji):**
> Precyzyjna, neo-ornamentalna ilustracja w stylu grawerskim (custom-deck engraving style), wykonana z nasyconymi ciemnoczerwonymi (#801515) ornamentami na kremowym tle. Styl bardzo bogaty i symetryczny, pełen skomplikowanych zwojów (scrollwork), precyzyjnych liści akantu i ornamentów grawerskich, przypominających te na banknotach lub w autorskich taliach kart. Linie czyste, ostre i jednolite, omijające surowość trawienia (etched). Ograniczona paleta kolorów tła. Centralnym elementem jest ozdobna, pogrubiona rama (karo/serce/pik/trefl) z nasyconym, czerwonym wypełnieniem i wyraźnym konturem. Szablon karty musi pozostać w 100% nienaruszony przez AI.

**Styl Postaci (Ilustracja Wewnątrz Ramki):**
> Precyzyjna, w pełni kolorowa ilustracja wektorowa, wykonana z wyraźnymi, czystymi, czarnymi konturami. To NIE jest uproszczony "line-art" ani płaskie wypełnienie monochromatyczne. Wykorzystuje pełną, wielokolorową paletę (skóra, włosy, ubrania np. szare, beżowe, czarne). Cieniowanie wyłącznie plamowe (cell-shaded) – czyste, zdefiniowane płaszczyzny koloru bez gradientów. Ilustracja nadaje nowoczesny, precyzyjny charakter, zachowując maksymalne podobieństwo do pierwowzoru ze zdjęcia wejściowego.

## 7. Instrukcja Inpaintingu (Ograniczenia Nakładania)
Logika wywołania API dla każdej karty:
1. Skrypt nakłada maskę na obszar wewnątrz centralnego symbolu oraz na narożne tarcze.
2. Skrypt wysyła polecenie: *"Seamless inpainting. Nie edytuj tła. Narzuć na centralny obszar zdjęcie wejściowe przerobione na styl opisany wyżej (wielokolorowa grafika wektorowa cell-shaded). Zdjęcie ma być wstawione ściśle w pionie. W narożnikach wstaw wartość [ZMIENNA_WARTOŚĆ] czcionką serif font w kolorze #801515 w pionie. Nie zmieniaj rozdzielczości obrazu wyjściowego."*


###
wygenerowane przez ai z takiego promta i wedle oczekiwan
opisz pomysl i jak ma dzialac wszystkow pliku markdown gotowy do skopiowania bo pisze program ktory bedzie generowal mi karty , wazne rozmiar kart ma byc 63 x88 mm, zdjecia ktore wygeneruje maja byc podpisane w stylu A_karo (wartosc_korol), bedzie to dzialac na zasadzie api od gogole ai studio oraz chce aby to dzialo w taki sposb zeby dalo sie latwo to edtywac jakie zdjecia (np. za pomoca interfejsu graficznego) dobierz zdjecie do tego i tego ) WAZNE zeby bylo opisane w projekcie i podkreslone ze zalezy mi na tej samej kolorystyce wartosci stylu czcionki stylu kart itd bede foldery z zdjcia( zbior zdjec ktore mozna wykorzystywac do robienia kart) tlo (tla ktore beda uzywane do robienia kart) przykladowe_karty_fajene ale beda sluzyc do wskazywania jak mniej wiecej chce aby wygladaly karty .

pnizej moje opisy dodtyczace stylu itd :

zastosuj kolor wartosci oraz innych elemnrtow nie liczac zdjecia Odcień oscyluje wokół #801515  

czcionka wartosci:serif font





Styl Tła i Wypełnienia Karty: To precyzyjna, neo-ornamentalna ilustracja w stylu grawerskim (custom-deck engraving style), wykonana z nasyconymi, nasyconymi ciemnoczerwonymi ornamentami na kremowym tle. Styl ten jest bardzo bogaty i symetryczny, pełen skomplikowanych zwojów (scrollwork), precyzyjnych liści akantu i ornamentów grawerskich, przypominających te na banknotach lub w wysokiej klasy, autorskich taliach kart kolekcjonerskich. Linie są czyste, ostre i jednolite, omijając surowość trawienia (etched), a paleta kolorów tła jest ściśle ograniczona. Centralnym elementem jest ozdobna, pogrubiona rama (w kształcie karo lub serca) z nasyconym, jednolitym czerwonym wypełnieniem i wyraźnym konturem, która zawiera centralną ilustrację. Na zewnętrznych krawędziach mogą występować dodatkowe, czerwone paski obramowania.



Styl Postaci (Ilustracja): Jest to precyzyjna, kolorowa ilustracja wektorowa, wykonana z wyraźnymi, czystymi, czarnymi konturami. To nie jest uproszczony "line-art" ani płaskie wypełnienie; wykorzystuje ona pełną, wielokolorową paletę dla postaci (skóra, włosy, ubrania w różnych odcieniach: szarym, beżowym, czarnym, czerwonym itp.). Cieniowanie jest plamowe (cell-shaded), czyli czyste, zdefiniowane płaszczyzny koloru bez gradientów, co nadaje ilustracji nowoczesny, ale precyzyjny charakter, zachowując przy tym duże podobieństwo do pierwowzoru ze zdjęcia. Centralna ilustracja postaci jest umieszczona wewnątrz czerwonej ramy. 

to jest kier czerwone  tlo ktorego nie masz edytowac tylko narzucac na to zdjecie przerobione na ai oraz wstawic wartosc np.(A, K,J ) zdejcie ma byc wstawione w pionie oraz wartosc tez nie zmieniacj rozdzielczosc zdjecie itd 

zdjecie wstaw w kolorze tzn w wielu kolorach  

