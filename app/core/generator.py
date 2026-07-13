"""Orkiestracja generowania kart w obu trybach + tła i rewers.

Tryb testowy: zmienna środowiskowa KARTY_FAKE_API=1 zastępuje wywołania API
tanimi atrapami (zwraca wejściowe zdjęcie / jednolity obraz po ~1 s) —
pozwala przeklikać cały pipeline GUI bez zużywania kredytów.
"""
from __future__ import annotations

import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from app import config
from app.api import gemini_client, stability_client
from app.core import compositor, masks, photo_analyzer, prompts, style_store
from app.core.models import CardSpec, GenMode, Suit

# Kolaż/maska wysyłane do API — 1536 px wystarcza inpaintingowi, a tniemy
# koszty uploadu; wynik i tak skalujemy z powrotem do rozdzielczości szablonu.
MAX_API_SIDE = 1536

# Zdjęcie-referencja twarzy: przy grupach 3+ każda twarz dostaje za mało
# pikseli w standardowym pomniejszeniu — większa referencja ratuje rysy.
PHOTO_REF_SIDE = 768
PHOTO_REF_SIDE_GRUPA = 1536
GRUPA_OD_OSOB = 3


def _fake_api() -> bool:
    return os.getenv("KARTY_FAKE_API", "") == "1"


def _provider() -> str:
    return config.current_model()["provider"]


def _fake_illustration(photo_path: Path | None) -> Image.Image:
    time.sleep(1.0)
    if photo_path is not None and photo_path.exists():
        img = Image.open(photo_path).convert("RGB")
        img.thumbnail((768, 768), Image.Resampling.LANCZOS)
        return ImageOps.posterize(img, 3)   # udawany "cell-shading"
    return Image.new("RGB", (600, 840), config.CREAM_HEX)


def _fake_template() -> Image.Image:
    time.sleep(1.0)
    img = Image.new("RGB", (744, 1039), config.CREAM_HEX)
    draw = ImageDraw.Draw(img)
    draw.rectangle([20, 20, 723, 1018], outline=config.ACCENT_HEX, width=8)
    return img


def _klamp_do_szablonu(wynik: Image.Image, spec: CardSpec) -> Image.Image:
    """Twardy klamp tła — jedyna obrona, której model nie może zignorować
    (Gemini honoruje instrukcje, nie piksele). Strefa dopuszczalna jest
    ADAPTACYJNA (masks.maska_klampu): rdzeń symbol+ring bezwarunkowo, dalej
    sylwetka postaci spójna z rdzeniem (próg różnicy od szablonu); tło,
    tarcze narożne i pas bordiury zawsze wracają piksel-w-piksel z szablonu."""
    template = Image.open(spec.suit.template_path).convert("RGB")
    if wynik.size != template.size:
        wynik = wynik.resize(template.size, Image.Resampling.LANCZOS)
    # Wyjście modelu SPRZED klampu do output/_raw/api/ — jedyne źródło do
    # rozstrzygania „model uciął vs klamp uciął" i strojenia progów KLAMP_*
    # offline (scripts.test_klamp), bez ponownych wywołań API
    api_path = spec.raw_path.parent / "api" / spec.raw_path.name
    api_path.parent.mkdir(parents=True, exist_ok=True)
    wynik.save(api_path, "PNG")
    # Kolor wypełnienia okna z kolażu (anty-bleed w masce klampu)
    styl = compositor.styl_z_presetu()
    kolor_hex = styl.kolor_czerwony if spec.suit.is_red else styl.kolor_czarny
    kolor_tla = (int(kolor_hex[1:3], 16), int(kolor_hex[3:5], 16),
                 int(kolor_hex[5:7], 16))
    maska = masks.maska_klampu(wynik, template, spec.suit.template_path,
                               kolor_tla=kolor_tla)
    # Baza kompozycji = szablon z oknem wypełnionym kolorem karty: feather
    # rdzenia i szczelina przy konturze mieszają się z kolorem wypełnienia,
    # nie z kremem szablonu („biały ślad" symbolu). Poza oknem baza jest
    # piksel-w-piksel szablonem, jak dotąd.
    baza = compositor.wypelnij_okno(template, spec.suit)
    return Image.composite(wynik, baza, maska)


