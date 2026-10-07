"""EDF Flextras: the free hours a customer has earned and booked, and Weekend Saver eligibility.

Ported from stevekirtley/HomeAssistant-EDFEnergy (MIT) - api_client/flextras_hours.py and
coordinators/flextras.py in 19.2.6 - with thanks. See NOTICE.

EDF serve these as server-driven UI screens rather than a plain API, but each screen carries
machine-readable components alongside the text meant for the app, and those are what is read
here. Anything that doesn't look like the expected screen returns None, so a bad response is
treated as "ask again later" rather than "nothing is booked".

Times in the booked-hours list are local (Europe/London), even where EDF label them UTC, so
the date and time are read as UK time. That matters because hours can be booked either side
of a clock change.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from homeassistant.util.dt import as_utc

UK_TZ = ZoneInfo("Europe/London")

BOOKED_HOURS_LIST = "BOOKED_HOURS_LIST"
SELECT_DAYS_LIST = "SELECT_DAYS_LIST"
HOURS_TO_USE_LIST = "HOURS_TO_USE_LIST"

# The per-entitlement hour count is only given in prose ("You have 4 hours left to use")
_HOURS_IN_TEXT = re.compile(r"(\d+(?:\.\d+)?)\s*hour")

# Weekend Saver checklist gates that can't be fixed by the customer (a three-or-more-rate tariff)
_STRUCTURAL_CHECKLIST_IDS = ("TariffType",)


def _components(response_body, component_type: str) -> dict | None:
    if not isinstance(response_body, dict) or not isinstance(response_body.get("components"), list):
        return None
    return next(
        (c["props"] for c in response_body["components"]
         if isinstance(c, dict) and c.get("type") == component_type and isinstance(c.get("props"), dict)),
        None,
    )


def _slot_datetime(date_str, time_str) -> datetime | None:
    """A slot's date and wall-clock (UK) time as a UTC instant."""
    if not isinstance(date_str, str) or not isinstance(time_str, str):
        return None
    try:
        naive = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return as_utc(naive.replace(tzinfo=UK_TZ))


def merge_adjacent(windows: list) -> list:
    """Join hours that run back to back into one window (hours are booked one at a time)."""
    merged = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def parse_booked_hours(response_body) -> dict | None:
    """The booked hours and hour balances from the Flextras hours screen."""
    props = _components(response_body, BOOKED_HOURS_LIST)
    if props is None:
        return None

    windows = []
    hours = []
    for item in props.get("items") or []:
        if not isinstance(item, dict):
            continue
        for slot in item.get("rawTimeSlots") or []:
            if not isinstance(slot, dict):
                continue
            start = _slot_datetime(slot.get("date"), slot.get("startTime"))
            end = _slot_datetime(slot.get("date"), slot.get("endTime"))
            if start is None or end is None:
                continue
            if end <= start:
                # An hour that runs over midnight is dated by the day it starts
                end = end + timedelta(days=1)
            windows.append((start, end))
            hours.append((slot["date"], slot["startTime"]))

    def number(key):
        value = props.get(key)
        return value if isinstance(value, (int, float)) else None

    return {
        "windows": merge_adjacent(windows),
        "hours": sorted(set(hours)),
        "bonus_hours": number("bonusHours"),
        "bonus_hours_remaining": number("bonusHoursRemaining"),
        "challenge_hours": number("challengeHours"),
        "challenge_hours_remaining": number("challengeHoursRemaining"),
        "total_remaining_hours": number("totalRemainingHours"),
    }


def parse_entitlements(response_body) -> list | None:
    """Each block of hours (joining bonus, monthly challenge hours) and when it expires.

    Unused challenge hours don't simply lapse: EDF books them at a time of its choosing near
    expiry, so knowing an expiry is coming lets you pick the slot first.
    """
    props = _components(response_body, HOURS_TO_USE_LIST)
    if props is None:
        return None

    entitlements = []
    for item in props.get("items") or []:
        if not isinstance(item, dict):
            continue
        description = item.get("description") or ""
        match = _HOURS_IN_TEXT.search(description)
        expires = item.get("date")
        entitlements.append({
            "kind": item.get("type"),
            "title": item.get("title"),
            "hours_left": float(match.group(1)) if match else None,
            "expires": expires if isinstance(expires, str) else None,
        })
    return entitlements


def parse_bookable_days(response_body) -> list | None:
    """The days EDF is currently offering for booking, flat and in date order."""
    props = _components(response_body, SELECT_DAYS_LIST)
    if props is None:
        return None

    days = []
    for month in props.get("months") or []:
        if not isinstance(month, dict):
            continue
        for day in month.get("days") or []:
            if isinstance(day, dict) and isinstance(day.get("date"), str):
                days.append({"date": day["date"], "available": bool(day.get("isAvailable"))})
    return sorted(days, key=lambda d: d["date"])


def parse_weekend_saver_challenges(response_body) -> tuple:
    """(can sign up, reasons it can't, excluded by tariff) from the Weekend Saver screen."""
    if not isinstance(response_body, dict):
        return None, [], False

    can_sign_up = None
    blockers = []
    tariff_excluded = False
    for component in response_body.get("components") or []:
        if not isinstance(component, dict):
            continue
        props = component.get("props") or {}
        if component.get("type") == "SIGNUP_BANNER" and "canSignUp" in props:
            can_sign_up = props.get("canSignUp")
        elif component.get("type") == "CHECKLIST":
            for item in props.get("checkList") or []:
                if isinstance(item, dict) and item.get("valid") is False:
                    if item.get("title"):
                        blockers.append(item["title"])
                    if any(marker in (item.get("id") or "") for marker in _STRUCTURAL_CHECKLIST_IDS):
                        tariff_excluded = True
    return can_sign_up, blockers, tariff_excluded
