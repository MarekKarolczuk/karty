"""Orkiestracja generowania kart w obu trybach + tła i rewers.

Tryb testowy: zmienna środowiskowa KARTY_FAKE_API=1 zastępuje wywołania API
tanimi atrapami (zwraca wejściowe zdjęcie / jednolity obraz po ~1 s) —
pozwala przeklikać cały pipeline GUI bez zużywania kredytów.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from app import config
from app.api import gemini_client, stability_client
from app.core import compositor, masks, prompts, style_store
from app.core.models import CardSpec, GenMode, Suit

# Kolaż/maska wysyłane do API — 1536 px wystarcza inpaintingowi, a tniemy
# koszty uploadu; wynik i tak skalujemy z powrotem do rozdzielczości szablonu.
MAX_API_SIDE = 1536


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


def _popout_card(spec: CardSpec, template_size: tuple[int, int]) -> Image.Image:
    """Pipeline pop-out: kolaż (szablon + wkadrowane zdjęcie) → inpainting
    w POSZERZONEJ masce (ponad ramę symbolu) → postać wychodzi z ramki.

    Kadr zdjęcia (zoom/przesunięcie) pochodzi z GUI (spec.transform) —
    zdjęcie nie jest już sztywno docinane do środka symbolu.
    """
    init = compositor.build_init_image(
        spec.suit, spec.photo_path, spec.transform, max_side=MAX_API_SIDE
    )
    if _fake_api():
        time.sleep(1.0)
        result = ImageOps.posterize(init, 3)   # udawany rezultat inpaintingu
    elif _provider() == "stability":
        mask = masks.get_popout_mask(spec.suit.template_path)
        result = stability_client.inpaint(init, mask, prompts.popout_prompt())
    else:
        result = gemini_client.edit_card_image(init, prompts.popout_prompt())

    if result.size != template_size:
        result = result.resize(template_size, Image.Resampling.LANCZOS)
    # Clamp przez maskę: cokolwiek API (zwłaszcza Gemini, który nie honoruje
    # twardej maski) przemalowało poza symbolem+ringiem, wraca do oryginału
    # szablonu — grawerowane tło zostaje piksel-w-piksel nietknięte.
    template = Image.open(spec.suit.template_path).convert("RGB")
    popout_full = masks.get_popout_mask(spec.suit.template_path)
    return Image.composite(result, template, popout_full)


def _build_card_raw(spec: CardSpec) -> Image.Image:
    """Buduje SUROWY obraz karty (bez narożników, bez zapisu) — AI nie rysuje
    tekstu; narożniki stempluje potem compositor.stempluj_narozniki()."""
    if spec.photo_path is None:
        raise ValueError(f"Karta {spec.label} nie ma przypisanego zdjęcia")

    template = Image.open(spec.suit.template_path).convert("RGB")

    if spec.mode is GenMode.HYBRID:   # tryb pop-out
        return _popout_card(spec, template.size)
    # GenMode.FULL_AI — wymaga dwóch obrazów wejściowych, tylko Gemini
    if _fake_api():
        return compositor.compose_card_raw(spec, _fake_illustration(spec.photo_path))
    if _provider() != "gemini":
        raise ValueError(
            "Tryb Pełne AI wymaga modelu Gemini (Stability przyjmuje jeden "
            "obraz wejściowy) — przełącz model albo użyj trybu pop-out"
        )
    prompt = prompts.full_card_prompt(prompts.SUIT_NAME_EN[spec.suit.nazwa])
    result = gemini_client.compose_full_card(template, spec.photo_path, prompt)
    if result.size != template.size:
        result = result.resize(template.size, Image.Resampling.LANCZOS)
    # Model mimo zakazu potrafi narysować coś w tarczach — twardy reset
    tmasks = masks.get_masks(spec.suit.template_path)
    return compositor.wyczysc_tarcze(result, template, tmasks)


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


def generate_template(suit: Suit, prompt: str | None = None) -> Path:
    """Generuje nowe tło (szablon) i zapisuje do folderu AKTYWNEGO presetu
    teł przodu (Style/tla_przodu/<preset>/).

    prompt=None → domyślny prompt grawerski per kolor; podanie własnego
    (np. z zakładki „Tła i rewersy") pozwala sterować stylem paczki."""
    if prompt is None:
        prompt = prompts.template_generation_prompt(
            prompts.SUIT_NAME_EN[suit.nazwa], suit.is_red
        )
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
            reference = Image.open(reference_path).convert("RGB")
            reference.thumbnail((768, 768), Image.Resampling.LANCZOS)
            contents.append(reference)
        img = gemini_client.generate_image(contents)
    img = _fit_card_ratio(img)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = style_store.front_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{suit.nazwa} ai {stamp}.png"
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
