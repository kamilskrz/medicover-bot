# 01 Spike: lista specjalizacji i struktura terminów

Status: resolved
Type: research

Wymaga zalogowanej sesji na prawdziwym koncie Medicover.

## Pytania
1. Czy `GET search-appointments/filters?RegionIds=<miasto>&SlotSearchType=Standard` (bez `SpecialtyIds`) zwraca pełną listę specjalizacji dla miasta?
2. Jeśli nie: czy da się ją zbudować ze słów kluczowych (`service-selector-configurator-os/api/v2/keywords?regionId=`) i ich ankiety (`.../keywords/<id>/triage/flat`)? Jak w drzewie ankiety wygląda węzeł, który niesie ID specjalizacji? Wtedy okno pokazuje najpierw słowo kluczowe, a potem specjalizację.
3. Jakie pola ma pojedynczy element `items` w odpowiedzi `search-appointments/slots`? Czy jest w nim stabilne ID terminu? Skąd brać datę i godzinę, lekarza i placówkę?
4. Czy `filters` przyjmuje `ClinicIds` i zawęża wtedy listę lekarzy?

## Jak
Rozszerzyć `python bot.py sniff` albo napisać jednorazowy skrypt w `.scratch/` na istniejącym `capture_headers()`. Odpowiedzi zapisać bez tokenów i danych osobowych.

## Kryteria akceptacji
- Odpowiedzi na pytania 1–4 są dopisane pod `## Answer`, z przykładowymi (zanonimizowanymi) fragmentami JSON.
- Jeśli pytanie 2 okaże się potrzebne, spec ma zaktualizowaną kaskadę.

## Answer

Uruchomione 2026-10-15 skryptem `.scratch/okno-wyszukiwania/spike.py`, region 206 (Szczecin). Surowy wynik jest w `spike-output.json`.

1. **Tak.** `filters?RegionIds=206&SlotSearchType=Standard` bez `SpecialtyIds` zwraca **85 specjalizacji** (oraz `clinics`, `doctors`, `doctorLanguages`, `regions`). Element wygląda tak: `{"id": "176", "value": "Alergolog dorośli", "type": "Center", "kind": "Specialty"}`. Uwagi:
   - nazwy mają nadmiarowe spacje, np. `"   Medicover Express - przeziębienie, grypa"` czy `"Chirurg dorośli "`, więc trzeba je przycinać;
   - na liście są też porady telefoniczne (`"type": "PhoneAdvice"`, np. „Dermatolog dorośli - porada telefoniczna”). Są to osobne specjalizacje, więc nie potrzebujemy osobnego filtra typu wizyty.
2. **Niepotrzebne.** Ścieżka przez słowo kluczowe odpada, a okno pokazuje specjalizacje bezpośrednio. (`keywords` zwraca 3 grupy: Konsultacje 35, Badania 5, Stomatologia 18. Ankieta „Neurologia” zwróciła 409 `GENDER_MISMATCH`, czyli ankiety zależą od pacjenta. To kolejny powód, żeby z nich nie korzystać.)
3. **Brak osobnego ID terminu.** Pola elementu `items`:
   - `appointmentDate`: `"2026-10-21T15:40:00"`, czas lokalny;
   - `appointmentDateOffset`;
   - `clinic {id, name, isPozClinic}`;
   - `doctor {id, name}`;
   - `doctorLanguages`;
   - `specialty {id, name}`;
   - `visitType`;
   - `bookingString`: długi, nieprzejrzysty token rezerwacji. Nie wiadomo, czy jest stały między zapytaniami, więc nie nadaje się na klucz;
   - `isOverbooking`, `visitOrigin`, `serviceId` i inne.

   **Klucz terminu**: `doctor.id` + `clinic.id` + `specialty.id` + `appointmentDate`.

   Na poziomie odpowiedzi jest też `nextSearchDate` i `additionalFilters`.
4. **Tak.** `filters?...&SpecialtyIds=16&ClinicIds=74640` zawęża lekarzy z 3 do 1.
