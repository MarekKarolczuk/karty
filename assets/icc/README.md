# Profile ICC CMYK (eksport do druku)

Eksport „Pliki CMYK do druku" (panel Eksport → DO DRUKU) konwertuje karty z RGB
na CMYK. Jeśli w tym folderze znajdzie się plik profilu **`*.icc`** lub **`*.icm`**,
konwersja użyje go z zarządzaniem kolorem (intent perceptual) i osadzi profil w
plikach TIFF. Bierze **pierwszy alfabetycznie** profil (patrz
`config.cmyk_profile_path()`).

Bez profilu w tym folderze konwersja spada do przybliżonego trybu Pillow
(`Image.convert("CMYK")`) — pliki są poprawnym CMYK-iem, ale kolor jest
niekalibrowany.

## Jak dodać właściwy profil

1. Najlepszy: profil **od Twojej drukarni** — wrzuć jego `.icc` tutaj.
2. Standard europejski (offset powlekany): **ISO Coated v2** / **eciCMYK**
   (darmowe do pobrania z eci.org).
3. Standard amerykański: **US Web Coated (SWOP) v2**.

Po wrzuceniu pliku nic więcej nie trzeba — eksport wykryje go automatycznie.

Licencje dołożonych profili odnotuj poniżej.