def _popout_card(spec: CardSpec) -> Image.Image:
    """Pipeline pop-out: kolaż (szablon + CAŁE zdjęcie położone na karcie)
    → model przerysowuje postać wychodzącą z okna symbolu → klamp adaptacyjny
    zostawia rdzeń + sylwetkę, resztę przywraca z szablonu.

    Kadr zdjęcia (zoom/przesunięcie) pochodzi z GUI (spec.transform) —
    zdjęcie nie jest docinane żadną maską.
    """
    init = compositor.build_init_image(
        spec.suit, spec.photo_path, spec.transform, max_side=MAX_API_SIDE
    )
    if _fake_api():
        time.sleep(1.0)
        result = ImageOps.posterize(init, 3)   # udawany rezultat inpaintingu
    elif _provider() == "stability":
        mask = masks.get_popout_mask(spec.suit.template_path)
        result = stability_client.inpaint(init, mask,
                                          prompts.popout_prompt(spec.suit))
    else:
        # seed per wariant: deterministyczna spójność, a kolejne warianty
        # (rosnący spec.variant) wciąż się różnią
        osoby = photo_analyzer.liczba_osob_z_cache(spec.photo_path)
        # Oryginalne zdjęcie osobno — twarze w kolażu są małe i model
        # karykaturyzował rysy (prompts.photo_ref_note); grupy 3+ dostają
        # większą referencję (więcej pikseli na każdą twarz)
        foto = ImageOps.exif_transpose(Image.open(spec.photo_path)).convert("RGB")
        strona = (PHOTO_REF_SIDE_GRUPA if (osoby or 0) >= GRUPA_OD_OSOB
                  else PHOTO_REF_SIDE)
        foto.thumbnail((strona, strona), Image.Resampling.LANCZOS)
        result = gemini_client.edit_card_image(
            init,
            prompts.popout_prompt(spec.suit, photo_ref=True,
                                  liczba_osob=osoby),
            seed=config.GEN_SEED + spec.variant, photo=foto,
        )

    # Cokolwiek API (zwłaszcza Gemini, który nie honoruje twardej maski)
    # przemalowało poza symbolem+ringiem, wraca do oryginału szablonu.
    return _klamp_do_szablonu(result, spec)


def _build_card_raw(spec: CardSpec) -> Image.Image:
    """Buduje SUROWY obraz karty (bez narożników, bez zapisu) — AI nie rysuje
    tekstu; narożniki stempluje potem compositor.stempluj_narozniki()."""
    if spec.photo_path is None:
        raise ValueError(f"Karta {spec.label} nie ma przypisanego zdjęcia")

    # Tła wrzucone ręcznie do folderu presetu / zmiana formatu w Ustawieniach:
    # plik dopasowuje się do wybranej wielkości zanim ruszy kolaż i klamp
    normalizuj_szablon(spec.suit.template_path)
    template = Image.open(spec.suit.template_path).convert("RGB")

    if spec.mode is GenMode.HYBRID:   # tryb pop-out
        return _popout_card(spec)
    # GenMode.FULL_AI — wymaga dwóch obrazów wejściowych, tylko Gemini
    if _fake_api():
        return _klamp_do_szablonu(
            compositor.compose_card_raw(spec, _fake_illustration(spec.photo_path)),
            spec,
        )
    if _provider() != "gemini":
        raise ValueError(
            "Tryb Pełne AI wymaga modelu Gemini (Stability przyjmuje jeden "
            "obraz wejściowy) — przełącz model albo użyj trybu pop-out"
        )
    osoby = photo_analyzer.liczba_osob_z_cache(spec.photo_path)
    prompt = prompts.full_card_prompt(spec.suit, liczba_osob=osoby)
    # Szablon idzie do modelu z oknem JUŻ wypełnionym kolorem karty (jak
    # kolaż pop-out): model widzi finalny kształt, rozmiar i KOLOR symbolu —
    # nie wymyśla własnego, większego serca ani wypełnienia
    result = gemini_client.compose_full_card(
        compositor.wypelnij_okno(template, spec.suit), spec.photo_path, prompt,
        seed=config.GEN_SEED + spec.variant,
        photo_max_side=(PHOTO_REF_SIDE_GRUPA
                        if (osoby or 0) >= GRUPA_OD_OSOB else 1024),
    )
    # Model mimo zakazu potrafi przemalować tło/ornamenty i dorysować pipy —
    # klamp przywraca WSZYSTKO poza symbolem+ringiem (w tym tarcze) z szablonu
    return _klamp_do_szablonu(result, spec)


def generate_card(spec: CardSpec) -> Path:
    """Generuje jedną kartę: surowe wyjście AI do output/_raw/ (PNG), finalna
    karta (raw + narożniki) do output/. Zwraca ścieżkę finalnego pliku."""
    raw = _build_card_raw(spec)
    template = Image.open(spec.suit.template_path).convert("RGB")
    compositor.save_raw(raw, spec, template.size)
    card = compositor.stempluj_narozniki(raw, spec)
    compositor.save_card(card, spec, template.size)
    return spec.output_path


