"""Klient Google AI Studio (Gemini) do generowania/edycji obrazów."""
from __future__ import annotations

import io
import time

from google import genai
from google.genai import types
from PIL import Image

from app import config


class GeminiError(RuntimeError):
    pass


# Klienci cache'owani per region Vertex (różne modele = różne endpointy, np.
# gemini-3 → "global"). Tryb AI Studio używa jednego stałego klucza.
_API_KEY_SLOT = "__api__"
_clients: dict[str, genai.Client] = {}


def reset_client() -> None:
    """Wymusza nowych klientów po zmianie klucza API / regionu (Ustawienia)."""
    _clients.clear()


def get_client(location: str | None = None) -> genai.Client:
    if config.USE_VERTEX:
        if not config.GCP_PROJECT:
            raise GeminiError(
                "Tryb Vertex AI włączony, ale brak ID projektu GCP — "
                "uzupełnij „Projekt GCP” w Ustawieniach."
            )
        loc = location or config.vertex_location_for()
        if loc not in _clients:
            # ADC (gcloud auth application-default login) — bez klucza API
            _clients[loc] = genai.Client(
                vertexai=True,
                project=config.GCP_PROJECT,
                location=loc,
            )
        return _clients[loc]

    if not config.GEMINI_API_KEY:
        raise GeminiError("Brak GEMINI_API_KEY — uzupełnij plik .env")
    if _API_KEY_SLOT not in _clients:
        _clients[_API_KEY_SLOT] = genai.Client(api_key=config.GEMINI_API_KEY)
    return _clients[_API_KEY_SLOT]


def _model_name() -> str:
    model = config.current_model()
    if model["provider"] == "gemini":
        return config.SELECTED_MODEL
    return "gemini-2.5-flash-image"  # fallback, gdy wybrany model nie jest z Gemini


def _generation_config(seed: int | None, poziom: int = 0,
                       temperature: float | None = None,
                       ) -> types.GenerateContentConfig:
    """Config stabilizujący spójność talii: niska temperatura + seed.

    temperature — nadpisanie per wywołanie (suwak „Siła poprawki" w poprawce
    selektywnej); None = domyślne config.GEN_TEMPERATURE.

    Dwustopniowa degradacja dla backendów odrzucających pola (INVALID_ARGUMENT):
    poziom 0 — pełny config; poziom 1 — bez response_modalities, ale SEED
    ZOSTAJE (spójność talii); poziom 2 — tylko temperatura."""
    temp = config.GEN_TEMPERATURE if temperature is None else temperature
    if poziom >= 2:
        return types.GenerateContentConfig(temperature=temp)
    if poziom == 1:
        return types.GenerateContentConfig(temperature=temp, seed=seed)
    return types.GenerateContentConfig(
        temperature=temp,
        seed=seed,
        response_modalities=["TEXT", "IMAGE"],
    )


def _raise_if_fatal(exc: Exception, model: str) -> None:
    """Mapuje błędy konta (billing / klucz / brak modelu) na FatalAPIError —
    nie do naprawienia ponowieniem, przerywają całą serię. Wspólne dla
    generate_image() i generate_text(). Zwykłe błędy (sieć, limity chwilowe)
    przepuszcza do retry."""
    from app.api.errors import FatalAPIError
    text = str(exc)
    # brak billingu / limit 0
    if "RESOURCE_EXHAUSTED" in text and "limit: 0" in text:
        raise FatalAPIError(
            "Konto Vertex AI nie ma dostępu do generowania obrazów "
            "(limit 0) — sprawdź billing/quota projektu GCP i włączone "
            "Vertex AI API (console.cloud.google.com)."
            if config.USE_VERTEX else
            "Darmowy plan tego klucza API nie obejmuje generowania obrazów "
            "(limit 0). Włącz rozliczenia (billing) dla projektu w "
            "https://aistudio.google.com/ i spróbuj ponownie."
        ) from exc
    # zły klucz / brak uprawnień ADC — błąd krytyczny konta
    if any(s in text for s in ("API key not valid", "PERMISSION_DENIED",
                               "UNAUTHENTICATED", "API_KEY_INVALID")):
        raise FatalAPIError(
            "Brak uprawnień do Vertex AI — uruchom `gcloud auth "
            "application-default login`, nadaj rolę „Vertex AI User” i "
            "sprawdź ID projektu GCP w Ustawieniach."
            if config.USE_VERTEX else
            "Klucz GEMINI_API_KEY jest nieprawidłowy lub bez uprawnień — "
            "popraw go w Ustawieniach."
        ) from exc
    # model niedostępny w regionie / brak dostępu — nie retry'uj
    if config.USE_VERTEX and any(
        s in text for s in ("404", "NOT_FOUND", "does not have access")
    ):
        region = config.vertex_location_for(model)
        raise FatalAPIError(
            f"Model „{model}” jest niedostępny na Vertex AI w regionie "
            f"„{region}” (lub projekt nie ma do niego dostępu). Wybierz "
            "inny model albo region w Ustawieniach."
        ) from exc


