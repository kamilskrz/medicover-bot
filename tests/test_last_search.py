"""Testy zapamiętanego wyszukiwania (last_search.json) z atrapą wątku roboczego."""
from __future__ import annotations

import json
from concurrent.futures import Future
from datetime import date

import app
import last_search
from search import FilterOptions, Option, Search
from worker import ApiError, LoginRequired

SZCZECIN = Option("206", "Szczecin")
NEUROLOG = Option("16", "Neurolog dorośli")
MALCZEWSKIEGO = Option("74640", "Medicover Malczewskiego")
KOWALSKI = Option("1002", "Kowalski Jan")
NOWAK = Option("1003", "Nowak Anna")

SAVED = Search(SZCZECIN, NEUROLOG, (MALCZEWSKIEGO,), (KOWALSKI, NOWAK), date(2026, 10, 20), date(2026, 11, 30))


class CascadeWorker:
    """Udaje worker.Worker: listy opcji zależą od poziomu kaskady, jak w API Medicover."""

    def __init__(self, doctors=(KOWALSKI, NOWAK), error=None):
        self.doctors = tuple(doctors)
        self.error = error
        self.option_calls = []
        self.started = []

    def snapshot(self):
        return {"status": "ready", "search": None, "slots": [], "last_check": None, "log": []}

    def load_options(self, region_id=None, specialty_id=None, clinic_ids=()):
        self.option_calls.append((region_id, specialty_id, tuple(clinic_ids)))
        fut = Future()
        if self.error:
            fut.set_exception(self.error)
        elif specialty_id is None:
            fut.set_result(FilterOptions(regions=(SZCZECIN,), specialties=(NEUROLOG,)))
        else:
            fut.set_result(FilterOptions(clinics=(MALCZEWSKIEGO,), doctors=self.doctors))
        return fut

    def start_search(self, search):
        self.started.append(search)

    def stop_search(self):
        pass


def start_body(**overrides):
    body = SAVED.to_dict()
    body.update(overrides)
    return body


def client_for(worker):
    return app.create_app(worker, restore_saved=last_search.restorer(worker)).test_client()


# --- zapis ---

def test_start_saves_search(last_search_path):
    worker = CascadeWorker()
    resp = client_for(worker).post("/api/start", json=start_body())
    assert resp.status_code == 200
    assert json.loads(last_search_path.read_text(encoding="utf-8")) == SAVED.to_dict()
    assert list(last_search_path.parent.iterdir()) == [last_search_path]  # bez plików tymczasowych


def test_start_overwrites_previous_search(last_search_path):
    last_search_path.write_text(json.dumps(SAVED.to_dict()), encoding="utf-8")
    body = start_body(clinics=[], doctors=[], date_from=None, date_to=None)
    assert client_for(CascadeWorker()).post("/api/start", json=body).status_code == 200
    assert json.loads(last_search_path.read_text(encoding="utf-8")) == Search(SZCZECIN, NEUROLOG).to_dict()


def test_invalid_start_does_not_save(last_search_path):
    worker = CascadeWorker()
    resp = client_for(worker).post("/api/start", json=start_body(specialty=None))
    assert resp.status_code == 400
    assert not last_search_path.exists()
    assert worker.started == []


def test_save_error_only_logs(monkeypatch, tmp_path):
    logged = []
    monkeypatch.setattr(last_search.bot, "log", logged.append)
    monkeypatch.setattr(last_search, "PATH", tmp_path / "brak-katalogu" / "last_search.json")
    worker = CascadeWorker()

    resp = client_for(worker).post("/api/start", json=start_body())

    assert resp.status_code == 200
    assert worker.started == [SAVED]
    assert any("Nie udało się zapisać" in line for line in logged)


# --- odczyt ---

def test_saved_search_round_trip(last_search_path):
    last_search.save(SAVED)
    worker = CascadeWorker()

    data = client_for(worker).get("/api/saved-search").get_json()

    assert data == {"search": SAVED.to_dict(), "warnings": []}
    assert worker.option_calls == [("206", None, ()), ("206", "16", ()), ("206", "16", ("74640",))]


def test_saved_search_drops_missing_doctor_with_warning():
    last_search.save(SAVED)

    data = client_for(CascadeWorker(doctors=(KOWALSKI,))).get("/api/saved-search").get_json()

    assert [d["id"] for d in data["search"]["doctors"]] == ["1002"]
    assert data["warnings"] == ["Lekarz Nowak Anna nie jest już dostępny – usunięto z filtrów"]


def test_missing_file_means_no_saved_search():
    worker = CascadeWorker()
    data = client_for(worker).get("/api/saved-search").get_json()
    assert data == {"search": None, "warnings": []}
    assert worker.option_calls == []


def test_corrupted_file_means_no_saved_search(last_search_path):
    worker = CascadeWorker()
    client = client_for(worker)
    for content in ("{niepoprawny json", "[]", '{"region": {"id": "206"}}', ""):
        last_search_path.write_text(content, encoding="utf-8")
        resp = client.get("/api/saved-search")
        assert resp.status_code == 200
        assert resp.get_json() == {"search": None, "warnings": []}


def test_load_options_error_gives_warning_not_500():
    last_search.save(SAVED)
    for error, reason in [(ApiError("API zwróciło 500"), "API zwróciło 500"),
                          (LoginRequired(), "wymagane logowanie")]:
        resp = client_for(CascadeWorker(error=error)).get("/api/saved-search")
        assert resp.status_code == 200
        assert resp.get_json() == {
            "search": None,
            "warnings": [f"Nie udało się przywrócić ostatniego wyszukiwania: {reason}"],
        }


def test_load_options_timeout_gives_warning():
    class SlowWorker(CascadeWorker):
        def load_options(self, *args):
            return Future()  # nigdy się nie kończy

    last_search.save(SAVED)
    restored = last_search.load(SlowWorker(), timeout=0.01)
    assert restored.search is None
    assert restored.warnings == ("Nie udało się przywrócić ostatniego wyszukiwania: Medicover nie odpowiedział na czas",)
