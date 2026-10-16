from __future__ import annotations

from datetime import date, datetime

import pytest

from search import (
    FilterOptions,
    Option,
    Restored,
    Search,
    Slot,
    format_slots,
    in_range,
    new_slots,
    parse_filter_options,
    parse_slots,
    restore_search,
)

SZCZECIN = Option("206", "Szczecin")
WARSZAWA = Option("204", "Warszawa")
STOMATOLOGIA = Option("16", "Stomatologia")
NEUROLOG = Option("27", "Neurolog dorośli")
MALCZEWSKIEGO = Option("74640", "Medicover Malczewskiego")
WOJSKA = Option("74641", "Medicover Wojska Polskiego")
HAJDULA = Option("1001", "Hajduła Rafał")
KOWALSKI = Option("1002", "Kowalski Jan")


def slot(when: str, doctor: Option = HAJDULA, clinic: Option = MALCZEWSKIEGO,
         specialty: Option = STOMATOLOGIA) -> Slot:
    return Slot(datetime.fromisoformat(when), doctor, clinic, specialty)


def api_slot(when: str, doctor: Option = HAJDULA, clinic: Option = MALCZEWSKIEGO,
             specialty: Option = STOMATOLOGIA) -> dict:
    return {
        "appointmentDate": when,
        "appointmentDateOffset": when + "+02:00",
        "doctor": {"id": doctor.id, "name": doctor.name},
        "clinic": {"id": clinic.id, "name": clinic.name, "isPozClinic": False},
        "specialty": {"id": specialty.id, "name": specialty.name},
        "bookingString": "nieprzejrzysty-token",
    }


# --- parse_filter_options ---

def test_parse_filter_options_trims_names():
    data = {
        "regions": [{"id": "206", "value": "Szczecin"}],
        "specialties": [
            {"id": "176", "value": "Chirurg dorośli ", "type": "Center", "kind": "Specialty"},
            {"id": "9", "value": "   Medicover Express - przeziębienie, grypa", "type": "Center"},
        ],
        "clinics": [{"id": "74640", "value": " Medicover Malczewskiego"}],
        "doctors": [{"id": "1001", "value": "Hajduła Rafał "}],
        "doctorLanguages": [{"id": "1", "value": "polski"}],
    }

    options = parse_filter_options(data)

    assert options == FilterOptions(
        regions=(SZCZECIN,),
        specialties=(Option("176", "Chirurg dorośli"),
                     Option("9", "Medicover Express - przeziębienie, grypa")),
        clinics=(MALCZEWSKIEGO,),
        doctors=(HAJDULA,),
    )


def test_parse_filter_options_missing_keys_give_empty_tuples():
    assert parse_filter_options({"specialties": [{"id": "16", "value": "Stomatologia"}]}) == \
        FilterOptions(specialties=(STOMATOLOGIA,))
    assert parse_filter_options({}) == FilterOptions()


def test_parse_filter_options_ids_are_strings():
    options = parse_filter_options({"regions": [{"id": 206, "value": "Szczecin"}]})
    assert options.regions == (SZCZECIN,)


# --- parse_slots ---

def test_parse_slots():
    data = {"items": [api_slot("2026-10-21T15:40:00")], "nextSearchDate": None}

    assert parse_slots(data) == [slot("2026-10-21T15:40:00")]


def test_parse_slots_without_items_is_empty():
    assert parse_slots({}) == []
    assert parse_slots({"items": None}) == []


# --- Slot.key ---

def test_slot_key():
    assert slot("2026-10-21T15:40:00").key == ("1001", "74640", "16", "2026-10-21T15:40:00")


# --- Search.slots_query ---

def test_slots_query_minimal_starts_today():
    search = Search(SZCZECIN, STOMATOLOGIA)

    assert search.slots_query(date(2026, 10, 15)) == [
        ("RegionIds", "206"),
        ("SpecialtyIds", "16"),
        ("Page", "1"),
        ("PageSize", "5000"),
        ("SlotSearchType", "Standard"),
        ("isOverbookingSearchDisabled", "false"),
        ("StartTime", "2026-10-15"),
    ]