def generate_sample(spec: CardSpec) -> Image.Image:
    """Generuje pojedynczą kartę PODGLĄDU — zwraca obraz, NIE zapisuje do output/
    (nie zaśmieca historii ani wariantów)."""
    return compositor.stempluj_narozniki(_build_card_raw(spec), spec)


def przestempluj_plik(spec: CardSpec) -> Path:
    """Przestemplowuje narożniki karty BEZ wywołań API: czyta surowy PNG
    z output/_raw/ (fallback dla starych kart bez raw: finalny .jpg z twardym
    resetem tarcz z szablonu), stempluje wg aktywnego presetu „wartosci"
    i nadpisuje finalny plik."""
    template = Image.open(spec.suit.template_path).convert("RGB")
    if spec.raw_path.exists():
        raw = Image.open(spec.raw_path).convert("RGB")
        if raw.size != template.size:
            raw = raw.resize(template.size, Image.Resampling.LANCZOS)
    elif spec.output_path.exists():
        stary = Image.open(spec.output_path).convert("RGB")
        if stary.size != template.size:
            stary = stary.resize(template.size, Image.Resampling.LANCZOS)
        tmasks = masks.get_masks(spec.suit.template_path)
        raw = compositor.wyczysc_tarcze(stary, template, tmasks)
    else:
        raise FileNotFoundError(f"Brak pliku karty {spec.label} do przestemplowania")
    card = compositor.stempluj_narozniki(raw, spec)
    compositor.save_card(card, spec, template.size)
    return spec.output_path


def _fit_card_ratio(img: Image.Image, landscape: bool = False) -> Image.Image:
    """Wymusza proporcje karty 63:88 — lub 88:63 dla rewersu poziomego
    (docięcie środka, bez zniekształceń)."""
    ratio = (config.CARD_MM[0] / config.CARD_MM[1] if landscape
             else config.CARD_MM[1] / config.CARD_MM[0])
    target_w = img.width
    target_h = round(target_w * ratio)
    return ImageOps.fit(img, (target_w, target_h), method=Image.Resampling.LANCZOS)


# Tolerancja odchyłu proporcji tła od wybranego formatu karty: poniżej progu
# tylko skalujemy szerokość (bez docięcia) — chroni domyślne tła 1696×2528
# (odchył ~6% od 63:88, który drukarnia skaluje bez widocznej dystorsji)
# przed docięciem ucinającym bordiurę
PROG_ODCHYLU_PROPORCJI = 0.08


def normalizuj_szablon(path: Path) -> None:
    """Dopasowuje PLIK tła do wybranego formatu karty i standardowej
    rozdzielczości (offline, idempotentnie) — tła wrzucone ręcznie do folderu
    presetu lub zmiana formatu w Ustawieniach nie rozstrajają klampu, którego
    stałe pikselowe (masks.KLAMP_*) są strojone pod szerokość
    config.TEMPLATE_STD_SZEROKOSC.

    Oryginał ląduje jednorazowo w podfolderze zrodla/ obok pliku (niewidoczny
    dla Suit.available_templates — skan tylko top-level) i kolejne
    normalizacje liczą się od niego, bez kumulacji docięć. Nadpisanie pliku
    podbija mtime, więc cache masek i kolażu unieważniają się same.
    """
    path = Path(path)
    target = config.template_target_size()
    with Image.open(path) as probka:
        size = probka.size
    ratio_target = target[0] / target[1]
    odchyl = abs(size[0] / size[1] - ratio_target) / ratio_target
    if size == target or (size[0] == config.TEMPLATE_STD_SZEROKOSC
                          and odchyl <= PROG_ODCHYLU_PROPORCJI):
        return
    zrodlo = path.parent / "zrodla" / path.name
    if not zrodlo.exists():
        zrodlo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, zrodlo)
    img = ImageOps.exif_transpose(Image.open(zrodlo)).convert("RGB")
    odchyl = abs(img.width / img.height - ratio_target) / ratio_target
    if odchyl > PROG_ODCHYLU_PROPORCJI:
        img = ImageOps.fit(img, target, method=Image.Resampling.LANCZOS)
    else:
        img = img.resize(
            (target[0], round(target[0] * img.height / img.width)),
            Image.Resampling.LANCZOS)
    # quality dotyczy tylko JPEG (PNG ignoruje) — domyślne 75 dokładałoby
    # widoczne artefakty do tła, z którego klamp składa finalne karty
    img.save(path, quality=95)
    print(f"[szablony] {path.name}: znormalizowano {size[0]}x{size[1]} -> "
          f"{img.width}x{img.height} (oryginał w zrodla/)")


