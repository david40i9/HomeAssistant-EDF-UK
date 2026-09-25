#!/usr/bin/env python3
"""Build a self-contained HTML dashboard from a UK company car list.

Usage:  python build.py [Car_List.xlsx] [dashboard.html]

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
SRC = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "Car_List.xlsx"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "dashboard.html"
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

# Pre-pinned shortlist: (make, regex on Type). First (cheapest P11D) match is pinned.
PREPIN = [
    ("BYD", r"^SEALION 7 .*\bCOMFORT\b"),
    ("BMW", r"^IX1 .*\bEDRIVE20 XLINE\b"),
    ("LEXUS", r"^RZ .*\b350E\b.*\bPREMIUM\+"),
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

KWH_RE = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s?KWH\b")  # "22KWCH" never matches
KW22_RE = re.compile(r"(?<!\d)22KW|/22\b")  # "TECH/PRO/22" is a truncated 22KWCH
OPTION_RE = re.compile(r"\s*\[[^\]]*\]")


def base_type(t: str) -> str:
    return re.sub(r"\s+", " ", OPTION_RE.sub("", t)).strip()


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

    rows, failures, no_eff = [], [], []
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
            "kw22": bool(KW22_RE.search(t)),
            "x": extras,
        })

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
        "sheet": sheet,
        "built": date.today().isoformat(),
        "noEff": no_eff,
        "failures": failures,
        "effRules": EFFICIENCY_RULES,
    }
    js = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DATA__*/null", js)
    OUT.write_text(html, encoding="utf-8")
    print(f"\nWrote {OUT.name}: {len(rows)} cars, {sum(r['ev'] for r in rows)} EVs, {OUT.stat().st_size/1024:.0f} KB")

    print(f"\nRows failing to parse: {len(failures)}")
    for f in failures:
        print("  " + f)
    print(f"EVs with no efficiency estimate: {len(no_eff)}")
    for f in no_eff:
        print("  " + f)

    # Spot checks at default settings: 40% taxpayer, 26/27, negative contribution = cash untaxed
    def net(r, rate=0.40, year=0):
        b = bik_year(r["bik"], r["ev"], year)
        return r["contrib"] + r["p11d"] * b / 100 * rate / 12, b

    def find(make, rx):
        for r in sorted(rows, key=lambda r: (bool(OPTION_RE.search(r["type"])), r["p11d"] or 0)):
            if r["make"].upper() == make and re.search(rx, r["type"]):
                return r

    checks = [
        ("BMW", r"^3 SERIES TOURING 320I M SPORT", 37),
        ("BMW", r"^IX1 .*EDRIVE20 XLINE", 4),
        ("BYD", r"^SEALION 7 .*COMFORT", 4),
        ("LEXUS", r"^RZ .*350E.*PREMIUM\+", 4),
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