def test_slots_query_repeats_clinics_and_doctors():
    search = Search(SZCZECIN, STOMATOLOGIA, clinics=(MALCZEWSKIEGO, WOJSKA),
                    doctors=(HAJDULA, KOWALSKI))

    query = search.slots_query(date(2026, 10, 15))

    assert [v for k, v in query if k == "ClinicIds"] == ["74640", "74641"]
    assert [v for k, v in query if k == "DoctorIds"] == ["1001", "1002"]


def test_slots_query_start_time_from_future_date_from():
    search = Search(SZCZECIN, STOMATOLOGIA, date_from=date(2026, 11, 1))

    assert ("StartTime", "2026-11-01") in search.slots_query(date(2026, 10, 15))


def test_slots_query_start_time_not_in_past():
    search = Search(SZCZECIN, STOMATOLOGIA, date_from=date(2026, 10, 1))

    assert ("StartTime", "2026-10-15") in search.slots_query(date(2026, 10, 15))


# --- in_range ---

def test_in_range_inclusive_on_both_ends():
    search = Search(SZCZECIN, STOMATOLOGIA, date_from=date(2026, 10, 20), date_to=date(2026, 10, 22))
    slots = [
        slot("2026-10-19T23:59:00"),
        slot("2026-10-20T08:00:00"),
        slot("2026-10-22T19:30:00"),
        slot("2026-10-23T07:00:00"),
    ]

    assert in_range(slots, search) == [slots[1], slots[2]]


def test_in_range_without_dates_keeps_all():
    slots = [slot("2026-10-19T10:00:00"), slot("2030-01-01T10:00:00")]

    assert in_range(slots, Search(SZCZECIN, STOMATOLOGIA)) == slots


# --- new_slots ---

def test_new_slots_keeps_input_order():
    old = slot("2026-10-21T15:40:00")
    later = slot("2026-10-25T09:00:00")
    earlier = slot("2026-10-20T09:00:00", doctor=KOWALSKI)

    assert new_slots([later, old, earlier], {old.key}) == [later, earlier]


def test_new_slots_differs_by_any_key_part():
    base = slot("2026-10-21T15:40:00")
    other_clinic = slot("2026-10-21T15:40:00", clinic=WOJSKA)

    assert new_slots([base, other_clinic], {base.key}) == [other_clinic]
    assert new_slots([base], set()) == [base]


# --- format_slots ---

def test_format_slots_sorted_one_per_line():
    slots = [
        slot("2026-10-25T09:05:00", doctor=KOWALSKI, clinic=WOJSKA),
        slot("2026-10-21T15:40:00"),
    ]

    assert format_slots(slots) == (
        "2026-10-21 15:40  Hajduła Rafał  Medicover Malczewskiego\n"
        "2026-10-25 09:05  Kowalski Jan  Medicover Wojska Polskiego"
    )


def test_format_slots_empty():
    assert format_slots([]) == ""


# --- to_dict / restore_search ---

FULL = Search(SZCZECIN, STOMATOLOGIA, clinics=(MALCZEWSKIEGO, WOJSKA), doctors=(HAJDULA, KOWALSKI),
              date_from=date(2026, 10, 20), date_to=date(2026, 11, 30))


class FakeApi:
    """Udaje `filters`: (region_id, specialty_id, clinic_ids) -> FilterOptions; zapisuje wywołania."""

    def __init__(self, regions=(SZCZECIN, WARSZAWA), specialties=(STOMATOLOGIA, NEUROLOG),
                 clinics=(MALCZEWSKIEGO, WOJSKA), doctors=(HAJDULA, KOWALSKI), doctors_by_clinics=None):
        self.regions = tuple(regions)
        self.specialties = tuple(specialties)
        self.clinics = tuple(clinics)
        self.doctors = tuple(doctors)
        self.doctors_by_clinics = doctors_by_clinics or {}
        self.calls = []

    def __call__(self, region_id, specialty_id, clinic_ids):
        self.calls.append((region_id, specialty_id, tuple(clinic_ids)))
        if region_id is None:
            return FilterOptions(regions=self.regions)
        doctors = self.doctors_by_clinics.get(tuple(clinic_ids), self.doctors)
        return FilterOptions(regions=self.regions, specialties=self.specialties,
                             clinics=self.clinics, doctors=doctors)


