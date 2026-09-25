import asyncio
import base64
import logging
import json
from typing import Any, List
import aiohttp
from asyncio import TimeoutError
from datetime import (datetime, timedelta, time, timezone)
from threading import RLock
from zoneinfo import ZoneInfo
from homeassistant.util.dt import (as_utc, now, as_local, parse_datetime, parse_date)
from ..const import INTEGRATION_VERSION

_LOGGER = logging.getLogger(__name__)

# Modified from HomeAssistant-OctopusEnergy by BottlecapDave (MIT)
# Modified by [your name] [year] — adapted for EDF Energy / Kraken API

user_agent_value = "bobby5291-ha-edf-energy"

EDF_BASE_URL = "https://api.edfgb-kraken.energy"

# Kraken rate limits token retrieval. A failed attempt doesn't update our token expiry, so without a
# cooldown every following request retries the login, which keeps the rate limit tripped.
# Ported from HomeAssistant-OctopusEnergy.
MINIMUM_TOKEN_RETRIEVAL_COOLDOWN_IN_MINUTES = 1
MAXIMUM_TOKEN_RETRIEVAL_COOLDOWN_IN_MINUTES = 30


def calculate_token_retrieval_cooldown(failure_count: int) -> timedelta:
  """How long to wait before retrying token retrieval after consecutive server failures."""
  if (failure_count < 1):
    return timedelta(minutes=0)

  minutes = MINIMUM_TOKEN_RETRIEVAL_COOLDOWN_IN_MINUTES * (2 ** (failure_count - 1))
  return timedelta(minutes=min(minutes, MAXIMUM_TOKEN_RETRIEVAL_COOLDOWN_IN_MINUTES))

api_token_query = '''mutation ObtainKrakenToken($email: String!, $password: String!) {
  obtainKrakenToken(input: { email: $email, password: $password }) {
    token
    refreshToken
    refreshExpiresIn
  }
}'''

api_token_refresh_query = '''mutation ObtainKrakenTokenFromRefreshToken($refreshToken: String!) {
  obtainKrakenToken(input: { refreshToken: $refreshToken }) {
    token
    refreshToken
    refreshExpiresIn
  }
}'''

extended_electricity_consumption_query = '''query ExtendedAnnualElectricityConsumption($mpan: String!) {
  extendedAnnualElectricityConsumption(mpan: $mpan) {
    eacStandard
    eacDay
    eacNight
  }
}'''

annual_gas_consumption_query = '''query AnnualGasConsumption($mprn: String!) {
  annualGasConsumption(mprn: $mprn) {
    aq
    supplierName
    supplierEffectiveFromDate
    aqEffectiveFromDate
  }
}'''

account_query = '''query {{
  account(accountNumber: "{account_id}") {{
    balance
    overdueBalance
    projectedBalance
    shouldReviewPayments
    recommendedBalanceAdjustment
    canRenewTariff
    directDebitInstructions(first: 1) {{
      edges {{
        node {{
          status
        }}
      }}
    }}
    paymentSchedules(active: true, first: 1) {{
      edges {{
        node {{
          paymentAmount
          paymentDay
        }}
      }}
    }}

    electricityAgreements(active: true) {{
      meterPoint {{
        mpan
        direction
        meters(includeInactive: false) {{
          activeFrom
          activeTo
          id
          serialNumber
          makeAndType
          meterType
          smartImportElectricityMeter {{
            deviceId
            manufacturer
            model
            firmwareVersion
          }}
          smartExportElectricityMeter {{
            deviceId
            manufacturer
            model
            firmwareVersion
          }}
        }}
        agreements(includeInactive: false) {{
          validFrom
          validTo
          tariff {{
            __typename
            ... on TariffType {{
              productCode
              tariffCode
              displayName
            }}
            ... on HalfHourlyTariff {{
              productCode
              tariffCode
              displayName
              standingCharge
              unitRates {{
                value
                validFrom
                validTo
              }}
            }}
            ... on StandardTariff {{
              unitRate
              standingCharge
            }}
            ... on DayNightTariff {{
              productCode
              tariffCode
              displayName
              standingCharge
            }}
            ... on FourRateEvTariff {{
              productCode
              tariffCode
              displayName
            }}
            ... on PrepayTariff {{
              productCode
              tariffCode
              displayName
              unitRate
              standingCharge
            }}
          }}
        }}
      }}
    }}

    gasAgreements(active: true) {{
      meterPoint {{
        mprn
        meters(includeInactive: false) {{
          activeFrom
          activeTo
          id
          serialNumber
          consumptionUnits
          modelName
          mechanism
          smartGasMeter {{
            deviceId
            manufacturer
            model
            firmwareVersion
          }}
        }}
        agreements(includeInactive: false) {{
          validFrom
          validTo
          tariff {{
            __typename
            ... on TariffType {{
              tariffCode
              productCode
            }}
            ... on GasTariffType {{
              unitRate
              standingCharge
            }}
          }}
        }}
      }}
    }}
  }}
}}'''

transactions_query = '''query AccountTransactions($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    transactions(first: 10) {
      edges {
        node {
          __typename
          postedDate
          ... on Payment {
            amounts { gross }
            isCredit
            title
          }
          ... on Charge {
            amounts { gross }
            isCredit
            title
          }
        }
      }
    }
  }
}'''

billing_query = '''query AccountBilling($accountNumber: String!) {
  account(accountNumber: $accountNumber) {
    paginatedPaymentForecast(first: 3) {
      edges { node { date amount method } }
    }
    bills(first: 1, includeOpenStatements: false) {
      edges {
        node {
          __typename
          billType
          fromDate
          toDate
          issuedDate
          ... on StatementType {
            openingBalance
            closingBalance
            paymentDueDate
            isFinal
            totalCharges { grossTotal }
            totalCredits { grossTotal }
          }
        }
      }
    }
    rewards { paymentDate schemeType rewardAmount paymentStatus }
    referralsCreated
    paymentAdequacy { suggestedDirectDebitAmount minimumDirectDebitAmount }
    campaigns { name slug startDate expiryDate }
  }
  smartMeterDataPreferences(accountNumber: $accountNumber) { readingFrequency }
}'''

applicable_rates_query = '''query ApplicableRates($accountNumber: String!, $mpxn: String!, $startAt: DateTime!, $endAt: DateTime!, $after: String) {
  applicableRates(accountNumber: $accountNumber, mpxn: $mpxn, startAt: $startAt, endAt: $endAt, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { value validFrom validTo } }
  }
}'''

export_measurements_query = '''query ExportMeasurements($accountNumber: String!, $mpan: String!, $startAt: DateTime, $endAt: DateTime, $after: String) {
  account(accountNumber: $accountNumber) {
    properties {
      measurements(first: 100, after: $after, startAt: $startAt, endAt: $endAt, utilityFilters: [{electricityFilters: {readingDirection: GENERATION, readingFrequencyType: THIRTY_MIN_INTERVAL, marketSupplyPointId: $mpan}}]) {
        pageInfo { hasNextPage endCursor }
        edges {
          node {
            value
            ... on IntervalMeasurementType { startAt endAt }
          }
        }
      }
    }
  }
}'''

electricity_meter_readings_query = '''query ElectricityMeterReadings($accountNumber: String!, $meterId: String!, $first: Int) {
  electricityMeterReadings(accountNumber: $accountNumber, meterId: $meterId, first: $first) {
    edges {
      node {
        readAt
        registers {
          identifier
          name
          value
          isQuarantined
        }
      }
    }
  }
}'''

gas_meter_readings_query = '''query GasMeterReadings($accountNumber: String!, $meterId: String!, $first: Int) {
  gasMeterReadings(accountNumber: $accountNumber, meterId: $meterId, first: $first) {
    edges {
      node {
        readAt
        registers {
          identifier
          name
          value
          isQuarantined
        }
      }
    }
  }
}'''




