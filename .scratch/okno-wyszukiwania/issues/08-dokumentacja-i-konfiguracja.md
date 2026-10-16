# 08 README, .env.example i porządki

Status: ready-for-human
Blocked by: 04, 05, 06, 07

- README: nowy sposób uruchamiania (`python bot.py`), opis okna, rola `sniff`, pierwsze uruchomienie przez `setup` z zaznaczeniem „Dodaj do zaufanych urządzeń” (konto ma weryfikację dwuetapową e-mailem), usunięcie instrukcji o `SEARCH_URL` i `NO_SLOTS_TEXT`.
- `.env.example`: usunąć `API_URL`, `SEARCH_URL`, `SEARCH_BUTTON`, `NO_SLOTS_TEXT`, `SLOT_SELECTOR` i `HEADLESS`. Uwaga: plik jest objęty regułą deny dla odczytu w `.claude/settings.json`, więc edycja może wymagać człowieka.
- `requirements.txt`: dodać `flask`.

## Answer

- README przepisany pod okno, `setup` z zaufanym urządzeniem, ręczne logowanie, `sniff` i testy.
- `flask` był już w `requirements.txt` (zgłoszenie 04).
- Zostaje dla człowieka: `.env.example` (zablokowany do odczytu dla agenta) – usunąć `API_URL`, `SEARCH_URL`, `SEARCH_BUTTON`, `NO_SLOTS_TEXT`, `SLOT_SELECTOR`, `HEADLESS` i dodać go do repo.