def test_to_dict():
    assert FULL.to_dict() == {
        "region": {"id": "206", "name": "Szczecin"},
        "specialty": {"id": "16", "name": "Stomatologia"},
        "clinics": [{"id": "74640", "name": "Medicover Malczewskiego"},
                    {"id": "74641", "name": "Medicover Wojska Polskiego"}],
        "doctors": [{"id": "1001", "name": "Hajduła Rafał"}, {"id": "1002", "name": "Kowalski Jan"}],
        "date_from": "2026-10-20",
        "date_to": "2026-11-30",
    }


def test_to_dict_without_dates():
    saved = Search(SZCZECIN, STOMATOLOGIA).to_dict()
    assert saved["date_from"] is None and saved["date_to"] is None
    assert saved["clinics"] == [] and saved["doctors"] == []


def test_restore_round_trip():
    api = FakeApi()

    assert restore_search(FULL.to_dict(), api) == Restored(search=FULL, warnings=())


def test_restore_asks_cascade_in_order():
    api = FakeApi()

    restore_search(FULL.to_dict(), api)

    assert api.calls == [
        ("206", None, ()),
        ("206", "16", ()),
        ("206", "16", ("74640", "74641")),
    ]


def test_restore_round_trip_minimal():
    search = Search(SZCZECIN, STOMATOLOGIA)

    assert restore_search(search.to_dict(), FakeApi()) == Restored(search=search)


def test_restore_missing_region_gives_no_search():
    result = restore_search(FULL.to_dict(), FakeApi(regions=(WARSZAWA,)))

    assert result.search is None
    assert result.warnings == ("Miasto Szczecin nie jest już dostępne – usunięto z filtrów",)


def test_restore_missing_specialty_gives_no_search():
    result = restore_search(FULL.to_dict(), FakeApi(specialties=(NEUROLOG,)))

    assert result.search is None
    assert result.warnings == ("Specjalizacja Stomatologia nie jest już dostępna – usunięto z filtrów",)


def test_restore_drops_missing_clinic_and_doctor():
    api = FakeApi(clinics=(MALCZEWSKIEGO,), doctors_by_clinics={("74640",): (HAJDULA,)})

    result = restore_search(FULL.to_dict(), api)

    assert result.search == Search(SZCZECIN, STOMATOLOGIA, clinics=(MALCZEWSKIEGO,), doctors=(HAJDULA,),
                                   date_from=date(2026, 10, 20), date_to=date(2026, 11, 30))
    assert result.warnings == (
        "Placówka Medicover Wojska Polskiego nie jest już dostępna – usunięto z filtrów",
        "Lekarz Kowalski Jan nie jest już dostępny – usunięto z filtrów",
    )
    assert api.calls[-1] == ("206", "16", ("74640",))


def test_restore_uses_current_names():
    api = FakeApi(doctors=(Option("1001", "Hajduła Rafał (lek. dent.)"), KOWALSKI))

    result = restore_search(FULL.to_dict(), api)

    assert result.search.doctors[0] == Option("1001", "Hajduła Rafał (lek. dent.)")
    assert result.warnings == ()


@pytest.mark.parametrize("saved", [
    {},
    None,
    "nonsens",
    [],
    {"region": {"id": "206", "name": "Szczecin"}},
    {"region": "206", "specialty": "16"},
    {"region": {"name": "Szczecin"}, "specialty": {"id": "16", "name": "Stomatologia"}},
    dict(FULL.to_dict(), date_from="20.10.2026"),
    dict(FULL.to_dict(), clinics=[{"name": "bez id"}]),
    dict(FULL.to_dict(), doctors="1001"),
])
def test_restore_broken_dict_gives_empty_result(saved):
    assert restore_search(saved, FakeApi()) == Restored(None, ())
