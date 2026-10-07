# EDF Flextras coordinator: registration, free hours (earned, booked, remaining) and Weekend Saver.
# Ported from stevekirtley/HomeAssistant-EDFEnergy (MIT) with thanks. See NOTICE.

import logging
from datetime import datetime, timedelta

from homeassistant.util.dt import utcnow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..const import (
    COORDINATOR_REFRESH_IN_SECONDS,
    DATA_ACCOUNT,
    DATA_FLEXTRAS_COORDINATOR_KEY,
    DATA_FLEXTRAS_KEY,
    DOMAIN,
    REFRESH_RATE_IN_MINUTES_FLEXTRAS,
)
from ..api_client import ApiException, EDFEnergyApiClient
from ..api_client.flextras import (
    parse_bookable_days,
    parse_booked_hours,
    parse_entitlements,
    parse_weekend_saver_challenges,
)
from . import BaseCoordinatorResult

_LOGGER = logging.getLogger(__name__)


class FlextrasCoordinatorResult(BaseCoordinatorResult):
    """Flextras state for an account. `status` is None if the account never joined."""

    def __init__(self, last_evaluated: datetime, request_attempts: int, status: dict | None = None,
                 hours: dict | None = None, entitlements: list | None = None, bookable_days: list | None = None,
                 weekend_saver: dict | None = None, last_retrieved: datetime | None = None,
                 last_error: Exception | None = None):
        super().__init__(last_evaluated, request_attempts, REFRESH_RATE_IN_MINUTES_FLEXTRAS, last_retrieved, last_error)
        self.status = status
        self.hours = hours
        self.entitlements = entitlements or []
        self.bookable_days = bookable_days or []
        self.weekend_saver = weekend_saver or {}

    @property
    def registered(self) -> bool:
        return bool(self.status and self.status.get("registrationDate") and not self.status.get("optedOut"))

    @property
    def free_windows(self) -> list:
        """Booked free hours as (start, end) windows, back-to-back hours merged."""
        return list((self.hours or {}).get("windows") or [])


async def async_refresh_flextras(current: datetime, client: EDFEnergyApiClient, account_id: str,
                                 property_id: str | None, existing: FlextrasCoordinatorResult | None):
    if existing is not None and current < existing.next_refresh:
        return existing

    try:
        status = await client.async_get_flextras_status(account_id)
        hours = entitlements = bookable_days = None
        weekend_saver = {}

        if status is not None and property_id is not None:
            hours_screen = await client.async_get_flextras_hours_screen(account_id, property_id)
            hours = parse_booked_hours(hours_screen)
            entitlements = parse_entitlements(hours_screen)
            bookable_days = parse_bookable_days(await client.async_get_flextras_bookable_days(account_id, property_id))

            can_sign_up, blockers, tariff_excluded = parse_weekend_saver_challenges(
                await client.async_get_weekend_saver_challenges(account_id, property_id))
            weekend_saver = {"can_sign_up": can_sign_up, "blockers": blockers, "tariff_excluded": tariff_excluded}

            # A screen that didn't parse is "try again", not "nothing booked": keep what we had
            if hours is None and existing is not None:
                hours = existing.hours
            if entitlements is None and existing is not None:
                entitlements = existing.entitlements

        return FlextrasCoordinatorResult(current, 1, status, hours, entitlements, bookable_days, weekend_saver)
    except ApiException as e:
        _LOGGER.debug(f"Failed to refresh Flextras for {account_id}: {e}")
        if existing is not None:
            return FlextrasCoordinatorResult(
                existing.last_evaluated, existing.request_attempts + 1, existing.status, existing.hours,
                existing.entitlements, existing.bookable_days, existing.weekend_saver,
                last_retrieved=existing.last_retrieved, last_error=e)
        return FlextrasCoordinatorResult(current - timedelta(minutes=REFRESH_RATE_IN_MINUTES_FLEXTRAS), 2, last_error=e)


async def async_setup_flextras_coordinator(hass, account_id: str, client: EDFEnergyApiClient):
    key = DATA_FLEXTRAS_KEY.format(account_id)

    async def async_update_data():
        account_result = hass.data[DOMAIN][account_id].get(DATA_ACCOUNT)
        account_info = account_result.account if account_result is not None else None
        property_ids = (account_info or {}).get("property_ids") or []
        result = await async_refresh_flextras(
            utcnow(), client, account_id, property_ids[0] if property_ids else None, hass.data[DOMAIN][account_id].get(key))
        hass.data[DOMAIN][account_id][key] = result
        return result

    coordinator = DataUpdateCoordinator(
        hass, _LOGGER, name=key, update_method=async_update_data,
        update_interval=timedelta(seconds=COORDINATOR_REFRESH_IN_SECONDS), always_update=True,
    )
    hass.data[DOMAIN][account_id][DATA_FLEXTRAS_COORDINATOR_KEY.format(account_id)] = coordinator
    return coordinator
