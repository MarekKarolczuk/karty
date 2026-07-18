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
    JOKER_CZERWONY = ("joker_czerwony", "★", True)
    JOKER_CZARNY = ("joker_czarny", "★", False)

    def __init__(self, nazwa: str, symbol: str, is_red: bool):
        self.nazwa = nazwa
        self.symbol = symbol
        self.is_red = is_red

    @property
    def czy_joker(self) -> bool:
        return self.nazwa.startswith("joker")

    @property
    def etykieta(self) -> str:
        """Nazwa do wyświetlania („Joker czerwony"); `nazwa` zostaje kluczem."""
        return self.nazwa.replace("_", " ").capitalize()

    @classmethod
    def kolory(cls) -> list["Suit"]:
        """Cztery klasyczne kolory (bez jokerów)."""
        return [s for s in cls if not s.czy_joker]

    @classmethod
    def jokery(cls) -> list["Suit"]:
        return [s for s in cls if s.czy_joker]

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


JOKER_WARTOSC = "JOKER"


def wartosci_dla(suit: Suit, values: list[str]) -> list[str]:
    """Lista wartości kart danego koloru: jokery mają jedną „wartość" JOKER,
    klasyczne kolory pełną listę talii."""
    return [JOKER_WARTOSC] if suit.czy_joker else list(values)


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
    def _suffix(self) -> str:
        return "" if self.variant <= 1 else f"_v{self.variant}"

    @property
    def output_name(self) -> str:
        return f"{self.value}_{self.suit.nazwa}{self._suffix}.jpg"

    @property
    def output_path(self) -> Path:
        return config.OUTPUT_DIR / self.output_name

    @property
    def raw_name(self) -> str:
        """Surowe wyjście AI (bez narożników) — nazewnictwo lustrzane do
        finalnego, ale bezstratny PNG."""
        return f"{self.value}_{self.suit.nazwa}{self._suffix}.png"

    @property
    def raw_path(self) -> Path:
        return config.RAW_DIR / self.raw_name

    @property
    def label(self) -> str:
        base = f"{self.value}{self.suit.symbol}"
        return base if self.variant <= 1 else f"{base} v{self.variant}"
