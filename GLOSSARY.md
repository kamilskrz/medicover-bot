# Medicover bot

Lokalna aplikacja, która cyklicznie sprawdza w Medicover Online dostępność terminów wizyt pasujących do filtrów wybranych przez użytkownika i alarmuje, gdy się pojawią.

## Filtry

**Wyszukiwanie**:
Komplet filtrów (miasto, specjalizacja, placówki, lekarze, zakres dat), których pilnuje bot. W danym momencie aktywne jest najwyżej jedno.
_Avoid_: zapytanie, search, konfiguracja

**Miasto**:
Region Medicover, w którym szukamy terminów. Dokładnie jedno w każdym wyszukiwaniu.
_Avoid_: region, lokalizacja

**Specjalizacja**:
Konkretny rodzaj wizyty u specjalisty, np. „Neurolog dorośli”. Dokładnie jedna w każdym wyszukiwaniu.
_Avoid_: specjalista, słowo kluczowe, usługa

**Słowo kluczowe**:
Ogólna dziedzina z wyszukiwarki Medicover, np. „Neurologia”, z której przez ankietę wstępną dochodzi się do specjalizacji. Nie jest filtrem wyszukiwania.
_Avoid_: specjalizacja, kategoria

**Placówka**:
Konkretne centrum medyczne Medicover. Wyszukiwanie może wskazać kilka placówek albo żadnej, co oznacza dowolną.
_Avoid_: klinika, oddział, centrum

**Lekarz**:
Konkretna osoba przyjmująca pacjentów. Wyszukiwanie może wskazać kilku lekarzy albo żadnego, co oznacza dowolnego.
_Avoid_: specjalista, doktor

**Zakres dat**:
Przedział od–do, w którym interesują nas terminy. Bez daty „od” liczy się od dziś, bez daty „do” zakres jest otwarty.
_Avoid_: data, okres

## Działanie bota

**Termin**:
Wolne miejsce na wizytę u konkretnego lekarza, w konkretnej placówce, w konkretnym dniu i o konkretnej godzinie.
_Avoid_: slot, wizyta, wolne miejsce

**Sprawdzenie**:
Pojedyncze odpytanie Medicover o terminy pasujące do aktywnego wyszukiwania.
_Avoid_: odświeżenie, poll, iteracja

**Alarm**:
Powiadomienie użytkownika (dźwięk, powiadomienie systemowe, opcjonalnie mail), że sprawdzenie znalazło terminy. Bot nigdy sam nie rezerwuje terminu.
_Avoid_: alert, notyfikacja
