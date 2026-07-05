"""Klient Stability AI REST API (v2beta stable-image).

Obsługuje: stylizację zdjęcia (image-to-image) i generowanie teł (text-to-image).
Stability przyjmuje tylko jeden obraz wejściowy, więc tryb "Pełne AI"
(szablon + zdjęcie w jednym wywołaniu) pozostaje domyślnie dla Gemini.
"""
from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import requests
from PIL import Image

from app import config


class StabilityAborted(RuntimeError):
    """Żądanie przerwane przez użytkownika (przycisk Anuluj)."""


# Sesja aktywnego żądania — zamknięcie jej z innego wątku przerywa połączenie
# HTTP w locie (natychmiastowe anulowanie, odpowiednik AbortController).
_active_session: requests.Session | None = None
_session_lock = threading.Lock()
_aborted = False


def abort_active() -> None:
    """Przerywa aktualnie trwające żądanie do Stability (jeśli jakieś jest)."""
    global _aborted
    _aborted = True
    with _session_lock:
        if _active_session is not None:
            _active_session.close()


def reset_abort() -> None:
    """Kasuje flagę anulowania przed nową serią generacji."""
    global _aborted
    _aborted = False

# Endpoint zachowujący strukturę/pozy ze zdjęcia przy pełnej stylizacji z promptu.
# Zwykły img2img gubi tożsamość osób przy silnej stylizacji (strength > ~0.6).
STRUCTURE_ENDPOINT = "https://api.stability.ai/v2beta/stable-image/control/structure"
CONTROL_STRENGTH = 0.7

# Inpainting z maską — pipeline pop-out: kolaż (szablon + zdjęcie) + poszerzona
# maska sięgająca ponad ramę symbolu → postać "wychodzi" z ramki.
INPAINT_ENDPOINT = "https://api.stability.ai/v2beta/stable-image/edit/inpaint"


class StabilityError(RuntimeError):
    pass


def _endpoint() -> str:
    model = config.current_model()
    return model.get(
        "endpoint", "https://api.stability.ai/v2beta/stable-image/generate/ultra"
    )


def _headers() -> dict:
    if not config.STABILITY_API_KEY:
        raise StabilityError("Brak STABILITY_API_KEY — uzupełnij plik .env")
    return {
        "authorization": f"Bearer {config.STABILITY_API_KEY}",
        "accept": "image/*",
    }


def _request(data: dict, files: dict, retries: int = 3,
             endpoint: str | None = None) -> Image.Image:
    global _active_session
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        if _aborted:
            raise StabilityAborted("Generowanie przerwane przez użytkownika")
        session = requests.Session()
        with _session_lock:
            _active_session = session
        try:
            response = session.post(
                endpoint or _endpoint(), headers=_headers(), data=data,
                files=files, timeout=180,
            )
            if response.status_code == 200:
                return Image.open(io.BytesIO(response.content)).convert("RGB")
            # 4xx = błąd nie do naprawienia (zły prompt, brak kredytów, zły klucz)
            # → FatalAPIError zatrzymuje CAŁĄ serię, nie tylko tę kartę
            detail = response.text[:400]
            if 400 <= response.status_code < 500:
                from app.api.errors import FatalAPIError
                hint = ""
                if response.status_code in (401, 403):
                    hint = " — sprawdź klucz STABILITY_API_KEY w Ustawieniach"
                elif response.status_code in (402, 429):
                    hint = " — brak kredytów / limit konta Stability"
                raise FatalAPIError(
                    f"Stability odrzuciło żądanie ({response.status_code}){hint}: {detail}"
                )
            last_error = RuntimeError(f"HTTP {response.status_code}: {detail}")
        except StabilityError:
            raise
        except Exception as exc:  # sieć / 5xx / przerwana sesja / błąd krytyczny
            from app.api.errors import FatalAPIError
            if isinstance(exc, FatalAPIError):
                raise
            if _aborted:
                raise StabilityAborted("Generowanie przerwane przez użytkownika")
            last_error = exc
        finally:
            with _session_lock:
                _active_session = None
            session.close()
        if attempt < retries:
            time.sleep(2 * attempt)
    raise StabilityError(
        f"Wywołanie Stability nie powiodło się po {retries} próbach: {last_error}"
    )


def _photo_bytes(path: Path, max_side: int = 1536) -> bytes:
    img = Image.open(path).convert("RGB")
    img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


def _image_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, "PNG")
    return buffer.getvalue()


def inpaint(init: Image.Image, mask: Image.Image, prompt: str) -> Image.Image:
    """Pop-out: przerysowanie obszaru maski na kolażu szablon+zdjęcie.

    Maska (L): biel = obszar do przerysowania. init i mask muszą mieć
    identyczne wymiary (skalowanie robi generator, parą).
    """
    if init.size != mask.size:
        mask = mask.resize(init.size, Image.Resampling.LANCZOS)
    data = {
        "prompt": prompt,
        "output_format": "png",
        # maskę poszerzamy sami (miękka krawędź w masks.get_popout_mask)
        "grow_mask": "0",
    }
    files = {
        "image": ("init.png", _image_bytes(init.convert("RGB")), "image/png"),
        "mask": ("mask.png", _image_bytes(mask.convert("L")), "image/png"),
    }
    return _request(data, files, endpoint=INPAINT_ENDPOINT)


def stylize_photo(photo_path: Path, prompt: str) -> Image.Image:
    """Zdjęcie -> ilustracja wektorowa: control/structure trzyma pozy i kompozycję."""
    data = {
        "prompt": prompt,
        "control_strength": str(CONTROL_STRENGTH),
        "output_format": "png",
    }
    files = {"image": ("photo.png", _photo_bytes(Path(photo_path)), "image/png")}
    return _request(data, files, endpoint=STRUCTURE_ENDPOINT)


def generate_template_image(prompt: str, reference: Path | None = None,
                            landscape: bool = False) -> Image.Image:
    """Tło karty: text-to-image (2:3 lub 3:2) albo wariacja istniejącego
    szablonu / zdjęcia referencyjnego."""
    if reference is not None and reference.exists():
        data = {
            "prompt": prompt,
            "strength": "0.6",   # zachowaj układ referencji, odśwież ornamenty
            "output_format": "png",
        }
        if "sd3" in _endpoint():
            data["mode"] = "image-to-image"
        files = {"image": ("ref.png", _photo_bytes(reference), "image/png")}
        return _request(data, files)

    data = {
        "prompt": prompt,
        # najbliższe 63:88 (lub 88:63); przycinamy potem do dokładnych proporcji
        "aspect_ratio": "3:2" if landscape else "2:3",
        "output_format": "png",
    }
    files = {"none": ("", b"")}
    return _request(data, files)
