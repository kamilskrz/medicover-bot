"""Wątek roboczy: jedyne miejsce, które korzysta z Playwrighta.

Synchroniczne API Playwrighta nie działa między wątkami, więc przeglądarka żyje w całości
w wątku `Worker`. Inne wątki (później serwer Flask) zlecają mu pracę przez kolejkę poleceń
(`load_options`, `start_search`, `stop_search`, `manual_login`, `shutdown`) i czytają stan
przez `snapshot()`.

Słownictwo: GLOSSARY.md. Kontekst: docs/adr/0001-*.md.
"""
from __future__ import annotations

import collections
import queue
import random
import threading
import time
from concurrent.futures import Future
from datetime import date, datetime
from typing import Callable, Iterable, Optional
from urllib.parse import urlencode

import bot
from search import FilterOptions, Search, Slot, in_range, parse_filter_options, parse_slots

API_BASE = "https://api-gateway-online24.medicover.pl/appointments/api/v2/search-appointments"
MAX_LOGIN_FAILURES = 2  # nieudane auto-logowania z rzędu, po których czekamy na człowieka
LOG_LINES = 200
MANUAL_LOGIN_TIMEOUT = 600  # s na ręczne zalogowanie w widocznej przeglądarce
MANUAL_LOGIN_POLL = 0.5  # s; co tyle sprawdzamy kolejkę i adres strony podczas ręcznego logowania
MANUAL_LOGIN_RETRY = 5  # s przerwy po nieudanym przechwyceniu tokenu poza stroną logowania

CONNECTING, READY, CHECKING, LOGIN_REQUIRED = "connecting", "ready", "checking", "login_required"
MANUAL_LOGIN = "manual_login"


class LoginRequired(Exception):
    """Nie da się uzyskać tokenu bez udziału człowieka."""


class ApiError(Exception):
    """API Medicover zwróciło błąd inny niż 401/403."""


class _Shutdown(Exception):
    """Polecenie shutdown przyszło w trakcie ręcznego logowania."""


def filters_url(region_id: Optional[str] = None, specialty_id: Optional[str] = None,
                clinic_ids: Iterable[str] = ()) -> str:
    """Adres `search-appointments/filters`; puste parametry są pomijane."""
    params = []
    if region_id:
        params.append(("RegionIds", region_id))
    if specialty_id:
        params.append(("SpecialtyIds", specialty_id))
    params += [("ClinicIds", c) for c in clinic_ids if c]
    params.append(("SlotSearchType", "Standard"))
    return f"{API_BASE}/filters?{urlencode(params)}"


def slots_url(search: Search, today: date) -> str:
    """Adres `search-appointments/slots` dla wyszukiwania (gotowy URL, bo `params`
    Playwrighta nie obsługują powtórzonych kluczy)."""
    return f"{API_BASE}/slots?{urlencode(search.slots_query(today))}"


