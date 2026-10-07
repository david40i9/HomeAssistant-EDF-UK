# Modified from HomeAssistant-OctopusEnergy by BottlecapDave (MIT)
# Modified by Bobby5291 — adapted for EDF Energy / Kraken API

from datetime import datetime, timedelta
import logging

from homeassistant.util.dt import as_local, as_utc, utcnow
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from ..const import (
    COORDINATOR_REFRESH_IN_SECONDS,
    DATA_ACCOUNT,
    DATA_PREVIOUS_CONSUMPTION_COORDINATOR_KEY,
    DOMAIN,
    EVENT_ELECTRICITY_PREVIOUS_CONSUMPTION_RATES,
    EVENT_GAS_PREVIOUS_CONSUMPTION_RATES,
    MINIMUM_CONSUMPTION_DATA_LENGTH,
    REFRESH_RATE_IN_MINUTES_PREVIOUS_CONSUMPTION,
    STATISTICS_BACKFILL_DAYS,
)

from ..api_client import ApiException, EDFEnergyApiClient
from ..utils import private_rates_to_public_rates
from ..utils.rate_information import get_min_max_average_rates
from ..statistics import async_get_statistic_hours_by_day
from ..statistics.consumption import electricity_consumption_statistic_id, gas_consumption_statistic_id
from . import BaseCoordinatorResult, get_electricity_meter_tariff, get_gas_meter_tariff

_LOGGER = logging.getLogger(__name__)


def __get_interval_end(item):
    return (item["end"].timestamp(), item["end"].fold)


def __sort_consumption(consumption_data):
    sorted_data = consumption_data.copy()
    sorted_data.sort(key=__get_interval_end)
    return sorted_data


