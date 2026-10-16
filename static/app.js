// Okno wyboru wyszukiwania. Czysty JS, bez bibliotek.
// Kaskada: Miasto -> Specjalizacja -> Placówki -> Lekarze, plus zakres dat.
// Stan bota czytamy z /api/state co ~2 s; listy opcji z /api/options (zob. app.py).
"use strict";

const POLL_MS = 2000;
const REGIONS_RETRY_MS = 15000;

const STATUS_TEXT = {
  connecting: "Łączenie z Medicover…",
  ready: "Gotowy",
  checking: "Sprawdzam…",
  login_required: "Wymagane logowanie",
  manual_login: "Czekam na zalogowanie w przeglądarce…",
};

const $ = (id) => document.getElementById(id);

// --- komunikacja z serwerem ---

async function api(path, options) {
  const resp = await fetch(path, options);
  let data = null;
  try {
    data = await resp.json();
  } catch (e) {
    // odpowiedź bez JSON-a, np. serwer zamknięty
  }
  if (!resp.ok) throw new Error((data && data.error) || `Błąd serwera (${resp.status})`);
  return data;
}

function fetchOptions(regionId, specialtyId, clinicIds) {
  const params = new URLSearchParams();
  if (regionId) params.append("region_id", regionId);
  if (specialtyId) params.append("specialty_id", specialtyId);
  for (const id of clinicIds || []) params.append("clinic_id", id);
  return api("/api/options?" + params.toString());
}

function post(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

// --- lista z filtrem tekstowym (jedna albo wiele pozycji) ---

function normalize(text) {
  return text.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l");
}

class Picker {
  constructor(id, multi, onChange) {
    this.el = $(id);
    this.multi = multi;
    this.onChange = onChange;
    this.items = [];
    this.selected = new Map(); // id -> {id, name}
    this.message = "";
    this.disabled = false;
    this.filter = this.el.querySelector(".filter");
    this.list = this.el.querySelector(".list");
    this.summary = this.el.querySelector(".summary");
    this.filter.addEventListener("input", () => this.render());
    this.list.addEventListener("change", (e) => this.toggle(e.target));
  }

  setItems(items, message) {
    this.items = items || [];
    this.message = message || "";
    this.render();
  }

  setSelected(options) {
    this.selected = new Map((options || []).map((o) => [o.id, o]));
    this.render();
  }

  values() {
    return [...this.selected.values()];
  }

  value() {
    return this.values()[0] || null;
  }

  setDisabled(disabled) {
    if (this.disabled === disabled) return;
    this.disabled = disabled;
    this.filter.disabled = disabled;
    this.el.classList.toggle("disabled", disabled);
    this.render();
  }

  toggle(input) {
    if (this.disabled) return;
    const item = this.items.find((o) => o.id === input.value);
    if (!item) return;
    if (!this.multi) this.selected = new Map([[item.id, item]]);
    else if (input.checked) this.selected.set(item.id, item);
    else this.selected.delete(item.id);
    this.renderSummary();
    this.onChange();
  }

  render() {
    const query = normalize(this.filter.value.trim());
    const shown = query ? this.items.filter((o) => normalize(o.name).includes(query)) : this.items;
    this.list.replaceChildren();
    if (!shown.length) {
      const p = document.createElement("div");
      p.className = "empty";
      p.textContent = this.message || (this.items.length ? "Brak pasujących pozycji" : "Brak pozycji");
      this.list.append(p);
    }
    for (const o of shown) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = this.multi ? "checkbox" : "radio";
      input.name = this.el.id;
      input.value = o.id;
      input.checked = this.selected.has(o.id);
      input.disabled = this.disabled;
      const span = document.createElement("span");
      span.textContent = o.name;
      label.append(input, span);
      this.list.append(label);
    }
    this.renderSummary();
  }

  renderSummary() {
    const names = this.values().map((o) => o.name);
    this.summary.textContent = names.length ? "Wybrano: " + names.join(", ") : "";
  }
}

// --- formularz i kaskada ---

const region = new Picker("pick-region", false, onRegionChange);
const specialty = new Picker("pick-specialty", false, onSpecialtyChange);
const clinics = new Picker("pick-clinics", true, onClinicsChange);
const doctors = new Picker("pick-doctors", true, updateButtons);
const pickers = [region, specialty, clinics, doctors];

