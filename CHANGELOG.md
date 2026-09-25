# Changelog

Version history of this fork. Versions are shown in Home Assistant under the integration's details. For the reasoning behind each fix, see [FORK_CHANGES.md](FORK_CHANGES.md); for what every entity does, see [docs/ENTITIES.md](docs/ENTITIES.md).

## 2.1.0 (2026-09-25)

### Removed
- **Live consumption**: the *Supports live consumption* option and its sensors (Current Demand, Current Consumption, Current Total Consumption, Current Accumulative Consumption/Cost, Current Total Export). EDF doesn't provide smart meter telemetry for any account (`KT-GB-4039`).
- **Daily Cost** sensors (electricity, export, gas). EDF publishes consumption a day or more late, so today's cost never had data. Weekly and Monthly Cost remain.

After updating, the removed sensors show as unavailable. Delete them from *Settings → Entities* if they appear.

### Fixed
- **Electricity Tariff Type** was always Unknown for EDF tariff codes. It now reports EV, Export, Economy 7, Standard, Smart / Half-Hourly, Dynamic / FreePhase or Prepay.

## 2.0.2 (2026-09-25)

### Fixed
- **401 "Cannot authenticate with provided Kraken token" errors.** Rates, standing charges and consumption didn't refresh the login token before use, so they failed once it expired. This was the main cause of the intermittent 401s, and of cost tracker errors after a 401.
- Current Rate attributes exceeded Home Assistant's 16KB recorder limit; the full rate lists are no longer recorded (still available on the entity).

## 2.0.1 (2026-09-25)

### Fixed
- Tariffs that publish only one payment method (e.g. FreePhase, direct debit only) no longer lose all their rates.
- Imported cost statistics are no longer rounded to the penny every half hour.
- Tariffs EDF temporarily hides after launching a new version (including half-hourly tariffs such as Go Electric) are priced from the account agreement instead of going unknown.

## 2.0.0 (2026-09-24)

### Changed (breaking)
- The integration's internal name is now **`edf_energy_uk`** ("EDF Energy UK"), so it can run alongside [stevekirtley's EDF Energy integration](https://github.com/stevekirtley/HomeAssistant-EDFEnergy). The integration must be removed and added again. Entity names are unchanged, so entity IDs normally come back the same.
- Service renamed to `edf_energy_uk.run_graphql_query`; events renamed to `edf_energy_uk_electricity_*` / `edf_energy_uk_gas_*`; Energy dashboard statistics renamed to `edf_energy_uk:…`.

## 1.9.8.7 (2026-09-24)

### Added
- [docs/ENTITIES.md](docs/ENTITIES.md): reference for every entity, attribute, event, service and repair.

### Fixed
- Smart Charging sensors *Intelligent Current State* and *Intelligent Dispatches Last Retrieved* were never created.

## 1.9.8.6 (2026-09-24)

### Fixed
- Direct debit prices: rates and standing charges used the (higher) non direct debit price.
- Export tariff rates and standing charge (EDF refuses its product endpoints for export tariffs).

### Added
- Meter reading sensors list every register in a `registers` attribute; quarantined readings are skipped.

## 1.9.8.5 (2026-09-24)

### Added
- `run_graphql_query` service: read-only, admin-only GraphQL queries against the EDF API for debugging.

## 1.9.8.4 (2026-09-24)

### Fixed
- Reconfigure reload deprecation (Home Assistant 2026.12).
- Restored attributes could revert state/device class changes.
- Token retrieval backs off after server errors instead of retrying on every request.

## 1.9.8.3 (2026-09-24)

### Fixed
- "Invalid credentials" when the password contains `"` or `\`: credentials are sent as GraphQL variables. The email is trimmed.
- Expected EDF errors (annual consumption not available) are logged quietly.

### Added
- *EDF Auth Token Expiry* diagnostic sensor (disabled by default).

## 1.9.8.2 (2026-09-24)

### Fixed
- Meter readings (need EDF's internal meter ID; newest reading first).
- Last Payment (direct debit payments were never matched).
- Direct Debit Amount (was never fetched).

## 1.9.8.1 (2026-09-24)

First fork release, based on upstream `main` (v1.9.9b beta).

### Fixed
- Login token handling: valid refresh tokens were discarded, expired tokens kept in use, and the refresh lock didn't work.
- "No active tariff" repair never fired.
- Invalid state class on money sensors.
