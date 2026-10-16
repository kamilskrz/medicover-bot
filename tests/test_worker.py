"""Testy wątku roboczego z podmienioną przeglądarką (bez Playwrighta i bez Medicover)."""
from __future__ import annotations

import threading
import time
from datetime import date, datetime
from urllib.parse import parse_qsl, urlparse

import pytest

import bot
import worker
from search import FilterOptions, Option, Search, Slot

SZCZECIN = Option("206", "Szczecin")
NEUROLOG = Option("16", "Neurolog dorośli")
SEARCH = Search(region=SZCZECIN, specialty=NEUROLOG)


def slot(day):
    return Slot(
        when=datetime(2026, 10, day, 15, 40),
        doctor=Option("1", "Jan Kowalski"),
        clinic=Option("2", "Centrum"),
        specialty=NEUROLOG,
    )


class FakeBrowser:
    """Udaje PlaywrightBrowser. `responses` to kolejka (status, json) dla kolejnych GET."""

    def __init__(self, tokens=({"authorization": "t1"},), login_ok=False, responses=(), two_factor=False):
        self.tokens = list(tokens)
        self.login_ok = login_ok
        self.two_factor = two_factor  # login() trafia na ekran weryfikacji dwuetapowej
        self.responses = list(responses)
        self.default_response = (200, {"items": []})
        self.calls = []  # (nazwa metody, wątek)
        self.urls = []
        self.logins = 0
        self.captures = 0
        self.headless = True
        self.reopens = []  # kolejne wartości headless z reopen()
        self.login_page = True  # czy widoczna karta jest na stronie logowania

    def _record(self, name):
        self.calls.append((name, threading.current_thread()))

    def open(self):
        self._record("open")

    def close(self):
        self._record("close")

    def capture_token(self):
        self._record("capture_token")
        self.captures += 1
        return self.tokens.pop(0) if self.tokens else {}

    def login(self):
        self._record("login")
        self.logins += 1
        if self.two_factor:
            raise bot.TwoFactorRequired()
        return self.login_ok

    def reopen(self, headless):
        self._record("reopen")
        self.reopens.append(headless)
        self.headless = headless

    def goto_app(self):
        self._record("goto_app")

    def on_login_page(self):
        self._record("on_login_page")
        return self.login_page

    def nudge(self):
        self._record("nudge")

    def get(self, url, headers):
        self._record("get")
        self.urls.append((url, dict(headers)))
        return self.responses.pop(0) if self.responses else self.default_response


def wait_for(cond, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.01)
    raise AssertionError("Warunek nie został spełniony w czasie.")


@pytest.fixture(autouse=True)
def fake_search_logic(monkeypatch):
    """Czysta logika z search.py jest testowana osobno - tu ją upraszczamy."""
    monkeypatch.setattr(Search, "slots_query", lambda self, today: [
        ("RegionIds", self.region.id), ("SpecialtyIds", self.specialty.id),
        ("StartTime", today.isoformat()), ("SlotSearchType", "Standard"),
    ])
    monkeypatch.setattr(worker, "parse_slots", lambda data: data.get("items", []))
    monkeypatch.setattr(worker, "in_range", lambda slots, search: [s for s in slots if s.when.day < 25])
    monkeypatch.setattr(worker, "parse_filter_options", lambda data: FilterOptions(
        specialties=tuple(Option(i["id"], i["value"]) for i in data.get("specialties", []))))
    monkeypatch.setattr(bot, "INTERVAL_MIN", 0)
    monkeypatch.setattr(bot, "INTERVAL_MAX", 0)
    monkeypatch.setattr(bot, "TOKEN_REFRESH", 3600)


@pytest.fixture
def make_worker():
    started = []

    def make(browser, **kwargs):
        w = worker.Worker(browser_factory=lambda: browser, **kwargs)
        w.start()
        started.append(w)
        return w

    yield make
    for w in started:
        w.shutdown(timeout=3)
        assert not w.is_alive()


def query(url):
    return parse_qsl(urlparse(url).query)


# --- adresy ---

