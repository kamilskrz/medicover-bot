# 02 Czysta logika wyszukiwania + testy

Status: resolved
Blocked by: 01

Wydzielić moduł bez zależności od Playwrighta i Flaska:
- model **Wyszukiwania** (miasto, specjalizacja, placówki, lekarze, zakres dat) i budowa parametrów zapytania `slots`;
- odrzucanie terminów spoza zakresu dat;
- rozpoznawanie nowych terminów względem poprzedniego sprawdzenia: klucz to `doctor.id` + `clinic.id` + `specialty.id` + `appointmentDate` (API nie zwraca ID terminu, zob. 01);
- kaskadowe czyszczenie przy zmianie miasta lub specjalizacji;
- przywracanie zapamiętanego wyszukiwania na podstawie aktualnych list opcji, ze zwracaniem ostrzeżeń o usuniętych pozycjach;
- formatowanie listy terminów (data, godzina, lekarz, placówka, od najwcześniejszego).

## Kryteria akceptacji
- Testy pytest pokrywają każdy punkt powyżej, a `pytest` przechodzi.
- `pytest` jest dodany do zależności deweloperskich.

## Answer

Logika jest w `search.py`, a testy w `tests/test_search.py` (35 testów, `pytest` przechodzi). Zależności deweloperskie są w `requirements-dev.txt`.
- Model `Search`: `slots_query(today)` buduje parametry `slots`, przy czym `StartTime` = max(„od”, dziś). `to_dict()` zapisuje stan do `last_search.json`.
- Moduł parsuje odpowiedzi `filters` i `slots`, przycina nazwy i odrzuca terminy spoza zakresu dat (`in_range`, obie granice włącznie).
- Nowe terminy wykrywa `new_slots` po kluczu `Slot.key` = lekarz + placówka + specjalizacja + `appointmentDate`.
- `format_slots` wypisuje jeden termin na linię, od najwcześniejszego.
- `restore_search` przywraca wyszukiwanie według aktualnych opcji. Kolejne pytania to `(miasto, None)`, `(miasto, specjalizacja)` i `(miasto, specjalizacja, placówki)`. Placówki i lekarzy, których już nie ma, usuwa z ostrzeżeniem. Gdy brakuje miasta lub specjalizacji, zwraca `search=None`. Uszkodzony plik daje `Restored(None, ())`.
- **Kaskadowe czyszczenie** przy zmianie miasta lub specjalizacji nie trafiło do tego modułu, bo jest stanem formularza w przeglądarce. Zrobi je zgłoszenie 04 w JS.
