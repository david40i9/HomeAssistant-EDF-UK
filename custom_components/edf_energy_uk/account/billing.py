# EDF Energy / Kraken API: payment forecast, statements, rewards and direct debit review

import logging

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import RestoreSensor, SensorDeviceClass, SensorStateClass

from ..coordinators.account_transactions import AccountTransactionsCoordinatorResult
from ..utils.attributes import dict_to_typed_dict
from .balance import EDFEnergyAccountSensor

_LOGGER = logging.getLogger(__name__)


def _pounds(pence):
    return round(pence / 100, 2) if pence is not None else None


class EDFEnergyBillingSensor(CoordinatorEntity, EDFEnergyAccountSensor, RestoreSensor):
    """Base for money sensors fed by the account billing data. Subclasses implement _update(billing)."""

    _key = None
    _label = None
    _icon = None

    def __init__(self, hass: HomeAssistant, coordinator, account_id: str):
        CoordinatorEntity.__init__(self, coordinator)
        EDFEnergyAccountSensor.__init__(self, hass, account_id)
        self._state = None

    @property
    def unique_id(self):
        return f"edf_energy_{self._account_id}_{self._key}"

    @property
    def name(self):
        return f"EDF {self._label} ({self._account_id})"

    @property
    def device_class(self):
        return SensorDeviceClass.MONETARY

    @property
    def state_class(self):
        return SensorStateClass.TOTAL

    @property
    def native_unit_of_measurement(self):
        return "GBP"

    @property
    def icon(self):
        return self._icon

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def native_value(self):
        return self._state

    def _update(self, billing: dict):
        raise NotImplementedError

    @callback
    def _handle_coordinator_update(self) -> None:
        result: AccountTransactionsCoordinatorResult = (
            self.coordinator.data
            if self.coordinator is not None and self.coordinator.data is not None
            else None
        )
        if result is not None and result.billing is not None:
            self._update(result.billing)
        self._attributes = dict_to_typed_dict(self._attributes)
        super()._handle_coordinator_update()

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        state = await self.async_get_last_state()
        last_sensor_state = await self.async_get_last_sensor_data()
        if state is not None and last_sensor_state is not None and self._state is None:
            self._state = None if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) else last_sensor_state.native_value
            self._attributes = dict_to_typed_dict(state.attributes)
            _LOGGER.debug(f'Restored {self.__class__.__name__} state: {self._state}')


class EDFEnergyNextPayment(EDFEnergyBillingSensor):
    """Amount of the next scheduled payment, with its date and the following payments."""

    _key = "next_payment"
    _label = "Next Payment"
    _icon = "mdi:calendar-cash"

    def _update(self, billing: dict):
        forecast = billing.get("payment_forecast") or []
        if not forecast:
            self._state = None
            self._attributes.update({"date": None, "method": None, "upcoming": []})
            return
        self._state = _pounds(forecast[0].get("amount"))
        self._attributes.update({
            "date": forecast[0].get("date"),
            "method": forecast[0].get("method"),
            "upcoming": [
                {"date": p.get("date"), "amount": _pounds(p.get("amount")), "method": p.get("method")}
                for p in forecast
            ],
        })


