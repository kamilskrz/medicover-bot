"""Okno wyboru wyszukiwania: serwer Flask na 127.0.0.1 i proste endpointy JSON.

Serwer nie dotyka Playwrighta. Pracę zleca wątkowi roboczemu (worker.py), a stan czyta
przez `worker.snapshot()`. Strona leży w static/ (czysty HTML, CSS i JS, bez CDN).

Endpointy:
  GET  /                  - strona okna
  GET  /api/state         - stan wątku roboczego (status, wyszukiwanie, terminy, log)
  GET  /api/options       - opcje filtrów; parametry region_id, specialty_id, clinic_id (powtarzany)
  GET  /api/saved-search  - zapamiętane wyszukiwanie (last_search.json) do wstępnego wypełnienia
  POST /api/start         - start wyszukiwania (JSON)
  POST /api/stop          - stop wyszukiwania
  POST /api/login         - ręczne logowanie w widocznej przeglądarce (przy statusie login_required)

Słownictwo: GLOSSARY.md.
"""
from __future__ import annotations

import logging
import webbrowser
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from flask import Flask, jsonify, request

import bot
import last_search
from search import FilterOptions, Option, Restored, Search, Slot
from worker import ApiError, LoginRequired

HOST = "127.0.0.1"  # tylko lokalnie, nigdy 0.0.0.0
OPTIONS_TIMEOUT = 60  # s; wątek roboczy może być w trakcie sprawdzenia albo logowania

# Funkcja zwracająca przywrócone wyszukiwanie z last_search.json (albo None); zob. last_search.py.
RestoreSaved = Callable[[], Optional[Restored]]


class BadRequest(Exception):
    """Niepoprawne dane od strony; komunikat trafia do okna."""


def create_app(worker, restore_saved: RestoreSaved | None = None) -> Flask:
    """Aplikacja Flask dla danego wątku roboczego (w testach: atrapy)."""
    app = Flask(__name__, static_folder=str(Path(__file__).parent / "static"), static_url_path="/static")

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/state")
    def state():
        return jsonify(snapshot_json(worker.snapshot()))

    @app.get("/api/options")
    def options():
        region_id = request.args.get("region_id") or None
        specialty_id = request.args.get("specialty_id") or None
        clinic_ids = tuple(c for c in request.args.getlist("clinic_id") if c)
        try:
            result = worker.load_options(region_id, specialty_id, clinic_ids).result(timeout=OPTIONS_TIMEOUT)
        except FutureTimeout:
            return _error("Medicover nie odpowiedział na czas – spróbuj ponownie.", 504)
        except LoginRequired:
            return _error("Wymagane logowanie – nie można pobrać list.", 503, login_required=True)
        except ApiError as e:
            return _error(f"Błąd API Medicover: {e}", 502)
        except Exception as e:  # noqa: BLE001
            return _error(f"Nie udało się pobrać list: {e}", 500)
        if not region_id and not result.regions:
            # Bez parametrów API powinno zwrócić listę miast; bez niej nie da się zacząć.
            return _error("Medicover nie zwrócił listy miast – spróbuj ponownie później.", 502)
        return jsonify(options_json(result))

    @app.get("/api/saved-search")
    def saved_search():
        # restore_saved (last_search.load) nie rzuca; i tak brak przywrócenia nie może dać 500.
        try:
            restored = restore_saved() if restore_saved else None
        except Exception as e:  # noqa: BLE001
            bot.log(f"Nie udało się przywrócić ostatniego wyszukiwania: {e}")
            restored = Restored(None, (f"Nie udało się przywrócić ostatniego wyszukiwania: {e}",))
        if restored is None:
            return jsonify({"search": None, "warnings": []})
        return jsonify({
            "search": restored.search.to_dict() if restored.search else None,
            "warnings": list(restored.warnings),
        })

    @app.post("/api/start")
    def start():
        try:
            search = parse_search(request.get_json(silent=True))
        except BadRequest as e:
            return _error(str(e), 400)
        worker.start_search(search)
        last_search.save(search)  # last_search.json; błąd zapisu tylko trafia do logu
        return jsonify({"ok": True, "search": search.to_dict()})

    @app.post("/api/stop")
    def stop():
        worker.stop_search()
        return jsonify({"ok": True})

    @app.post("/api/login")
    def manual_login():
        # Wątek roboczy otworzy widoczną przeglądarkę; postęp widać w statusie (manual_login).
        worker.manual_login()
        return jsonify({"ok": True})

    return app


