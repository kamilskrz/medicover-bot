#!/usr/bin/env python3
"""Spike 01: skąd lista specjalizacji i jak wyglądają terminy w API.

Uruchom z katalogu projektu:  .venv/bin/python .scratch/okno-wyszukiwania/spike.py [REGION_ID]
Wynik: .scratch/okno-wyszukiwania/spike-output.json (bez nagłówków i tokenów).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import bot  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

API = "https://api-gateway-online24.medicover.pl"
REGION = sys.argv[1] if len(sys.argv) > 1 else "206"
NEURO_KEYWORD = "32083ffe-12b3-440f-e744-08deba536788"  # „Neurologia” z sniff.log
OUT = Path(__file__).with_name("spike-output.json")


def main():
    result = {"region": REGION}
    with sync_playwright() as p:
        ctx = bot.launch(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        headers = bot.capture_headers(page)
        if not headers:
            print("Brak tokenu - loguję się...")
            bot.auto_login(page)
            headers = bot.capture_headers(page)
        if not headers:
            sys.exit("Nie udało się zdobyć tokenu. Zaloguj się ręcznie (python bot.py setup) i spróbuj ponownie.")

        def get(path, **params):
            nonlocal headers
            for attempt in (1, 2):
                time.sleep(1.5)  # nie zasypujemy API
                resp = ctx.request.get(f"{API}{path}", params=params, headers=headers)
                print(f"{resp.status} {path} {params}")
                if resp.status != 401 or attempt == 2:
                    break
                print("401 - loguję się ponownie i przechwytuję świeży token...")
                bot.auto_login(page)
                headers = bot.capture_headers(page) or headers
            return resp.status, (resp.json() if resp.ok else resp.text()[:500])

        # Q1: filters bez SpecialtyIds
        status, data = get("/appointments/api/v2/search-appointments/filters",
                           RegionIds=REGION, SlotSearchType="Standard")
        specialties = data.get("specialties", []) if isinstance(data, dict) else []
        result["q1_filters_without_specialty"] = {
            "status": status,
            "specialties_count": len(specialties),
            "specialties_sample": specialties[:40],
            "keys": list(data.keys()) if isinstance(data, dict) else data,
        }

        # Q2: słowa kluczowe + drzewo ankiety
        status, data = get("/service-selector-configurator-os/api/v2/keywords", regionId=REGION)
        groups = data.get("groups", []) if isinstance(data, dict) else []
        result["q2_keywords"] = {
            "status": status,
            "groups": [{"type": g.get("type"), "name": g.get("name"), "count": len(g.get("keywords", []))}
                       for g in groups],
            "sample": [k for g in groups for k in g.get("keywords", [])][:10],
        }
        status, tree = get(f"/service-selector-configurator-os/api/v2/keywords/{NEURO_KEYWORD}/triage/flat",
                           regionId=REGION)
        if isinstance(tree, list):
            result["q2_triage_neurologia"] = {
                "status": status,
                "selection_types": sorted({n.get("selectionType") for n in tree}),
                "node_keys": sorted({k for n in tree for k in n}),
                "nodes": tree,  # małe drzewo, zapisujemy całe
            }
        else:
            result["q2_triage_neurologia"] = {"status": status, "body": tree}

        # Q3: struktura terminu - szukamy specjalizacji, która ma jakiekolwiek terminy
        today = time.strftime("%Y-%m-%d")
        candidates = [s["id"] for s in specialties][:12] or ["16"]
        result["q3_slots"] = {"tried": []}
        for sid in candidates:
            status, data = get("/appointments/api/v2/search-appointments/slots",
                               RegionIds=REGION, SpecialtyIds=sid, SlotSearchType="Standard",
                               Page="1", PageSize="5", StartTime=today,
                               isOverbookingSearchDisabled="false")
            count = data.get("count") if isinstance(data, dict) else None
            result["q3_slots"]["tried"].append({"specialty": sid, "status": status, "count": count})
            if count:
                result["q3_slots"]["sample_items"] = data.get("items", [])[:3]
                result["q3_slots"]["item_keys"] = sorted({k for i in data.get("items", []) for k in i})
                result["q3_slots"]["other_keys"] = {k: v for k, v in data.items() if k != "items"}
                break

        # Q4: czy ClinicIds zawęża lekarzy w filters
        _, base = get("/appointments/api/v2/search-appointments/filters",
                      RegionIds=REGION, SpecialtyIds="16", SlotSearchType="Standard")
        clinics = base.get("clinics", []) if isinstance(base, dict) else []
        result["q4_clinic_narrowing"] = {"without_clinic": {
            "clinics": clinics, "doctors": base.get("doctors") if isinstance(base, dict) else None}}
        if clinics:
            _, narrowed = get("/appointments/api/v2/search-appointments/filters",
                              RegionIds=REGION, SpecialtyIds="16", ClinicIds=clinics[-1]["id"],
                              SlotSearchType="Standard")
            result["q4_clinic_narrowing"]["with_clinic"] = {
                "clinic": clinics[-1],
                "doctors": narrowed.get("doctors") if isinstance(narrowed, dict) else narrowed,
            }
        ctx.close()

    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Zapisano {OUT}")


if __name__ == "__main__":
    main()
