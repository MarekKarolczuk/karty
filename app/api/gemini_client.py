"""Klient Google AI Studio (Gemini) do generowania/edycji obrazów."""
from __future__ import annotations

import io
import time

from google import genai
from PIL import Image

from app import config


class GeminiError(RuntimeError):
    pass


_client: genai.Client | None = None


def reset_client() -> None:
    """Wymusza nowego klienta po zmianie klucza API (Ustawienia)."""
    global _client
    _client = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise GeminiError("Brak GEMINI_API_KEY — uzupełnij plik .env")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _model_name() -> str:
    model = config.current_model()
    if model["provider"] == "gemini":
        return config.SELECTED_MODEL
    return "gemini-2.5-flash-image"  # fallback, gdy wybrany model nie jest z Gemini


def generate_image(contents: list, retries: int = 3) -> Image.Image:
    """Wysyła prompt (tekst + obrazy PIL) i zwraca pierwszy obraz z odpowiedzi."""
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = get_client().models.generate_content(
                model=_model_name(),
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
                    "Darmowy plan tego klucza API nie obejmuje generowania obrazów "
                    "(limit 0). Włącz rozliczenia (billing) dla projektu w "
                    "https://aistudio.google.com/ i spróbuj ponownie."
                ) from exc
            # zły / nieautoryzowany klucz — też błąd krytyczny konta
            if any(s in text for s in ("API key not valid", "PERMISSION_DENIED",
                                       "UNAUTHENTICATED", "API_KEY_INVALID")):
                raise FatalAPIError(
                    "Klucz GEMINI_API_KEY jest nieprawidłowy lub bez uprawnień — "
                    "popraw go w Ustawieniach."
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
