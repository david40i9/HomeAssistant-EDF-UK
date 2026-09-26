#!/usr/bin/env python3
"""Build a self-contained HTML dashboard from a UK company car list.

Usage:  python build.py [Car_List.xlsx] [dashboard.html] [--all]

By default only the cars in SCOPE are published; --all publishes every row.

Reads the first sheet, derives CO2 / BIK / battery / efficiency fields and
embeds everything as JSON in template.html -> dashboard.html. All money
calculations that depend on user-editable rates are repeated live in JS; the
Python versions here exist for the spot checks printed at the end.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ALL = "--all" in sys.argv
ARGS = [a for a in sys.argv[1:] if a != "--all"]
SRC = Path(ARGS[0]) if len(ARGS) > 0 else HERE / "Car_List.xlsx"
OUT = Path(ARGS[1]) if len(ARGS) > 1 else HERE / "dashboard.html"
TEMPLATE = HERE / "template.html"

COL = {
    "make": "MakeDescription",
    "model": "ModelDescription",
    "type": "Type",
    "fuel": "Fuel",
    "body": "BodyStyle",
    "p11d": "TaxableListPrice",
    "contrib": "Private Use Contribution",
    "co2": "CO2 Emission Value (g/km)",
    "co2max": "CO2 Emission Value With Maximum options (g/km)",
    "ins": "InsuranceGroup",
}

# Cars published to the dashboard: (make, regex on Type, electric only). Pass --all to skip.
SCOPE_LABEL = "Mercedes CLA electric, BYD and Toyota electric"
SCOPE = [
    ("MERCEDES-BENZ", r"^CLA ELECTRIC\b", True),
    ("BYD", r"", True),
    ("TOYOTA", r"", True),
]

# Pre-pinned shortlist: (make, regex on Type). First (cheapest P11D) match is pinned.
PREPIN = [
    ("MERCEDES-BENZ", r"^CLA ELECTRIC SALOON CLA 200 .*\bSPORT\b"),
    ("MERCEDES-BENZ", r"^CLA ELECTRIC SALOON CLA 250\+ .*\bSPORT\b"),
    ("MERCEDES-BENZ", r"^CLA ELECTRIC SHOOTING BRAKE CLA 250\+ .*\bSPORT\b"),
    ("BYD", r"^SEALION 7 .*\bCOMFORT\b"),
]

# ---------------------------------------------------------------------------
# Real-world efficiency (mi/kWh) - ESTIMATES. Ordered rules; first match wins.
# Each rule: (regex on base Type, mi/kWh). Base Type has [option] suffix removed.
# ---------------------------------------------------------------------------
AWD = r"(?=.*\b(?:AWD|ALL4|4M|XDRIVE)\b)"
EFFICIENCY_RULES: list[tuple[str, float]] = [
    # BMW
    (r"^IX[12] .*\bEDRIVE20\b", 3.7),
    (r"^IX[12] .*\bXDRIVE30\b", 3.4),
    (r"^IX3\b", 4.0),
    (r"^I5 SALOON\b", 3.6),
    (r"^I5 TOURING\b", 3.4),
    # BYD (SURF before DOLPHIN, SEALION before SEAL)
    (r"^DOLPHIN SURF\b", 4.0),
    (r"^DOLPHIN\b", 3.6),
    (r"^ATTO 2\b", 3.6),
    (r"^ATTO 3\b" + AWD, 3.1),
    (r"^ATTO 3\b", 3.4),
    (r"^SEALION 7\b" + AWD, 2.9),
    (r"^SEALION 7\b", 3.1),
    (r"^SEAL\b(?! ?ION)" + AWD, 3.4),
    (r"^SEAL\b(?! ?ION)", 3.7),
    # Lexus
    (r"^RZ .*\b350E\b", 3.5),
    (r"^RZ .*\b500E\b", 3.2),
    (r"^ES ELECTRIC\b", 3.8),
    # Mercedes CLA electric: saloon figures, Shooting Brake 0.2 lower (handled below)
    (r"^CLA ELECTRIC .*\bCLA 200\b", 4.6),
    (r"^CLA ELECTRIC .*\bCLA 250\+", 4.7),
    (r"^CLA ELECTRIC .*\bCLA 350\b", 4.5),
    (r"^GLB ELECTRIC .*\bGLB 250\+", 3.5),
    (r"^GLB ELECTRIC .*\bGLB 350\b", 3.3),
    # Mini
    (r"^ACEMAN .*\b(?:JOHN COOPER WORKS|JCW)\b", 3.6),
    (r"^ACEMAN .*\bSE\b", 3.8),
    (r"^ACEMAN .*\bE\b", 3.9),
    (r"^COUNTRYMAN ELECTRIC .*\bSE\b.*\bALL4\b", 3.3),
    (r"^COUNTRYMAN ELECTRIC .*\bE\b", 3.5),
    # Toyota
    (r"^URBAN CRUISER .*" + AWD, 3.4),
    (r"^URBAN CRUISER .*\b49 ?KWH\b", 3.8),
    (r"^URBAN CRUISER .*\b61 ?KWH\b", 3.7),
    (r"^C-HR\+ .*" + AWD, 3.4),
    (r"^C-HR\+ .*\b123KW\b", 3.8),
    (r"^C-HR\+ ", 3.7),
    (r"^BZ4X ELECTRIC TOURING\b" + AWD, 3.3),
    (r"^BZ4X ELECTRIC TOURING\b", 3.6),
    (r"^BZ4X\b" + AWD, 3.4),
    (r"^BZ4X\b", 3.8),
    (r"^PROACE CITY VERSO\b", 2.8),
    (r"^PROACE VERSO\b", 2.3),
    # Volvo
    (r"^EX30 .*\b315KW\b", 3.4),
    (r"^EX30\b", 3.7),
    (r"^EX40 .*\b(?:300|325)KW\b", 3.0),
    (r"^EX40\b", 3.2),
    (r"^EC40\b", 3.3),
]
EFFICIENCY_RULES_C = [(re.compile(p), v) for p, v in EFFICIENCY_RULES]

# ---------------------------------------------------------------------------
# 0-62 mph (seconds) - manufacturer-quoted figures, researched September 2026.
# NOT in the source list. Rule: (regex on base Type, seconds, source, engine cc or None).
# First match wins. Anything unmatched is left blank and reported - never guessed.
# ---------------------------------------------------------------------------
ACCEL_RULES: list[tuple[str, float, str, int | None]] = [
    # BMW
    (r"^1 SERIES .*\b123\b", 6.3, "Auto Express", None),
    (r"^1 SERIES .*\b120\b", 7.8, "Auto Express", None),
    (r"^2 SERIES GRAN COUPE .*\b223\b", 6.4, "BMW UK / What Car?", None),
    (r"^2 SERIES GRAN COUPE .*\b220\b", 7.9, "BMW UK / What Car?", None),
    (r"^2 SERIES ACTIVE TOURER .*\b223I\b", 7.0, "Parkers", None),
    (r"^2 SERIES ACTIVE TOURER .*\b220I\b", 8.1, "Parkers", None),
    (r"^3 SERIES SALOON .*\b320I\b", 7.4, "BMW UK", None),
    (r"^3 SERIES TOURING .*\b320I\b", 7.6, "BMW UK", None),
    (r"^X1 .*\bSDRIVE 18D\b", 8.9, "What Car? / Top Gear", None),
    (r"^X1 .*\bSDRIVE 20I\b", 8.3, "What Car? / Top Gear", None),
    (r"^X1 .*\bXDRIVE 23I\b", 7.1, "What Car? / Top Gear", None),
    (r"^X1 .*\bXDRIVE 23D\b", 7.4, "What Car? / Top Gear", None),
    (r"^X2 .*\bSDRIVE 20I\b", 8.3, "What Car?", None),
    (r"^I5 SALOON\b", 6.0, "BMW UK", None),
    (r"^I5 TOURING\b", 6.1, "BMW UK", None),
    (r"^IX[12] .*\bEDRIVE20\b", 8.6, "BMW UK / DrivingElectric", None),
    (r"^IX[12] .*\bXDRIVE30\b", 5.6, "BMW UK / DrivingElectric", None),
    (r"^IX3\b", 5.9, "BMW Group press (iX3 40)", None),
    # BYD
    (r"^DOLPHIN SURF .*\b65KW\b.*\b30 ?KWH\b", 11.1, "Auto Express", None),
    (r"^DOLPHIN SURF .*\b65KW\b", 12.1, "Auto Express", None),
    (r"^DOLPHIN SURF .*\b115KW\b", 9.1, "Auto Express", None),
    (r"^DOLPHIN\b(?! SURF)", 7.0, "BYD UK / DriveElectric", None),
    (r"^ATTO 2\b", 7.9, "Autocar (BYD claim)", None),
    (r"^ATTO 3\b.*\bAWD\b", 3.9, "Autocar", None),
    (r"^ATTO 3\b", 5.5, "GreenCarGuide", None),
    (r"^SEAL SALOON\b.*\bAWD\b", 3.8, "GreenCarGuide", None),
    (r"^SEAL SALOON\b", 5.9, "GreenCarGuide", None),
    (r"^SEALION 7\b.*\bAWD\b", 4.5, "BYD UK", None),
    (r"^SEALION 7\b", 6.7, "BYD UK", None),
    # Lexus
    (r"^RZ .*\b350E\b", 7.5, "Lexus UK", None),
    (r"^RZ .*\b500E\b", 4.6, "Lexus UK", None),
    (r"^ES ELECTRIC\b", 8.0, "Lexus UK", None),
    (r"^LBX .*\bAWD\b", 9.6, "Lexus UK", None),
    (r"^LBX\b", 9.2, "Lexus UK", None),
    (r"^UX .*\b300H\b", 8.1, "Lexus (FWD)", None),
    (r"^NX .*\b350H\b", 7.7, "Lexus UK (AWD)", None),
    # Mercedes-Benz
    (r"^CLA ELECTRIC SHOOTING BRAKE .*\bCLA 200\b", 7.6, "Mercedes UK / Carwow", None),
    (r"^CLA ELECTRIC SHOOTING BRAKE .*\bCLA 250\+", 6.8, "Mercedes UK / Carwow", None),
    (r"^CLA ELECTRIC SHOOTING BRAKE .*\bCLA 350\b", 5.0, "Mercedes UK / Carwow", None),
    (r"^CLA ELECTRIC SALOON .*\bCLA 200\b", 7.5, "Mercedes / ArenaEV", None),
    (r"^CLA ELECTRIC SALOON .*\bCLA 250\+", 6.7, "Mercedes / ArenaEV", None),
    (r"^CLA ELECTRIC SALOON .*\bCLA 350\b", 4.9, "Mercedes / Fleet News", None),
    (r"^GLB ELECTRIC .*\bGLB 250\+", 7.4, "Fleet News", None),
    (r"^GLB ELECTRIC .*\bGLB 350\b", 5.5, "Fleet News", None),
    (r"^A CLASS DIESEL .*\bA200D\b", 8.1, "Parkers", None),
    (r"^A CLASS .*\bA180\b", 9.2, "Parkers", None),
    (r"^A CLASS .*\bA200\b", 8.2, "Parkers", None),
    (r"^CLA SHOOTING BRAKE .*\bCLA 180\b", 9.6, "automobile-catalog (pre-2025 CLA)", 1332),
    (r"^CLA SHOOTING BRAKE .*\bCLA 180\b", 8.9, "Autoblog (CLA hybrid)", None),
    (r"^CLA SALOON .*\bCLA 180\b", 8.8, "Parkers (CLA hybrid)", None),
    (r"^CLA SALOON .*\bCLA 200\b", 8.0, "Parkers (CLA hybrid)", None),
    (r"^GLA .*\bGLA 180\b", 9.6, "Top Gear spec", None),
    (r"^GLA .*\bGLA 200\b", 8.9, "Auto Express", None),
    # Mini
    (r"^ACEMAN .*\b(?:JOHN COOPER WORKS|JCW)\b", 6.4, "BMW Group press", None),
    (r"^ACEMAN .*\bSE\b", 7.1, "BMW Group press", None),
    (r"^ACEMAN .*\bE\b", 7.9, "BMW Group press", None),
    (r"^COUNTRYMAN ELECTRIC .*\bSE\b.*\bALL4\b", 5.6, "MINI (0-100 km/h)", None),
    (r"^COUNTRYMAN ELECTRIC .*\bE\b", 8.6, "Autocar", None),
    (r"^COUNTRYMAN HATCHBACK 1\.5 C\b", 8.3, "MINI (0-100 km/h)", None),
    (r"^COOPER HATCHBACK 2\.0 S\b", 6.8, "BMW Group press (5-door)", None),
    (r"^COOPER HATCHBACK 1\.5 C\b", 8.0, "BMW Group press (5-door)", None),
    # Toyota
    (r"^AYGO X\b", 9.2, "Toyota UK", None),
    (r"^YARIS CROSS .*\b130\b.*\bAWD\b", 11.3, "Toyota UK", None),
    (r"^YARIS CROSS .*\b130\b", 10.7, "Toyota UK", None),
    (r"^YARIS CROSS .*\bAWD\b", 11.8, "Toyota UK", None),
    (r"^YARIS CROSS\b", 11.2, "Toyota UK", None),
    (r"^YARIS HATCHBACK .*\b130\b", 9.2, "DrivingElectric", None),
    (r"^YARIS HATCHBACK\b", 9.7, "DrivingElectric", None),
    (r"^COROLLA TOURING SPORT .*\b2\.0\b", 7.7, "Toyota UK", None),
    (r"^COROLLA TOURING SPORT .*\b1\.8\b", 9.4, "Toyota UK", None),
    (r"^COROLLA HATCHBACK .*\b2\.0\b", 7.4, "DrivingElectric", None),
    (r"^COROLLA HATCHBACK .*\b1\.8\b", 9.1, "DrivingElectric", None),
    (r"^C-HR HATCHBACK .*\b2\.0\b", 8.1, "Toyota UK", None),
    (r"^C-HR HATCHBACK .*\b1\.8\b", 9.9, "Toyota UK", None),
    (r"^C-HR\+ .*\bAWD\b", 5.2, "Toyota UK", None),
    (r"^C-HR\+ .*\b123KW\b", 8.4, "Auto Express", None),
    (r"^C-HR\+ ", 7.3, "Parkers", None),
    (r"^BZ4X ELECTRIC TOURING\b.*\bAWD\b", 4.5, "Top Gear", None),
    (r"^BZ4X ELECTRIC TOURING\b", 7.3, "Top Gear", None),
    (r"^BZ4X\b.*\bAWD\b", 5.1, "Carwow", None),
    (r"^BZ4X\b.*\b123KW\b", 8.6, "Carwow", None),
    (r"^BZ4X\b", 7.3, "Carwow", None),
    (r"^URBAN CRUISER .*\b49 ?KWH\b", 9.6, "Parkers", None),
    (r"^URBAN CRUISER .*\b61 ?KWH\b", 8.7, "Parkers", None),
    (r"^PROACE CITY VERSO\b", 11.2, "Carwow / Auto Express", None),
    (r"^PROACE VERSO\b", 13.3, "Parkers (75kWh)", None),
    # Volvo
    (r"^EX30 .*\b315KW\b", 3.6, "Volvo UK", None),
    (r"^EX30 .*\b69 ?KWH\b", 5.3, "Volvo UK", None),
    (r"^EX30\b", 5.7, "Volvo UK", None),
    (r"^EX40 .*\b325KW\b", 4.6, "DrivingElectric", None),
    (r"^EX40 .*\b300KW\b", 4.8, "DrivingElectric", None),
    (r"^EX40\b", 7.4, "DrivingElectric", None),
    (r"^EC40\b", 7.3, "Volvo", None),
    (r"^V60 .*\bB4P?\b", 7.3, "Parkers", None),
]
ACCEL_RULES_C = [(re.compile(p), v, src, cc) for p, v, src, cc in ACCEL_RULES]

KWH_RE = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s?KWH\b")  # "22KWCH" never matches
KW22_RE = re.compile(r"(?<!\d)22KW|/22\b")  # "TECH/PRO/22" is a truncated 22KWCH
OPTION_RE = re.compile(r"\s*\[[^\]]*\]")


def base_type(t: str) -> str:
    return re.sub(r"\s+", " ", OPTION_RE.sub("", t)).strip()


def accel(t: str, cc):
    b = base_type(t)
    for rx, v, src, need_cc in ACCEL_RULES_C:
        if rx.search(b) and (need_cc is None or cc == need_cc):
            return v, src
    return None, None


def efficiency(t: str):
    b = base_type(t)
    for rx, v in EFFICIENCY_RULES_C:
        if rx.search(b):
            if b.startswith("CLA ELECTRIC SHOOTING BRAKE"):
                v = round(v - 0.2, 2)
            return v
    return None


def bik_2627(co2: float, is_ev: bool):
    """BIK % for 2026/27 per the brief. None if outside the specified table."""
    if is_ev or co2 == 0:
        return 4
    if co2 < 51:
        return None  # 1-50g (PHEV) bands not specified in the brief
    table = [(55, 17), (60, 18), (65, 19), (70, 20), (75, 21), (80, 21)]
    for upper, pct in table:
        if co2 < upper:
            return pct
    return min(22 + int((co2 - 80) // 5), 37)


def bik_year(b2627: int, is_ev: bool, year: int) -> int:
    """year index: 0=26/27, 1=27/28, 2=28/29, 3=29/30"""
    if is_ev:
        return [4, 5, 7, 9][year]
    return [b2627, b2627, min(b2627 + 1, 38), min(b2627 + 2, 39)][year]


def num(x):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def main():
    xl = pd.ExcelFile(SRC)
    sheet = xl.sheet_names[0]
    df = pd.read_excel(xl, sheet_name=sheet)
    df.columns = [str(c).strip() for c in df.columns]
    print(f"Source: {SRC.name}  sheet: {sheet!r}  rows: {len(df)}  columns: {len(df.columns)}")
    for c in df.columns:
        print(f"  - {c}  [{df[c].dtype}, {df[c].notna().sum()} non-null]")
    missing = [v for v in COL.values() if v not in df.columns]
    if missing:
        print(f"WARNING: expected columns missing: {missing}")
    extra = [c for c in df.columns if c not in COL.values()]

    rows, failures, no_eff, no_acc = [], [], [], []
    for i, r in df.iterrows():
        g = lambda k: r.get(COL[k]) if COL[k] in df.columns else None
        t = str(g("type") or "").strip()
        fuel = str(g("fuel") or "").strip() or "Unknown"
        p11d = num(g("p11d"))
        contrib = num(g("contrib"))
        co2m, co2s = num(g("co2max")), num(g("co2"))
        co2 = co2m if co2m is not None else co2s
        is_ev = fuel.lower() == "electric" or co2 == 0
        problems = []
        if p11d is None or p11d <= 0:
            problems.append("no P11D")
        if contrib is None:
            problems.append("no contribution")
        if co2 is None:
            problems.append("no CO2")
        bik = bik_2627(co2, is_ev) if co2 is not None else None
        if co2 is not None and bik is None:
            problems.append(f"CO2 {co2:g}g outside specified BIK bands")
        kwh = eff = None
        if is_ev:
            m = KWH_RE.search(t)
            kwh = float(m.group(1)) if m else None
            if kwh is None:
                problems.append("battery kWh not found in Type")
            eff = efficiency(t)
            if eff is None:
                no_eff.append(f"{g('make')} | {t}")
        if problems:
            failures.append(f"row {i + 2}: {g('make')} {t} -> {', '.join(problems)}")
        acc, acc_src = accel(t, num(r.get("EngineSize")))
        if acc is None:
            no_acc.append(f"{g('make')} | {t}")
        extras = {c: (None if pd.isna(r[c]) else (r[c].item() if hasattr(r[c], "item") else r[c])) for c in extra}
        rows.append({
            "id": int(i),
            "make": str(g("make") or "").strip(),
            "model": str(g("model") or "").strip(),
            "type": t,
            "fuel": fuel,
            "body": str(g("body") or "").strip() or "Unknown",
            "p11d": p11d,
            "contrib": contrib,
            "co2": co2,
            "co2src": "max" if co2m is not None else ("std" if co2s is not None else None),
            "ins": num(g("ins")),
            "ev": bool(is_ev),
            "bik": bik,
            "kwh": kwh,
            "eff": eff,
            "acc": acc,
            "accSrc": acc_src,
            "kw22": bool(KW22_RE.search(t)),
            "x": extras,
        })

    all_rows = rows
    if not ALL:
        def in_scope(r):
            return any(r["make"].upper() == mk and re.search(rx, r["type"]) and (r["ev"] or not ev_only)
                       for mk, rx, ev_only in SCOPE)
        rows = [r for r in all_rows if in_scope(r)]
        keep = {r["id"] for r in rows}
        failures = [f for f in failures if int(f.split(":")[0].split()[1]) - 2 in keep]
        no_eff = [f for f in no_eff if any(f == f"{r['make']} | {r['type']}" for r in rows)]
        no_acc = [f for f in no_acc if any(f == f"{r['make']} | {r['type']}" for r in rows)]

    # Pre-pins
    pins = []
    for make, rx in PREPIN:
        c = [r for r in rows if r["make"].upper() == make and re.search(rx, r["type"]) and r["p11d"]]
        c.sort(key=lambda r: (bool(OPTION_RE.search(r["type"])), r["p11d"]))
        if c:
            pins.append(c[0]["id"])
        else:
            print(f"WARNING: pre-pin not found: {make} /{rx}/")

    payload = {
        "rows": rows,
        "pins": pins,
        "extraCols": extra,
        "source": SRC.name,
        "scope": None if ALL else SCOPE_LABEL,
        "totalRows": len(all_rows),
        "sheet": sheet,
        "built": date.today().isoformat(),
        "noEff": no_eff,
        "noAcc": no_acc,
        "failures": failures,
        "effRules": EFFICIENCY_RULES,
    }
    js = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", js)
    OUT.write_text(html, encoding="utf-8")
    print(f"\nScope: {'all cars' if ALL else SCOPE_LABEL} ({len(rows)} of {len(all_rows)} rows)")
    print(f"Wrote {OUT.name}: {len(rows)} cars, {sum(r['ev'] for r in rows)} EVs, {OUT.stat().st_size/1024:.0f} KB")

    print(f"\nRows failing to parse: {len(failures)}")
    for f in failures:
        print("  " + f)
    print(f"Cars with no 0-62 figure: {len(no_acc)}")
    for f in no_acc:
        print("  " + f)
    print(f"EVs with no efficiency estimate: {len(no_eff)}")
    for f in no_eff:
        print("  " + f)

    # Spot checks at default settings: 40% taxpayer, 26/27, negative contribution = cash untaxed
    def net(r, rate=0.40, year=0):
        b = bik_year(r["bik"], r["ev"], year)
        return r["contrib"] + r["p11d"] * b / 100 * rate / 12, b

    def find(make, rx):
        for r in sorted(all_rows, key=lambda r: (bool(OPTION_RE.search(r["type"])), r["p11d"] or 0)):
            if r["make"].upper() == make and re.search(rx, r["type"]):
                return r

    checks = [
        ("BMW", r"^3 SERIES TOURING 320I M SPORT", 37),
        ("BMW", r"^IX1 .*EDRIVE20 XLINE", 4),
        ("BYD", r"^SEALION 7 .*COMFORT", 4),
        ("MERCEDES-BENZ", r"^CLA ELECTRIC SALOON CLA 250\+ .*SPORT", 4),
        ("TOYOTA", r"^YARIS\b", None),
    ]
    print("\nSpot checks (40% rate, 2026/27, negative contribution = untaxed cash):")
    ok = True
    for make, rx, expect in checks:
        r = find(make, rx)
        if not r:
            print(f"  NOT FOUND {make} {rx}")
            ok = False
            continue
        n, b = net(r)
        n20, _ = net(r, 0.20)
        n3, b3 = net(r, 0.40, 3)
        flag = "" if expect is None else ("  OK" if b == expect else f"  FAIL (expected {expect}%)")
        ok &= expect is None or b == expect
        rng = f"  range {r['kwh'] * 0.92 * r['eff']:.0f} mi" if r["kwh"] and r["eff"] else ""
        print(f"  [{r['id']}] {r['type']}\n      CO2 {r['co2']:g}g  P11D £{r['p11d']:,.0f}  contrib £{r['contrib']:.2f}/m  "
              f"BIK {b}%{flag}  net@40 £{n:,.0f}  net@20 £{n20:,.0f}  29/30 BIK {b3}% net@40 £{n3:,.0f}{rng}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