def test_filters_url_pomija_puste_i_powtarza_placowki():
    assert query(worker.filters_url("206")) == [("RegionIds", "206"), ("SlotSearchType", "Standard")]
    assert query(worker.filters_url("206", "16", ["74640", "1"])) == [
        ("RegionIds", "206"), ("SpecialtyIds", "16"),
        ("ClinicIds", "74640"), ("ClinicIds", "1"), ("SlotSearchType", "Standard"),
    ]
    assert worker.filters_url().endswith("/search-appointments/filters?SlotSearchType=Standard")


def test_slots_url_z_parametrow_wyszukiwania():
    url = worker.slots_url(SEARCH, date(2026, 10, 15))
    assert url.startswith(worker.API_BASE + "/slots?")
    assert ("StartTime", "2026-10-15") in query(url)


# --- łączenie ---

def test_po_starcie_z_tokenem_gotowy(make_worker):
    w = make_worker(FakeBrowser())
    wait_for(lambda: w.snapshot()["status"] == "ready")
    assert any("Połączono" in line for line in w.snapshot()["log"])


def test_bez_tokenu_loguje_sie_automatycznie(make_worker):
    browser = FakeBrowser(tokens=[{}, {"authorization": "t2"}], login_ok=True)
    w = make_worker(browser)
    wait_for(lambda: w.snapshot()["status"] == "ready")
    assert browser.logins == 1


def test_najwyzej_dwa_nieudane_logowania_potem_wymagane_logowanie(make_worker):
    alarms = []
    browser = FakeBrowser(tokens=[], login_ok=False)
    w = make_worker(browser, on_login_required=lambda: alarms.append(1))
    wait_for(lambda: w.snapshot()["status"] == "login_required")
    assert browser.logins == 2
    assert alarms == [1]


# --- opcje filtrów ---

def test_load_options_zwraca_future_z_opcjami(make_worker):
    browser = FakeBrowser(responses=[(200, {"specialties": [{"id": "16", "value": "Neurolog dorośli"}]})])
    w = make_worker(browser)
    opts = w.load_options("206", None, ["74640"]).result(timeout=3)
    assert opts.specialties == (NEUROLOG,)
    url, headers = browser.urls[0]
    assert "/filters?" in url and ("ClinicIds", "74640") in query(url)
    assert headers == {"authorization": "t1"}


def test_load_options_blad_api_trafia_do_future(make_worker):
    w = make_worker(FakeBrowser(responses=[(500, None)]))
    with pytest.raises(worker.ApiError):
        w.load_options("206").result(timeout=3)


# --- sprawdzanie ---

def test_sprawdzanie_zapisuje_terminy_w_zakresie_i_wola_on_check(make_worker):
    checks = []
    browser = FakeBrowser()
    browser.default_response = (200, {"items": [slot(28), slot(21), slot(20)]})
    w = make_worker(browser, on_check=lambda search, slots: checks.append(slots))
    w.start_search(SEARCH)
    wait_for(lambda: len(checks) >= 2)  # INTERVAL 0 s: kolejne sprawdzenia lecą od razu
    snap = w.snapshot()
    assert snap["status"] == "checking"
    assert snap["search"] == SEARCH
    assert snap["slots"] == [slot(20), slot(21)]  # bez 28., od najwcześniejszego
    assert checks[0] == [slot(20), slot(21)]
    assert isinstance(snap["last_check"], datetime)
    assert "/slots?" in browser.urls[0][0]


def test_stop_i_shutdown_dzialaja_od_razu_mimo_dlugiej_przerwy(make_worker, monkeypatch):
    monkeypatch.setattr(bot, "INTERVAL_MIN", 1000)
    monkeypatch.setattr(bot, "INTERVAL_MAX", 1000)
    checks = []
    browser = FakeBrowser()
    w = make_worker(browser, on_check=lambda search, slots: checks.append(slots))
    w.start_search(SEARCH)
    wait_for(lambda: len(checks) == 1)
    w.stop_search()
    wait_for(lambda: w.snapshot()["status"] == "ready")
    assert w.snapshot()["search"] is None
    t0 = time.monotonic()
    w.shutdown(timeout=3)
    assert not w.is_alive() and time.monotonic() - t0 < 1
    assert len(checks) == 1
    assert browser.calls[-1][0] == "close"