def generate_image(contents: list, retries: int = 3,
                   seed: int | None = None,
                   temperature: float | None = None) -> Image.Image:
    """Wysyła prompt (tekst + obrazy PIL) i zwraca pierwszy obraz z odpowiedzi.

    seed — deterministyczny wariant (spójność talii); None = losowo
    (tła/rewers, gdzie warianty MAJĄ się różnić).
    temperature — nadpisanie per wywołanie (siła poprawki selektywnej);
    None = config.GEN_TEMPERATURE."""
    last_error: Exception | None = None
    model = _model_name()
    poziom_configu = 0
    for attempt in range(1, retries + 1):
        try:
            response = get_client(config.vertex_location_for(model)).models.generate_content(
                model=model,
                contents=contents,
                config=_generation_config(seed, poziom=poziom_configu,
                                          temperature=temperature),
            )
            for candidate in response.candidates or []:
                if candidate.content is None:
                    continue
                for part in candidate.content.parts or []:
                    if part.inline_data is not None and part.inline_data.data:
                        return Image.open(io.BytesIO(part.inline_data.data)).convert("RGB")
            raise GeminiError(
                f"Model nie zwrócił obrazu (odpowiedź: {getattr(response, 'text', None) or 'pusta'})"
            )
        except GeminiError:
            raise
        except Exception as exc:  # błędy sieci / limity API
            last_error = exc
            text = str(exc)
            # backend odrzucił pole configu — degradacja stopniowa (tylko
            # w górę, każdy poziom raz): najpierw bez response_modalities
            # (SEED ZOSTAJE — spójność talii), dopiero potem bez seeda
            if "INVALID_ARGUMENT" in text:
                if "seed" in text.lower() and poziom_configu < 2:
                    poziom_configu = 2
                    continue
                if "response_modalit" in text.lower() and poziom_configu < 1:
                    poziom_configu = 1
                    continue
            _raise_if_fatal(exc, model)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise GeminiError(f"Wywołanie Gemini nie powiodło się po {retries} próbach: {last_error}")