def generate_template(suit: Suit, prompt: str | None = None, *,
                      reference: Path | None = None,
                      use_auto_reference: bool = True,
                      seed: int | None = None) -> Path:
    """Generuje nowe tło (szablon) i zapisuje do folderu AKTYWNEGO presetu
    teł przodu (Style/tla_przodu/<preset>/).

    prompt=None → domyślny prompt grawerski per kolor; podanie własnego
    (np. z zakładki „Tła i rewersy") pozwala sterować stylem paczki.
    reference — jawny obraz referencyjny (tryb kompletu: pierwsze tło zestawu
    kotwiczy pozostałe kolory); use_auto_reference=False bez reference =
    świeży start bez obrazu (nowy zestaw nie ma dziedziczyć starego wyglądu).
    seed — deterministyczna spójność zestawu (None = losowo)."""
    if prompt is None:
        prompt = prompts.template_generation_prompt(
            prompts.SUIT_NAME_EN[suit.nazwa], suit.is_red
        )
    reference_path = reference
    if reference_path is None and use_auto_reference:
        try:
            reference_path = suit.template_path
        except FileNotFoundError:
            reference_path = None  # pierwszy szablon tego koloru — bez referencji

    if _fake_api():
        img = _fake_template()
    elif _provider() == "stability":
        img = stability_client.generate_template_image(prompt, reference_path)
    else:
        contents: list = [prompt]
        if reference_path is not None:
            reference_img = Image.open(reference_path).convert("RGB")
            reference_img.thumbnail((768, 768), Image.Resampling.LANCZOS)
            contents.append(reference_img)
        img = gemini_client.generate_image(contents, seed=seed)
    # Proporcje wybranego formatu + standardowa rozdzielczość (model zwraca
    # ~1024 px — upscale LANCZOS): wszystkie tła mają jedną skalę pod klamp
    img = ImageOps.fit(img, config.template_target_size(),
                       method=Image.Resampling.LANCZOS)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = style_store.front_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{suit.nazwa} ai {stamp}.png"
    img.save(path)
    return path


def import_template(suit: Suit, src: Path) -> Path:
    """Wgrywa WŁASNY obraz użytkownika jako tło przodu danego koloru — bez
    API: docina do proporcji wybranego formatu karty, skaluje do standardowej
    rozdzielczości i zapisuje do folderu aktywnego presetu teł przodu.
    Zwraca ścieżkę nowego pliku."""
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    # Jawny import zawsze dopasowuje w pełni: proporcje wybranego formatu
    # karty + standardowa rozdzielczość (skala strojenia klampu)
    img = ImageOps.fit(img, config.template_target_size(),
                       method=Image.Resampling.LANCZOS)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = style_store.front_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{suit.nazwa} wlasne {stamp}.png"
    img.save(path)
    return path


def generate_back(prompt: str | None = None,
                  source_photo: Path | None = None,
                  orientation: str = "portrait") -> Path:
    """Generuje wspólny rewers talii i zapisuje jako rewers.png w folderze
    AKTYWNEGO presetu rewersu (Style/rewers/<preset>/).

    source_photo != None → tryb image-to-image (rewers inspirowany zdjęciem);
    orientation: "portrait" | "landscape" (poziomy rewers jest zapisywany
    w proporcji 88:63 — eksporter obraca go do komórki pionowej).
    Poprzedni rewers nie jest kasowany (kosztował kredyty) — dostaje
    sufiks _stary_<stamp>.
    """
    if prompt is None:
        prompt = prompts.back_generation_prompt(orientation=orientation)

    if _fake_api():
        img = _fake_template()
        if source_photo is not None and Path(source_photo).exists():
            img = _fake_illustration(Path(source_photo))
    elif _provider() == "stability":
        img = stability_client.generate_template_image(
            prompt, Path(source_photo) if source_photo else None,
            landscape=(orientation == "landscape"),
        )
    else:
        contents: list = [prompt]
        if source_photo is not None and Path(source_photo).exists():
            reference = Image.open(source_photo).convert("RGB")
            reference.thumbnail((768, 768), Image.Resampling.LANCZOS)
            contents.append(reference)
        img = gemini_client.generate_image(contents)
    img = _fit_card_ratio(img, landscape=(orientation == "landscape"))

    back = style_store.back_path()
    back.parent.mkdir(parents=True, exist_ok=True)
    if back.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = back.with_name(f"rewers_stary_{stamp}.png")
        back.rename(backup)
    img.save(back)
    return back
