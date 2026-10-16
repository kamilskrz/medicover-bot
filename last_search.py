"""Zapamiętane wyszukiwanie: zapis do last_search.json i przywracanie przy starcie okna.

Plik leży w katalogu projektu (w .gitignore). Logika przywracania jest w search.restore_search;
tu jest tylko plik i pobieranie aktualnych list przez wątek roboczy.

Słownictwo: GLOSSARY.md.
"""
from __future__ import annotations

import json
import os
import tempfile
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from typing import Callable, Optional, Tuple

import bot
from search import FilterOptions, Restored, Search, restore_search
from worker import LoginRequired

PATH = bot.BASE / "last_search.json"
OPTIONS_TIMEOUT = 60  # s na każde pytanie o listy; jak w app.OPTIONS_TIMEOUT


def save(search: Search, path: Optional[Path] = None):
    """Zapisuje wyszukiwanie atomowo (plik tymczasowy + os.replace). Błąd tylko loguje."""
    path = Path(path or PATH)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".last_search.", suffix=".tmp", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(search.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        tmp = None
    except Exception as e:  # noqa: BLE001
        bot.log(f"Nie udało się zapisać ostatniego wyszukiwania: {e}")
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def load(worker, path: Optional[Path] = None, timeout: float = OPTIONS_TIMEOUT) -> Optional[Restored]:
    """Przywraca wyszukiwanie z pliku względem aktualnych list z Medicover.

    Brak pliku albo uszkodzony plik -> None (puste okno). Błąd pobierania list -> Restored
    bez wyszukiwania, z ostrzeżeniem dla okna. Nigdy nie rzuca wyjątku.
    """
    path = Path(path or PATH)
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        bot.log(f"Pominięto uszkodzony {path.name}: {e}")
        return None

    def options_for(region_id: Optional[str], specialty_id: Optional[str],
                    clinic_ids: Tuple[str, ...]) -> FilterOptions:
        return worker.load_options(region_id, specialty_id, clinic_ids).result(timeout=timeout)

    try:
        restored = restore_search(saved, options_for)
    except Exception as e:  # noqa: BLE001
        reason = _reason(e)
        bot.log(f"Nie udało się przywrócić ostatniego wyszukiwania: {reason}")
        return Restored(None, (f"Nie udało się przywrócić ostatniego wyszukiwania: {reason}",))
    if restored.search is None and not restored.warnings:
        return None  # plik w niepoprawnym formacie
    return restored


def _reason(e: Exception) -> str:
    if isinstance(e, FutureTimeout):
        return "Medicover nie odpowiedział na czas"
    if isinstance(e, LoginRequired):
        return "wymagane logowanie"
    return str(e) or type(e).__name__


def restorer(worker, path: Optional[Path] = None) -> Callable[[], Optional[Restored]]:
    """Funkcja dla create_app(..., restore_saved=...)."""
    return lambda: load(worker, path)
