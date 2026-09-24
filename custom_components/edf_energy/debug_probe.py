# TEMPORARY debug probe - remove once meter readings / transactions / direct debit queries are fixed.
# Runs only when config entry diagnostics are downloaded. Read-only queries; IDs are redacted.

import json
import logging
import re

from .api_client import EDFEnergyApiClient

_LOGGER = logging.getLogger(__name__)

_QUERY_FIELD_PATTERN = re.compile(r"reading|transaction|payment|directdebit|schedule", re.IGNORECASE)
_ACCOUNT_FIELD_PATTERN = re.compile(r"transaction|payment|directdebit|schedule|reading", re.IGNORECASE)

_TYPE_REF = "name kind ofType { name kind ofType { name kind ofType { name kind } } }"

_QUERY_FIELDS = f'''query {{
  __schema {{
    queryType {{
      fields {{
        name
        args {{ name type {{ {_TYPE_REF} }} }}
        type {{ {_TYPE_REF} }}
      }}
    }}
  }}
}}'''

_TYPE_QUERY = f'''query ($name: String!) {{
  __type(name: $name) {{
    name
    kind
    fields {{ name args {{ name type {{ {_TYPE_REF} }} }} type {{ {_TYPE_REF} }} }}
    possibleTypes {{ name }}
  }}
}}'''

_EXTRA_TYPES = [
  "AccountType",
  "TransactionType",
  "Payment",
  "Charge",
  "Credit",
  "Refund",
  "TransactionAmountType",
  "DirectDebitInstructionType",
  "PaymentScheduleType",
]

_ELEC_READINGS = '''query ($accountNumber: String!, $meterId: String!) {
  electricityMeterReadings(accountNumber: $accountNumber, meterId: $meterId, %s) {
    edges { node { readAt registers { identifier value } } }
  }
}'''

_ELEC_READINGS_MINIMAL = '''query ($accountNumber: String!, $meterId: String!) {
  electricityMeterReadings(accountNumber: $accountNumber, meterId: $meterId, first: 3) {
    edges { node { readAt } }
  }
}'''

_GAS_READINGS = '''query ($accountNumber: String!, $meterId: String!) {
  gasMeterReadings(accountNumber: $accountNumber, meterId: $meterId, %s) {
    edges { node { readAt registers { identifier value } } }
  }
}'''

_TRANSACTIONS = '''query ($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    transactions(first: 5) {
      edges {
        node {
          __typename
          postedDate
          title
          isCredit
          ... on Payment { amounts { gross net tax } }
          ... on Charge { amounts { gross net tax } }
        }
      }
    }
  }
}'''

_PAYMENT_SCHEDULES = '''query ($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    paymentSchedules(first: 3) {
      edges { node { paymentAmount paymentDay validFrom validTo isVariablePaymentAmount } }
    }
  }
}'''


def _unwrap_type_name(type_ref):
  while type_ref is not None:
    if type_ref.get("name"):
      return type_ref["name"]
    type_ref = type_ref.get("ofType")
  return None


def _filter_type(type_body, pattern):
  if not type_body or not type_body.get("fields") or pattern is None:
    return type_body
  filtered = dict(type_body)
  filtered["fields"] = [f for f in type_body["fields"] if pattern.search(f["name"])]
  return filtered


async def _run(client: EDFEnergyApiClient, query: str, variables=None):
  try:
    return await client.async_debug_graphql(query, variables)
  except Exception as e:
    return {"exception": f"{type(e).__name__}: {e}"}