class EDFEnergyLastStatement(EDFEnergyBillingSensor):
    """Net amount of the most recent statement (bill): positive when it charged the account, negative when
    it credited it. EDF credits export payments as negative electricity charges, so an export-only
    statement is negative. Each charge and credit line is listed with its VAT."""

    _key = "last_statement"
    _label = "Last Statement"
    _icon = "mdi:file-document-outline"

    def _update(self, billing: dict):
        bill = billing.get("last_bill")
        if bill is None:
            return
        charges = bill.get("total_charges")
        credits = bill.get("total_credits") or 0
        self._state = _pounds(charges - credits) if charges is not None else None

        lines = []
        payments = []
        for t in bill.get("transactions") or []:
            sign = -1 if t.get("is_credit") and t.get("type") != "Payment" else 1
            item = {
                "title": t.get("title"),
                "type": t.get("type"),
                "posted_date": t.get("posted_date"),
                "net": _pounds(sign * t["net"]) if t.get("net") is not None else None,
                "vat": _pounds(sign * t["tax"]) if t.get("tax") is not None else None,
                "total": _pounds(sign * t["gross"]) if t.get("gross") is not None else None,
            }
            # Payments are reported with the statement but aren't part of what it charges
            (payments if t.get("type") == "Payment" else lines).append(item)

        self._attributes.update({
            "bill_type": bill.get("bill_type"),
            "from_date": bill.get("from_date"),
            "to_date": bill.get("to_date"),
            "issued_date": bill.get("issued_date"),
            "payment_due_date": bill.get("payment_due_date"),
            "opening_balance": _pounds(bill.get("opening_balance")),
            "closing_balance": _pounds(bill.get("closing_balance")),
            "charges": _pounds(charges),
            "charges_before_vat": _pounds(bill.get("total_charges_net")),
            "vat": _pounds(bill.get("total_charges_tax")),
            "credits": _pounds(credits),
            "is_credit": charges is not None and charges - credits < 0,
            "lines": lines,
            "payments": payments,
            "is_final": bill.get("is_final"),
        })


class EDFEnergySuggestedDirectDebit(EDFEnergyBillingSensor):
    """Direct debit amount EDF's payment review suggests, with the minimum it would accept."""

    _key = "suggested_direct_debit"
    _label = "Suggested Direct Debit"
    _icon = "mdi:scale-balance"

    def _update(self, billing: dict):
        self._state = _pounds(billing.get("suggested_direct_debit"))
        self._attributes.update({
            "minimum_amount": _pounds(billing.get("minimum_direct_debit")),
        })


class EDFEnergyRewards(EDFEnergyBillingSensor):
    """Total of the account's rewards (e.g. refer a friend), with each reward listed."""

    _key = "rewards"
    _label = "Rewards"
    _icon = "mdi:gift-outline"

    def _update(self, billing: dict):
        rewards = billing.get("rewards") or []
        self._state = _pounds(sum(r.get("amount") or 0 for r in rewards))
        self._attributes.update({
            "referrals_created": billing.get("referrals_created"),
            "rewards": [
                {
                    "payment_date": r.get("payment_date"),
                    "scheme_type": r.get("scheme_type"),
                    "amount": _pounds(r.get("amount")),
                    "payment_status": r.get("payment_status"),
                }
                for r in rewards
            ],
        })


class EDFEnergyTextBillingSensor(EDFEnergyBillingSensor):
    """Base for non-money sensors fed by the account billing data."""

    @property
    def device_class(self):
        return None

    @property
    def state_class(self):
        return None

    @property
    def native_unit_of_measurement(self):
        return None


class EDFEnergySmartMeterDataFrequency(EDFEnergyTextBillingSensor):
    """How often EDF may collect smart meter readings (HALF_HOURLY, DAILY or MONTHLY).

    Half-hourly consumption, costs and Energy dashboard statistics need HALF_HOURLY. It can be changed
    in the EDF account's smart meter data settings.
    """

    _key = "smart_meter_data_frequency"
    _label = "Smart Meter Data Frequency"
    _icon = "mdi:meter-electric-outline"

    @property
    def entity_category(self):
        return EntityCategory.DIAGNOSTIC

    def _update(self, billing: dict):
        self._state = billing.get("smart_meter_reading_frequency")


class EDFEnergyCampaigns(EDFEnergyTextBillingSensor):
    """Number of EDF campaigns (schemes and account processes) the account is enrolled in, each listed."""

    _key = "campaigns"
    _label = "Campaigns"
    _icon = "mdi:bullhorn-outline"

    def _update(self, billing: dict):
        campaigns = billing.get("campaigns") or []
        self._state = len(campaigns)
        self._attributes.update({"campaigns": campaigns})
