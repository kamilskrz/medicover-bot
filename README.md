# Medicover bot

Lokalna aplikacja, która cyklicznie sprawdza w Medicover Online dostępność terminów dla wybranego wyszukiwania (miasto, specjalizacja, placówki, lekarze, zakres dat). Gdy pojawi się nowy termin, alarmuje dźwiękiem, powiadomieniem macOS i opcjonalnie mailem. Terminów nie rezerwuje.

Słownictwo: [GLOSSARY.md](GLOSSARY.md). Decyzje: [docs/adr/](docs/adr/).

## Instalacja
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # uzupełnij MEDICOVER_USER, MEDICOVER_PASSWORD i opcjonalnie SMTP
```

Konfiguracja w `.env`:

| Zmienna | Znaczenie |
| --- | --- |
| `MEDICOVER_USER`, `MEDICOVER_PASSWORD` | dane do automatycznego logowania |
| `INTERVAL_MIN`, `INTERVAL_MAX` | losowy odstęp między sprawdzeniami w sekundach (domyślnie 45–90) |
| `TOKEN_REFRESH` | co ile sekund odświeżać token sesji (domyślnie 120) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `MAIL_TO` | wysyłka maili z alarmem (opcjonalnie) |

## Pierwsze uruchomienie: zaufane urządzenie
Konto Medicover ma weryfikację dwuetapową: przy logowaniu wysyła kod mailem. Bot nie wpisuje kodu, więc raz zaloguj się ręcznie:

```bash
python bot.py setup
```

Zaloguj się w otwartej przeglądarce, wpisz kod z maila i **zaznacz „Dodaj do zaufanych urządzeń”**. Potem naciśnij Enter w terminalu. Od tej pory bot loguje się sam, w tle i bez kodu. Sesja i znacznik zaufanego urządzenia są zapisane w `browser_profile/`, a hasło jest tylko w `.env`.

## Użycie
```bash
python bot.py
```

1. W przeglądarce otworzy się okno bota (adres `127.0.0.1`, dostępny tylko lokalnie).
2. Poczekaj na status „Gotowy”. Wybierz **miasto** i **specjalizację** (obowiązkowe), a opcjonalnie **placówki**, **lekarzy** i **zakres dat**. Listy pochodzą na żywo z Medicover i zawężają się kaskadowo.
3. **Start** uruchamia sprawdzanie, a **Stop** je zatrzymuje i odblokowuje filtry.
4. Alarm włącza się tylko dla nowych terminów. Aktualne terminy widać w tabeli w oknie.

Zamknięcie karty nie zatrzymuje bota: otwórz ją ponownie, a zobaczysz bieżący stan. Aplikację kończy **Ctrl+C** w terminalu.

Ostatnie wyszukiwanie zapisuje się w `last_search.json` i wypełnia formularz przy kolejnym uruchomieniu. Jeśli jakiś lekarz lub placówka zniknęli z oferty, okno pokaże ostrzeżenie.

## Gdy sesja wygaśnie
Bot najpierw loguje się automatycznie. Jeśli Medicover poprosi o kod albo logowanie się nie uda, sprawdzanie zostaje wstrzymane i dostajesz cichy alarm. Wtedy w oknie kliknij **Zaloguj ręcznie**: otworzy się widoczna przeglądarka. Zaloguj się, wpisz kod i zaznacz „Dodaj do zaufanych urządzeń”. Po zalogowaniu bot sam wznowi wyszukiwanie.

## Diagnostyka
`python bot.py sniff` zapisuje zapytania aplikacji Medicover do `sniff.log`, bez nagłówków z tokenami. Przydaje się, gdy Medicover zmieni swoje API.

## Testy
```bash
pip install -r requirements-dev.txt
pytest
```
