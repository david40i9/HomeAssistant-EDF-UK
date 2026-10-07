# EDF Flextras entities: membership, free hours left and booked, Weekend Saver, and free electricity
# windows built from the booked hours. Ported from stevekirtley/HomeAssistant-EDFEnergy (MIT). See NOTICE.

from datetime import datetime

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.util.dt import as_local, now, parse_date

from ..coordinators.flextras import FlextrasCoordinatorResult
from ..utils.attributes import dict_to_typed_dict
from .balance import EDFEnergyAccountSensor

FREE_ELECTRICITY_SUMMARY = "EDF free electricity"


def _current_and_next(windows: list, current: datetime):
    """The window in progress (or None) and the next one to start (or None)."""
    active = next(((s, e) for s, e in windows if s <= current < e), None)
    upcoming = next(((s, e) for s, e in sorted(windows) if s > current), None)
    return active, upcoming


class _FlextrasEntity(CoordinatorEntity, EDFEnergyAccountSensor):
    _platform = "sensor"

    def __init__(self, hass: HomeAssistant, coordinator, account_id: str):
        CoordinatorEntity.__init__(self, coordinator)
        EDFEnergyAccountSensor.__init__(self, hass, account_id)
        if self._platform != "sensor":
            self.entity_id = generate_entity_id(f"{self._platform}.{{}}", self.unique_id, hass=hass)

    @property
    def result(self) -> FlextrasCoordinatorResult | None:
        return self.coordinator.data if self.coordinator is not None else None

    @property
    def extra_state_attributes(self):
        return self._attributes

    @callback
    def _handle_coordinator_update(self) -> None:
        if self.result is not None:
            self._update(self.result)
        self._attributes = dict_to_typed_dict(self._attributes)
        super()._handle_coordinator_update()

    def _update(self, result: FlextrasCoordinatorResult):
        raise NotImplementedError


class EDFEnergyFlextrasMember(_FlextrasEntity, BinarySensorEntity):
    """On while the account is registered for Flextras, with the schemes it has joined."""

    _platform = "binary_sensor"

    @property
    def unique_id(self):
        return f"edf_energy_{self._account_id}_flextras_member"

    @property
    def name(self):
        return f"EDF Flextras Member ({self._account_id})"

    @property
    def icon(self):
        return "mdi:star-circle-outline"

    @property
    def is_on(self):
        return self.result.registered if self.result is not None else None

    def _update(self, result):
        status = result.status or {}
        self._attributes.update({
            "registration_date": parse_date(status["registrationDate"][:10]) if status.get("registrationDate") else None,
            "opted_out": status.get("optedOut"),
            "power_perks_signup_date": parse_date(status["powerPerksSignUpDate"][:10]) if status.get("powerPerksSignUpDate") else None,
            "tastecard_activation_date": parse_date(status["tasteCardActivationDate"][:10]) if status.get("tasteCardActivationDate") else None,
            "bonus_hours_awarded": status.get("bonusHoursAwarded"),
            "bonus_hours_claimed": status.get("claimedSignUpBonusHours"),
        })


class EDFEnergyFlextrasHoursLeft(_FlextrasEntity, SensorEntity):
    """Free hours left to book, with the hours already booked and when unused hours expire."""

    @property
    def unique_id(self):
        return f"edf_energy_{self._account_id}_flextras_hours_left"

    @property
    def name(self):
        return f"EDF Flextras Hours Left ({self._account_id})"

    @property
    def icon(self):
        return "mdi:clock-star-four-points-outline"

    @property
    def native_unit_of_measurement(self):
        return "h"

    @property
    def native_value(self):
        hours = self.result.hours if self.result is not None else None
        return hours.get("total_remaining_hours") if hours else None

    def _update(self, result):
        hours = result.hours or {}
        expiring = sorted(
            (e for e in result.entitlements if e.get("expires") and (e.get("hours_left") or 0) > 0),
            key=lambda e: e["expires"],
        )
        next_expiry = parse_date(expiring[0]["expires"][:10]) if expiring else None
        self._attributes.update({
            "bonus_hours_remaining": hours.get("bonus_hours_remaining"),
            "challenge_hours_remaining": hours.get("challenge_hours_remaining"),
            "hours_booked": len(hours.get("hours") or []),
            "booked_hours": [f"{d} {t}" for d, t in hours.get("hours") or []],
            "entitlements": result.entitlements,
            "next_expiry": next_expiry,
            "days_until_expiry": (next_expiry - now().date()).days if next_expiry else None,
            "bookable_days": [d["date"] for d in result.bookable_days if d.get("available")],
        })