integration_context_header = "Ha-Integration-Context"


def get_valid_from(rate):
  return rate["valid_from"]

def get_start(rate):
  return (rate["start"].timestamp(), rate["start"].fold)

def _payment_method_is_favoured(payment_method: str, favour_direct_debit_rates: bool):
  return (payment_method.lower() == "direct_debit") == (favour_direct_debit_rates == True)

def _favoured_payment_method_available(items, favour_direct_debit_rates: bool):
  """Whether the favoured payment method appears anywhere in the data. The other method is only
  excluded when the favoured one is present, so tariffs that publish a single payment method
  (e.g. dynamic tariffs that are direct debit only) still produce rates.
  From stevekirtley/HomeAssistant-EDFEnergy (MIT)."""
  return any(item.get("payment_method") is not None and _payment_method_is_favoured(item["payment_method"], favour_direct_debit_rates) for item in items)

def _should_skip_for_payment_method(item, favour_direct_debit_rates: bool, favoured_available: bool):
  payment_method = item.get("payment_method")
  if payment_method is None:
    return False
  return favoured_available and not _payment_method_is_favoured(payment_method, favour_direct_debit_rates)

def rates_to_thirty_minute_increments(data, period_from: datetime, period_to: datetime, tariff_code: str, price_cap: float = None, favour_direct_debit_rates = True):
  """Process the collection of rates to ensure they're in 30 minute periods"""
  starting_period_from = period_from
  results = []
  if ("results" in data):
    items = data["results"]
    items.sort(key=get_valid_from)

    favoured_available = _favoured_payment_method_available(items, favour_direct_debit_rates)

    for item in items:
      # EDF returns separate direct debit and non direct debit prices - only use the ones that apply (ported from Octopus Energy)
      if _should_skip_for_payment_method(item, favour_direct_debit_rates, favoured_available):
        continue

      value_inc_vat = float(item["value_inc_vat"])

      is_capped = False
      if (price_cap is not None and value_inc_vat > price_cap):
        value_inc_vat = price_cap
        is_capped = True

      if "valid_from" in item and item["valid_from"] is not None:
        valid_from = as_utc(parse_datetime(item["valid_from"]))
        if (valid_from < starting_period_from):
          valid_from = starting_period_from
      else:
        valid_from = starting_period_from

      if "valid_to" in item and item["valid_to"] is not None:
        target_date = as_utc(parse_datetime(item["valid_to"]))
        if (target_date > period_to):
          target_date = period_to
      else:
        target_date = period_to

      while valid_from < target_date:
        valid_to = valid_from + timedelta(minutes=30)
        results.append({
          "value_inc_vat": value_inc_vat,
          "start": valid_from,
          "end": valid_to,
          "tariff_code": tariff_code,
          "is_capped": is_capped
        })
        valid_from = valid_to
        starting_period_from = valid_to

  return results

def get_standing_charge(data: list, tariff_code: str, favour_direct_debit_rates: bool = True):
  favoured_available = _favoured_payment_method_available(data, favour_direct_debit_rates)
  for item in data:
    if _should_skip_for_payment_method(item, favour_direct_debit_rates, favoured_available):
      continue

    return {
      "start": parse_datetime(item["valid_from"]) if "valid_from" in item and item["valid_from"] is not None else None,
      "end": parse_datetime(item["valid_to"]) if "valid_to" in item and item["valid_to"] is not None else None,
      "value_inc_vat": float(item["value_inc_vat"]),
      "tariff_code": tariff_code,
    }
  return None


class ApiException(Exception): ...

class ServerException(ApiException): ...

class TimeoutException(ApiException): ...

class RequestException(ApiException):
  errors: list[str]

  def __init__(self, message: str, errors: list[str]):
    super().__init__(message)
    self.errors = errors

class AuthenticationException(RequestException): ...


def process_graphql_response(data: Any, url: str, request_context: str, ignore_errors: bool, accepted_error_codes: list[str], expected_error_codes: list[str] = []):
  if ("graphql" in url and "errors" in data and ignore_errors == False):
    msg = f'Errors in request ({url}) ({request_context}): {data["errors"]}'
    errors = list(map(lambda error: error["message"].strip(".,!"), data["errors"]))
    errors_as_string = ', '.join(errors)
    error_codes = [(error.get("extensions") or {}).get("errorCode") for error in data["errors"]]
    if expected_error_codes and all(code in expected_error_codes for code in error_codes):
      # Known responses for some accounts (e.g. data EDF doesn't provide) - log quietly to avoid spam
      _LOGGER.debug(msg)
    else:
      _LOGGER.warning(msg)

    for error in data["errors"]:
      if ("extensions" in error and
          "errorCode" in error["extensions"] and
          error["extensions"]["errorCode"] in ("KT-CT-1138", "KT-CT-1139", "KT-CT-1111", "KT-CT-1143", "KT-CT-1134", "KT-CT-1135")):
        raise AuthenticationException(f"Authentication failed - {errors_as_string}. See logs for more details.", errors)

      if ("extensions" in error and
          "errorCode" in error["extensions"] and
          error["extensions"]["errorCode"] in accepted_error_codes):
        return None

    raise RequestException(f"Failed - {errors_as_string}. See logs for more details.", errors)

  return data


