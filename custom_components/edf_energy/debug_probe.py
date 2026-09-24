# TEMPORARY debug probe - remove once meter readings / transactions / direct debit queries are fixed.
# Runs only when config entry diagnostics are downloaded. Read-only queries; IDs are redacted.

import json
import logging
import re
from datetime import timedelta

from homeassistant.util.dt import now

from .api_client import EDFEnergyApiClient

_LOGGER = logging.getLogger(__name__)

_TYPE_REF = "name kind ofType { name kind ofType { name kind ofType { name kind } } }"

_TYPE_QUERY = f'''query ($name: String!) {{
  __type(name: $name) {{
    name
    kind
    fields {{ name args {{ name type {{ {_TYPE_REF} }} }} type {{ {_TYPE_REF} }} }}
    enumValues {{ name }}
  }}
}}'''

_TYPES = [
  "ElectricityMeterReadingType",
  "GasMeterReadingType",
  "MeterReadingEventType",
  "TransactionTypeFilter",
  "ElectricityMeterType",
  "GasMeterType",
]

_METER_IDS = '''query ($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    electricityAgreements(active: true) {
      meterPoint { mpan direction meters(includeInactive: false) { id serialNumber } }
    }
    gasAgreements(active: true) {
      meterPoint { mprn meters(includeInactive: false) { id serialNumber } }
    }
  }
}'''

_READINGS = '''query ($accountNumber: String!, $meterId: String!, $readFrom: DateTime) {
  %s(accountNumber: $accountNumber, meterId: $meterId, readFrom: $readFrom, first: 5) {
    totalCount
    edges { node { %s } }
  }
}'''

_PAYMENTS = '''query ($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    transactions(first: 3, transactionTypes: [PAYMENT]) {
      edges { node { __typename postedDate title isCredit amounts { gross } ... on Payment { paymentTransactionType } } }
    }
  }
}'''


async def _run(client: EDFEnergyApiClient, query: str, variables=None):
  try:
    return await client.async_debug_graphql(query, variables)
  except Exception as e:
    return {"exception": f"{type(e).__name__}: {e}"}


def _node_fields(type_body):
  """Build a selection of scalar fields (plus registers sub-fields) for a reading node type."""
  scalars = []
  for field in (type_body or {}).get("fields") or []:
    kind = field["type"].get("kind")
    inner = field["type"].get("ofType") or {}
    if kind == "SCALAR" or kind == "ENUM" or (kind == "NON_NULL" and inner.get("kind") in ("SCALAR", "ENUM")):
      if not field.get("args"):
        scalars.append(field["name"])
  return " ".join(scalars) or "__typename"


