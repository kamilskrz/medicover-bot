#!/usr/bin/env python3
"""Medicover appointment watcher.

Tryby:
  python bot.py         - otwiera okno wyboru wyszukiwania (app.py: Flask na 127.0.0.1 i wątek roboczy)
  python bot.py setup   - otwiera przeglądarkę, logujesz się ręcznie i zapisujesz zaufane urządzenie
  python bot.py sniff   - zapisuje zapytania aplikacji Medicover do sniff.log (diagnostyka)
"""
import os
import smtplib
import subprocess
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

BASE = Path(__file__).parent
load_dotenv(BASE / ".env")

PROFILE_DIR = BASE / "browser_profile"
LOGIN_URL_MARKERS = [m.strip() for m in os.getenv("LOGIN_URL_MARKERS", "login,logon,signin,signout,session-expired").split(",")]
APP_URL = os.getenv("APP_URL", "https://online24.medicover.pl/")
MEDICOVER_USER = os.getenv("MEDICOVER_USER", "")
MEDICOVER_PASSWORD = os.getenv("MEDICOVER_PASSWORD", "")
TOKEN_REFRESH = int(os.getenv("TOKEN_REFRESH", "120"))  # co ile s odświeżać sesję/token
INTERVAL_MIN = int(os.getenv("INTERVAL_MIN", "45"))
INTERVAL_MAX = int(os.getenv("INTERVAL_MAX", "90"))

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
MAIL_TO = os.getenv("MAIL_TO", SMTP_USER)

TWO_FACTOR_TEXT = "Weryfikacja dwuetapowa"  # nagłówek ekranu z kodem wysłanym e-mailem
LOGIN_WAIT = 30  # s na opuszczenie strony logowania po kliknięciu „Zaloguj”

# Funkcje dostające każdą linię logu (np. bufor logu w worker.py).
log_hooks = []


def log(msg):
    line = f"[{datetime.now():%H:%M:%S}] {msg}"
    print(line, flush=True)
    for hook in list(log_hooks):
        hook(line)


def play_sound(times=5):
    for _ in range(times):
        subprocess.run(["afplay", "/System/Library/Sounds/Glass.aiff"], check=False)


def mac_notify(title, text):
    script = f'display notification "{text}" with title "{title}" sound name "Glass"'
    subprocess.run(["osascript", "-e", script], check=False)


def send_mail(subject, body):
    if not (SMTP_USER and SMTP_PASSWORD):
        return
    msg = EmailMessage()
    recipients = [a.strip() for a in MAIL_TO.split(",") if a.strip()]
    msg["From"], msg["To"], msg["Subject"] = SMTP_USER, ", ".join(recipients), subject
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        log("Wysłano maila.")
    except Exception as e:  # noqa: BLE001
        log(f"Nie udało się wysłać maila: {e}")


def alert(subject, body, sound=True):
    log(subject)
    mac_notify("Medicover bot", subject)
    send_mail(subject, body)
    if sound:
        play_sound()


class TwoFactorRequired(Exception):
    """Po kliknięciu „Zaloguj” Medicover pokazał ekran weryfikacji dwuetapowej (kod w mailu).
    Nie ponawiamy: każda próba wysyła użytkownikowi kolejny mail z kodem."""


def on_login_page(url):
    """Czy adres należy do stron logowania (LOGIN_URL_MARKERS)."""
    return any(m and m in url.lower() for m in LOGIN_URL_MARKERS)


def capture_headers(page):
    """Ładuje aplikację i podsłuchuje nagłówki (token) jej własnych zapytań do API."""
    got = {}

    def on_request(req):
        if "api-gateway-online24.medicover.pl" in req.url and "authorization" in req.headers:
            got.update(
                {k: v for k, v in req.headers.items() if k == "authorization" or k.startswith("x-")}
            )

    page.on("request", on_request)
    try:
        page.goto(APP_URL, wait_until="domcontentloaded")
        for _ in range(40):
            if got or on_login_page(page.url):
                break
            page.wait_for_timeout(500)
    finally:
        page.remove_listener("request", on_request)
    return got