class PlaywrightBrowser:
    """Persistent context Playwrighta w browser_profile/. Używać tylko z wątku `Worker`."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self._pw = None
        self._ctx = None
        self._page = None

    def open(self):
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._launch()

    def _launch(self):
        self._ctx = bot.launch(self._pw, headless=self.headless)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()

    def reopen(self, headless: bool):
        """Zamyka kontekst i otwiera nowy na tym samym profilu (widoczny albo headless)."""
        try:
            if self._ctx:
                self._ctx.close()
        except Exception:  # noqa: BLE001
            pass  # np. użytkownik sam zamknął okno przeglądarki
        self._ctx = self._page = None
        self.headless = headless
        self._launch()

    def goto_app(self):
        self._page.goto(bot.APP_URL, wait_until="domcontentloaded")

    def on_login_page(self) -> bool:
        """Czy karta jest na stronie logowania. Rzuca, gdy użytkownik zamknął okno."""
        if self._page.is_closed():
            raise RuntimeError("Okno przeglądarki zostało zamknięte.")
        return bot.on_login_page(self._page.url)

    def close(self):
        try:
            if self._ctx:
                self._ctx.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._pw = self._ctx = self._page = None

    def capture_token(self) -> dict:
        return bot.capture_headers(self._page)

    def login(self) -> bool:
        return bot.auto_login(self._page)

    def nudge(self):
        """Ruch myszką, żeby aplikacja nie uznała sesji za bezczynną."""
        self._page.mouse.move(random.randint(100, 800), random.randint(100, 600))

    def get(self, url: str, headers: dict):
        """GET z tokenem. Zwraca (status, json albo None, gdy odpowiedź nie jest ok)."""
        resp = self._ctx.request.get(url, headers=headers or None)
        return resp.status, (resp.json() if resp.ok else None)


class Worker(threading.Thread):
    def __init__(self, on_check: Optional[Callable[[Search, list], None]] = None,
                 on_login_required: Optional[Callable[[], None]] = None,
                 browser_factory: Callable[[], object] = PlaywrightBrowser,
                 on_search_start: Optional[Callable[[Search], None]] = None,
                 manual_login_timeout: float = MANUAL_LOGIN_TIMEOUT):
        super().__init__(name="playwright-worker", daemon=True)
        self._on_check = on_check
        self._on_search_start = on_search_start
        self._on_login_required = on_login_required
        self._browser_factory = browser_factory
        self._manual_login_timeout = manual_login_timeout
        self._browser = None
        self._commands: queue.Queue = queue.Queue()

        # Stan widoczny dla innych wątków - tylko pod self._lock.
        self._lock = threading.Lock()
        self._status = CONNECTING
        self._search: Optional[Search] = None
        self._slots: list = []
        self._last_check: Optional[datetime] = None
        self._log = collections.deque(maxlen=LOG_LINES)

        # Stan wewnętrzny wątku roboczego (tylko z run()).
        self._headers: dict = {}
        self._token_ts = 0.0
        self._login_failures = 0
        self._next_check = 0.0

    # --- interfejs dla innych wątków ---

    def load_options(self, region_id: Optional[str] = None, specialty_id: Optional[str] = None,
                     clinic_ids: Iterable[str] = ()) -> "Future[FilterOptions]":
        """Zleca pobranie opcji filtrów. Wynik (albo wyjątek) przychodzi w Future."""
        fut: Future = Future()
        self._commands.put(("options", (region_id, specialty_id, tuple(clinic_ids)), fut))
        return fut

    def start_search(self, search: Search):
        """Uruchamia sprawdzanie wyszukiwania (pierwsze sprawdzenie od razu)."""
        self._commands.put(("start", search, None))

    def stop_search(self):
        self._commands.put(("stop", None, None))

    def manual_login(self):
        """Otwiera widoczną przeglądarkę do ręcznego logowania (tylko w stanie `login_required`).
        Po zalogowaniu wątek wraca do headless i wznawia wstrzymane wyszukiwanie."""
        self._commands.put(("login", None, None))

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "status": self._status,
                "search": self._search,
                "slots": list(self._slots),
                "last_check": self._last_check,
                "log": list(self._log),
            }

    def shutdown(self, timeout: float = 30):
        """Zamyka przeglądarkę i kończy wątek."""
        self._commands.put(("shutdown", None, None))
        if self.is_alive() and threading.current_thread() is not self:
            self.join(timeout)

    # --- wątek roboczy ---

    def run(self):
        bot.log_hooks.append(self._append_log)
        try:
            self._browser = self._browser_factory()
            self._browser.open()
            self._connect()
            self._loop()
        except Exception as e:  # noqa: BLE001
            bot.log(f"Wątek roboczy przerwany błędem: {e}")
        finally:
            if self._browser is not None:
                try:
                    self._browser.close()
                except Exception as e:  # noqa: BLE001
                    bot.log(f"Błąd zamykania przeglądarki: {e}")
            self._fail_pending()
            bot.log("Wątek roboczy zakończony.")
            bot.log_hooks.remove(self._append_log)

    def _append_log(self, line: str):
        with self._lock:
            self._log.append(line)

    def _set(self, **fields):
        with self._lock:
            for k, v in fields.items():
                setattr(self, f"_{k}", v)

    def _connect(self):
        bot.log("Łączenie z Medicover...")
        if self._authenticate():
            self._set(status=READY)
            bot.log("Połączono z Medicover.")
        else:
            self._enter_login_required()

    def _loop(self):
        while True:
            timeout = None  # bez aktywnego wyszukiwania czekamy tylko na polecenia
            if self._search is not None and self._status == CHECKING:
                timeout = max(0.0, self._next_check - time.monotonic())
            try:
                kind, arg, fut = self._commands.get(timeout=timeout)
            except queue.Empty:
                self._check()
                self._next_check = time.monotonic() + random.randint(bot.INTERVAL_MIN, bot.INTERVAL_MAX)
                continue
            if not self._handle(kind, arg, fut):
                return

    def _handle(self, kind: str, arg, fut: Optional[Future]) -> bool:
        """Wykonuje polecenie z kolejki. Zwraca False, gdy wątek ma się zakończyć."""
        if kind == "shutdown":
            return False
        if kind == "options":
            self._load_options(arg, fut)
        elif kind == "start":
            self._begin_search(arg)
        elif kind == "stop":
            self._end_search()
        elif kind == "login":
            if self._status == MANUAL_LOGIN:
                bot.log("Ręczne logowanie już trwa - czekam na zalogowanie w przeglądarce.")
            elif self._status != LOGIN_REQUIRED:
                bot.log("Ręczne logowanie pominięte - bot ma działającą sesję.")
            else:
                return self._manual_login()
        return True

    def _fail_pending(self):
        while True:
            try:
                _, _, fut = self._commands.get_nowait()
            except queue.Empty:
                return
            if fut is not None and not fut.done():
                fut.set_exception(RuntimeError("Wątek roboczy został zatrzymany."))

    def _begin_search(self, search: Search):
        with self._lock:
            self._search = search
            self._slots = []
            self._last_check = None
            if self._status not in (LOGIN_REQUIRED, MANUAL_LOGIN):
                self._status = CHECKING
        self._next_check = time.monotonic()  # pierwsze sprawdzenie od razu
        bot.log(f"Start wyszukiwania: {search.specialty.name}, {search.region.name}.")
        if self._on_search_start:
            try:
                self._on_search_start(search)
            except Exception as e:  # noqa: BLE001
                bot.log(f"Błąd obsługi startu wyszukiwania: {e}")

    def _end_search(self):
        with self._lock:
            self._search = None
            if self._status == CHECKING:
                self._status = READY
        bot.log("Zatrzymano sprawdzanie.")

    def _load_options(self, args, fut: Future):
        if not fut.set_running_or_notify_cancel():
            return
        if self._status in (LOGIN_REQUIRED, MANUAL_LOGIN):
            # Bez sesji nie próbujemy: każde automatyczne logowanie może wysłać mail z kodem.
            fut.set_exception(LoginRequired())
            return
        try:
            data = self._get_json(filters_url(*args))
            fut.set_result(parse_filter_options(data))
        except LoginRequired as e:
            self._enter_login_required()
            fut.set_exception(e)
        except Exception as e:  # noqa: BLE001
            bot.log(f"Błąd pobierania opcji filtrów: {e}")
            fut.set_exception(e)

    def _check(self):
        search = self._search
        try:
            data = self._get_json(slots_url(search, date.today()))
            slots = sorted(in_range(parse_slots(data), search), key=lambda s: s.when)
        except LoginRequired:
            self._enter_login_required()
            return
        except Exception as e:  # noqa: BLE001
            bot.log(f"Błąd sprawdzania: {e}")
            return
        self._set(slots=slots, last_check=datetime.now())
        bot.log(f"Sprawdzenie: terminy w zakresie: {len(slots)}.")
        if self._on_check:
            try:
                self._on_check(search, slots)
            except Exception as e:  # noqa: BLE001
                bot.log(f"Błąd obsługi wyniku sprawdzenia: {e}")

    def _enter_login_required(self):
        if self._status == LOGIN_REQUIRED:
            return
        self._set(status=LOGIN_REQUIRED)
        bot.log("Wymagane logowanie - sprawdzanie wstrzymane.")
        if self._on_login_required:
            try:
                self._on_login_required()
            except Exception as e:  # noqa: BLE001
                bot.log(f"Błąd alarmu o logowaniu: {e}")

    def _manual_login(self) -> bool:
        """Widoczna przeglądarka na tym samym profilu; czeka, aż użytkownik się zaloguje.

        W trakcie czekania obsługuje kolejkę krótkimi krokami. Zwraca False, gdy przyszło
        polecenie shutdown (wątek ma się zakończyć), w przeciwnym razie True."""
        self._set(status=MANUAL_LOGIN)
        bot.log("Ręczne logowanie: otwieram okno przeglądarki. Zaloguj się, wpisz kod z maila "
                "i zaznacz „Dodaj do zaufanych urządzeń”.")
        logged_in = False
        try:
            self._browser.reopen(headless=False)
            self._browser.goto_app()
            logged_in = self._wait_for_manual_login()
        except _Shutdown:
            return False  # run() zamknie przeglądarkę
        except Exception as e:  # noqa: BLE001
            bot.log(f"Ręczne logowanie przerwane: {e}")
        self._browser.reopen(headless=True)  # błąd tutaj kończy wątek (run() go zaloguje)
        headers = self._browser.capture_token() if logged_in else {}
        if not headers:
            if logged_in:
                bot.log("Po ręcznym logowaniu nie udało się przechwycić tokenu w trybie headless.")
            # Bez ponownego alarmu: użytkownik właśnie próbował się zalogować.
            self._set(status=LOGIN_REQUIRED)
            bot.log("Wymagane logowanie - sprawdzanie wstrzymane.")
            return True
        self._headers, self._token_ts = headers, time.time()
        self._login_failures = 0
        if self._search is not None:
            # Wznowienie, a nie nowy start: bez on_search_start, więc pamięć alarmu zostaje.
            self._next_check = time.monotonic()
            self._set(status=CHECKING)
            bot.log("Zalogowano - wznawiam sprawdzanie.")
        else:
            self._set(status=READY)
            bot.log("Zalogowano - bot gotowy.")
        return True

    def _wait_for_manual_login(self) -> bool:
        """True, gdy karta opuściła stronę logowania i udało się przechwycić token;
        False po upływie limitu. Rzuca _Shutdown przy poleceniu shutdown."""
        deadline = time.monotonic() + self._manual_login_timeout
        next_try = 0.0
        while time.monotonic() < deadline:
            try:
                kind, arg, fut = self._commands.get(timeout=MANUAL_LOGIN_POLL)
            except queue.Empty:
                pass
            else:
                if not self._handle(kind, arg, fut):
                    raise _Shutdown()
            if time.monotonic() < next_try or self._browser.on_login_page():
                continue
            if self._browser.capture_token():
                return True
            next_try = time.monotonic() + MANUAL_LOGIN_RETRY
        bot.log(f"Nie zalogowano w ciągu {self._manual_login_timeout / 60:g} min - zamykam okno przeglądarki.")
        return False

    # --- token i API ---

    def _authenticate(self, force_login: bool = False) -> bool:
        """Przechwytuje token; w razie potrzeby loguje się automatycznie
        (najwyżej MAX_LOGIN_FAILURES nieudanych prób z rzędu)."""
        if not force_login:
            self._headers = self._browser.capture_token()
            self._token_ts = time.time()
            if self._headers:
                return True
        while self._login_failures < MAX_LOGIN_FAILURES:
            bot.log("Brak sesji - loguję się automatycznie...")
            try:
                ok = self._browser.login()
            except bot.TwoFactorRequired:
                # Profil nie jest zaufanym urządzeniem: kolejna próba to tylko kolejny mail z kodem.
                return False
            if ok:
                self._headers = self._browser.capture_token()
                self._token_ts = time.time()
                if self._headers:
                    self._login_failures = 0
                    return True
            self._login_failures += 1
            bot.log(f"Nieudane automatyczne logowanie ({self._login_failures}/{MAX_LOGIN_FAILURES}).")
        return False

    def _get_json(self, url: str) -> dict:
        """GET do API z tokenem; po 401/403 bierze nowy token, a potem loguje się ponownie."""
        if time.time() - self._token_ts > bot.TOKEN_REFRESH:
            self._headers = {}  # profilaktycznie odśwież sesję, zanim wygaśnie
        else:
            try:
                self._browser.nudge()
            except Exception:  # noqa: BLE001
                pass
        for attempt in range(3):
            # próba 0: bieżący token, 1: świeżo przechwycony, 2: po ponownym logowaniu
            if not self._headers and not self._authenticate(force_login=attempt == 2):
                raise LoginRequired()
            status, data = self._browser.get(url, self._headers)
            if status in (401, 403):
                self._headers = {}  # token wygasł - pobierz nowy i spróbuj raz jeszcze
                continue
            if not 200 <= status < 300:
                raise ApiError(f"API zwróciło {status}")
            self._login_failures = 0
            return data
        raise LoginRequired()
