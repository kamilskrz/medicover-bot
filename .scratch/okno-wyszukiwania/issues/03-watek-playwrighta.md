# 03 Wątek roboczy Playwrighta i usunięcie scrapowania

Status: resolved
Blocked by: 01

- Jeden wątek jako jedyny korzysta z Playwrighta (persistent context w `browser_profile/`, domyślnie headless) i przyjmuje polecenia z kolejki: zaloguj, pobierz opcje filtrów (kaskadowo), wykonaj sprawdzenie dla danego wyszukiwania.
- Wykorzystać istniejące `capture_headers()`, `auto_login()` i logikę ponawiania przy 401/403 z `check_api()`. Parametry zapytania pochodzą z wyszukiwania (02), a nie z `API_URL`.
- Usunąć `check()`, tryb `run`, `SEARCH_URL`, `SEARCH_BUTTON`, `NO_SLOTS_TEXT`, `SLOT_SELECTOR`, `API_URL`, `api_url_for_today()` i `HEADLESS`. Tryby `sniff` i `setup` zostają. Z `setup` usunąć instrukcje o `SEARCH_URL` i dopisać: „zaznacz Dodaj do zaufanych urządzeń”.

## Kryteria akceptacji
- Wątek udostępnia stan (łączenie / gotowy / sprawdzanie / wymagane logowanie), ostatnie terminy i bufor logu do odczytu z innego wątku.
- Żadne wywołanie Playwrighta nie odbywa się poza tym wątkiem.

## Answer

`worker.py`, klasa `Worker(threading.Thread)`. Jako jedyna dotyka Playwrighta, przez `PlaywrightBrowser` (persistent context w `browser_profile/`, headless). Inne wątki korzystają tylko z poniższych metod:

- `Worker(on_check=None, on_login_required=None, browser_factory=PlaywrightBrowser)`:
  - `on_check(slots)` dostaje terminy w zakresie, od najwcześniejszego, po każdym udanym sprawdzeniu (tu podepnie się alarm z 05);
  - `on_login_required()` jest wołane raz przy przejściu w `login_required`;
  - `browser_factory` to szew dla testów.
- `load_options(region_id=None, specialty_id=None, clinic_ids=()) -> Future[FilterOptions]`: `search-appointments/filters` z pominięciem pustych parametrów. Błąd trafia do Future (`ApiError`, `LoginRequired`).
- `start_search(search)` i `stop_search()`: sprawdzenie od razu, potem co `randint(INTERVAL_MIN, INTERVAL_MAX)` s. Wątek czeka na kolejce z timeoutem, więc polecenia działają od razu.
- `snapshot() -> dict`: `status` (`connecting` / `ready` / `checking` / `login_required`), `search`, `slots`, `last_check`, `log` (200 ostatnich linii `[HH:MM:SS] ...`). `checking` oznacza aktywne wyszukiwanie, a nie samo trwające zapytanie.
- `shutdown(timeout=30)`: zamyka przeglądarkę i dołącza wątek. Oczekujące Future dostają wyjątek.

Token: przechwytywany przez `capture_headers` i odświeżany co `TOKEN_REFRESH`. Po 401/403 bot próbuje kolejno: nowy token, potem ponowne `auto_login`. Po 2 nieudanych auto-logowaniach z rzędu przechodzi w `login_required`. Sprawdzanie jest wtedy wstrzymane, ale wyszukiwanie zostaje w stanie, żeby 06 mogło je wznowić. Log zbiera wszystko, co przechodzi przez `bot.log` (`bot.log_hooks`).

`python bot.py` bez argumentu uruchamia tymczasowy podgląd `watch()`, który zastąpi okno z 04.

### Po teście na żywo (główny agent)
- W trybie headless Chromium przedstawia się jako `HeadlessChrome` i aplikacja Medicover nie wysyła wtedy zapytań do API, więc token się nie pojawia. Kończy się to 2 nieudanymi auto-logowaniami, a każde wysyła mail z kodem 2FA. Rozwiązanie: `bot.launch(headless=True)` ustawia UA zwykłego Chrome w wersji dołączonego Chromium (`desktop_user_agent`).
- Po tej poprawce zaufane urządzenie działa też w trybie headless, bez 2FA. Zweryfikowane na żywo: opcje filtrów, kaskada, powtórzone `ClinicIds`, sprawdzenie (4 terminy), Stop i czyste zamknięcie.
- `bot.make_worker()` to jedyne miejsce, gdzie powstaje `Worker` z podpiętymi reakcjami.
