"""Testy serwera Flask z atrapą wątku roboczego (bez Playwrighta i bez Medicover)."""
from __future__ import annotations

from concurrent.futures import Future
from datetime import date, datetime

import pytest

import app
from search import FilterOptions, Option, Restored, Search, Slot
from worker import ApiError, LoginRequired

SZCZECIN = Option("206", "Szczecin")
NEUROLOG = Option("16", "Neurolog dorośli")
MALCZEWSKIEGO = Option("74640", "Medicover Malczewskiego")
KOWALSKI = Option("1002", "Kowalski Jan")


class FakeWorker:
    """Udaje worker.Worker: zapamiętuje polecenia i zwraca gotowe Future."""

    def __init__(self, snapshot=None, options=None, error=None):
        self._snapshot = snapshot or {
            "status": "ready", "search": None, "slots": [], "last_check": None, "log": [],
        }
        self.options = options or FilterOptions()
        self.error = error
        self.option_calls = []
        self.started = []
        self.stops = 0
        self.logins = 0

    def snapshot(self):
        return dict(self._snapshot)

    def load_options(self, region_id=None, specialty_id=None, clinic_ids=()):
        self.option_calls.append((region_id, specialty_id, tuple(clinic_ids)))
        fut = Future()
        if self.error:
            fut.set_exception(self.error)
        else:
            fut.set_result(self.options)
        return fut

    def start_search(self, search):
        self.started.append(search)

    def stop_search(self):
        self.stops += 1

    def manual_login(self):
        self.logins += 1


def client_for(worker, **kwargs):
    return app.create_app(worker, **kwargs).test_client()


def start_body(**overrides):
    body = {
        "region": {"id": "206", "name": "Szczecin"},
        "specialty": {"id": "16", "name": "Neurolog dorośli"},
        "clinics": [{"id": "74640", "name": "Medicover Malczewskiego"}],
        "doctors": [{"id": "1002", "name": "Kowalski Jan"}],
        "date_from": "2026-10-20",
        "date_to": "2026-11-30",
    }
    body.update(overrides)
    return body


# --- strona ---

def test_index_serves_page_without_external_resources():
    resp = client_for(FakeWorker()).get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Medicover bot" in html
    assert "http://" not in html and "https://" not in html


# --- stan ---

def test_state_serializes_snapshot():
    search = Search(SZCZECIN, NEUROLOG, (MALCZEWSKIEGO,), (), date(2026, 10, 20), None)
    slot = Slot(datetime(2026, 10, 21, 15, 40), KOWALSKI, MALCZEWSKIEGO, NEUROLOG)
    worker = FakeWorker(snapshot={
        "status": "checking",
        "search": search,
        "slots": [slot],
        "last_check": datetime(2026, 10, 15, 14, 5, 12),
        "log": ["[14:05:12] Sprawdzenie: terminy w zakresie: 1."],
    })

    data = client_for(worker).get("/api/state").get_json()

    assert data == {
        "status": "checking",
        "search": {
            "region": {"id": "206", "name": "Szczecin"},
            "specialty": {"id": "16", "name": "Neurolog dorośli"},
            "clinics": [{"id": "74640", "name": "Medicover Malczewskiego"}],
            "doctors": [],
            "date_from": "2026-10-20",
            "date_to": None,
        },
        "slots": [{
            "date": "2026-10-21", "time": "15:40",
            "doctor": "Kowalski Jan", "clinic": "Medicover Malczewskiego",
        }],
        "last_check": "2026-10-15T14:05:12",
        "log": ["[14:05:12] Sprawdzenie: terminy w zakresie: 1."],
    }


def test_state_without_search_and_check():
    data = client_for(FakeWorker()).get("/api/state").get_json()
    assert data["status"] == "ready"
    assert data["search"] is None
    assert data["slots"] == []
    assert data["last_check"] is None


# --- opcje ---

def test_options_without_params_returns_regions():
    worker = FakeWorker(options=FilterOptions(regions=(SZCZECIN,)))
    resp = client_for(worker).get("/api/options")
    assert resp.status_code == 200
    assert resp.get_json() == {
        "regions": [{"id": "206", "name": "Szczecin"}],
        "specialties": [], "clinics": [], "doctors": [],
    }
    assert worker.option_calls == [(None, None, ())]


def test_options_passes_cascade_params():
    worker = FakeWorker(options=FilterOptions(doctors=(KOWALSKI,)))
    resp = client_for(worker).get("/api/options?region_id=206&specialty_id=16&clinic_id=1&clinic_id=2")
    assert resp.status_code == 200
    assert resp.get_json()["doctors"] == [{"id": "1002", "name": "Kowalski Jan"}]
    assert worker.option_calls == [("206", "16", ("1", "2"))]