# --- serializacja ---

def option_json(option: Option) -> dict:
    return {"id": option.id, "name": option.name}


def options_json(options: FilterOptions) -> dict:
    return {
        "regions": [option_json(o) for o in options.regions],
        "specialties": [option_json(o) for o in options.specialties],
        "clinics": [option_json(o) for o in options.clinics],
        "doctors": [option_json(o) for o in options.doctors],
    }


def slot_json(slot: Slot) -> dict:
    return {
        "date": slot.when.strftime("%Y-%m-%d"),
        "time": slot.when.strftime("%H:%M"),
        "doctor": slot.doctor.name,
        "clinic": slot.clinic.name,
    }


def snapshot_json(snap: dict) -> dict:
    """`worker.snapshot()` -> JSON dla okna."""
    search = snap.get("search")
    last_check = snap.get("last_check")
    return {
        "status": snap["status"],
        "search": search.to_dict() if search else None,
        "slots": [slot_json(s) for s in snap.get("slots") or ()],
        "last_check": last_check.isoformat() if last_check else None,
        "log": list(snap.get("log") or ()),
    }


def parse_search(data) -> Search:
    """JSON ze strony -> Search. Wymaga miasta i specjalizacji oraz date_from <= date_to."""
    if not isinstance(data, dict):
        raise BadRequest("Brak danych wyszukiwania.")
    region = _parse_option(data.get("region"), "Wybierz miasto.")
    specialty = _parse_option(data.get("specialty"), "Wybierz specjalizację.")
    clinics = tuple(_parse_option(c, "Niepoprawna placówka.") for c in _parse_list(data.get("clinics")))
    doctors = tuple(_parse_option(d, "Niepoprawny lekarz.") for d in _parse_list(data.get("doctors")))
    date_from = _parse_date(data.get("date_from"), "Niepoprawna data „od”.")
    date_to = _parse_date(data.get("date_to"), "Niepoprawna data „do”.")
    if date_from and date_to and date_from > date_to:
        raise BadRequest("Data „od” jest późniejsza niż data „do”.")
    return Search(region, specialty, clinics, doctors, date_from, date_to)


def _parse_option(raw, message: str) -> Option:
    if not isinstance(raw, dict) or not str(raw.get("id") or "").strip():
        raise BadRequest(message)
    return Option(str(raw["id"]).strip(), str(raw.get("name") or "").strip())


def _parse_list(raw) -> list:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise BadRequest("Niepoprawna lista placówek lub lekarzy.")
    return raw


def _parse_date(raw, message: str) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise BadRequest(message) from None


def _error(message: str, status: int, **extra):
    return jsonify({"error": message, **extra}), status


# --- uruchomienie ---

def main():
    """Tryb domyślny `python bot.py`: wątek roboczy, serwer na wolnym porcie i karta przeglądarki."""
    from werkzeug.serving import make_server

    logging.getLogger("werkzeug").setLevel(logging.WARNING)  # bez linii o każdym odpytaniu stanu

    worker = bot.make_worker()
    worker.start()
    try:
        # Port 0 = wolny port wybrany przez system, bez wyścigu między sprawdzeniem a bindem.
        window = create_app(worker, restore_saved=last_search.restorer(worker))
        server = make_server(HOST, 0, window, threaded=True)
        url = f"http://{HOST}:{server.server_port}/"
        bot.log(f"Okno bota: {url} (Ctrl+C kończy).")
        webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        bot.log("Koniec.")
        worker.shutdown()