def test_po_401_ponawia_z_nowym_tokenem(make_worker):
    checks = []
    browser = FakeBrowser(tokens=[{"authorization": "t1"}, {"authorization": "t2"}],
                          responses=[(401, None), (200, {"items": [slot(20)]})])
    w = make_worker(browser, on_check=lambda search, slots: checks.append(slots))
    w.start_search(SEARCH)
    wait_for(lambda: checks)
    assert [h["authorization"] for _, h in browser.urls[:2]] == ["t1", "t2"]
    assert browser.logins == 0
    assert checks[0] == [slot(20)]


def test_wygasla_sesja_w_trakcie_wstrzymuje_sprawdzanie(make_worker):
    alarms = []
    browser = FakeBrowser(tokens=[{"authorization": "t1"}], login_ok=False)
    browser.default_response = (401, None)
    w = make_worker(browser, on_login_required=lambda: alarms.append(1))
    w.start_search(SEARCH)
    wait_for(lambda: w.snapshot()["status"] == "login_required")
    gets = len(browser.urls)
    time.sleep(0.2)
    assert len(browser.urls) == gets  # sprawdzanie wstrzymane
    assert browser.logins == 2
    assert alarms == [1]
    assert w.snapshot()["search"] == SEARCH  # wyszukiwanie zostaje do wznowienia (zgłoszenie 06)


def test_odswieza_token_po_token_refresh(make_worker, monkeypatch):
    monkeypatch.setattr(bot, "TOKEN_REFRESH", -1)
    checks = []
    browser = FakeBrowser(tokens=[{"authorization": f"t{i}"} for i in range(10)])
    w = make_worker(browser, on_check=lambda search, slots: checks.append(slots))
    w.start_search(SEARCH)
    wait_for(lambda: len(checks) >= 2)
    assert browser.urls[0][1] != browser.urls[1][1]


def test_przegladarka_tylko_w_watku_roboczym(make_worker):
    browser = FakeBrowser()
    w = make_worker(browser, on_check=lambda search, slots: None)
    w.load_options("206").result(timeout=3)
    w.start_search(SEARCH)
    wait_for(lambda: w.snapshot()["last_check"])
    w.shutdown(timeout=3)
    assert browser.calls and all(t is w for _, t in browser.calls)


def test_bufor_logu_ma_godziny_i_limit(make_worker):
    w = make_worker(FakeBrowser())
    wait_for(lambda: w.snapshot()["status"] == "ready")
    for i in range(300):
        bot.log(f"linia {i}")
    log = w.snapshot()["log"]
    assert len(log) == worker.LOG_LINES
    assert log[-1].endswith("linia 299") and log[-1].startswith("[")


def test_on_check_dostaje_wyszukiwanie_a_on_search_start_kazdy_start(make_worker):
    events = []
    browser = FakeBrowser()
    browser.default_response = (200, {"items": [slot(20)]})
    w = make_worker(browser, on_check=lambda search, slots: events.append(("check", search, slots)),
                    on_search_start=lambda search: events.append(("start", search)))
    w.start_search(SEARCH)
    wait_for(lambda: any(e[0] == "check" for e in events))
    w.stop_search()
    w.start_search(SEARCH)  # Stop i ponowny Start z tymi samymi filtrami to też nowy start
    wait_for(lambda: [e[0] for e in list(events)].count("start") == 2)
    assert events[0] == ("start", SEARCH)
    assert events[1] == ("check", SEARCH, [slot(20)])


# --- weryfikacja dwuetapowa i ręczne logowanie (zgłoszenie 06) ---

def test_weryfikacja_dwuetapowa_od_razu_wymagane_logowanie_bez_drugiej_proby(make_worker):
    alarms = []
    browser = FakeBrowser(tokens=[], two_factor=True)
    w = make_worker(browser, on_login_required=lambda: alarms.append(1))
    wait_for(lambda: w.snapshot()["status"] == "login_required")
    time.sleep(0.1)
    assert browser.logins == 1  # każda próba to mail z kodem, więc tylko jedna
    assert alarms == [1]