async def async_run_debug_probe(client: EDFEnergyApiClient, account_id: str, account_info: dict | None):
  results = {}
  sensitive = {account_id: "ACCOUNT"}

  # 1. Reading, meter and filter types
  types = {}
  for name in _TYPES:
    res = await _run(client, _TYPE_QUERY, {"name": name})
    body = res.get("body") if isinstance(res.get("body"), dict) else None
    types[name] = (body or {}).get("data", {}).get("__type") if body else res
  # Also the register type used by readings, if any
  for reading_type in ("ElectricityMeterReadingType", "GasMeterReadingType"):
    for field in (types.get(reading_type) or {}).get("fields") or []:
      ref = field["type"]
      while ref and not ref.get("name"):
        ref = ref.get("ofType")
      if ref and ref.get("kind") == "OBJECT" and ref["name"] not in types:
        res = await _run(client, _TYPE_QUERY, {"name": ref["name"]})
        body = res.get("body") if isinstance(res.get("body"), dict) else None
        types[ref["name"]] = (body or {}).get("data", {}).get("__type") if body else res
  results["types"] = types

  # 2. Internal meter IDs
  meter_ids = await _run(client, _METER_IDS, {"accountNumber": account_id})
  results["meter_ids"] = meter_ids

  # 3. Readings using internal IDs (and serials again, with a readFrom window)
  elec_fields = _node_fields(types.get("ElectricityMeterReadingType"))
  gas_fields = _node_fields(types.get("GasMeterReadingType"))
  read_from = (now() - timedelta(days=60)).isoformat()
  readings = {}
  try:
    account = meter_ids["body"]["data"]["account"]
  except Exception:
    account = None

  for agreement in (account or {}).get("electricityAgreements") or []:
    point = agreement.get("meterPoint") or {}
    sensitive[str(point.get("mpan"))] = f"MPAN_{len(sensitive)}"
    label = f"elec_{(point.get('direction') or 'unknown').lower()}"
    for meter in point.get("meters") or []:
      sensitive[str(meter.get("serialNumber"))] = f"SERIAL_{len(sensitive)}"
      sensitive[str(meter.get("id"))] = f"METERID_{len(sensitive)}"
      readings[f"{label}_id"] = await _run(client, _READINGS % ("electricityMeterReadings", elec_fields), {"accountNumber": account_id, "meterId": str(meter.get("id")), "readFrom": read_from})
      readings[f"{label}_id_no_window"] = await _run(client, _READINGS % ("electricityMeterReadings", elec_fields), {"accountNumber": account_id, "meterId": str(meter.get("id")), "readFrom": None})
      readings[f"{label}_serial_window"] = await _run(client, _READINGS % ("electricityMeterReadings", elec_fields), {"accountNumber": account_id, "meterId": str(meter.get("serialNumber")), "readFrom": read_from})

  for agreement in (account or {}).get("gasAgreements") or []:
    point = agreement.get("meterPoint") or {}
    sensitive[str(point.get("mprn"))] = f"MPRN_{len(sensitive)}"
    for meter in point.get("meters") or []:
      sensitive[str(meter.get("serialNumber"))] = f"SERIAL_{len(sensitive)}"
      sensitive[str(meter.get("id"))] = f"METERID_{len(sensitive)}"
      readings["gas_id"] = await _run(client, _READINGS % ("gasMeterReadings", gas_fields), {"accountNumber": account_id, "meterId": str(meter.get("id")), "readFrom": read_from})
      readings["gas_id_no_window"] = await _run(client, _READINGS % ("gasMeterReadings", gas_fields), {"accountNumber": account_id, "meterId": str(meter.get("id")), "readFrom": None})
      readings["gas_serial_window"] = await _run(client, _READINGS % ("gasMeterReadings", gas_fields), {"accountNumber": account_id, "meterId": str(meter.get("serialNumber")), "readFrom": read_from})
  results["readings"] = readings
  results["reading_fields_used"] = {"electricity": elec_fields, "gas": gas_fields}

  # 4. Payments only, via the transactionTypes filter
  results["payments"] = await _run(client, _PAYMENTS, {"accountNumber": account_id})

  # Also redact any IDs the integration already knows about
  for point in (account_info or {}).get("electricity_meter_points", []) or []:
    sensitive[str(point.get("mpan"))] = f"MPAN_{len(sensitive)}"
    for meter in point.get("meters", []):
      sensitive[str(meter.get("serial_number"))] = f"SERIAL_{len(sensitive)}"
      if meter.get("device_id"):
        sensitive[str(meter["device_id"])] = f"DEVICE_{len(sensitive)}"
  for point in (account_info or {}).get("gas_meter_points", []) or []:
    sensitive[str(point.get("mprn"))] = f"MPRN_{len(sensitive)}"
    for meter in point.get("meters", []):
      sensitive[str(meter.get("serial_number"))] = f"SERIAL_{len(sensitive)}"
      if meter.get("device_id"):
        sensitive[str(meter["device_id"])] = f"DEVICE_{len(sensitive)}"

  text = json.dumps(results, default=str)
  for value, token in sorted(sensitive.items(), key=lambda kv: -len(kv[0])):
    if value and value != "None" and len(value) >= 4:
      text = re.sub(r'(?<![A-Za-z0-9])' + re.escape(value) + r'(?![A-Za-z0-9])', token, text, flags=re.IGNORECASE)
  return json.loads(text)
