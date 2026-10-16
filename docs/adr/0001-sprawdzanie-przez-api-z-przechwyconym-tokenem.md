# Sprawdzanie przez API Medicover z tokenem przechwyconym z przeglądarki

Bot pyta API Medicover Online (`api-gateway-online24.medicover.pl`) o terminy bezpośrednio, z nagłówkiem `Authorization` przechwyconym z zapytań, które wysyła sama aplikacja Medicover w przeglądarce Playwrighta. Nie scrapuje HTML. Medicover to SPA, a filtry nie siedzą w adresie, więc scrapowanie zależało od tekstów i selektorów, które łatwo się psują. API zwraca ustrukturyzowane terminy i listy opcji do filtrów (`search-appointments/filters`), na których stoi okno wyboru wyszukiwania. Przeglądarka nadal jest potrzebna do logowania i odświeżania tokenu, bo nie odtwarzamy samodzielnie przepływu OAuth Medicover.

## Consequences

- Ścieżka scrapowania HTML (`SEARCH_URL`, `NO_SLOTS_TEXT`, `SLOT_SELECTOR`, `SEARCH_BUTTON`) zostaje usunięta.
- Korzystamy z nieudokumentowanego API, więc zmiana po stronie Medicover może zepsuć bota bez ostrzeżenia. Tryb `sniff` zostaje, żeby w takiej sytuacji dało się szybko podejrzeć nowe zapytania.