class EDFEnergyWeekendSaverAvailable(_FlextrasEntity, BinarySensorEntity):
    """On if the account can sign up for Weekend Saver; otherwise EDF's reasons why not."""

    _platform = "binary_sensor"

    @property
    def unique_id(self):
        return f"edf_energy_{self._account_id}_weekend_saver_available"

    @property
    def name(self):
        return f"EDF Weekend Saver Available ({self._account_id})"

    @property
    def icon(self):
        return "mdi:calendar-weekend-outline"

    @property
    def is_on(self):
        return (self.result.weekend_saver or {}).get("can_sign_up") if self.result is not None else None

    def _update(self, result):
        weekend_saver = result.weekend_saver or {}
        self._attributes.update({
            "blockers": weekend_saver.get("blockers") or [],
            "excluded_by_tariff": weekend_saver.get("tariff_excluded"),
        })


class EDFEnergyFreeElectricityActive(_FlextrasEntity, BinarySensorEntity):
    """On during a free electricity window you've booked through Flextras."""

    _platform = "binary_sensor"

    @property
    def unique_id(self):
        return f"edf_energy_{self._account_id}_free_electricity_active"

    @property
    def name(self):
        return f"EDF Free Electricity Active ({self._account_id})"

    @property
    def icon(self):
        return "mdi:flash" if self.is_on else "mdi:flash-outline"

    @property
    def is_on(self):
        if self.result is None:
            return None
        active, _ = _current_and_next(self.result.free_windows, now())
        return active is not None

    def _update(self, result):
        active, upcoming = _current_and_next(result.free_windows, now())
        self._attributes.update({
            "current_start": as_local(active[0]) if active else None,
            "current_end": as_local(active[1]) if active else None,
            "next_start": as_local(upcoming[0]) if upcoming else None,
            "next_end": as_local(upcoming[1]) if upcoming else None,
        })


class EDFEnergyNextFreeElectricity(_FlextrasEntity, SensorEntity):
    """When the current or next free electricity window starts, with when it ends."""

    @property
    def unique_id(self):
        return f"edf_energy_{self._account_id}_free_electricity_next"

    @property
    def name(self):
        return f"EDF Next Free Electricity ({self._account_id})"

    @property
    def icon(self):
        return "mdi:calendar-star"

    @property
    def device_class(self):
        return SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self):
        if self.result is None:
            return None
        active, upcoming = _current_and_next(self.result.free_windows, now())
        window = active or upcoming
        return window[0] if window else None

    def _update(self, result):
        active, upcoming = _current_and_next(result.free_windows, now())
        window = active or upcoming
        self._attributes.update({
            "end": as_local(window[1]) if window else None,
            "duration_in_minutes": int((window[1] - window[0]).total_seconds() // 60) if window else None,
            "is_active": active is not None,
        })


class EDFEnergyFreeElectricityCalendar(_FlextrasEntity, CalendarEntity):
    """The free electricity windows you've booked, as calendar events."""

    _platform = "calendar"

    @property
    def unique_id(self):
        return f"edf_energy_{self._account_id}_free_electricity_calendar"

    @property
    def name(self):
        return f"EDF Free Electricity ({self._account_id})"

    @property
    def icon(self):
        return "mdi:calendar-star"

    def _event(self, window) -> CalendarEvent:
        return CalendarEvent(start=as_local(window[0]), end=as_local(window[1]), summary=FREE_ELECTRICITY_SUMMARY)

    @property
    def event(self) -> CalendarEvent | None:
        if self.result is None:
            return None
        active, upcoming = _current_and_next(self.result.free_windows, now())
        window = active or upcoming
        return self._event(window) if window else None

    async def async_get_events(self, hass: HomeAssistant, start_date: datetime, end_date: datetime):
        if self.result is None:
            return []
        return [self._event(w) for w in self.result.free_windows if w[1] > start_date and w[0] < end_date]

    def _update(self, result):
        pass