let formSeq = 0; // każda zmiana kaskady unieważnia odpowiedzi na wcześniejsze zapytania
let status = null;
let locked = null; // aktywne wyszukiwanie pokazane w zablokowanym formularzu
let regionsLoaded = false;
let regionsTried = 0;
let regionsLoading = false;
let savedChecked = false;

function showMessages(id, lines) {
  const box = $(id);
  box.replaceChildren(...lines.map((line) => Object.assign(document.createElement("p"), { textContent: line })));
  box.hidden = !lines.length;
}

const showError = (text) => showMessages("error", text ? [text] : []);
const showWarnings = (lines) => showMessages("warnings", lines || []);

// Pozycje z `available` (z aktualnymi nazwami), które były w `selected`.
const keep = (selected, available) => available.filter((a) => selected.some((o) => o.id === a.id));
const missing = (selected, kept) => selected.filter((o) => !kept.some((k) => k.id === o.id));

function resetBelowRegion() {
  specialty.setSelected([]);
  specialty.setItems([], "Najpierw wybierz miasto");
  resetBelowSpecialty();
}

function resetBelowSpecialty() {
  clinics.setSelected([]);
  clinics.setItems([], "Najpierw wybierz specjalizację");
  doctors.setSelected([]);
  doctors.setItems([], "Najpierw wybierz specjalizację");
}

async function onRegionChange() {
  const seq = ++formSeq;
  resetBelowRegion();
  specialty.setItems([], "Ładowanie…");
  showError("");
  updateButtons();
  try {
    const o = await fetchOptions(region.value().id);
    if (seq !== formSeq) return;
    specialty.setItems(o.specialties, "Brak specjalizacji w tym mieście");
  } catch (e) {
    if (seq !== formSeq) return;
    specialty.setItems([], "Nie udało się pobrać listy");
    showError(e.message);
  }
}

async function onSpecialtyChange() {
  const seq = ++formSeq;
  resetBelowSpecialty();
  clinics.setItems([], "Ładowanie…");
  doctors.setItems([], "Ładowanie…");
  showError("");
  updateButtons();
  try {
    const o = await fetchOptions(region.value().id, specialty.value().id);
    if (seq !== formSeq) return;
    clinics.setItems(o.clinics, "Brak placówek");
    doctors.setItems(o.doctors, "Brak lekarzy");
  } catch (e) {
    if (seq !== formSeq) return;
    clinics.setItems([], "Nie udało się pobrać listy");
    doctors.setItems([], "Nie udało się pobrać listy");
    showError(e.message);
  }
}

async function onClinicsChange() {
  // Wybrane placówki zawężają listę lekarzy; lekarze spoza niej wypadają z wyboru.
  const seq = ++formSeq;
  doctors.setItems(doctors.items, "Ładowanie…");
  showError("");
  updateButtons();
  try {
    const o = await fetchOptions(region.value().id, specialty.value().id, clinics.values().map((c) => c.id));
    if (seq !== formSeq) return;
    const before = doctors.values();
    const kept = keep(before, o.doctors);
    doctors.setItems(o.doctors, "Brak lekarzy w wybranych placówkach");
    doctors.setSelected(kept);
    showWarnings(
      missing(before, kept).map((d) => `Lekarz ${d.name} nie przyjmuje w wybranych placówkach – usunięto z wyboru`)
    );
    updateButtons();
  } catch (e) {
    if (seq !== formSeq) return;
    showError(e.message);
  }
}

async function loadRegions() {
  regionsTried = Date.now();
  regionsLoading = true;
  const seq = formSeq;
  try {
    const o = await fetchOptions();
    if (seq !== formSeq || locked) return;
    region.setItems(o.regions, "Brak miast");
    regionsLoaded = true;
    showError("");
    if (!savedChecked) await loadSavedSearch();
  } catch (e) {
    if (seq !== formSeq) return;
    region.setItems([], "Nie udało się pobrać listy miast");
    showError(e.message);
  } finally {
    regionsLoading = false;
  }
}