def auto_login(page):
    """Loguje się danymi z .env. Zwraca True, jeśli po logowaniu jesteśmy poza stroną logowania.

    Rzuca TwoFactorRequired, gdy zamiast aplikacji pojawi się ekran weryfikacji dwuetapowej:
    wtedy profil nie jest zaufanym urządzeniem i potrzebny jest człowiek (ręczne logowanie)."""
    if not (MEDICOVER_USER and MEDICOVER_PASSWORD):
        return False
    try:
        page.goto(APP_URL, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("#usernameInput", timeout=10000)
        except PWTimeout:
            # brak formularza: albo już jesteśmy zalogowani, albo strona jest w innym stanie
            return not on_login_page(page.url)
        page.fill("#usernameInput", MEDICOVER_USER)
        page.fill("#passwordInput", MEDICOVER_PASSWORD)
        terms = page.locator("#acceptTerms")
        if terms.count() and terms.is_visible() and not terms.is_checked():
            terms.check()
        page.click("#login-button")
        # Czekamy na jedno z dwóch: wyjście ze stron logowania albo ekran weryfikacji dwuetapowej.
        deadline = time.monotonic() + LOGIN_WAIT
        while time.monotonic() < deadline:
            if not on_login_page(page.url):
                page.wait_for_timeout(2000)
                return True
            if page.get_by_text(TWO_FACTOR_TEXT).first.is_visible():
                log("Medicover wymaga weryfikacji dwuetapowej (kod wysłany e-mailem) - przerywam automatyczne logowanie.")
                raise TwoFactorRequired()
            page.wait_for_timeout(500)
        log(f"Automatyczne logowanie nie powiodło się: po {LOGIN_WAIT} s nadal strona logowania.")
        return False
    except TwoFactorRequired:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"Automatyczne logowanie nie powiodło się: {e}")
        return False


def desktop_user_agent(p):
    """UA zwykłego Chrome w wersji dołączonego Chromium. Z „HeadlessChrome” aplikacja Medicover nie startuje."""
    out = subprocess.run([p.chromium.executable_path, "--version"], capture_output=True, text=True).stdout
    version = out.strip().split()[-1] if out.strip() else "148.0.0.0"
    return (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        f"(KHTML, like Gecko) Chrome/{version} Safari/537.36"
    )


def launch(p, headless=True):
    extra = {"user_agent": desktop_user_agent(p)} if headless else {}
    return p.chromium.launch_persistent_context(
        str(PROFILE_DIR), headless=headless, viewport={"width": 1280, "height": 900}, **extra
    )


def setup():
    with sync_playwright() as p:
        ctx = launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://mol.medicover.pl")
        print(
            "\n1. Zaloguj się do Medicover i zaznacz „Dodaj do zaufanych urządzeń”.\n"
            "2. Gdy zobaczysz stronę główną aplikacji, wróć tu i naciśnij Enter, żeby zapisać sesję.\n"
        )
        input("Enter, gdy skończysz... ")
        ctx.close()


def sniff():
    """Zapisuje zapytania XHR/fetch do sniff.log (bez nagłówków z tokenami/ciasteczkami)."""
    out = open(BASE / "sniff.log", "w", encoding="utf-8")

    def on_response(resp):
        req = resp.request
        if req.resource_type not in ("xhr", "fetch"):
            return
        try:
            body = resp.text()[:600].replace("\n", " ")
        except Exception:  # noqa: BLE001
            body = "<brak treści>"
        out.write(
            f"{req.method} {req.url}\n  status: {resp.status}\n"
            f"  post_data: {(req.post_data or '')[:600]}\n  response: {body}\n\n"
        )
        out.flush()

    with sync_playwright() as p:
        ctx = launch(p, headless=False)
        ctx.on("response", on_response)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto("https://mol.medicover.pl")
        print(
            "\nZaloguj się, wejdź w wyszukiwanie, ustaw filtr lekarza i kliknij 'Szukaj'.\n"
            "Gdy zobaczysz wyniki (lub brak terminów), wróć tu i naciśnij Enter.\n"
        )
        input("Enter, gdy skończysz... ")
        ctx.close()
    out.close()
    print("Zapisano sniff.log")


def make_worker():
    """Wątek roboczy z podpiętymi reakcjami (alarm, wygaśnięcie sesji). Jedyne miejsce, gdzie powstaje Worker."""
    from alarm import Alarm  # importy tutaj, bo worker.py i alarm.py importują bot.py
    from worker import Worker

    alarm = Alarm()
    return Worker(
        on_check=alarm.on_check,
        on_search_start=alarm.reset,
        on_login_required=lambda: alert(
            "Sesja Medicover wygasła - kliknij «Zaloguj ręcznie» w oknie bota.", APP_URL, sound=False
        )
    )


if __name__ == "__main__":
    # Uruchamiamy funkcje z modułu `bot`, a nie z `__main__`: worker.py importuje `bot`,
    # więc inaczej istniałyby dwie kopie konfiguracji i log_hooks.
    import app
    import bot

    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    modes = {"setup": bot.setup, "sniff": bot.sniff, "": app.main}
    if mode not in modes:
        sys.exit("Użycie: python bot.py [setup|sniff]")
    modes[mode]()