async def async_run_debug_probe(client: EDFEnergyApiClient, account_id: str, account_info: dict | None):
  results = {}
  sensitive = {account_id: "ACCOUNT"}

  # 1. Schema: query fields relating to readings / transactions / payments
  schema = await _run(client, _QUERY_FIELDS)
  type_names = set(_EXTRA_TYPES)
  try:
    fields = schema["body"]["data"]["__schema"]["queryType"]["fields"]
    matching = [f for f in fields if _QUERY_FIELD_PATTERN.search(f["name"])]
    results["schema_query_fields"] = matching
    for f in matching:
      name = _unwrap_type_name(f.get("type"))
      if name:
        type_names.add(name)
  except Exception:
    results["schema_query_fields"] = schema

  # 2. Schema: the types involved (AccountType filtered to relevant fields)
  types = {}
  for name in sorted(type_names):
    res = await _run(client, _TYPE_QUERY, {"name": name})
    body = res.get("body", {}).get("data", {}).get("__type") if isinstance(res.get("body"), dict) else None
    if body is None:
      types[name] = res.get("body", res)
      continue
    types[name] = _filter_type(body, _ACCOUNT_FIELD_PATTERN) if name == "AccountType" else body
    # Follow connection -> edge -> node types one level for reading/transaction connections
    for field in body.get("fields") or []:
      inner = _unwrap_type_name(field.get("type"))
      if inner and inner not in type_names and re.search(r"reading|edge|transaction|register", inner, re.IGNORECASE):
        inner_res = await _run(client, _TYPE_QUERY, {"name": inner})
        types[inner] = inner_res.get("body", {}).get("data", {}).get("__type") if isinstance(inner_res.get("body"), dict) else inner_res
  results["schema_types"] = types

  # 3. Meter reading query variants
  readings = {}
  for point in (account_info or {}).get("electricity_meter_points", []) or []:
    mpan = str(point.get("mpan"))
    sensitive[mpan] = f"MPAN_{len(sensitive)}"
    for meter in point.get("meters", []):
      serial = str(meter.get("serial_number"))
      sensitive[serial] = f"SERIAL_{len(sensitive)}"
      label = f"elec_{'export' if meter.get('is_export') else 'import'}"
      readings[f"{label}_serial_last5"] = await _run(client, _ELEC_READINGS % "last: 5", {"accountNumber": account_id, "meterId": serial})
      readings[f"{label}_serial_first5"] = await _run(client, _ELEC_READINGS % "first: 5", {"accountNumber": account_id, "meterId": serial})
      readings[f"{label}_serial_minimal"] = await _run(client, _ELEC_READINGS_MINIMAL, {"accountNumber": account_id, "meterId": serial})
      readings[f"{label}_mpan_first5"] = await _run(client, _ELEC_READINGS % "first: 5", {"accountNumber": account_id, "meterId": mpan})
      if meter.get("device_id"):
        sensitive[str(meter["device_id"])] = f"DEVICE_{len(sensitive)}"
        readings[f"{label}_device_first5"] = await _run(client, _ELEC_READINGS % "first: 5", {"accountNumber": account_id, "meterId": str(meter["device_id"])})

  for point in (account_info or {}).get("gas_meter_points", []) or []:
    mprn = str(point.get("mprn"))
    sensitive[mprn] = f"MPRN_{len(sensitive)}"
    for meter in point.get("meters", []):
      serial = str(meter.get("serial_number"))
      sensitive[serial] = f"SERIAL_{len(sensitive)}"
      readings["gas_serial_last5"] = await _run(client, _GAS_READINGS % "last: 5", {"accountNumber": account_id, "meterId": serial})
      readings["gas_serial_first5"] = await _run(client, _GAS_READINGS % "first: 5", {"accountNumber": account_id, "meterId": serial})
      readings["gas_mprn_first5"] = await _run(client, _GAS_READINGS % "first: 5", {"accountNumber": account_id, "meterId": mprn})
      if meter.get("device_id"):
        sensitive[str(meter["device_id"])] = f"DEVICE_{len(sensitive)}"
  results["meter_readings"] = readings

  # 4. Transactions and payment schedules (raw)
  results["transactions"] = await _run(client, _TRANSACTIONS, {"accountNumber": account_id})
  results["payment_schedules"] = await _run(client, _PAYMENT_SCHEDULES, {"accountNumber": account_id})

  # Redact account number, MPANs, MPRNs, serials and device IDs anywhere in the output
  text = json.dumps(results, default=str)
  for value, token in sorted(sensitive.items(), key=lambda kv: -len(kv[0])):
    if value and value != "None":
      text = re.sub(re.escape(value), token, text, flags=re.IGNORECASE)
  return json.loads(text)
