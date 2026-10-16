# Medicover bot

Lokalna aplikacja, która pilnuje wolnych terminów w Medicover Online. Wybierasz w oknie przeglądarki miasto, specjalizację i opcjonalnie placówki, lekarzy oraz zakres dat. Bot co minutę sprawdza dostępność i alarmuje dźwiękiem, powiadomieniem macOS i opcjonalnie mailem, gdy pojawi się **nowy** termin. Terminów nie rezerwuje.

> **Projekt w całości zbudowany z AI.** Cały kod, testy, specyfikacja, zgłoszenia, ADR i ta dokumentacja powstały w pracy z [Claude Code](https://claude.com/claude-code). Moja rola: pomysł, decyzje produktowe i techniczne, prowadzenie agenta, review i testy na żywym koncie.
>
> **Czas:** [[4h]] · **Rozmiar:** ok. 1,8 tys. linii kodu aplikacji + 86 testów (pytest)

## Stos

Python · Playwright (Chromium) · Flask · vanilla JS/HTML/CSS · pytest · Claude Code

## Jak powstał

Projekt przeszedł drogę od skryptu do działającej aplikacji w kilku krokach, każdy prowadzony z Claude Code:

1. **Prototyp: scrapowanie HTML.** Pierwsza wersja klikała w wyszukiwarkę Medicover i czytała wynik ze strony. Działała, ale psuła się przy każdej zmianie tekstów i selektorów w SPA.
2. **Zwrot: nieudokumentowane API.** Tryb `sniff` podsłuchał zapytania aplikacji Medicover. Okazało się, że da się pytać API bezpośrednio, z tokenem przechwyconym z przeglądarki. Decyzja i jej konsekwencje są spisane w [ADR 0001](docs/adr/0001-sprawdzanie-przez-api-z-przechwyconym-tokenem.md).
3. **Spec i podział pracy.** Razem z agentem doprecyzowałem wymagania w [specyfikacji](.scratch/okno-wyszukiwania/spec.md), a słownictwo domenowe w [GLOSSARY.md](GLOSSARY.md). Prace podzieliliśmy na [8 zgłoszeń](.scratch/okno-wyszukiwania/issues/), zaczynając od spike'a ([spike.py](.scratch/okno-wyszukiwania/spike.py)), który sprawdził strukturę danych API, zanim powstał właściwy kod.
4. **Implementacja zgłoszenie po zgłoszeniu.** Czysta logika (kaskada filtrów, zakres dat, wykrywanie nowych terminów) najpierw w testach, potem wątek Playwrighta, serwer Flask, okno, alarm, obsługa wygasłej sesji i zapamiętywanie wyszukiwania. Każde zgłoszenie kończy się sekcją „Answer” z tym, co faktycznie powstało.
5. **Weryfikacja na żywo.** Testy jednostkowe nie wyłapią wszystkiego. Przykład z [zgłoszenia 03](.scratch/okno-wyszukiwania/issues/03-watek-playwrighta.md): w trybie headless Chromium przedstawia się jako `HeadlessChrome`, a aplikacja Medicover wtedy w ogóle nie odpytuje API. Bot nie dostawał tokenu, ponawiał logowanie i każda próba wysyłała mail z kodem 2FA. Poprawka: podmiana User-Agenta na zwykły Chrome.

Agent pracuje według reguł repozytorium: [CLAUDE.md](CLAUDE.md) i [docs/agents/](docs/agents/) opisują, gdzie są zgłoszenia, jakie mają etykiety i skąd brać słownictwo. [.claude/settings.json](.claude/settings.json) blokuje agentowi odczyt `.env` i profilu przeglądarki, więc hasła i sesja nigdy nie trafiają do kontekstu modelu.

## Architektura

```
przeglądarka (okno)  ──HTTP/JSON──▶  Flask (app.py, 127.0.0.1)
                                          │ kolejka poleceń
                                          ▼
                                     Worker (worker.py)  ── jedyny wątek z Playwrightem
                                          │  logowanie, przechwycenie tokenu
                                          ▼
                                     API Medicover  ──▶  nowe terminy?  ──▶  alarm.py
```

| Moduł | Rola |
| --- | --- |
| [bot.py](bot.py) | punkt wejścia, tryby `setup` i `sniff`, logowanie i przechwytywanie tokenu |
| [worker.py](worker.py) | wątek roboczy: jedyny użytkownik Playwrighta, kolejka poleceń, cykl sprawdzeń, odnawianie sesji |
| [search.py](search.py) | czysta logika: parametry zapytań, kaskada filtrów, zakres dat, wykrywanie nowych terminów |
| [app.py](app.py) + [static/](static/) | serwer Flask i okno wyboru wyszukiwania |
| [alarm.py](alarm.py) | dźwięk, powiadomienie macOS, mail |
| [last_search.py](last_search.py) | zapamiętanie ostatniego wyszukiwania i odrzucenie nieaktualnych lekarzy/placówek |

Kilka decyzji wartych uwagi:

- **Jeden wątek dla Playwrighta.** Synchroniczne API Playwrighta nie działa między wątkami, więc Flask zleca pracę przez kolejkę i dostaje `Future`.
- **Szew dla testów.** `Worker` przyjmuje `browser_factory`, dzięki czemu cykl sprawdzeń, ponawianie przy 401/403 i przejście w „wymagane logowanie” są testowane bez prawdziwej przeglądarki i bez Medicover.
- **Ostrożność wobec konta.** Losowy odstęp między sprawdzeniami, najwyżej 2 automatyczne logowania z rzędu, potem pauza i prośba o ręczne logowanie, zamiast ryzykować blokadę.

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

### Pierwsze uruchomienie: zaufane urządzenie

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

### Gdy sesja wygaśnie

Bot najpierw loguje się automatycznie. Jeśli Medicover poprosi o kod albo logowanie się nie uda, sprawdzanie zostaje wstrzymane i dostajesz cichy alarm. Wtedy w oknie kliknij **Zaloguj ręcznie**: otworzy się widoczna przeglądarka. Zaloguj się, wpisz kod i zaznacz „Dodaj do zaufanych urządzeń”. Po zalogowaniu bot sam wznowi wyszukiwanie.

### Diagnostyka

`python bot.py sniff` zapisuje zapytania aplikacji Medicover do `sniff.log`, bez nagłówków z tokenami. Przydaje się, gdy Medicover zmieni swoje API.

## Testy

```bash
pip install -r requirements-dev.txt
pytest
```

86 testów pokrywa czystą logikę wyszukiwania, wątek roboczy (z atrapą przeglądarki), endpointy Flaska, alarm i zapamiętane wyszukiwanie. Testów na prawdziwym Medicover nie ma: ten zakres sprawdzałem ręcznie na żywym koncie.
