"""Modele danych: kolory kart i specyfikacja pojedynczej karty."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app import config
from app.core import style_store


class Suit(Enum):
    KIER = ("kier", "♥", True)
    KARO = ("karo", "♦", True)
    PIK = ("pik", "♠", False)
    TREFL = ("trefl", "♣", False)

    def __init__(self, nazwa: str, symbol: str, is_red: bool):
        self.nazwa = nazwa
        self.symbol = symbol
        self.is_red = is_red

    @property
    def value_color(self) -> str:
        return config.ACCENT_HEX if self.is_red else config.BLACK_HEX

    @property
    def template_path(self) -> Path:
        """Aktywny szablon tła: wybrany przez użytkownika albo pierwszy pasujący."""
        override = config.TEMPLATE_OVERRIDES.get(self.nazwa)
        if override and Path(override).exists():
            return Path(override)
        templates = self.available_templates()
        if not templates:
            raise FileNotFoundError(
                f"Brak szablonu dla koloru '{self.nazwa}' "
                f"w {style_store.front_dir()}"
            )
        return templates[0]

    def available_templates(self) -> list[Path]:
        """Wszystkie szablony tego koloru z folderu AKTYWNEGO presetu teł
        przodu (nazwa pliku zawiera kolor)."""
        d = style_store.front_dir()
        if not d.is_dir():
            return []
        return [
            p for p in sorted(d.iterdir())
            if p.suffix.lower() in config.IMAGE_EXTS and self.nazwa in p.stem.lower()
        ]

    @classmethod
    def from_nazwa(cls, nazwa: str) -> "Suit":
        for suit in cls:
            if suit.nazwa == nazwa:
                return suit
        raise ValueError(f"Nieznany kolor: {nazwa}")


class GenMode(Enum):
    HYBRID = "hybrid"
    FULL_AI = "full_ai"


@dataclass
class CardSpec:
    value: str                      # np. "A", "K", "10"
    suit: Suit
    photo_path: Path | None = None
    mode: GenMode = GenMode.HYBRID
    variant: int = 1                # która wersja karty (1 = plik bez sufiksu)
    transform: dict | None = None   # kadr z GUI: {"zoom","dx","dy"}

    @property
    def output_name(self) -> str:
        suffix = "" if self.variant <= 1 else f"_v{self.variant}"
        return f"{self.value}_{self.suit.nazwa}{suffix}.jpg"

    @property
    def output_path(self) -> Path:
        return config.OUTPUT_DIR / self.output_name

    @property
    def label(self) -> str:
        base = f"{self.value}{self.suit.symbol}"
        return base if self.variant <= 1 else f"{base} v{self.variant}"
