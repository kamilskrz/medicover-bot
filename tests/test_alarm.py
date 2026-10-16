"""Testy alarmu z podmienionym `bot.alert` (bez maili, dźwięków i powiadomień)."""
from __future__ import annotations

from datetime import datetime

import pytest

import bot
from alarm import Alarm
from search import Option, Search, Slot

SZCZECIN = Option("206", "Szczecin")
NEUROLOG = Option("16", "Neurolog dorośli")
SEARCH = Search(region=SZCZECIN, specialty=NEUROLOG)


def slot(day, hour=15):
    return Slot(
        when=datetime(2026, 10, day, hour, 40),
        doctor=Option("1", "Jan Kowalski"),
        clinic=Option("2", "Centrum"),
        specialty=NEUROLOG,
    )


@pytest.fixture
def alerts(monkeypatch):
    sent = []
    monkeypatch.setattr(bot, "alert", lambda subject, body, **kw: sent.append((subject, body)))
    monkeypatch.setattr(bot, "APP_URL", "https://example.test/")
    return sent


@pytest.fixture
def alarm():
    a = Alarm()
    a.reset(SEARCH)
    return a


def test_brak_terminow_brak_alarmu(alarm, alerts):
    alarm.on_check(SEARCH, [])
    alarm.on_check(SEARCH, [])
    assert alerts == []


def test_pierwsze_terminy_wlaczaja_alarm(alarm, alerts):
    alarm.on_check(SEARCH, [slot(21), slot(20)])
    assert len(alerts) == 1
    subject, body = alerts[0]
    assert subject == "Nowe terminy: Neurolog dorośli, Szczecin (2)"
    new_part, all_part = body.split("Wszystkie aktualne terminy:")
    assert "2026-10-20 15:40  Jan Kowalski  Centrum" in new_part
    assert "2026-10-21 15:40" in new_part
    assert "2026-10-20 15:40" in all_part
    assert body.rstrip().endswith("https://example.test/")


def test_temat_z_aktywnego_wyszukiwania(alerts):
    kardiolog = Search(region=Option("1", "Warszawa"), specialty=Option("9", "Kardiolog"))
    a = Alarm()
    a.reset(kardiolog)
    a.on_check(kardiolog, [slot(20)])
    assert alerts[0][0] == "Nowe terminy: Kardiolog, Warszawa (1)"
    assert "eurolog" not in alerts[0][0]


def test_te_same_terminy_brak_alarmu(alarm, alerts):
    alarm.on_check(SEARCH, [slot(20)])
    alarm.on_check(SEARCH, [slot(20)])
    alarm.on_check(SEARCH, [slot(20)])
    assert len(alerts) == 1


def test_jeden_nowy_termin_tylko_on_w_sekcji_nowych(alarm, alerts):
    alarm.on_check(SEARCH, [slot(20)])
    alarm.on_check(SEARCH, [slot(20), slot(22)])
    assert len(alerts) == 2
    subject, body = alerts[1]
    assert subject.endswith("(1)")
    new_part, all_part = body.split("Wszystkie aktualne terminy:")
    assert "2026-10-22 15:40" in new_part and "2026-10-20" not in new_part
    assert "2026-10-20 15:40" in all_part and "2026-10-22 15:40" in all_part


def test_znikniecie_i_powrot_terminu_wlacza_alarm(alarm, alerts):
    alarm.on_check(SEARCH, [slot(20), slot(21)])
    alarm.on_check(SEARCH, [slot(21)])
    assert len(alerts) == 1  # samo zniknięcie nie alarmuje
    alarm.on_check(SEARCH, [slot(20), slot(21)])
    assert len(alerts) == 2
    assert alerts[1][0].endswith("(1)")


def test_reset_po_nowym_wyszukiwaniu(alarm, alerts):
    alarm.on_check(SEARCH, [slot(20)])
    alarm.reset(SEARCH)  # Stop i ponowny Start z tymi samymi filtrami
    alarm.on_check(SEARCH, [slot(20)])
    assert len(alerts) == 2


def test_inne_wyszukiwanie_bez_sygnalu_startu_tez_zeruje_pamiec(alarm, alerts):
    alarm.on_check(SEARCH, [slot(20)])
    other = Search(region=SZCZECIN, specialty=Option("9", "Kardiolog"))
    alarm.on_check(other, [slot(20)])
    assert len(alerts) == 2


def test_make_worker_podpina_alarm():
    import worker

    w = bot.make_worker()
    assert isinstance(w, worker.Worker)
    assert isinstance(w._on_check.__self__, Alarm)
    assert w._on_search_start.__self__ is w._on_check.__self__