class EDFEnergyApiClient:
  _session_lock = RLock()

  def __init__(self, email: str, password: str, timeout_in_seconds = 20):
    if email is None:
      raise Exception('Email is not set')
    if password is None:
      raise Exception('Password is not set')

    # Trim whitespace picked up when pasting the email address, which EDF rejects as invalid credentials
    self._email = email.strip()
    self._password = password
    self._base_url = EDF_BASE_URL

    self._graphql_token = None
    self._graphql_expiration = None
    self._graphql_refresh_token = None
    self._graphql_refresh_expiration = None
    self._refresh_token_lock = asyncio.Lock()
    self._token_retrieval_failures = 0
    self._token_retrieval_cooldown_until = None

    self._timeout = aiohttp.ClientTimeout(total=None, sock_connect=timeout_in_seconds, sock_read=timeout_in_seconds)
    self._default_headers = { "user-agent": f'{user_agent_value}/{INTEGRATION_VERSION}' }

    self._session = None
    # Kraken internal meter IDs keyed by (mpan/mprn, serial number), needed for meter readings queries
    self._meter_ids = {}
    # Unit rate / standing charge from each agreement, keyed by tariff code (see __record_agreement_rates)
    self._agreement_rates = {}
    # Tariffs the REST product endpoints refused, so we go straight to the agreement rates
    self._unavailable_product_tariffs = set()
    # Export MPAN -> account number, for reading export consumption from GraphQL measurements
    self._export_mpans = {}
    # Tariff code -> (account number, MPAN/MPRN, is export), for pricing from applicableRates
    self._tariff_supply_points = {}
    # Whether to use direct debit prices from the product endpoints. Updated from the account's
    # direct debit status when it loads; defaults to direct debit as most accounts pay that way.
    self._favour_direct_debit_rates = True

  @property
  def auth_token_expiry(self):
    """Datetime the current GraphQL auth token expires, or None if not yet authenticated."""
    return self._graphql_expiration

  async def async_close(self):
    with self._session_lock:
      if self._session is not None:
        await self._session.close()

  def _create_client_session(self):
    if self._session is not None:
      return self._session

    with self._session_lock:
      if self._session is not None:
        return self._session

      self._session = aiohttp.ClientSession(headers=self._default_headers, skip_auto_headers=['User-Agent'])
      return self._session

  async def async_refresh_token(self):
    """Refresh user token"""
    if (self._graphql_expiration is not None and (self._graphql_expiration - timedelta(minutes=5)) > now()):
      return

    async with self._refresh_token_lock:
      # Check that our token wasn't refreshed while waiting for the lock
      if (self._graphql_expiration is not None and (self._graphql_expiration - timedelta(minutes=5)) > now()):
        return

      if (self._token_retrieval_cooldown_until is not None and self._token_retrieval_cooldown_until > now()):
        msg = f"Token retrieval is in cooldown until {self._token_retrieval_cooldown_until} after {self._token_retrieval_failures} consecutive failure(s) - skipping refresh"
        _LOGGER.debug(msg)
        raise ServerException(msg)

      if (self._graphql_refresh_expiration is not None and self._graphql_refresh_expiration < now()):
        _LOGGER.debug("Refresh token expired - clearing")
        self._graphql_refresh_token = None
        self._graphql_expiration = None

      try:
        try:
          await self.__async_fetch_token()
        except AuthenticationException:
          if (self._graphql_refresh_token is not None):
            _LOGGER.debug("Failed to refresh auth token using refresh token, attempting to use original credentials")
            self._graphql_refresh_token = None
            self._graphql_expiration = None
            await self.__async_fetch_token()
          else:
            raise

      except TimeoutError:
        _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
        raise TimeoutException()
      except ServerException:
        self._token_retrieval_failures += 1
        self._token_retrieval_cooldown_until = now() + calculate_token_retrieval_cooldown(self._token_retrieval_failures)
        _LOGGER.debug(f"Failed to retrieve auth token {self._token_retrieval_failures} time(s) in a row - not attempting again until {self._token_retrieval_cooldown_until}")
        raise

      self._token_retrieval_failures = 0
      self._token_retrieval_cooldown_until = None

  async def __async_fetch_token(self):
    client = self._create_client_session()
    url = f'{self._base_url}/v1/graphql/'
    payload = (
      {"query": api_token_query, "variables": {"email": self._email, "password": self._password}}
      if self._graphql_refresh_token is None
      else {"query": api_token_refresh_query, "variables": {"refreshToken": self._graphql_refresh_token}}
    )
    headers = { "context": "refresh-token" }
    async with client.post(url, headers=headers, json=payload) as token_response:
      token_response_body = await self.__async_read_response__(token_response, url)
      if (token_response_body is not None and
          "data" in token_response_body and
          "obtainKrakenToken" in token_response_body["data"] and
          token_response_body["data"]["obtainKrakenToken"] is not None and
          "token" in token_response_body["data"]["obtainKrakenToken"] and
          "refreshToken" in token_response_body["data"]["obtainKrakenToken"] and
          "refreshExpiresIn" in token_response_body["data"]["obtainKrakenToken"]):

        self._graphql_token = token_response_body["data"]["obtainKrakenToken"]["token"]
        self._graphql_refresh_token = token_response_body["data"]["obtainKrakenToken"]["refreshToken"]
        self._graphql_refresh_expiration = datetime.fromtimestamp(token_response_body["data"]["obtainKrakenToken"]["refreshExpiresIn"], tz=timezone.utc)
        self._graphql_expiration = self.__decode_jwt_expiry(self._graphql_token)
      elif (self._graphql_expiration is None or self._graphql_expiration < now()):
        raise AuthenticationException("Failed to retrieve auth token and current token is expired", [])
      else:
        _LOGGER.error("Failed to retrieve auth token")

  def __decode_jwt_expiry(self, token: str):
    try:
      payload = token.split(".")[1]
      payload += "=" * (-len(payload) % 4)
      claims = json.loads(base64.urlsafe_b64decode(payload))

      if "exp" in claims:
        return datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
    except Exception:
      _LOGGER.debug("Failed to decode JWT expiry", exc_info=True)

    _LOGGER.debug("Falling back to default token expiration of 1 hour")
    return now() + timedelta(hours=1)

  def register_meter_ids(self, account_info):
    """Seed meter IDs from previously mapped (e.g. cached) account info."""
    for point in (account_info or {}).get("electricity_meter_points") or []:
      self.__record_meter_ids(point.get("mpan"), point.get("meters") or [])
    for point in (account_info or {}).get("gas_meter_points") or []:
      self.__record_meter_ids(point.get("mprn"), point.get("meters") or [])
    self.__record_agreement_rates(account_info)

  def __record_agreement_rates(self, account_info):
    """Keep the unit rate/standing charge EDF reports on each agreement (in pence), keyed by tariff code.

    Used when the REST product endpoints won't serve a tariff (EDF refuses export products, for example).
    Also picks direct debit or non direct debit product prices based on the account's direct debit.
    """
    for point in (account_info or {}).get("electricity_meter_points") or []:
      # is_export is recorded on each meter, not on the meter point
      is_export = any(meter.get("is_export") for meter in point.get("meters") or [])
      if is_export and point.get("mpan") is not None and account_info.get("id") is not None:
        self._export_mpans[str(point["mpan"])] = account_info["id"]

    if account_info is not None and "direct_debit_status" in account_info:
      self._favour_direct_debit_rates = (account_info.get("direct_debit_status") or "").upper() == "ACTIVE"

    for point in ((account_info or {}).get("electricity_meter_points") or []) + ((account_info or {}).get("gas_meter_points") or []):
      supply_point = point.get("mpan") or point.get("mprn")
      point_is_export = any(meter.get("is_export") for meter in point.get("meters") or [])
      for agreement in point.get("agreements") or []:
        tariff_code = agreement.get("tariff_code")
        if tariff_code is not None and supply_point is not None and account_info.get("id") is not None:
          self._tariff_supply_points[tariff_code] = (account_info["id"], str(supply_point), point_is_export)
        if tariff_code is not None and (agreement.get("unit_rate") is not None or agreement.get("unit_rates") or agreement.get("standing_charge") is not None):
          self._agreement_rates[tariff_code] = {
            "tariff_type": agreement.get("tariff_type"),
            "unit_rate": agreement.get("unit_rate"),
            "unit_rates": agreement.get("unit_rates") or [],
            "standing_charge": agreement.get("standing_charge"),
          }

  def __record_meter_ids(self, point_id, meters):
    for meter in meters:
      if meter.get("meter_id") is not None:
        self._meter_ids[(str(point_id), str(meter["serial_number"]))] = str(meter["meter_id"])

  def map_electricity_meters(self, meter_point):
    is_export = (meter_point["meterPoint"]["direction"] == 'EXPORT') \
      if "meterPoint" in meter_point and "direction" in meter_point["meterPoint"] and meter_point["meterPoint"]["direction"] is not None \
      else None

    meters = list(
      map(lambda m: {
        "active_from": parse_date(m["activeFrom"]) if m["activeFrom"] is not None else None,
        "active_to": parse_date(m["activeTo"]) if m["activeTo"] is not None else None,
        "meter_id": m.get("id"),
        "serial_number": m["serialNumber"],
        "is_export": is_export if is_export is not None else m["smartExportElectricityMeter"] is not None,
        "is_smart_meter": f'{m["meterType"]}'.startswith("S1") or f'{m["meterType"]}'.startswith("S2"),
        "device_id": m["smartImportElectricityMeter"]["deviceId"] if m["smartImportElectricityMeter"] is not None else None,
        "manufacturer": m["smartImportElectricityMeter"]["manufacturer"]
          if m["smartImportElectricityMeter"] is not None
          else m["smartExportElectricityMeter"]["manufacturer"]
          if m["smartExportElectricityMeter"] is not None
          else m["makeAndType"],
        "model": m["smartImportElectricityMeter"]["model"]
          if m["smartImportElectricityMeter"] is not None
          else m["smartExportElectricityMeter"]["model"]
          if m["smartExportElectricityMeter"] is not None
          else None,
        "firmware": m["smartImportElectricityMeter"]["firmwareVersion"]
          if m["smartImportElectricityMeter"] is not None
          else m["smartExportElectricityMeter"]["firmwareVersion"]
          if m["smartExportElectricityMeter"] is not None
          else None
      },
      meter_point["meterPoint"]["meters"]
        if "meterPoint" in meter_point and "meters" in meter_point["meterPoint"] and meter_point["meterPoint"]["meters"] is not None
        else []
      )
    )

    meters.sort(key=lambda meter: meter["active_from"], reverse=True)
    self.__record_meter_ids(meter_point["meterPoint"]["mpan"], meters)

    return {
      "mpan": meter_point["meterPoint"]["mpan"],
      "meters": meters,
      "agreements": list(map(lambda a: {
        "start": a["validFrom"],
        "end": a["validTo"],
        "tariff_code": a["tariff"]["tariffCode"] if "tariff" in a and "tariffCode" in a["tariff"] else None,
        "product_code": a["tariff"]["productCode"] if "tariff" in a and "productCode" in a["tariff"] else None,
        "display_name": a["tariff"]["displayName"] if "tariff" in a and "displayName" in a["tariff"] else None,
        "tariff_type": a["tariff"].get("__typename") if a.get("tariff") else None,
        "unit_rate": a["tariff"].get("unitRate") if a.get("tariff") else None,
        "unit_rates": [
          {"value": r.get("value"), "valid_from": r.get("validFrom"), "valid_to": r.get("validTo")}
          for r in (a["tariff"].get("unitRates") or [])
          if r.get("value") is not None and r.get("validFrom") is not None
        ] if a.get("tariff") else [],
        "standing_charge": a["tariff"].get("standingCharge") if a.get("tariff") else None,
      },
      meter_point["meterPoint"]["agreements"]
        if "meterPoint" in meter_point and "agreements" in meter_point["meterPoint"] and meter_point["meterPoint"]["agreements"] is not None
        else []
      ))
    }

  def map_gas_meters(self, meter_point):
    meters = list(
      map(lambda m: {
        "active_from": parse_date(m["activeFrom"]) if m["activeFrom"] is not None else None,
        "active_to": parse_date(m["activeTo"]) if m["activeTo"] is not None else None,
        "meter_id": m.get("id"),
        "serial_number": m["serialNumber"],
        "consumption_units": m["consumptionUnits"],
        "is_smart_meter": m["mechanism"] == "S1" or m["mechanism"] == "S2",
        "device_id": m["smartGasMeter"]["deviceId"] if m["smartGasMeter"] is not None else None,
        "manufacturer": m["smartGasMeter"]["manufacturer"] if m["smartGasMeter"] is not None else m["modelName"],
        "model": m["smartGasMeter"]["model"] if m["smartGasMeter"] is not None else None,
        "firmware": m["smartGasMeter"]["firmwareVersion"] if m["smartGasMeter"] is not None else None
      },
      meter_point["meterPoint"]["meters"]
        if "meterPoint" in meter_point and "meters" in meter_point["meterPoint"] and meter_point["meterPoint"]["meters"] is not None
        else []
      )
    )

    meters.sort(key=lambda meter: meter["active_from"], reverse=True)
    self.__record_meter_ids(meter_point["meterPoint"]["mprn"], meters)

    return {
      "mprn": meter_point["meterPoint"]["mprn"],
      "meters": meters,
      "agreements": list(map(lambda a: {
        "start": a["validFrom"],
        "end": a["validTo"],
        "tariff_code": a["tariff"]["tariffCode"] if "tariff" in a and "tariffCode" in a["tariff"] else None,
        "product_code": a["tariff"]["productCode"] if "tariff" in a and "productCode" in a["tariff"] else None,
        "tariff_type": a["tariff"].get("__typename") if a.get("tariff") else None,
        "unit_rate": a["tariff"].get("unitRate") if a.get("tariff") else None,
        "unit_rates": [
          {"value": r.get("value"), "valid_from": r.get("validFrom"), "valid_to": r.get("validTo")}
          for r in (a["tariff"].get("unitRates") or [])
          if r.get("value") is not None and r.get("validFrom") is not None
        ] if a.get("tariff") else [],
        "standing_charge": a["tariff"].get("standingCharge") if a.get("tariff") else None,
      },
      meter_point["meterPoint"]["agreements"]
        if "meterPoint" in meter_point and "agreements" in meter_point["meterPoint"] and meter_point["meterPoint"]["agreements"] is not None
        else []
      ))
    }

  async def async_run_graphql_query(self, query: str, variables: dict | None = None):
    """Runs an arbitrary graphql query. This is intended to be used for debugging purposes only."""
    await self.async_refresh_token()

    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'

      payload = { "query": query }
      if variables is not None:
        payload["variables"] = variables

      headers = { "Authorization": self._graphql_token, "context": "run-graphql-query" }
      async with client.post(url, json=payload, headers=headers) as response:
        # Errors are returned to the caller as part of the response, rather than raised, so they can be inspected
        try:
          body = await self.__async_read_response__(response, url, ignore_errors=True)
        except RequestException as e:
          # e.g. a 400 for an invalid query - return the message rather than failing the service call
          return {"errors": [str(e)]}
        return body if body is not None else {}

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

  async def async_get_account(self, account_id: str):
    """Get the user's account"""
    await self.async_refresh_token()

    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = { "query": account_query.format(account_id=account_id) }
      headers = { "Authorization": self._graphql_token, "context": "get-account" }
      async with client.post(url, json=payload, headers=headers) as account_response:
        account_response_body = await self.__async_read_response__(account_response, url)
        _LOGGER.debug(f'account: {account_response_body}')

        if (account_response_body is not None and
            "data" in account_response_body and
            "account" in account_response_body["data"] and
            account_response_body["data"]["account"] is not None):

          account = account_response_body["data"]["account"]

          account_info = {
            "id": account_id,
            "balance": account.get("balance"),
            "overdue_balance": account.get("overdueBalance"),
            "projected_balance": account.get("projectedBalance"),
            "should_review_payments": account.get("shouldReviewPayments"),
            "recommended_balance_adjustment": account.get("recommendedBalanceAdjustment"),
            "can_renew_tariff": account.get("canRenewTariff"),
            "direct_debit_status": account["directDebitInstructions"]["edges"][0]["node"].get("status") if account.get("directDebitInstructions") and account["directDebitInstructions"].get("edges") else None,
            "direct_debit_amount": account["paymentSchedules"]["edges"][0]["node"].get("paymentAmount") if account.get("paymentSchedules") and account["paymentSchedules"].get("edges") else None,
            "direct_debit_payment_day": account["paymentSchedules"]["edges"][0]["node"].get("paymentDay") if account.get("paymentSchedules") and account["paymentSchedules"].get("edges") else None,
            "electricity_meter_points": list(map(self.map_electricity_meters,
              account["electricityAgreements"]
                if "electricityAgreements" in account and account["electricityAgreements"] is not None
                else []
            )),
            "gas_meter_points": list(map(self.map_gas_meters,
              account["gasAgreements"]
                if "gasAgreements" in account and account["gasAgreements"] is not None
                else []
            )),
          }
          self.__record_agreement_rates(account_info)
          return account_info
        else:
          _LOGGER.error("Failed to retrieve account")

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

    return None

  async def async_get_account_transactions(self, account_id: str):
    """Get recent account transactions (payments and charges)."""
    await self.async_refresh_token()
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {
        "query": transactions_query,
        "variables": {"accountNumber": account_id},
      }
      headers = {"Authorization": self._graphql_token, "context": "account-transactions"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if (body is not None and
            "data" in body and
            "account" in body["data"] and
            body["data"]["account"] is not None and
            "transactions" in body["data"]["account"]):
          edges = body["data"]["account"]["transactions"].get("edges") or []
          results = []
          for edge in edges:
            node = edge.get("node") or {}
            amounts = node.get("amounts") or {}
            gross = amounts.get("gross")
            results.append({
              "type": node.get("__typename"),
              "posted_date": node.get("postedDate"),
              "gross_amount": float(gross) if gross is not None else None,
              "is_credit": node.get("isCredit"),
              "title": node.get("title"),
            })
          return results
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return None

  async def async_get_account_billing(self, account_id: str):
    """Get the payment forecast, latest statement, rewards, direct debit review, campaigns and smart meter data frequency. Personal fields
    (addresses, names, referral codes) are deliberately not requested."""
    await self.async_refresh_token()
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {
        "query": billing_query,
        "variables": {"accountNumber": account_id},
      }
      headers = {"Authorization": self._graphql_token, "context": "account-billing"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if body is None or body.get("data") is None or body["data"].get("account") is None:
          return None
        account = body["data"]["account"]

        def edges(connection):
          return [edge.get("node") or {} for edge in ((connection or {}).get("edges") or [])]

        forecast = [
          {"date": node.get("date"), "amount": node.get("amount"), "method": node.get("method")}
          for node in edges(account.get("paginatedPaymentForecast"))
        ]

        bills = edges(account.get("bills"))
        last_bill = None
        if bills:
          bill = bills[0]
          last_bill = {
            "bill_type": bill.get("billType"),
            "from_date": bill.get("fromDate"),
            "to_date": bill.get("toDate"),
            "issued_date": bill.get("issuedDate"),
            "opening_balance": bill.get("openingBalance"),
            "closing_balance": bill.get("closingBalance"),
            "payment_due_date": bill.get("paymentDueDate"),
            "is_final": bill.get("isFinal"),
            "total_charges": (bill.get("totalCharges") or {}).get("grossTotal"),
            "total_credits": (bill.get("totalCredits") or {}).get("grossTotal"),
          }

        rewards = [
          {
            "payment_date": reward.get("paymentDate"),
            "scheme_type": reward.get("schemeType"),
            "amount": reward.get("rewardAmount"),
            "payment_status": reward.get("paymentStatus"),
          }
          for reward in (account.get("rewards") or [])
        ]

        adequacy = account.get("paymentAdequacy") or {}
        return {
          "payment_forecast": forecast,
          "last_bill": last_bill,
          "rewards": rewards,
          "referrals_created": account.get("referralsCreated"),
          "suggested_direct_debit": adequacy.get("suggestedDirectDebitAmount"),
          "minimum_direct_debit": adequacy.get("minimumDirectDebitAmount"),
          "campaigns": [
            {
              "name": campaign.get("name"),
              "slug": campaign.get("slug"),
              "start_date": campaign.get("startDate"),
              "expiry_date": campaign.get("expiryDate"),
            }
            for campaign in (account.get("campaigns") or [])
          ],
          "smart_meter_reading_frequency": (body["data"].get("smartMeterDataPreferences") or {}).get("readingFrequency"),
        }
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

  async def async_get_electricity_meter_readings(self, account_id: str, mpan: str, serial_number: str):
    """Get the latest electricity meter register reading via GraphQL."""
    meter_id = self._meter_ids.get((str(mpan), str(serial_number)))
    if meter_id is None:
      _LOGGER.debug(f'No meter ID known yet for electricity meter {mpan}/{serial_number} - skipping readings')
      return None

    await self.async_refresh_token()
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {
        "query": electricity_meter_readings_query,
        "variables": {"accountNumber": account_id, "meterId": meter_id, "first": 5},
      }
      headers = {"Authorization": self._graphql_token, "context": "electricity-readings"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url)
        return self.__extract_latest_meter_reading__(body, "electricityMeterReadings")
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return None

  async def async_get_gas_meter_readings(self, account_id: str, mprn: str, serial_number: str):
    """Get the latest gas meter register reading via GraphQL."""
    meter_id = self._meter_ids.get((str(mprn), str(serial_number)))
    if meter_id is None:
      _LOGGER.debug(f'No meter ID known yet for gas meter {mprn}/{serial_number} - skipping readings')
      return None

    await self.async_refresh_token()
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {
        "query": gas_meter_readings_query,
        "variables": {"accountNumber": account_id, "meterId": meter_id, "first": 5},
      }
      headers = {"Authorization": self._graphql_token, "context": "gas-readings"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url)
        return self.__extract_latest_meter_reading__(body, "gasMeterReadings")
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return None

  async def async_get_extended_electricity_consumption(self, mpan: str):
    """Get extended annual electricity consumption estimates (EAC) for an MPAN."""
    await self.async_refresh_token()
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {
        "query": extended_electricity_consumption_query,
        "variables": {"mpan": mpan},
      }
      headers = {"Authorization": self._graphql_token, "context": "extended-electricity-consumption"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, expected_error_codes=["KT-CT-1111"])
        if (body is not None and
            "data" in body and
            "extendedAnnualElectricityConsumption" in body["data"] and
            body["data"]["extendedAnnualElectricityConsumption"] is not None):
          data = body["data"]["extendedAnnualElectricityConsumption"]
          return {
            "eac_standard": float(data["eacStandard"]) if data.get("eacStandard") is not None else None,
            "eac_day": float(data["eacDay"]) if data.get("eacDay") is not None else None,
            "eac_night": float(data["eacNight"]) if data.get("eacNight") is not None else None,
          }
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return None

  async def async_get_annual_gas_consumption(self, mprn: str):
    """Get annual gas consumption (AQ) for an MPRN."""
    await self.async_refresh_token()
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {
        "query": annual_gas_consumption_query,
        "variables": {"mprn": mprn},
      }
      headers = {"Authorization": self._graphql_token, "context": "annual-gas-consumption"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, expected_error_codes=["KT-CT-1111"])
        if (body is not None and
            "data" in body and
            "annualGasConsumption" in body["data"] and
            body["data"]["annualGasConsumption"] is not None):
          data = body["data"]["annualGasConsumption"]
          return {
            "aq": float(data["aq"]) if data.get("aq") is not None else None,
            "supplier_name": data.get("supplierName"),
            "supplier_effective_from": data.get("supplierEffectiveFromDate"),
            "aq_effective_from": data.get("aqEffectiveFromDate"),
          }
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return None

  async def async_get_intelligent_device(self, account_id: str):
    """Return the first enrolled SmartFlex EV device for the account, or None."""
    await self.async_refresh_token()
    query = '''query {{
  devices(accountNumber: "{account_id}") {{
    id
    name
    deviceType
    provider
    integrationDeviceId
    status {{
      currentState
      isSuspended
    }}
    preferences {{
      targetType
      unit
      mode
      schedules {{
        dayOfWeek
        time
        min
        max
        upperLimit
      }}
    }}
    ... on SmartFlexVehicle {{
      make
      model
    }}
    ... on SmartFlexChargePoint {{
      make
      model
    }}
  }}
}}'''.format(account_id=account_id)
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {"query": query}
      headers = {"Authorization": self._graphql_token, "context": "intelligent-device"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if (body is not None and "data" in body and
            "devices" in body["data"] and body["data"]["devices"]):
          devices = body["data"]["devices"]
          ev_types = {"ELECTRIC_VEHICLES", "BATTERIES"}
          for d in devices:
            if d.get("deviceType") in ev_types or d.get("deviceType") is None:
              prefs = d.get("preferences") or {}
              schedules = prefs.get("schedules") or []
              target_time = None
              target_percentage = None
              if schedules:
                first = schedules[0]
                target_time = first.get("time")
                raw_min = first.get("min")
                target_percentage = int(float(raw_min)) if raw_min is not None else None
              return {
                "id": d.get("id"),
                "name": d.get("name"),
                "device_type": d.get("deviceType"),
                "make": d.get("make"),
                "model": d.get("model"),
                "current_state": (d.get("status") or {}).get("currentState"),
                "is_suspended": (d.get("status") or {}).get("isSuspended", False),
                "mode": prefs.get("mode"),
                "unit": prefs.get("unit"),
                "target_time": target_time,
                "target_percentage": target_percentage,
              }
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return None

  async def async_get_intelligent_dispatches(self, account_id: str, device_id: str):
    """Return planned and completed dispatches for an EV device."""
    await self.async_refresh_token()
    planned_query = '''query {{
  flexPlannedDispatches(deviceId: "{device_id}") {{
    start
    end
    type
    energyAddedKwh
  }}
}}'''.format(device_id=device_id)
    completed_query = '''query {{
  completedDispatches(accountNumber: "{account_id}") {{
    start
    end
    startDt
    endDt
    deltaKwh
    delta
    meta {{
      source
      location
    }}
  }}
}}'''.format(account_id=account_id)
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      headers = {"Authorization": self._graphql_token, "context": "intelligent-dispatches"}
      planned = []
      completed = []
      async with client.post(url, json={"query": planned_query}, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if body is not None and "data" in body and "flexPlannedDispatches" in body["data"]:
          raw = body["data"]["flexPlannedDispatches"] or []
          for d in raw:
            start = parse_datetime(d["start"]) if d.get("start") else None
            end = parse_datetime(d["end"]) if d.get("end") else None
            if start and end:
              planned.append({
                "start": as_utc(start),
                "end": as_utc(end),
                "type": d.get("type"),
                "energy_kwh": float(d["energyAddedKwh"]) if d.get("energyAddedKwh") is not None else None,
              })
      async with client.post(url, json={"query": completed_query}, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if body is not None and "data" in body and "completedDispatches" in body["data"]:
          raw = body["data"]["completedDispatches"] or []
          for d in raw:
            start_raw = d.get("startDt") or d.get("start")
            end_raw = d.get("endDt") or d.get("end")
            start = parse_datetime(start_raw) if start_raw else None
            end = parse_datetime(end_raw) if end_raw else None
            if start and end:
              meta = d.get("meta") or {}
              completed.append({
                "start": as_utc(start),
                "end": as_utc(end),
                "delta_kwh": float(d["deltaKwh"]) if d.get("deltaKwh") is not None else None,
                "delta": float(d["delta"]) if d.get("delta") is not None else None,
                "source": meta.get("source"),
                "location": meta.get("location"),
              })
      return {"planned": planned, "completed": completed}
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return None

  async def async_set_intelligent_smart_control(self, device_id: str, suspend: bool) -> bool:
    """Suspend or unsuspend smart charging for a device."""
    await self.async_refresh_token()
    action = "SUSPEND" if suspend else "UNSUSPEND"
    mutation = '''mutation {{
  updateDeviceSmartControl(input: {{ deviceId: "{device_id}", action: {action} }}) {{
    id
    status {{
      currentState
      isSuspended
    }}
  }}
}}'''.format(device_id=device_id, action=action)
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {"query": mutation}
      headers = {"Authorization": self._graphql_token, "context": "intelligent-smart-control"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if body is not None and "data" in body and "updateDeviceSmartControl" in body["data"]:
          return body["data"]["updateDeviceSmartControl"] is not None
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return False

  async def async_set_intelligent_boost_charge(self, device_id: str, boost: bool) -> bool:
    """Start (BOOST) or cancel (CANCEL) a bump charge."""
    await self.async_refresh_token()
    action = "BOOST" if boost else "CANCEL"
    mutation = '''mutation {{
  updateBoostCharge(input: {{ deviceId: "{device_id}", action: {action} }}) {{
    id
    status {{
      currentState
      isSuspended
    }}
  }}
}}'''.format(device_id=device_id, action=action)
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {"query": mutation}
      headers = {"Authorization": self._graphql_token, "context": "intelligent-boost-charge"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if body is not None and "data" in body and "updateBoostCharge" in body["data"]:
          return body["data"]["updateBoostCharge"] is not None
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return False

  async def async_set_intelligent_preferences(self, device_id: str, target_percentage: int, target_time: str) -> bool:
    """Set charge target percentage and ready-by time (HH:MM) for all days."""
    await self.async_refresh_token()
    days = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY"]
    schedules = [{"dayOfWeek": d, "time": target_time, "min": target_percentage, "max": 100} for d in days]
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      payload = {
        "query": """mutation SetDevicePreferences($input: SmartFlexDevicePreferencesInput!) {
  setDevicePreferences(input: $input) {
    id
    preferences { targetType unit mode schedules { dayOfWeek time min max } }
  }
}""",
        "variables": {
          "input": {
            "deviceId": device_id,
            "mode": "CHARGE",
            "unit": "PERCENTAGE",
            "schedules": schedules,
          }
        },
      }
      headers = {"Authorization": self._graphql_token, "context": "intelligent-set-preferences"}
      async with client.post(url, json=payload, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
        if body is not None and "data" in body and "setDevicePreferences" in body["data"]:
          return body["data"]["setDevicePreferences"] is not None
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()
    return False

  async def __async_fetch_electricity_rates_endpoint(self, client, product_code: str, tariff_code: str, endpoint: str, period_from: datetime, period_to: datetime):
    """Fetch all pages from a single electricity rates endpoint. Returns list or None on failure."""
    results = []
    page = 1
    has_more = True
    period_from_str = period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    period_to_str = period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": self._graphql_token, "context": "electricity-rates"}

    while has_more:
      url = f'{self._base_url}/v1/products/{product_code}/electricity-tariffs/{tariff_code}/{endpoint}?period_from={period_from_str}&period_to={period_to_str}&page={page}'
      try:
        async with client.get(url, headers=headers) as response:
          data = await self.__async_read_response__(response, url, is_product_endpoint=True)
          if data is None:
            return None
          results = results + rates_to_thirty_minute_increments(data, period_from, period_to, tariff_code, None, self._favour_direct_debit_rates)
          has_more = "next" in data and data["next"] is not None
          if has_more:
            page += 1
      except RequestException:
        return None

    return results

  def __agreement_rates(self, tariff_code: str, period_from: datetime, period_to: datetime):
    """30 minute rates built from the prices on the account agreement, or None if unknown.

    Flat tariffs (standard, prepay, gas) carry a single unit rate. Half-hourly tariffs such as
    Go Electric carry the current day's dated rate bands. Day/night tariffs carry prices but not
    their time bands, so they are left to the pricing API. Approach from
    stevekirtley/HomeAssistant-EDFEnergy (MIT).
    """
    info = self._agreement_rates.get(tariff_code) or {}
    if info.get("unit_rate") is not None:
      return rates_to_thirty_minute_increments({"results": [{"value_inc_vat": info["unit_rate"], "valid_from": None, "valid_to": None}]}, period_from, period_to, tariff_code)

    bands = info.get("unit_rates") or []
    if bands:
      results = rates_to_thirty_minute_increments({"results": [
        {"value_inc_vat": band["value"], "valid_from": band["valid_from"], "valid_to": band["valid_to"]}
        for band in bands
      ]}, period_from, period_to, tariff_code)
      return results if results else None

    return None

  async def __async_fallback_rates(self, tariff_code: str, period_from: datetime, period_to: datetime):
    """Rates for a tariff the product endpoints won't serve: the account's applicable rates, else the agreement."""
    try:
      rates = await self.__async_applicable_rates(tariff_code, period_from, period_to)
    except ApiException:
      _LOGGER.debug(f'Failed to retrieve applicable rates for {tariff_code}', exc_info=True)
      rates = None
    if rates:
      return rates
    return self.__agreement_rates(tariff_code, period_from, period_to)

  async def __async_applicable_rates(self, tariff_code: str, period_from: datetime, period_to: datetime):
    """30 minute rates from the account's applicableRates, or None if unavailable.

    These are the prices EDF applies to this account for any period, so they also cover hidden,
    export and day/night tariffs. EDF returns them excluding VAT; import and gas prices have 5%
    VAT added, export payments don't carry VAT.
    """
    supply = self._tariff_supply_points.get(tariff_code)
    if supply is None or period_from is None or period_to is None:
      return None
    account_id, mpxn, is_export = supply
    vat_multiplier = 1.0 if is_export else 1.05

    items = []
    client = self._create_client_session()
    url = f'{self._base_url}/v1/graphql/'
    headers = {"Authorization": self._graphql_token, "context": "applicable-rates"}
    after = None
    for _ in range(20):
      variables = {
        "accountNumber": account_id,
        "mpxn": mpxn,
        "startAt": period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endAt": period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
      }
      if after is not None:
        variables["after"] = after
      async with client.post(url, json={"query": applicable_rates_query, "variables": variables}, headers=headers) as response:
        body = await self.__async_read_response__(response, url, ignore_errors=True)
      connection = ((body or {}).get("data") or {}).get("applicableRates") or {}
      for edge in connection.get("edges") or []:
        node = edge.get("node") or {}
        if node.get("value") is None:
          continue
        items.append({
          "value_inc_vat": round(float(node["value"]) * vat_multiplier, 4),
          "valid_from": node.get("validFrom"),
          "valid_to": node.get("validTo"),
        })
      page_info = connection.get("pageInfo") or {}
      if not page_info.get("hasNextPage") or page_info.get("endCursor") is None:
        break
      after = page_info["endCursor"]

    if not items:
      return None
    results = rates_to_thirty_minute_increments({"results": items}, period_from, period_to, tariff_code)
    return results if results else None

  def __agreement_standing_charge(self, tariff_code: str):
    """Standing charge from the account agreement, or None if unknown."""
    standing_charge = (self._agreement_rates.get(tariff_code) or {}).get("standing_charge")
    if standing_charge is None:
      return None
    return { "start": None, "end": None, "value_inc_vat": float(standing_charge), "tariff_code": tariff_code }

  def __mark_product_unavailable(self, tariff_code: str):
    if tariff_code not in self._unavailable_product_tariffs:
      self._unavailable_product_tariffs.add(tariff_code)
      _LOGGER.info(f'EDF does not provide product rates for {tariff_code} - using the rates on the account agreement instead')

  async def async_get_electricity_rates(self, product_code: str, tariff_code: str, period_from: datetime, period_to: datetime):
    """Get electricity rates, handling single-rate and day/night tariffs."""
    # REST endpoints use the GraphQL token too, so make sure it is current (Octopus uses an API key here instead)
    await self.async_refresh_token()
    if tariff_code in self._unavailable_product_tariffs:
      return await self.__async_fallback_rates(tariff_code, period_from, period_to)

    try:
      client = self._create_client_session()

      # Try standard (single-rate) endpoint first
      try:
        results = await self.__async_fetch_electricity_rates_endpoint(
          client, product_code, tariff_code, "standard-unit-rates", period_from, period_to
        )
      except AuthenticationException:
        fallback = await self.__async_fallback_rates(tariff_code, period_from, period_to)
        if fallback is None:
          raise
        self.__mark_product_unavailable(tariff_code)
        return fallback

      if results is None:
        # Tariff has day/night rates — fetch both and combine
        _LOGGER.debug(f'Standard rates unavailable for {tariff_code}, trying day/night endpoints')
        try:
          day_results = await self.__async_fetch_electricity_rates_endpoint(
            client, product_code, tariff_code, "day-unit-rates", period_from, period_to
          ) or []
          night_results = await self.__async_fetch_electricity_rates_endpoint(
            client, product_code, tariff_code, "night-unit-rates", period_from, period_to
          ) or []
        except AuthenticationException:
          fallback = await self.__async_fallback_rates(tariff_code, period_from, period_to)
          if fallback is None:
            raise
          self.__mark_product_unavailable(tariff_code)
          return fallback

        results = day_results + night_results
        if not results:
          # Nothing from the product endpoints - use the agreement's unit rate if EDF gave us one
          return await self.__async_fallback_rates(tariff_code, period_from, period_to)

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

    results.sort(key=get_start)
    return results

  async def async_get_electricity_standing_charge(self, product_code: str, tariff_code: str, period_from: datetime, period_to: datetime):
    """Get the electricity standing charge"""
    # REST endpoints use the GraphQL token too, so make sure it is current (Octopus uses an API key here instead)
    await self.async_refresh_token()
    if tariff_code in self._unavailable_product_tariffs:
      return self.__agreement_standing_charge(tariff_code)

    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/products/{product_code}/electricity-tariffs/{tariff_code}/standing-charges?period_from={period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}&period_to={period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}'
      headers = { "Authorization": self._graphql_token, "context": "electricity-standing-charge" }
      async with client.get(url, headers=headers) as response:
        try:
          data = await self.__async_read_response__(response, url, is_product_endpoint=True)
        except AuthenticationException:
          fallback = self.__agreement_standing_charge(tariff_code)
          if fallback is None:
            raise
          self.__mark_product_unavailable(tariff_code)
          return fallback
        if (data is not None and "results" in data and len(data["results"]) > 0):
          return get_standing_charge(data["results"], tariff_code, self._favour_direct_debit_rates)

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

    return self.__agreement_standing_charge(tariff_code)

  async def async_get_electricity_consumption(self, mpan: str, serial_number: str, period_from: datetime = None, period_to: datetime = None, page_size: int = None):
    """Get the electricity consumption"""
    # EDF doesn't serve export consumption on the REST endpoint, but does in GraphQL measurements
    if str(mpan) in self._export_mpans and period_from is not None and period_to is not None:
      results = await self.async_get_export_measurements(self._export_mpans[str(mpan)], mpan, period_from, period_to)
      if results:
        return results

    # REST endpoints use the GraphQL token too, so make sure it is current (Octopus uses an API key here instead)
    await self.async_refresh_token()
    try:
      client = self._create_client_session()

      query_params = []
      if period_from is not None:
        query_params.append(f'period_from={period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}')
      if period_to is not None:
        query_params.append(f'period_to={period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}')
      if page_size is not None:
        query_params.append(f'page_size={page_size}')

      query_string = '&'.join(query_params)
      url = f"{self._base_url}/v1/electricity-meter-points/{mpan}/meters/{serial_number}/consumption{f'?{query_string}' if query_string else ''}"
      headers = { "Authorization": self._graphql_token, "context": "electricity-consumption" }
      async with client.get(url, headers=headers) as response:
        data = await self.__async_read_response__(response, url)
        if (data is not None and "results" in data):
          results = []
          for item in data["results"]:
            item = self.__process_consumption(item)
            if (period_from is None or as_utc(item["start"]) >= period_from) and (period_to is None or as_utc(item["end"]) <= period_to):
              results.append(item)
            else:
              _LOGGER.debug(f'Skipping electricity consumption item outside requested scope - mpan: {mpan}')
          results.sort(key=self.__get_interval_end)
          return results

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

    return None

  async def async_get_export_measurements(self, account_id: str, mpan: str, period_from: datetime, period_to: datetime):
    """Get half-hourly export consumption from GraphQL measurements, in the same shape as the REST consumption."""
    await self.async_refresh_token()
    results = []
    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/graphql/'
      headers = {"Authorization": self._graphql_token, "context": "export-measurements"}
      after = None
      # A week of half hours is 336 readings; stop well short of runaway paging
      for _ in range(50):
        payload = {
          "query": export_measurements_query,
          "variables": {
            "accountNumber": account_id,
            "mpan": str(mpan),
            "startAt": period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "endAt": period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
          },
        }
        if after is not None:
          payload["variables"]["after"] = after
        async with client.post(url, json=payload, headers=headers) as response:
          body = await self.__async_read_response__(response, url, ignore_errors=True)
        if body is None or body.get("data") is None or body["data"].get("account") is None:
          break

        next_after = None
        for prop in body["data"]["account"].get("properties") or []:
          connection = (prop or {}).get("measurements") or {}
          for edge in connection.get("edges") or []:
            node = edge.get("node") or {}
            if node.get("value") is None or node.get("startAt") is None or node.get("endAt") is None:
              continue
            start = as_utc(parse_datetime(node["startAt"]))
            end = as_utc(parse_datetime(node["endAt"]))
            if start >= period_from and end <= period_to:
              results.append({"consumption": float(node["value"]), "start": start, "end": end})
          page_info = connection.get("pageInfo") or {}
          if page_info.get("hasNextPage"):
            next_after = page_info.get("endCursor")

        if next_after is None:
          break
        after = next_after
    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

    results.sort(key=self.__get_interval_end)
    return results

  async def async_get_gas_rates(self, product_code: str, tariff_code: str, period_from: datetime, period_to: datetime):
    """Get the gas rates"""
    # REST endpoints use the GraphQL token too, so make sure it is current (Octopus uses an API key here instead)
    await self.async_refresh_token()
    if tariff_code in self._unavailable_product_tariffs:
      return await self.__async_fallback_rates(tariff_code, period_from, period_to)

    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/products/{product_code}/gas-tariffs/{tariff_code}/standard-unit-rates?period_from={period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}&period_to={period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}'
      headers = { "Authorization": self._graphql_token, "context": "gas-rates" }
      async with client.get(url, headers=headers) as response:
        try:
          data = await self.__async_read_response__(response, url, is_product_endpoint=True)
        except AuthenticationException:
          fallback = await self.__async_fallback_rates(tariff_code, period_from, period_to)
          if fallback is None:
            raise
          self.__mark_product_unavailable(tariff_code)
          return fallback
        if data is None:
          return await self.__async_fallback_rates(tariff_code, period_from, period_to)
        return rates_to_thirty_minute_increments(data, period_from, period_to, tariff_code, None, self._favour_direct_debit_rates)

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

  async def async_get_gas_standing_charge(self, product_code: str, tariff_code: str, period_from: datetime, period_to: datetime):
    """Get the gas standing charge"""
    # REST endpoints use the GraphQL token too, so make sure it is current (Octopus uses an API key here instead)
    await self.async_refresh_token()
    if tariff_code in self._unavailable_product_tariffs:
      return self.__agreement_standing_charge(tariff_code)

    try:
      client = self._create_client_session()
      url = f'{self._base_url}/v1/products/{product_code}/gas-tariffs/{tariff_code}/standing-charges?period_from={period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}&period_to={period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}'
      headers = { "Authorization": self._graphql_token, "context": "gas-standing-charge" }
      async with client.get(url, headers=headers) as response:
        try:
          data = await self.__async_read_response__(response, url, is_product_endpoint=True)
        except AuthenticationException:
          fallback = self.__agreement_standing_charge(tariff_code)
          if fallback is None:
            raise
          self.__mark_product_unavailable(tariff_code)
          return fallback
        if (data is not None and "results" in data and len(data["results"]) > 0):
          return get_standing_charge(data["results"], tariff_code, self._favour_direct_debit_rates)

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

    return self.__agreement_standing_charge(tariff_code)

  async def async_get_gas_consumption(self, mprn: str, serial_number: str, period_from: datetime = None, period_to: datetime = None, page_size: int = None):
    """Get the gas consumption"""
    # REST endpoints use the GraphQL token too, so make sure it is current (Octopus uses an API key here instead)
    await self.async_refresh_token()
    try:
      client = self._create_client_session()

      query_params = []
      if period_from is not None:
        query_params.append(f'period_from={period_from.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}')
      if period_to is not None:
        query_params.append(f'period_to={period_to.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}')
      if page_size is not None:
        query_params.append(f'page_size={page_size}')

      query_string = '&'.join(query_params)
      url = f"{self._base_url}/v1/gas-meter-points/{mprn}/meters/{serial_number}/consumption{f'?{query_string}' if query_string else ''}"
      headers = { "Authorization": self._graphql_token, "context": "gas-consumption" }
      async with client.get(url, headers=headers) as response:
        data = await self.__async_read_response__(response, url)
        if (data is not None and "results" in data):
          results = []
          for item in data["results"]:
            item = self.__process_consumption(item)
            if (period_from is None or as_utc(item["start"]) >= period_from) and (period_to is None or as_utc(item["end"]) <= period_to):
              results.append(item)
            else:
              _LOGGER.debug(f'Skipping gas consumption item outside requested scope - mprn: {mprn}')
          results.sort(key=self.__get_interval_end)
          return results

    except TimeoutError:
      _LOGGER.warning(f'Failed to connect. Timeout of {self._timeout} exceeded.')
      raise TimeoutException()

    return None

  def __get_interval_end(self, item):
    return (item["end"].timestamp(), item["end"].fold)

  def __process_consumption(self, item):
    return {
      "consumption": float(item["consumption"]),
      "start": as_utc(parse_datetime(item["interval_start"])),
      "end": as_utc(parse_datetime(item["interval_end"]))
    }

  def __extract_latest_meter_reading__(self, body, field_name: str):
    """Pick the most recent reading from a *MeterReadings GraphQL connection response."""
    if body is None or "data" not in body or body["data"].get(field_name) is None:
      return None

    edges = body["data"][field_name].get("edges") or []
    readings = []
    for edge in edges:
      node = edge.get("node") or {}
      read_at = node.get("readAt")
      # Skip registers EDF has quarantined as suspect
      registers = [r for r in (node.get("registers") or []) if r.get("value") is not None and not r.get("isQuarantined")]
      if read_at is None or len(registers) == 0:
        continue
      readings.append({
        "read_at": read_at,
        "value": float(registers[0]["value"]),
        "registers": [{"name": r.get("name") or r.get("identifier"), "value": float(r["value"])} for r in registers],
      })

    if not readings:
      return None

    readings.sort(key=lambda r: parse_datetime(r["read_at"]))
    return readings[-1]

  async def __async_read_response__(self, response, url, ignore_errors=False, accepted_error_codes=[], expected_error_codes=[], is_product_endpoint=False):
    """Reads the response, logging any errors.

    `is_product_endpoint` marks the REST /v1/products/ endpoints. EDF refuses some products (e.g. export tariffs)
    with a 401 even though the token is valid, so those responses must not discard the token.
    """
    text = await response.text()

    if response.status >= 400:
      if response.status >= 500:
        msg = f'Response received - {url} - EDF Energy server error: {response.status}; {text}'
        _LOGGER.warning(msg)
        raise ServerException(msg)
      elif response.status in [401, 403]:
        # Cloudfront errors can come back as a 403, so treat those as server errors rather than auth failures
        if response.status == 403 and "The request could not be satisfied" in text and "cloudfront" in text:
          msg = f'Response received - {url} - EDF Energy server error: {response.status}; {text}'
          _LOGGER.info(msg)
          raise ServerException(msg)

        msg = f'Response received - {url} - Unauthenticated request: {response.status}; {text}'
        if is_product_endpoint:
          # Product not available to this token - callers fall back to the rates on the account's agreement
          _LOGGER.debug(msg)
          raise AuthenticationException(msg, [])

        # Reset the GraphQL token and refresh token so that we re-authenticate on the next request
        self._graphql_token = None
        self._graphql_expiration = None
        self._graphql_refresh_token = None
        self._graphql_refresh_expiration = None
        _LOGGER.warning(msg)
        raise AuthenticationException(msg, [])
      elif response.status not in [404]:
        msg = f'Response received - {url} - Failed to send request: {response.status}; {text}'
        _LOGGER.warning(msg)
        raise RequestException(msg, [])

      _LOGGER.info(f"Response received - {url} - Unexpected response: {response.status}; {text}")
      return None

    _LOGGER.debug(f'Response received - {url} - Successful response')

    data_as_json = None
    try:
      data_as_json = json.loads(text)
    except:
      raise Exception(f'Failed to extract response json: {url}; {text}')

    return process_graphql_response(data_as_json, url, "edf-energy", ignore_errors, accepted_error_codes, expected_error_codes)