def test_options_without_regions_is_readable_error():
    resp = client_for(FakeWorker(options=FilterOptions())).get("/api/options")
    assert resp.status_code == 502
    assert "listy miast" in resp.get_json()["error"]


def test_options_for_region_may_have_no_regions():
    worker = FakeWorker(options=FilterOptions(specialties=(NEUROLOG,)))
    resp = client_for(worker).get("/api/options?region_id=206")
    assert resp.status_code == 200
    assert resp.get_json()["specialties"] == [{"id": "16", "name": "Neurolog dorośli"}]


def test_options_login_required_is_readable_error():
    resp = client_for(FakeWorker(error=LoginRequired())).get("/api/options")
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["error"].startswith("Wymagane logowanie")
    assert data["login_required"] is True


def test_options_api_error_is_readable_error():
    resp = client_for(FakeWorker(error=ApiError("API zwróciło 500"))).get("/api/options")
    assert resp.status_code == 502
    assert "API zwróciło 500" in resp.get_json()["error"]


def test_options_timeout_is_readable_error(monkeypatch):
    class SlowWorker(FakeWorker):
        def load_options(self, *args):
            return Future()  # nigdy się nie kończy

    monkeypatch.setattr(app, "OPTIONS_TIMEOUT", 0.01)
    resp = client_for(SlowWorker()).get("/api/options")
    assert resp.status_code == 504
    assert "na czas" in resp.get_json()["error"]


# --- start ---

def test_start_builds_search():
    worker = FakeWorker()
    resp = client_for(worker).post("/api/start", json=start_body())
    assert resp.status_code == 200
    assert worker.started == [
        Search(SZCZECIN, NEUROLOG, (MALCZEWSKIEGO,), (KOWALSKI,), date(2026, 10, 20), date(2026, 11, 30))
    ]


def test_start_without_optional_fields():
    worker = FakeWorker()
    body = start_body(clinics=[], doctors=[], date_from=None, date_to="")
    assert client_for(worker).post("/api/start", json=body).status_code == 200
    assert worker.started == [Search(SZCZECIN, NEUROLOG)]


def test_start_same_day_range_is_ok():
    worker = FakeWorker()
    body = start_body(date_from="2026-10-20", date_to="2026-10-20")
    assert client_for(worker).post("/api/start", json=body).status_code == 200


@pytest.mark.parametrize("body, message", [
    (start_body(region=None), "miasto"),
    (start_body(region={"id": "", "name": "Szczecin"}), "miasto"),
    (start_body(specialty=None), "specjalizację"),
    (start_body(date_from="2026-11-30", date_to="2026-10-20"), "późniejsza"),
    (start_body(date_from="30.11.2026"), "data"),
    (start_body(clinics="74640"), "lista"),
    (None, "Brak danych"),
])
def test_start_validation(body, message):
    worker = FakeWorker()
    client = client_for(worker)
    resp = client.post("/api/start", json=body) if body is not None else client.post("/api/start")
    assert resp.status_code == 400
    assert message.lower() in resp.get_json()["error"].lower()
    assert worker.started == []


# --- stop ---

def test_stop_calls_worker():
    worker = FakeWorker()
    resp = client_for(worker).post("/api/stop")
    assert resp.status_code == 200
    assert worker.stops == 1


# --- ręczne logowanie (zgłoszenie 06) ---

def test_login_calls_worker_manual_login():
    worker = FakeWorker(snapshot={
        "status": "login_required", "search": None, "slots": [], "last_check": None, "log": [],
    })
    resp = client_for(worker).post("/api/login")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    assert worker.logins == 1


def test_state_serializes_manual_login_status():
    worker = FakeWorker(snapshot={
        "status": "manual_login", "search": Search(SZCZECIN, NEUROLOG), "slots": [], "last_check": None, "log": [],
    })
    data = client_for(worker).get("/api/state").get_json()
    assert data["status"] == "manual_login"
    assert data["search"]["region"] == {"id": "206", "name": "Szczecin"}


# --- punkt podpięcia dla 07 ---

def test_saved_search_is_empty_by_default():
    data = client_for(FakeWorker()).get("/api/saved-search").get_json()
    assert data == {"search": None, "warnings": []}


def test_saved_search_uses_restore_hook():
    restored = Restored(Search(SZCZECIN, NEUROLOG), ("Lekarz X nie jest już dostępny – usunięto z filtrów",))
    data = client_for(FakeWorker(), restore_saved=lambda: restored).get("/api/saved-search").get_json()
    assert data["search"]["region"] == {"id": "206", "name": "Szczecin"}
    assert data["warnings"] == ["Lekarz X nie jest już dostępny – usunięto z filtrów"]