def generate_text(contents: list, retries: int = 3) -> str:
    """Wysyła prompt (tekst + obrazy PIL) do taniego modelu tekstowo-wizyjnego
    (config.ANALYSIS_MODEL) i zwraca odpowiedź TEKSTOWĄ — JSON analizy zdjęcia
    (auto-przydział). Osobna od generate_image(): inny model, config wymuszający
    JSON (response_mime_type), czytanie part.text zamiast inline_data."""
    last_error: Exception | None = None
    model = config.ANALYSIS_MODEL
    minimal_config = False
    for attempt in range(1, retries + 1):
        try:
            if minimal_config:
                gen_config = types.GenerateContentConfig(
                    temperature=config.ANALYSIS_TEMPERATURE)
            else:
                gen_config = types.GenerateContentConfig(
                    temperature=config.ANALYSIS_TEMPERATURE,
                    response_mime_type="application/json",
                )
            response = get_client(config.vertex_location_for(model)).models.generate_content(
                model=model,
                contents=contents,
                config=gen_config,
            )
            parts_text: list[str] = []
            for candidate in response.candidates or []:
                if candidate.content is None:
                    continue
                for part in candidate.content.parts or []:
                    if part.text:
                        parts_text.append(part.text)
            if parts_text:
                return "".join(parts_text)
            raise GeminiError("Model nie zwrócił tekstu analizy (pusta odpowiedź)")
        except GeminiError:
            raise
        except Exception as exc:  # błędy sieci / limity API
            last_error = exc
            text = str(exc)
            # backend odrzucił response_mime_type — ponów z minimalnym configiem
            if not minimal_config and "INVALID_ARGUMENT" in text \
                    and "response_mime" in text.lower():
                minimal_config = True
                continue
            _raise_if_fatal(exc, model)
            if attempt < retries:
                time.sleep(2 * attempt)
    raise GeminiError(f"Analiza Gemini nie powiodła się po {retries} próbach: {last_error}")


def _load_photo(path, max_side: int = 1024) -> Image.Image:
    """Wczytuje i zmniejsza zdjęcie wejściowe (mniejsze koszty, szybszy upload)."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return img


def stylize_photo(photo_path, style_prompt: str,
                  seed: int | None = None) -> Image.Image:
    """Tryb hybrydowy: zdjęcie -> ilustracja wektorowa cell-shaded."""
    return generate_image([style_prompt, _load_photo(photo_path)], seed=seed)


def compose_full_card(template: Image.Image, photo_path, prompt: str,
                      seed: int | None = None,
                      photo_max_side: int = 1024) -> Image.Image:
    """Tryb pełne AI: szablon + zdjęcie -> gotowa karta.

    photo_max_side — pomniejszenie zdjęcia; grupy 3+ dostają większą wartość
    (więcej pikseli na każdą twarz — patrz generator.PHOTO_REF_SIDE_GRUPA)."""
    contents: list = [prompt, template,
                      _load_photo(photo_path, max_side=photo_max_side)]
    return generate_image(contents, seed=seed)


def edit_region(card: Image.Image, zaznaczenie: Image.Image, prompt: str,
                seed: int | None = None,
                temperature: float | None = None,
                photo: Image.Image | None = None) -> Image.Image:
    """Korekcyjny inpainting: wycinek karty + TEN SAM wycinek z regionem
    poprawki zaznaczonym magentą (compositor.zaznacz_region_poprawki) +
    prompt użytkownika. Gemini nie ma twardej maski API — wizualna adnotacja
    na drugim obrazie działa lepiej niż czarno-biała maska, a deterministyczną
    ochronę reszty karty robi generator (composite po masce + strefy twarde).
    photo (opcjonalne) — oryginalne zdjęcie karty jako OSTATNI obraz
    (prompts._FIX_PHOTO_REF: uzupełnianie uciętych elementów sceny wiernie
    do oryginału). temperature — z suwaka „Siła poprawki"
    (generator._FIX_TEMPERATURA)."""
    contents: list = [prompt, card, zaznaczenie.convert("RGB")]
    if photo is not None:
        contents.append(photo)
    return generate_image(contents, seed=seed, temperature=temperature)


def edit_card_image(init: Image.Image, prompt: str,
                    seed: int | None = None,
                    photo: Image.Image | None = None) -> Image.Image:
    """Pop-out: kolaż (szablon + wkadrowane zdjęcie) -> przerysowana karta.

    Gemini edytuje instrukcyjnie (bez twardej maski) — prompt wymusza
    wychodzenie postaci poza ramę i nienaruszanie bordiury/narożników.
    photo (opcjonalne) — oryginalne zdjęcie jako DRUGI obraz contents
    (wierność twarzy i rekwizytów, patrz prompts.photo_ref_note())."""
    contents: list = [prompt, init]
    if photo is not None:
        contents.append(photo)
    return generate_image(contents, seed=seed)