def get_complete_days(consumption_data: list | None) -> list:
    """The complete local (UK) days in the data, oldest first, as (date, half hours) pairs.

    EDF publishes consumption late and in pieces, so a day only counts once every half hour is present.
    The expected count follows the day's length, so the clock-change days (46 or 50 half hours) work too.
    """
    if not consumption_data:
        return []

    days = {}
    for item in consumption_data:
        days.setdefault(as_local(item["start"]).date(), []).append(item)

    complete = []
    for day in sorted(days.keys()):
        items = days[day]
        day_start = as_local(items[0]["start"]).replace(hour=0, minute=0, second=0, microsecond=0)
        next_day_start = (day_start + timedelta(days=1, hours=2)).replace(hour=0, minute=0, second=0, microsecond=0)
        expected = int((as_utc(next_day_start) - as_utc(day_start)).total_seconds() // 1800)
        unique = {as_utc(item["start"]): item for item in items}
        if len(unique) == expected:
            complete.append((day, __sort_consumption(list(unique.values()))))
    return complete


def get_latest_day(consumption_data: list | None):
    """Return the half hours of the most recent complete local (UK) day, or None.

    Same approach as @stevekirtley's EDF integration and Octopus Energy.
    """
    complete = get_complete_days(consumption_data)
    return complete[-1][1] if complete else None


class PreviousConsumptionCoordinatorResult(BaseCoordinatorResult):
    consumption: list
    rates: list
    standing_charge: float
    statistics_consumption: list | None
    statistics_rates: list | None

    def __init__(self, last_evaluated: datetime, request_attempts: int, consumption: list, rates: list, standing_charge, last_error: Exception | None = None,
                 statistics_consumption: list | None = None, statistics_rates: list | None = None):
        super().__init__(last_evaluated, request_attempts, REFRESH_RATE_IN_MINUTES_PREVIOUS_CONSUMPTION, None, last_error)
        self.consumption = consumption
        self.rates = rates
        self.standing_charge = standing_charge
        # What to import into long-term statistics: the latest day, or several days when earlier
        # ones are missing from the statistics (e.g. after the integration was down) and need filling in
        self.statistics_consumption = statistics_consumption if statistics_consumption is not None else consumption
        self.statistics_rates = statistics_rates if statistics_rates is not None else rates


async def async_get_statistics_backfill(
    client: EDFEnergyApiClient,
    account_info,
    identifier: str,
    serial_number: str,
    is_electricity: bool,
    tariff,
    complete_days: list,
    period_to: datetime,
    async_get_statistic_hours_by_day,
):
    """Consumption and rates to import into statistics, reaching back to fill in missing days.

    Normally that's just the latest complete day (returns None, None). If an earlier day in the last
    week has no statistics (or only some hours), everything from that day to the latest is returned, so
    the missing day is filled in and the running totals of the days after it are rewritten to match.
    Only an unbroken run of complete days on the same tariff is used, so one set of rates covers it.
    """
    if async_get_statistic_hours_by_day is None or len(complete_days) < 2:
        return None, None

    run = [complete_days[-1]]
    for day, items in reversed(complete_days[:-1]):
        if day != run[0][0] - timedelta(days=1):
            break
        day_tariff = (
            get_electricity_meter_tariff(items[0]["start"], account_info, identifier, serial_number)
            if is_electricity
            else get_gas_meter_tariff(items[0]["start"], account_info, identifier, serial_number)
        )
        if day_tariff is None or day_tariff.code != tariff.code:
            break
        run.insert(0, (day, items))

    if len(run) < 2:
        return None, None

    try:
        hours_by_day = await async_get_statistic_hours_by_day(run[0][1][0]["start"], period_to)
    except Exception:
        _LOGGER.debug("Could not read existing statistics to check for missing days", exc_info=True)
        return None, None

    missing = [day for day, items in run[:-1] if hours_by_day.get(day, 0) < len(items) // 2]
    if not missing:
        return None, None

    window = [items for day, items in run if day >= missing[0]]
    window_consumption = [item for items in window for item in items]
    window_from = window_consumption[0]["start"]
    if is_electricity:
        window_rates = await client.async_get_electricity_rates(tariff.product, tariff.code, window_from, period_to)
    else:
        window_rates = await client.async_get_gas_rates(tariff.product, tariff.code, window_from, period_to)
    if not window_rates:
        return None, None

    kind = "Electricity" if is_electricity else "Gas"
    days_text = ", ".join(day.isoformat() for day in missing)
    _LOGGER.info(f"{kind} {identifier}/{serial_number}: filling in statistics for {days_text} (re-importing {len(window)} days)")
    return window_consumption, window_rates


async def async_fetch_consumption_and_rates(
    previous_data: PreviousConsumptionCoordinatorResult | None,
    current: datetime,
    account_info,
    client: EDFEnergyApiClient,
    identifier: str,
    serial_number: str,
    is_electricity: bool,
    fire_event,
    async_get_statistic_hours_by_day=None,
) -> PreviousConsumptionCoordinatorResult | None:

    if previous_data is not None and current < previous_data.next_refresh:
        return previous_data

    if account_info is None:
        return previous_data

    # Look back over the last few local days and use the latest complete one. Previously this took
    # yesterday in UTC, which during BST ran 1am to 1am and accepted a day with only a few readings.
    today_start = as_utc(as_local(current).replace(hour=0, minute=0, second=0, microsecond=0))
    # Reach back a week further than the latest day, so days missing from the statistics can be filled in
    search_from = as_utc(as_local(current - timedelta(days=STATISTICS_BACKFILL_DAYS + 1)).replace(hour=0, minute=0, second=0, microsecond=0))

    try:
        if is_electricity:
            raw_consumption = await client.async_get_electricity_consumption(identifier, serial_number, search_from, today_start, page_size=500)
        else:
            raw_consumption = await client.async_get_gas_consumption(identifier, serial_number, search_from, today_start, page_size=500)

        complete_days = get_complete_days(raw_consumption)
        consumption_data = complete_days[-1][1] if complete_days else None
        if consumption_data is None:
            _LOGGER.debug(f"{'electricity' if is_electricity else 'gas'} {identifier}/{serial_number}: no complete day of consumption yet")
            return PreviousConsumptionCoordinatorResult(
                current,
                1,
                previous_data.consumption if previous_data is not None else None,
                previous_data.rates if previous_data is not None else None,
                previous_data.standing_charge if previous_data is not None else None,
            )

        period_from = consumption_data[0]["start"]
        period_to = consumption_data[-1]["end"]

        tariff = (
            get_electricity_meter_tariff(period_from, account_info, identifier, serial_number)
            if is_electricity
            else get_gas_meter_tariff(period_from, account_info, identifier, serial_number)
        )
        if tariff is None:
            return previous_data

        if is_electricity:
            rate_data = await client.async_get_electricity_rates(tariff.product, tariff.code, period_from, period_to)
            standing_charge = await client.async_get_electricity_standing_charge(tariff.product, tariff.code, period_from, period_to)
        else:
            rate_data = await client.async_get_gas_rates(tariff.product, tariff.code, period_from, period_to)
            standing_charge = await client.async_get_gas_standing_charge(tariff.product, tariff.code, period_from, period_to)

        _LOGGER.debug(f"{'electricity' if is_electricity else 'gas'} {identifier}/{serial_number}: consumption: {len(consumption_data) if consumption_data is not None else None}; rates: {len(rate_data) if rate_data is not None else None}")

        statistics_consumption, statistics_rates = await async_get_statistics_backfill(
            client, account_info, identifier, serial_number, is_electricity, tariff, complete_days, period_to,
            async_get_statistic_hours_by_day,
        )

        if (consumption_data is not None and
                len(consumption_data) >= MINIMUM_CONSUMPTION_DATA_LENGTH and
                rate_data is not None and
                len(rate_data) > 0 and
                standing_charge is not None):

            consumption_data = __sort_consumption(consumption_data)
            public_rates = private_rates_to_public_rates(rate_data)
            min_max_average = get_min_max_average_rates(public_rates)

            if is_electricity:
                fire_event(EVENT_ELECTRICITY_PREVIOUS_CONSUMPTION_RATES, {
                    "mpan": identifier,
                    "serial_number": serial_number,
                    "tariff_code": tariff.code,
                    "rates": public_rates,
                    "min_rate": min_max_average["min"],
                    "max_rate": min_max_average["max"],
                    "average_rate": min_max_average["average"],
                })
            else:
                fire_event(EVENT_GAS_PREVIOUS_CONSUMPTION_RATES, {
                    "mprn": identifier,
                    "serial_number": serial_number,
                    "tariff_code": tariff.code,
                    "rates": public_rates,
                    "min_rate": min_max_average["min"],
                    "max_rate": min_max_average["max"],
                    "average_rate": min_max_average["average"],
                })

            return PreviousConsumptionCoordinatorResult(
                current, 1, consumption_data, rate_data, standing_charge["value_inc_vat"],
                statistics_consumption=statistics_consumption,
                statistics_rates=statistics_rates,
            )

        return PreviousConsumptionCoordinatorResult(
            current,
            1,
            previous_data.consumption if previous_data is not None else None,
            previous_data.rates if previous_data is not None else None,
            previous_data.standing_charge if previous_data is not None else None,
        )

    except Exception as e:
        if not isinstance(e, ApiException):
            raise

        if previous_data is not None:
            result = PreviousConsumptionCoordinatorResult(
                previous_data.last_evaluated,
                previous_data.request_attempts + 1,
                previous_data.consumption,
                previous_data.rates,
                previous_data.standing_charge,
                last_error=e,
            )
            if result.request_attempts == 2:
                _LOGGER.warning(f"Failed to retrieve previous consumption for {'electricity' if is_electricity else 'gas'} {identifier}/{serial_number} - using cached data.")
        else:
            result = PreviousConsumptionCoordinatorResult(
                current - timedelta(minutes=REFRESH_RATE_IN_MINUTES_PREVIOUS_CONSUMPTION),
                2, None, None, None, last_error=e,
            )
            _LOGGER.warning(f"Failed to retrieve previous consumption for {'electricity' if is_electricity else 'gas'} {identifier}/{serial_number}.")

        return result


async def async_create_previous_consumption_and_rates_coordinator(
    hass,
    account_id: str,
    client: EDFEnergyApiClient,
    identifier: str,
    serial_number: str,
    is_electricity: bool,
):
    """Create previous consumption coordinator."""
    key = f'{identifier}_{serial_number}_previous_consumption_and_rates'

    def statistic_id(account_info):
        if not is_electricity:
            return gas_consumption_statistic_id(serial_number, identifier, True)
        is_export = any(
            meter.get("is_export")
            for point in (account_info or {}).get("electricity_meter_points") or []
            if str(point.get("mpan")) == str(identifier)
            for meter in point.get("meters") or []
            if str(meter.get("serial_number")) == str(serial_number)
        )
        return electricity_consumption_statistic_id(serial_number, identifier, is_export)

    async def async_update_data():
        account_result = hass.data[DOMAIN][account_id].get(DATA_ACCOUNT)
        account_info = account_result.account if account_result is not None else None
        previous_data = hass.data[DOMAIN][account_id].get(key)
        current = utcnow()

        async def async_hours_by_day(start, end):
            return await async_get_statistic_hours_by_day(hass, statistic_id(account_info), start, end)

        result = await async_fetch_consumption_and_rates(
            previous_data,
            current,
            account_info,
            client,
            identifier,
            serial_number,
            is_electricity,
            hass.bus.async_fire,
            async_hours_by_day,
        )

        if result is not None:
            hass.data[DOMAIN][account_id][key] = result

        return hass.data[DOMAIN][account_id].get(key)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=key,
        update_method=async_update_data,
        update_interval=timedelta(seconds=COORDINATOR_REFRESH_IN_SECONDS),
        always_update=True,
    )

    hass.data[DOMAIN][account_id][DATA_PREVIOUS_CONSUMPTION_COORDINATOR_KEY.format(identifier, serial_number)] = coordinator
    return coordinator
