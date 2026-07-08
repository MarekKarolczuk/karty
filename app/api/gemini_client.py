"""Klient Google AI Studio (Gemini) do generowania/edycji obrazów."""
from __future__ import annotations

import io
import os
import time

from google import genai
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


# id zawierające te fragmenty na pewno NIE są generatorami obrazu
_NON_IMAGE_HINTS = ("embedding", "veo", "tts", "audio", "-live")


def _is_image_model(model_id: str, actions: list[str] | None) -> bool:
    """Heurystyka: czy model generuje obrazy przez generate_content.
    `actions` bywa None (Vertex nie zawsze zwraca supported_actions)."""
    mid = model_id.lower()
    if any(hint in mid for hint in _NON_IMAGE_HINTS):
        return False
    supports_gc = actions is None or "generateContent" in actions
    if mid.startswith("imagen"):
        # Imagen działa przez predict — bez generateContent nie umiemy go wołać
        return actions is not None and "generateContent" in actions
    return "image" in mid and supports_gc


def list_image_models() -> dict[str, dict]:
    """Odkrywa modele obrazowe dostępne w aktywnym źródle (AI Studio / Vertex).

    Zwraca {model_id: {"label": str|None, "vertex_location": str|None}}.
    Na Vertex łączy wyniki z endpointu "global" i regionu użytkownika
    (rodzina gemini-3* jest serwowana tylko z "global")."""
    if os.getenv("KARTY_FAKE_API", "") == "1":
        return {
            "gemini-3-pro-image": {"label": "Gemini 3 Pro Image",
                                   "vertex_location": "global"},
            "gemini-2.5-flash-image": {"label": "Gemini 2.5 Flash Image",
                                       "vertex_location": None},
            "gemini-3.1-flash-image-preview": {
                "label": "Gemini 3.1 Flash Image (Nano Banana 2)",
                "vertex_location": "global"},
        }

    locations: list[str | None]
    if config.USE_VERTEX:
        locations = ["global", config.GCP_LOCATION]
    else:
        locations = [None]

    discovered: dict[str, dict] = {}
    errors: list[str] = []
    for loc in locations:
        try:
            models = get_client(loc).models.list()
        except Exception as exc:   # jedna lokacja może nie listować
            errors.append(f"{loc or 'api'}: {str(exc)[:120]}")
            continue
        for model in models:
            model_id = (model.name or "").split("/")[-1]
            if not model_id or model_id in discovered:
                continue
            if not _is_image_model(model_id, model.supported_actions):
                continue
            discovered[model_id] = {
                "label": model.display_name or None,
                "vertex_location": ("global" if loc == "global" else None),
            }
    if not discovered and errors:
        raise GeminiError(
            "Nie udało się pobrać listy modeli: " + "   ·   ".join(errors)
        )
    return discovered


def generate_image(contents: list, retries: int = 3) -> Image.Image:
    """Wysyła prompt (tekst + obrazy PIL) i zwraca pierwszy obraz z odpowiedzi."""
    last_error: Exception | None = None
    model = _model_name()
    for attempt in range(1, retries + 1):
        try:
            response = get_client(config.vertex_location_for(model)).models.generate_content(
                model=model,
                contents=contents,
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
            from app.api.errors import FatalAPIError
            last_error = exc
            text = str(exc)
            # brak billingu / limit 0 — nie do naprawienia ponowieniem: zatrzymaj serię
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
            if attempt < retries:
                time.sleep(2 * attempt)
    raise GeminiError(f"Wywołanie Gemini nie powiodło się po {retries} próbach: {last_error}")


def _load_photo(path, max_side: int = 1024) -> Image.Image:
    """Wczytuje i zmniejsza zdjęcie wejściowe (mniejsze koszty, szybszy upload)."""
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return img


def stylize_photo(photo_path, style_prompt: str) -> Image.Image:
    """Tryb hybrydowy: zdjęcie -> ilustracja wektorowa cell-shaded."""
    return generate_image([style_prompt, _load_photo(photo_path)])


def compose_full_card(template: Image.Image, photo_path, prompt: str) -> Image.Image:
    """Tryb pełne AI: szablon + zdjęcie -> gotowa karta."""
    return generate_image([prompt, template, _load_photo(photo_path)])


def edit_card_image(init: Image.Image, prompt: str) -> Image.Image:
    """Pop-out: kolaż (szablon + wkadrowane zdjęcie) -> przerysowana karta.

    Gemini edytuje instrukcyjnie (bez twardej maski) — prompt wymusza
    wychodzenie postaci poza ramę i nienaruszanie bordiury/narożników.
    """
    return generate_image([prompt, init])
