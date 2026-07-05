"""Wspólne typy błędów API.

FatalAPIError = błąd nie do naprawienia ponowieniem ani kolejnymi kartami
(brak kredytów / billing / zły klucz / limit konta). Sygnalizuje, że cała
seria generowania powinna się natychmiast zatrzymać z jednym komunikatem,
zamiast powtarzać ten sam błąd dla każdej z 52 kart.
"""
from __future__ import annotations


class FatalAPIError(RuntimeError):
    pass