// Zapamiętane wyszukiwanie (last_search.json) przywrócone przez serwer względem aktualnych list,
// z ostrzeżeniami o pozycjach, które wypadły. Tylko wypełnia formularz: Start naciska użytkownik.
// Aktywne wyszukiwanie (zablokowany formularz) i wybór użytkownika mają pierwszeństwo.
async function loadSavedSearch() {
  savedChecked = true;
  let saved;
  try {
    saved = await api("/api/saved-search");
  } catch (e) {
    return; // brak zapamiętanego wyszukiwania nie jest błędem okna
  }
  if (locked || region.value()) return;
  const warnings = saved.warnings || [];
  if (saved.search) await applySearch(saved.search, warnings);
  else showWarnings(warnings);
}

// Ustawia formularz na wyszukiwanie: ładuje kolejne poziomy kaskady i zaznacza to, co nadal
// jest na listach. Używane po Stop (odblokowanie filtrów) i do wstępnego wypełnienia
// zapamiętanym wyszukiwaniem; `extraWarnings` to ostrzeżenia z przywracania po stronie serwera.
async function applySearch(s, extraWarnings) {
  const seq = ++formSeq;
  const warnings = [...(extraWarnings || [])];
  showError("");
  try {
    const top = await fetchOptions();
    if (seq !== formSeq) return;
    region.setItems(top.regions, "Brak miast");
    regionsLoaded = true;
    const r = top.regions.find((o) => o.id === s.region.id);
    region.setSelected(r ? [r] : []);
    resetBelowRegion();
    if (!r) {
      warnings.push(`Miasto ${s.region.name} nie jest już dostępne – usunięto z filtrów`);
      return;
    }

    const forRegion = await fetchOptions(r.id);
    if (seq !== formSeq) return;
    specialty.setItems(forRegion.specialties, "Brak specjalizacji w tym mieście");
    const sp = forRegion.specialties.find((o) => o.id === s.specialty.id);
    if (!sp) {
      warnings.push(`Specjalizacja ${s.specialty.name} nie jest już dostępna – usunięto z filtrów`);
      return;
    }
    specialty.setSelected([sp]);

    const forSpecialty = await fetchOptions(r.id, sp.id);
    if (seq !== formSeq) return;
    clinics.setItems(forSpecialty.clinics, "Brak placówek");
    const keptClinics = keep(s.clinics, forSpecialty.clinics);
    clinics.setSelected(keptClinics);
    let doctorOptions = forSpecialty.doctors;
    if (keptClinics.length) {
      doctorOptions = (await fetchOptions(r.id, sp.id, keptClinics.map((c) => c.id))).doctors;
      if (seq !== formSeq) return;
    }
    doctors.setItems(doctorOptions, "Brak lekarzy");
    const keptDoctors = keep(s.doctors, doctorOptions);
    doctors.setSelected(keptDoctors);

    for (const c of missing(s.clinics, keptClinics)) warnings.push(`Placówka ${c.name} nie jest już dostępna – usunięto z filtrów`);
    for (const d of missing(s.doctors, keptDoctors)) warnings.push(`Lekarz ${d.name} nie jest już dostępny – usunięto z filtrów`);
  } catch (e) {
    if (seq !== formSeq) return;
    regionsLoaded = false; // spróbujemy pobrać miasta ponownie przy kolejnym odpytaniu stanu
    showError(e.message);
  } finally {
    if (seq === formSeq) {
      $("date-from").value = s.date_from || "";
      $("date-to").value = s.date_to || "";
      showWarnings(warnings);
      updateButtons();
    }
  }
}

// Zablokowany formularz pokazuje tylko wartości aktywnego wyszukiwania.
function showLocked(s) {
  formSeq++; // odpowiedzi na wcześniejsze zapytania nie nadpiszą zablokowanego widoku
  const items = [[region, [s.region]], [specialty, [s.specialty]], [clinics, s.clinics], [doctors, s.doctors]];
  for (const [picker, values] of items) {
    picker.setItems(values, picker.multi ? "Dowolne" : "");
    picker.setSelected(values);
  }
  $("date-from").value = s.date_from || "";
  $("date-to").value = s.date_to || "";
}

function setLocked(isLocked) {
  for (const p of pickers) p.setDisabled(isLocked);
  $("date-from").disabled = isLocked;
  $("date-to").disabled = isLocked;
}

