"""Wyszukiwanie, terminy i opcje filtrów - czysta logika, bez Playwrighta i Flaska.

Słownictwo: GLOSSARY.md. Kształt odpowiedzi API: .scratch/okno-wyszukiwania/issues/01-*.md.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional, Tuple


@dataclass(frozen=True)
class Option:
    """Pozycja z listy filtrów (miasto, specjalizacja, placówka, lekarz)."""

    id: str
    name: str


@dataclass(frozen=True)
class FilterOptions:
    """Opcje zwrócone przez `search-appointments/filters`, z przyciętymi nazwami."""

    regions: tuple[Option, ...] = ()
    specialties: tuple[Option, ...] = ()
    clinics: tuple[Option, ...] = ()
    doctors: tuple[Option, ...] = ()


@dataclass(frozen=True)
class Search:
    """Wyszukiwanie: komplet filtrów, których pilnuje bot."""

    region: Option
    specialty: Option
    clinics: tuple[Option, ...] = ()  # puste = dowolna placówka
    doctors: tuple[Option, ...] = ()  # puste = dowolny lekarz
    date_from: date | None = None  # brak = od dziś
    date_to: date | None = None  # brak = bez końca; włącznie

    def slots_query(self, today: date) -> list[tuple[str, str]]:
        """Parametry zapytania `search-appointments/slots` (klucze list powtórzone, np. DoctorIds)."""
        start = max(self.date_from, today) if self.date_from else today
        return [
            ("RegionIds", self.region.id),
            ("SpecialtyIds", self.specialty.id),
            *(("ClinicIds", c.id) for c in self.clinics),
            *(("DoctorIds", d.id) for d in self.doctors),
            ("Page", "1"),
            ("PageSize", "5000"),
            ("SlotSearchType", "Standard"),
            ("isOverbookingSearchDisabled", "false"),
            ("StartTime", start.isoformat()),
        ]

    def to_dict(self) -> dict:
        """Postać do zapisu w last_search.json (ID wraz z nazwami, daty ISO)."""
        return {
            "region": _option_dict(self.region),
            "specialty": _option_dict(self.specialty),
            "clinics": [_option_dict(c) for c in self.clinics],
            "doctors": [_option_dict(d) for d in self.doctors],
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
        }


@dataclass(frozen=True)
class Slot:
    """Termin: wolne miejsce na wizytę."""

    when: datetime  # appointmentDate, czas lokalny
    doctor: Option
    clinic: Option
    specialty: Option

    @property
    def key(self) -> tuple[str, str, str, str]:
        """Tożsamość terminu między sprawdzeniami (API nie zwraca ID terminu)."""
        return (self.doctor.id, self.clinic.id, self.specialty.id, self.when.isoformat())


@dataclass(frozen=True)
class Restored:
    """Wynik przywracania zapamiętanego wyszukiwania względem aktualnych opcji."""

    search: Search | None  # None, gdy brak miasta lub specjalizacji na aktualnych listach
    warnings: tuple[str, ...] = field(default=())


def parse_filter_options(data: dict) -> FilterOptions:
    """Odpowiedź `search-appointments/filters` -> FilterOptions."""

    def options(key: str) -> tuple[Option, ...]:
        return tuple(Option(str(o["id"]), o["value"].strip()) for o in data.get(key) or ())

    return FilterOptions(
        regions=options("regions"),
        specialties=options("specialties"),
        clinics=options("clinics"),
        doctors=options("doctors"),
    )


def parse_slots(data: dict) -> list[Slot]:
    """Odpowiedź `search-appointments/slots` -> terminy."""

    def option(o: dict) -> Option:
        return Option(str(o["id"]), o["name"].strip())

    return [
        Slot(
            when=datetime.fromisoformat(item["appointmentDate"]),
            doctor=option(item["doctor"]),
            clinic=option(item["clinic"]),
            specialty=option(item["specialty"]),
        )
        for item in data.get("items") or ()
    ]


def in_range(slots: list[Slot], search: Search) -> list[Slot]:
    """Odrzuca terminy po `date_to` (i przed `date_from`)."""
    return [
        s for s in slots
        if (search.date_from is None or s.when.date() >= search.date_from)
        and (search.date_to is None or s.when.date() <= search.date_to)
    ]


def new_slots(current: list[Slot], previous_keys: set[tuple[str, str, str, str]]) -> list[Slot]:
    """Terminy z bieżącego sprawdzenia, których nie było w poprzednim."""
    return [s for s in current if s.key not in previous_keys]


def format_slots(slots: list[Slot]) -> str:
    """Lista terminów do maila/logu: data, godzina, lekarz, placówka, od najwcześniejszego."""
    return "\n".join(
        f"{s.when:%Y-%m-%d %H:%M}  {s.doctor.name}  {s.clinic.name}"
        for s in sorted(slots, key=lambda s: s.when)
    )


# Źródło opcji dla przywracania: (region_id, specialty_id, clinic_ids) -> FilterOptions
OptionsLookup = Callable[[Optional[str], Optional[str], Tuple[str, ...]], "FilterOptions"]


def restore_search(saved: dict, options_for: OptionsLookup) -> Restored:
    """Przywraca wyszukiwanie z last_search.json; usuwa placówki/lekarzy, których już nie ma."""
    try:
        region = _parse_option(saved["region"])
        specialty = _parse_option(saved["specialty"])
        clinics = tuple(_parse_option(c) for c in _as_list(saved.get("clinics")))
        doctors = tuple(_parse_option(d) for d in _as_list(saved.get("doctors")))
        date_from = _parse_date(saved.get("date_from"))
        date_to = _parse_date(saved.get("date_to"))
    except (KeyError, TypeError, ValueError, AttributeError):
        return Restored(None, ())

    # Specjalizacje API zwraca dopiero dla miasta, więc pierwsze pytanie jest już z regionem.
    top = options_for(region.id, None, ())
    current_region = _find(top.regions, region)
    if not current_region:
        return Restored(None, (f"Miasto {region.name} nie jest już dostępne – usunięto z filtrów",))
    current_specialty = _find(top.specialties, specialty)
    if not current_specialty:
        return Restored(None, (f"Specjalizacja {specialty.name} nie jest już dostępna – usunięto z filtrów",))
    region, specialty = current_region, current_specialty

    warnings: list[str] = []
    for_specialty = options_for(region.id, specialty.id, ())
    kept_clinics = _keep(clinics, for_specialty.clinics, "Placówka {} nie jest już dostępna", warnings)
    if kept_clinics:
        doctor_options = options_for(region.id, specialty.id, tuple(c.id for c in kept_clinics)).doctors
    else:
        doctor_options = for_specialty.doctors
    kept_doctors = _keep(doctors, doctor_options, "Lekarz {} nie jest już dostępny", warnings)

    search = Search(region, specialty, kept_clinics, kept_doctors, date_from, date_to)
    return Restored(search, tuple(warnings))


def _option_dict(option: Option) -> dict:
    return {"id": option.id, "name": option.name}


def _parse_option(raw: dict) -> Option:
    if not isinstance(raw, dict) or not raw.get("id"):
        raise ValueError(f"niepoprawna pozycja filtra: {raw!r}")
    return Option(str(raw["id"]), str(raw.get("name") or ""))


def _as_list(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise TypeError(f"oczekiwano listy: {raw!r}")
    return raw


def _parse_date(raw) -> date | None:
    return date.fromisoformat(raw) if raw else None


def _find(options: tuple[Option, ...], wanted: Option) -> Option | None:
    """Aktualna pozycja o tym samym ID (z aktualną nazwą)."""
    return next((o for o in options if o.id == wanted.id), None)


def _keep(saved: tuple[Option, ...], current: tuple[Option, ...], message: str,
          warnings: list[str]) -> tuple[Option, ...]:
    """Zostawia pozycje obecne na aktualnej liście; o pozostałych dopisuje ostrzeżenie."""
    kept = []
    for option in saved:
        found = _find(current, option)
        if found:
            kept.append(found)
        else:
            warnings.append(message.format(option.name) + " – usunięto z filtrów")
    return tuple(kept)