def test_opcje_przy_wymaganym_logowaniu_nie_dotykaja_przegladarki(make_worker):
    browser = FakeBrowser(tokens=[], two_factor=True)
    w = make_worker(browser)
    wait_for(lambda: w.snapshot()["status"] == "login_required")
    calls = len(browser.calls)
    with pytest.raises(worker.LoginRequired):
        w.load_options("206").result(timeout=3)
    assert len(browser.calls) == calls
    assert browser.logins == 1


def expire_session(make_worker, **kwargs):
    """Worker z aktywnym wyszukiwaniem, które wstrzymała wygasła sesja (2 nieudane auto-logowania)."""
    browser = FakeBrowser(tokens=[{"authorization": "t1"}], login_ok=False)
    browser.default_response = (401, None)
    w = make_worker(browser, **kwargs)
    w.start_search(SEARCH)
    wait_for(lambda: w.snapshot()["status"] == "login_required")
    return w, browser


def test_reczne_logowanie_wznawia_wstrzymane_wyszukiwanie(make_worker):
    events = []
    alarms = []
    w, browser = expire_session(
        make_worker,
        on_check=lambda search, slots: events.append(("check", slots)),
        on_search_start=lambda search: events.append(("start", search)),
        on_login_required=lambda: alarms.append(1),
    )
    w.manual_login()
    wait_for(lambda: w.snapshot()["status"] == "manual_login")
    assert browser.reopens == [False]
    assert any(name == "goto_app" for name, _ in browser.calls)

    # Użytkownik się loguje: karta opuszcza stronę logowania, token z widocznej i z headless.
    browser.tokens = [{"authorization": "widoczna"}, {"authorization": "t2"}]
    browser.default_response = (200, {"items": [slot(20)]})
    w.manual_login()  # drugie kliknięcie w trakcie czekania nic nie psuje
    browser.login_page = False
    wait_for(lambda: any(e[0] == "check" for e in list(events)))

    snap = w.snapshot()
    assert snap["status"] == "checking"
    assert snap["search"] == SEARCH
    assert browser.reopens == [False, True]  # z powrotem headless
    assert browser.urls[-1][1] == {"authorization": "t2"}
    assert [e[0] for e in events].count("start") == 1  # wznowienie to nie nowy start
    assert alarms == [1]
    assert w._login_failures == 0


def test_reczne_logowanie_bez_wyszukiwania_konczy_sie_gotowoscia(make_worker):
    browser = FakeBrowser(tokens=[], two_factor=True)
    w = make_worker(browser)
    wait_for(lambda: w.snapshot()["status"] == "login_required")
    browser.tokens = [{"authorization": "widoczna"}, {"authorization": "t2"}]
    browser.login_page = False
    w.manual_login()
    wait_for(lambda: w.snapshot()["status"] == "ready")
    assert browser.reopens == [False, True]
    assert browser.logins == 1  # ręczne logowanie nie woła auto-logowania


def test_reczne_logowanie_po_limicie_czasu_wraca_do_wymaganego_logowania(make_worker):
    alarms = []
    w, browser = expire_session(make_worker, manual_login_timeout=0.3,
                                on_login_required=lambda: alarms.append(1))
    w.manual_login()
    wait_for(lambda: w.snapshot()["status"] == "manual_login")
    wait_for(lambda: w.snapshot()["status"] == "login_required")
    assert browser.reopens == [False, True]
    assert w.snapshot()["search"] == SEARCH
    assert alarms == [1]  # bez drugiego alarmu
    assert any("Nie zalogowano" in line for line in w.snapshot()["log"])


def test_shutdown_w_trakcie_recznego_logowania(make_worker):
    w, browser = expire_session(make_worker)
    w.manual_login()
    wait_for(lambda: w.snapshot()["status"] == "manual_login")
    t0 = time.monotonic()
    w.shutdown(timeout=3)
    assert not w.is_alive() and time.monotonic() - t0 < 2
    assert browser.calls[-1][0] == "close"


def test_reczne_logowanie_pominiete_gdy_sesja_dziala(make_worker):
    browser = FakeBrowser()
    w = make_worker(browser)
    wait_for(lambda: w.snapshot()["status"] == "ready")
    w.manual_login()
    wait_for(lambda: any("pominięte" in line for line in w.snapshot()["log"]))
    assert browser.reopens == []
    assert w.snapshot()["status"] == "ready"
