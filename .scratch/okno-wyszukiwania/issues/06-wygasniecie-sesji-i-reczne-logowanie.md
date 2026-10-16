# 06 Wygaśnięcie sesji i ręczne logowanie

Status: resolved
Blocked by: 03, 04

- Logowanie przy starcie i w trakcie sprawdzania: automatycznie, najwyżej 2 nieudane próby z rzędu.
- `auto_login()` rozpoznaje ekran weryfikacji dwuetapowej (nagłówek „Weryfikacja dwuetapowa”, kod wysyłany e-mailem). Wtedy od razu przechodzi w stan „wymagane logowanie”, bez czekania 30 s i bez kolejnej próby, bo każda próba wysyła nowy mail z kodem.
- Potem stan „wymagane logowanie”: sprawdzanie jest wstrzymane, a okno pokazuje przycisk **Zaloguj ręcznie**.
- Komunikat przy przycisku przypomina, żeby zaznaczyć „Dodaj do zaufanych urządzeń”.
- Przycisk restartuje kontekst Playwrighta w trybie widocznym na tym samym `browser_profile/`. Bot czeka, aż użytkownik opuści stronę logowania, wraca do headless i wznawia przerwane sprawdzanie.

## Kryteria akceptacji
- Po ręcznym zalogowaniu aktywne wcześniej wyszukiwanie wznawia się bez ponownego Startu.
- Wysyłany jest jeden alarm bez dźwięku o wymaganym logowaniu, jak dotąd.

## Answer

`pytest`: 91 testów przechodzi. Nie łączyłem się z prawdziwym Medicover.

### Weryfikacja dwuetapowa (`bot.py`)
- `bot.auto_login` po kliknięciu `#login-button` co 0,5 s sprawdza (najdłużej `LOGIN_WAIT` = 30 s) dwa warunki: czy adres opuścił strony logowania (`bot.on_login_page(url)`, wydzielone z `LOGIN_URL_MARKERS`) i czy widać tekst `TWO_FACTOR_TEXT` = „Weryfikacja dwuetapowa” (`page.get_by_text(...).first.is_visible()`).
- Wybór: **osobny wyjątek `bot.TwoFactorRequired`** zamiast trzeciej wartości zwracanej. `True`/`False` znaczą to co dotąd, a 2FA to inny rodzaj wyniku: „nie ponawiaj”. Wyjątek przechodzi przez ogólne `except Exception` w `auto_login` (jest przepuszczany jawnie).
- `Worker._authenticate` łapie `TwoFactorRequired` i od razu zwraca `False`. Nie zwiększa licznika nieudanych logowań i nie robi drugiej próby, więc worker przechodzi w `login_required` (z jednym alarmem).

### Ręczne logowanie (`worker.py`)
- `Worker.manual_login()` wstawia do kolejki polecenie `login`. Działa tylko w stanie `login_required`. W `manual_login` tylko loguje „już trwa”, w innych stanach „pominięte”.
- Nowy status `manual_login` (`worker.MANUAL_LOGIN`). Przebieg:
  1. `browser.reopen(headless=False)` zamyka kontekst headless i otwiera `bot.launch(p, headless=False)` na tym samym `browser_profile/`, potem `browser.goto_app()` (`APP_URL`).
  2. Co `MANUAL_LOGIN_POLL` = 0,5 s wątek odbiera polecenia z kolejki (wspólna metoda `_handle`, ta sama co w głównej pętli). `shutdown` kończy czekanie i wątek. `start`/`stop` zmieniają wyszukiwanie bez zmiany statusu. `load_options` dostaje od razu `LoginRequired`.
  3. Gdy `browser.on_login_page()` zwróci `False`, wątek próbuje `capture_token()`. Jeśli token jest pusty, kolejna próba po `MANUAL_LOGIN_RETRY` = 5 s, bo `capture_headers` przeładowuje kartę. Zamknięcie okna przez użytkownika (`page.is_closed()`) przerywa czekanie.
  4. Limit `MANUAL_LOGIN_TIMEOUT` = 600 s (argument konstruktora `manual_login_timeout`, w testach krótszy).
  5. Zawsze `browser.reopen(headless=True)`. Po sukcesie wątek przechwytuje token w headless, zeruje `_login_failures` i przechodzi w `ready` albo, przy wstrzymanym wyszukiwaniu, w `checking` ze sprawdzeniem od razu. **Bez `on_search_start`**, bo wznowienie to nie nowy start i pamięć alarmu zostaje.
  6. Po limicie, zamknięciu okna albo braku tokenu w headless wątek wraca do `login_required` bez drugiego alarmu, bo użytkownik właśnie próbował się logować.
- **Usunięta prowizorka**: `_get_json` nie przełącza już `login_required` na `checking`/`ready` po udanym zapytaniu. Z `login_required` wychodzi się tylko przez ręczne logowanie. Do tego `load_options` w `login_required`/`manual_login` od razu zwraca `LoginRequired` bez dotykania przeglądarki, bo wcześniej mogło wywołać `capture_token`, a przy wyzerowanym liczniku nawet auto-logowanie i mail z kodem. Główna pętla sprawdza tylko w statusie `checking`.
- `PlaywrightBrowser` ma nowe metody `reopen(headless)`, `goto_app()` i `on_login_page()`. `FakeBrowser` w testach je udaje i ma flagę `two_factor`.

### Flask i okno
- `POST /api/login` woła `worker.manual_login()` i zwraca `{ok: true}`. Status `manual_login` przechodzi przez `/api/state` bez zmian.
- `#login-slot` (`index.html`) zawiera przycisk **Zaloguj ręcznie** i podpowiedź „Otworzy się okno przeglądarki. Zaloguj się, wpisz kod z maila i zaznacz «Dodaj do zaufanych urządzeń».”. `renderStatus` pokazuje slot tylko przy `login_required`. Przycisk po kliknięciu jest zablokowany do następnego pokazania slotu.
- Status `manual_login`: „Czekam na zalogowanie w przeglądarce…” (z dopiskiem „– sprawdzanie wstrzymane”, gdy jest wyszukiwanie) i pomarańczowa kropka.
- `bot.make_worker()`: alarm `on_login_required` brzmi „Sesja Medicover wygasła - kliknij «Zaloguj ręcznie» w oknie bota.”. Bez dźwięku, raz przy przejściu w `login_required`.

### Do sprawdzenia na żywo
1. Normalny start na zaufanym profilu: auto-logowanie bez 2FA, `ready`.
2. Profil niezaufany (np. kopia zapasowa `browser_profile/` i świeży profil): jedna próba, jeden mail z kodem, od razu `login_required` (bez 30 s), jeden alarm.
3. **Zaloguj ręcznie**: otwiera się widoczny Chromium na profilu, logowanie z kodem i „Dodaj do zaufanych urządzeń”. Po `/home` okno się zamyka, a bot wraca do `ready`/`checking`. Czy token w headless jest przechwytywany od razu po zamknięciu widocznego kontekstu?
4. Wznowienie wstrzymanego wyszukiwania po ręcznym logowaniu, bez alarmu „nowe terminy” dla terminów sprzed przerwy.
5. Zamknięcie widocznego okna ręcznie: powrót do `login_required` i działający przycisk.
6. Ctrl+C w trakcie `manual_login`: widoczne okno się zamyka, proces kończy się czysto.
7. Czy `get_by_text("Weryfikacja dwuetapowa")` łapie nagłówek na prawdziwej stronie (tekst może być w innym elemencie albo mieć inne spacje).