function updateButtons() {
  $("start").disabled = !!locked || status !== "ready" || !region.value() || !specialty.value();
  $("stop").disabled = !locked;
}

$("start").addEventListener("click", async () => {
  const body = {
    region: region.value(),
    specialty: specialty.value(),
    clinics: clinics.values(),
    doctors: doctors.values(),
    date_from: $("date-from").value || null,
    date_to: $("date-to").value || null,
  };
  if (body.date_from && body.date_to && body.date_from > body.date_to) {
    showError("Data „od” jest późniejsza niż data „do”.");
    return;
  }
  $("start").disabled = true;
  try {
    await post("/api/start", body);
    showError("");
    showWarnings([]);
  } catch (e) {
    showError(e.message);
  }
  refresh();
});

$("stop").addEventListener("click", async () => {
  $("stop").disabled = true;
  try {
    await post("/api/stop");
  } catch (e) {
    showError(e.message);
  }
  refresh();
});

// --- stan bota ---

function renderStatus(st) {
  let text = STATUS_TEXT[st.status] || st.status;
  if (st.status === "checking") {
    text += st.last_check ? ` (ostatnie sprawdzenie: ${st.last_check.slice(11, 19)})` : " (pierwsze sprawdzenie w toku)";
  }
  if ((st.status === "login_required" || st.status === "manual_login") && st.search) {
    text += " – sprawdzanie wstrzymane";
  }
  $("status-text").textContent = text;
  $("status-dot").className = "dot " + st.status;
  const needsLogin = st.status === "login_required";
  if (needsLogin && $("login-slot").hidden) $("manual-login").disabled = false;
  $("login-slot").hidden = !needsLogin;
}

$("manual-login").addEventListener("click", async () => {
  $("manual-login").disabled = true; // do następnego pokazania przycisku
  try {
    await post("/api/login");
    showError("");
  } catch (e) {
    showError(e.message);
    $("manual-login").disabled = false;
  }
  refresh();
});

function renderSlots(st) {
  const body = $("slots");
  body.replaceChildren();
  if (!st.slots.length) {
    let text = "Brak terminów w zakresie";
    if (!st.search) text = "Brak aktywnego wyszukiwania";
    else if (!st.last_check) text = "Czekam na pierwsze sprawdzenie…";
    const tr = document.createElement("tr");
    tr.append(Object.assign(document.createElement("td"), { colSpan: 4, className: "empty", textContent: text }));
    body.append(tr);
    return;
  }
  for (const s of st.slots) {
    const tr = document.createElement("tr");
    for (const value of [s.date, s.time, s.doctor, s.clinic]) {
      tr.append(Object.assign(document.createElement("td"), { textContent: value }));
    }
    body.append(tr);
  }
}

function renderLog(st) {
  const box = $("log");
  const text = st.log.join("\n");
  if (box.textContent === text) return;
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 30;
  box.textContent = text;
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function render(st) {
  status = st.status;
  renderStatus(st);
  renderSlots(st);
  renderLog(st);

  if (st.search) {
    // Aktywne wyszukiwanie (także wstrzymane przez wymagane logowanie): filtry zablokowane.
    if (!locked || JSON.stringify(locked) !== JSON.stringify(st.search)) showLocked(st.search);
    locked = st.search;
    setLocked(true);
  } else if (locked) {
    const previous = locked;
    locked = null;
    setLocked(false);
    applySearch(previous); // przywróć pełne listy, zostawiając wybór z zakończonego wyszukiwania
  } else if (!regionsLoaded && !regionsLoading && (status === "ready" || status === "checking") && Date.now() - regionsTried > REGIONS_RETRY_MS) {
    loadRegions();
  }
  updateButtons();
}

let pollTimer = null;

async function refresh() {
  clearTimeout(pollTimer);
  try {
    render(await api("/api/state"));
  } catch (e) {
    $("status-text").textContent = "Brak połączenia z botem (czy python bot.py nadal działa?)";
    $("status-dot").className = "dot offline";
    status = null;
    updateButtons();
  }
  pollTimer = setTimeout(refresh, POLL_MS);
}

region.setItems([], "Czekam na połączenie z Medicover…");
resetBelowRegion();
refresh();
