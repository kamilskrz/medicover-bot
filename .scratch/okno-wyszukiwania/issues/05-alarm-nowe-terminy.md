# 05 Alarm tylko dla nowych terminów

Status: resolved
Blocked by: 02, 03

- Alarm (dźwięk, powiadomienie macOS, mail, jeśli SMTP jest skonfigurowany) włącza się tylko wtedy, gdy sprawdzenie zawiera termin nieobecny w poprzednim sprawdzeniu.
- Treść powiadomienia i maila wymienia specjalizację i miasto zamiast zaszytego „neurologa”. Mail zawiera sformatowaną listę terminów.
- Usunąć powtarzane `play_sound(2)` przy każdym sprawdzeniu.
- Po alarmie sprawdzanie trwa dalej.

## Answer

Alarm jest w `alarm.py`, w klasie `Alarm`, a testy w `tests/test_alarm.py`. `pytest`: 59 testów przechodzi.
- `Alarm.reset(search)` zeruje pamięć. `Alarm.on_check(search, slots)` liczy nowe terminy przez `search.new_slots` względem kluczy (`Slot.key`) z poprzedniego sprawdzenia, a potem zapamiętuje klucze bieżącego. Zniknięcie terminu i jego powrót oznacza więc nowy termin. Gdy przyjdzie inne wyszukiwanie niż zapamiętane, pamięć też się zeruje (zabezpieczenie).
- `bot.alert(subject, body)` jest wołane tylko wtedy, gdy są nowe terminy. Temat ma postać `Nowe terminy: <specjalizacja>, <miasto> (<liczba nowych>)`. Treść zawiera kolejno: `Nowe terminy:` z `format_slots(nowe)`, `Wszystkie aktualne terminy:` z `format_slots(wszystkie)` i `bot.APP_URL`. `alert()` w `bot.py` się nie zmieniło. Nic nie zatrzymuje sprawdzania i nie ma piszczenia przy każdym sprawdzeniu.
- `bot.make_worker()` tworzy `Alarm` i podpina go: `Worker(on_check=alarm.on_check, on_search_start=alarm.reset, on_login_required=...)`. `watch()` i `__main__` są bez zmian.

### Zmiana w `worker.py` (tylko konstruktor i callbacki, publiczne API bez zmian)
- `on_check` dostaje teraz `(search, slots)` zamiast `(slots)`: `self._on_check(search, slots)` w `_check()`.
- Nowy opcjonalny argument konstruktora `on_search_start: Callable[[Search], None] = None`, dodany na końcu, po `browser_factory`. Jest wołany w `_begin_search()` przy każdym `start_search`, także przy ponownym Start z tymi samymi filtrami, w wątku roboczym. Wyjątek trafia do logu. Dzięki niemu pierwsze sprawdzenie nowego wyszukiwania traktuje wszystkie terminy jako nowe.
- `snapshot`, `load_options`, `start_search`, `stop_search` i `shutdown` są bez zmian. `tests/test_worker.py` dostosowano do nowej sygnatury i dodano test obu callbacków.
