"""Alarm tylko dla nowych terminów.

`Alarm` podpina się pod `Worker`: `on_search_start=alarm.reset`, `on_check=alarm.on_check`.
Pamięta klucze terminów z poprzedniego sprawdzenia i woła `bot.alert` tylko wtedy,
gdy sprawdzenie znalazło termin, którego wcześniej nie było. Sprawdzanie trwa dalej.

Słownictwo: GLOSSARY.md.
"""
from __future__ import annotations

from typing import Optional

import bot
from search import Search, Slot, format_slots, new_slots


class Alarm:
    """Stan alarmu dla aktywnego wyszukiwania. Wołany tylko z wątku roboczego."""

    def __init__(self):
        self._search: Optional[Search] = None
        self._previous_keys: set = set()

    def reset(self, search: Optional[Search] = None):
        """Nowe wyszukiwanie (także ponowny Start z tymi samymi filtrami): pierwsze
        sprawdzenie traktuje wszystkie terminy jako nowe."""
        self._search = search
        self._previous_keys = set()

    def on_check(self, search: Search, slots: list[Slot]):
        """Wynik sprawdzenia: alarm, jeśli są terminy nieobecne w poprzednim sprawdzeniu."""
        if search != self._search:
            self.reset(search)  # zabezpieczenie, gdyby sygnał startu nie dotarł
        fresh = new_slots(slots, self._previous_keys)
        self._previous_keys = {s.key for s in slots}
        if fresh:
            bot.alert(subject(search, len(fresh)), body(fresh, slots))


def subject(search: Search, count: int) -> str:
    return f"Nowe terminy: {search.specialty.name}, {search.region.name} ({count})"


def body(fresh: list[Slot], slots: list[Slot]) -> str:
    return (
        f"Nowe terminy:\n{format_slots(fresh)}\n\n"
        f"Wszystkie aktualne terminy:\n{format_slots(slots)}\n\n"
        f"{bot.APP_URL}"
    )
