# 04 Serwer Flask i okno wyboru wyszukiwania

Status: resolved
Blocked by: 02, 03

- `python bot.py` uruchamia Flask na `127.0.0.1` (wolny port) i otwiera kartę przez `webbrowser`. Ctrl+C kończy proces i zamyka przeglądarkę Playwrighta.
- Jedna strona HTML z kaskadą Miasto → Specjalizacja → Placówki → Lekarze (z wyszukiwaniem po tekście, wielokrotny wybór dla placówek i lekarzy) i polami dat od–do.
- Przyciski Start i Stop. Podczas sprawdzania filtry są zablokowane.
- Strona co około 2 s pyta o stan i pokazuje status, log oraz listę terminów.

## Kryteria akceptacji
- Zmiana miasta lub specjalizacji czyści pola niższego poziomu i przeładowuje ich opcje.
- Start bez miasta albo specjalizacji jest zablokowany.
- Zamknięcie i ponowne otwarcie karty pokazuje bieżący stan.

## Answer

Serwer jest w `app.py`, a strona w `static/` (`index.html`, `app.js`, `style.css`: czysty HTML, CSS i JS, bez CDN). Testy są w `tests/test_app.py` i korzystają z Flask test clienta oraz atrapy workera.
- `create_app(worker, restore_saved=None)` zwraca aplikację Flask. Serwer nie dotyka Playwrighta: zleca pracę workerowi i czyta jego `snapshot()`.
- `main()` tworzy workera przez `bot.make_worker()` i go uruchamia. Serwer startuje przez `werkzeug.serving.make_server("127.0.0.1", 0, ...)`, czyli na wolnym porcie wybranym przez system, bez reloadera i bez debug. Następnie `main()` otwiera kartę przez `webbrowser.open`. Ctrl+C zatrzymuje serwer i wywołuje `worker.shutdown()`. Logi werkzeuga o każdym zapytaniu są wyciszone.
- `python bot.py` bez argumentu uruchamia `app.main()`. `watch()` zostało usunięte, a `flask` jest dopisany do `requirements.txt`.

### Endpointy
- `GET /`: strona okna.
- `GET /api/state` zwraca `{status, search, slots, last_check, log}`:
  - `search` to `Search.to_dict()` albo `null`;
  - `slots` to lista `{date: "YYYY-MM-DD", time: "HH:MM", doctor, clinic}`;
  - `last_check` to data ISO albo `null`.
- `GET /api/options?region_id=&specialty_id=&clinic_id=…` zwraca `{regions, specialties, clinics, doctors}` jako listy `{id, name}`. `clinic_id` można powtórzyć, a puste parametry są pomijane. Timeout wynosi 60 s (`OPTIONS_TIMEOUT`). Błędy przychodzą jako JSON `{error}` bez stack trace'a:
  - `LoginRequired`: 503 z `login_required: true`;
  - `ApiError`: 502;
  - timeout: 504;
  - inny wyjątek: 500;
  - wywołanie bez `region_id`, które nie zwraca miast: 502 „Medicover nie zwrócił listy miast…”.
- `POST /api/start` przyjmuje JSON `{region: {id, name}, specialty: {id, name}, clinics: [...], doctors: [...], date_from, date_to}`. Daty są w ISO albo puste. Brak miasta lub specjalizacji, niepoprawna data albo `date_from > date_to` daje 400 `{error}`. Poprawne dane budują `search.Search` i trafiają do `worker.start_search`.
- `POST /api/stop`: `worker.stop_search()`.
- `GET /api/saved-search` zwraca `{search, warnings}`. Dziś zawsze `{search: null, warnings: []}` (zob. niżej).

### Okno
- Każde pole to lista z filtrem „Szukaj…” (radio dla miasta i specjalizacji, checkboxy dla placówek i lekarzy). Filtr ignoruje wielkość liter i polskie znaki.
- Kaskada działa tak:
  - opcje bez parametrów zwracają miasta;
  - z `region_id` zwracają specjalizacje;
  - z `region_id` i `specialty_id` zwracają placówki i lekarzy;
  - z placówkami zwracają zawężonych lekarzy. Lekarze spoza nowej listy wypadają z wyboru, a okno pokazuje ostrzeżenie.
- Zmiana miasta czyści specjalizację, placówki i lekarzy. Zmiana specjalizacji czyści placówki i lekarzy. Spóźnione odpowiedzi na wcześniejsze zapytania są ignorowane (licznik `formSeq`).
- Listę miast strona pobiera, gdy status to `ready` albo `checking`. Po błędzie ponawia najwcześniej po 15 s.
- Start jest aktywny tylko przy statusie `ready`, gdy wybrane są miasto i specjalizacja.
- Filtry są zablokowane, a Stop aktywny, gdy `state.search != null`. Obejmuje to `checking` i wyszukiwanie wstrzymane przez `login_required`. Zablokowany formularz pokazuje wartości aktywnego wyszukiwania, także w nowo otwartej karcie. Po Stop strona przeładowuje pełne listy i zachowuje wybór (`applySearch` w `app.js`).
- Strona pyta o stan co 2 s. Log przewija się sam, gdy jest przewinięty na dół.

### Punkty podpięcia
- **06 (ręczne logowanie)**:
  - w nagłówku jest pusty `<div id="login-slot" hidden>` obok statusu;
  - w `renderStatus()` w `app.js` jest komentarz, gdzie go pokazać przy `login_required`;
  - endpoint (np. `POST /api/login`) trzeba dopisać w `create_app`;
  - błąd opcji ma flagę `login_required: true`.
- **07 (zapamiętane wyszukiwanie)**:
  - `create_app(worker, restore_saved=...)`: `restore_saved()` ma zwrócić `search.Restored` albo `None` (np. `restore_search` na `last_search.json` z `options_for` wołającym `worker.load_options(...).result()`);
  - `GET /api/saved-search` serializuje wynik;
  - JS po pierwszym wczytaniu miast woła `loadSavedSearch()`: wypełnia formularz przez `applySearch()`, jeśli użytkownik nic nie wybrał, i pokazuje ostrzeżenia;
  - zapis do `last_search.json` należy dodać w `POST /api/start`, gdzie jest komentarz „Zgłoszenie 07”;
  - `main()` musi przekazać `restore_saved`.

### Do sprawdzenia na żywo
Sprawdziłem tylko headless Chromium z atrapą workera (kaskada, filtr, blokada, nowa karta, Stop). Na prawdziwym Medicover trzeba jeszcze sprawdzić:
- czy `filters` bez parametrów zwraca `regions`;
- kaskadę z prawdziwymi ID;
- start i stop;
- Ctrl+C.
