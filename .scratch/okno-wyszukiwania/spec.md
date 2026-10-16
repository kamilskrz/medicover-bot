# Spec: okno wyboru wyszukiwania

Status: ready-for-agent

Słownictwo: [GLOSSARY.md](../../GLOSSARY.md). Kontekst techniczny: [ADR 0001](../../docs/adr/0001-sprawdzanie-przez-api-z-przechwyconym-tokenem.md).

## Cel

Zamiast edytować `API_URL` w `.env`, użytkownik po uruchomieniu bota wybiera **Wyszukiwanie** w oknie i naciska **Start**. Bot cyklicznie sprawdza terminy pasujące do tego wyszukiwania. Aplikacja działa tylko lokalnie i nie będzie serwowana.

## Zachowanie

### Uruchomienie
- `python bot.py` uruchamia serwer Flask na `127.0.0.1` i otwiera kartę przeglądarki z oknem.
- Zamknięcie karty nie zatrzymuje bota. Po ponownym otwarciu karta pokazuje bieżący stan. Aplikację kończy Ctrl+C.
- `python bot.py setup` działa jak dotąd: otwiera widoczną przeglądarkę do ręcznego logowania. Tak przy pierwszym uruchomieniu dodajesz `browser_profile/` do zaufanych urządzeń Medicover.
- `python bot.py sniff` działa jak dotąd (narzędzie diagnostyczne).

### Logowanie
- Po starcie bot loguje się w tle danymi z `.env` (`MEDICOVER_USER`, `MEDICOVER_PASSWORD`) w przeglądarce Playwrighta działającej headless. Do czasu uzyskania tokenu okno pokazuje „Łączenie z Medicover…”.
- Konto ma weryfikację dwuetapową z kodem wysyłanym na e-mail. Bot nie obsługuje kodu: zakładamy, że `browser_profile/` jest zaufanym urządzeniem, bo przy logowaniu przez `setup` lub **Zaloguj ręcznie** zaznaczyłeś „Dodaj do zaufanych urządzeń”. Jeśli po kliknięciu „Zaloguj” pojawi się ekran weryfikacji dwuetapowej, jest to od razu „Wymagane logowanie”, bez czekania na timeout i bez ponawiania.
- Jeśli automatyczne logowanie się nie uda, okno pokazuje „Wymagane logowanie” i przycisk **Zaloguj ręcznie**, który otwiera widoczną przeglądarkę. Po zalogowaniu bot wraca do pracy bez ręcznego wznawiania.
- Gdy sesja wygaśnie w trakcie sprawdzania, bot najpierw próbuje zalogować się automatycznie, najwyżej 2 razy z rzędu, żeby nie zablokować konta. Potem wstrzymuje sprawdzanie i przechodzi do ścieżki ręcznej opisanej wyżej.

### Wybór wyszukiwania
- Pola tworzą kaskadę: **Miasto → Specjalizacja → Placówki → Lekarze**, plus **Zakres dat**.
  - Miasto: dokładnie jedno.
  - Specjalizacja: dokładnie jedna, np. „Neurolog dorośli”.
  - Placówki: zero lub więcej (zero = dowolna).
  - Lekarze: zero lub więcej (zero = dowolny).
  - Zakres dat: „od” i „do”, obie opcjonalne.
- Listy są pobierane na żywo z API Medicover (`search-appointments/filters`) i zawężają się kaskadowo. Wybór placówek zawęża listę lekarzy.
- Zmiana miasta czyści specjalizację, placówki i lekarzy. Zmiana specjalizacji czyści placówki i lekarzy.
- Długie listy mają wyszukiwanie po wpisanym tekście.
- Ostatnie wyszukiwanie zapisuje się w `last_search.json` (w `.gitignore`) i jest wstępnie wybrane przy kolejnym uruchomieniu. Placówki i lekarze, których nie ma już na aktualnych listach, wypadają z wyboru, a okno pokazuje ostrzeżenie, np. „Lekarz X nie jest już dostępny – usunięto z filtrów”.

### Sprawdzanie
- **Start** uruchamia sprawdzenia co losowe `INTERVAL_MIN`–`INTERVAL_MAX` s (z `.env`). **Stop** zatrzymuje je i odblokowuje edycję filtrów.
- W danym momencie aktywne jest najwyżej jedno wyszukiwanie.
- Sprawdzenie odpytuje `search-appointments/slots` z `RegionIds`, `SpecialtyIds`, `ClinicIds`, `DoctorIds`, `StartTime` = data „od” lub dziś, a także `SlotSearchType=Standard`. Terminy po dacie „do” bot odrzuca po swojej stronie.
- Okno pokazuje status (łączenie / gotowy / sprawdzanie / wymagane logowanie), log na żywo i listę terminów z ostatniego sprawdzenia: data, godzina, lekarz, placówka, od najwcześniejszego. Strona pyta serwer o stan co około 2 s.

### Alarm
- Alarm (dźwięk, powiadomienie macOS, opcjonalnie mail) włącza się tylko wtedy, gdy sprawdzenie znajdzie termin, którego nie było w poprzednim sprawdzeniu.
- Mail zawiera listę terminów w tym samym formacie co okno.
- Po alarmie bot sprawdza dalej, aż użytkownik naciśnie Stop. Bot nigdy sam nie rezerwuje terminu.

## Architektura
- Flask na `127.0.0.1` obsługuje stronę i proste endpointy JSON (stan, opcje filtrów, start, stop, ręczne logowanie).
- Jeden wątek roboczy jako jedyny korzysta z Playwrighta, bo jego synchroniczne API nie działa między wątkami. Serwer zleca mu pracę przez kolejkę: logowanie, przechwycenie tokenu, pobranie opcji filtrów i sprawdzenie.
- Czysta logika jest wydzielona i testowana w pytest: zakres dat, wykrywanie nowych terminów, kaskadowe czyszczenie i przywracanie zapamiętanego wyszukiwania. Nie ma testów na prawdziwym Medicover.

## Konfiguracja
- W `.env` zostają: dane logowania do Medicover, SMTP, `MAIL_TO`, `INTERVAL_MIN`, `INTERVAL_MAX` i `TOKEN_REFRESH`. Okno nie pozwala ich edytować.
- Z `.env` i kodu znikają: `API_URL`, `SEARCH_URL`, `SEARCH_BUTTON`, `NO_SLOTS_TEXT`, `SLOT_SELECTOR`, `HEADLESS` oraz tryb `run`. Tryb `setup` zostaje (logowanie ręczne i zaufane urządzenie), ale bez instrukcji o kopiowaniu adresu do `SEARCH_URL`.

## Poza zakresem
Wpisywanie kodu weryfikacji dwuetapowej w oknie lub odczyt kodu z poczty, kilka wyszukiwań naraz, filtr języka lekarza, typ wizyty (telekonsultacje), filtr pory dnia, automatyczna rezerwacja, edycja `.env` z okna, uruchamianie bez okna, serwowanie poza localhost.

## Ustalenia ze spike'a (zgłoszenie 01)
- Pełna lista specjalizacji dla miasta pochodzi z `filters` bez `SpecialtyIds`. Nazwy trzeba przycinać ze spacji.
- Kolejne poziomy kaskady pochodzą z `filters` z coraz większą liczbą parametrów (`SpecialtyIds`, potem `ClinicIds`).
- Terminy nie mają własnego ID. Termin identyfikujemy po lekarzu, placówce, specjalizacji i dacie z godziną (`appointmentDate`).
