# Changelog

Version history of this fork. Versions are shown in Home Assistant under the integration's details. Credits in brackets name the people whose fixes, reports or findings each change is based on. For the reasoning behind each fix, see [FORK_CHANGES.md](FORK_CHANGES.md); for what every entity does, see [docs/ENTITIES.md](docs/ENTITIES.md).

## 2.3.0 (2026-09-25)

### Added
- **Smart Meter Data Frequency** (diagnostic): how often EDF may collect your smart meter readings. Half-hourly consumption, costs and Energy dashboard statistics need `HALF_HOURLY`; if it says `DAILY` or `MONTHLY`, that's why they stay blank.
- **Campaigns**: the EDF schemes and account processes your account is enrolled in (for example Sunday Saver, or a meter settlement change in progress).

### Improved
- Tariffs EDF won't price through its product endpoints (export, temporarily hidden and day/night tariffs) are now priced from the account's **applicable rates**. These are the prices EDF applies to your account for any period, so past days are priced correctly too. The agreement prices remain as a last resort.

## 2.2.2 (2026-09-25)

### Fixed
- Export consumption from 2.2.0 wasn't used: export meters weren't recognised. They are now.

## 2.2.1 (2026-09-25)

### Fixed
- **Previous day consumption and cost used the wrong day.** "Yesterday" was taken in UTC, so during British Summer Time it ran from 1am to 1am, and a day was used even if EDF had only published a few readings. The sensors now show the most recent *complete* UK day (every half hour present, including the 46- and 50-half-hour clock-change days), so they match your bill and no longer go blank while EDF catches up. (Approach from @stevekirtley's integration and @BottlecapDave's Octopus Energy.)

## 2.2.0 (2026-09-25)

### Added
- **Next Payment**: amount and date of your next scheduled payment, with the next three listed.
- **Last Statement**: charges on your most recent statement, with its period, due date and balances.
- **Suggested Direct Debit**: the amount EDF's payment review suggests, and the minimum it would accept.
- **Rewards**: total rewards (such as refer-a-friend), each listed, and the number of referrals.

Found by exploring EDF's GraphQL API with the `run_graphql_query` service. No addresses, names or referral codes are fetched.

### Fixed
- **Export consumption** (Export Previous Accumulative Consumption and Cost, the export cost trackers and the Energy dashboard's return to grid) was always unknown. EDF doesn't serve export on its consumption endpoint, but does in GraphQL `measurements`, which is now used for export meters.

## 2.1.0 (2026-09-25)

### Removed
- **Live consumption**: the *Supports live consumption* option and its sensors (Current Demand, Current Consumption, Current Total Consumption, Current Accumulative Consumption/Cost, Current Total Export). EDF doesn't provide smart meter telemetry for any account (`KT-GB-4039`). (Confirmed with EDF by @stevekirtley in [his #25](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/25); reported by @ArcadePunks in [Bobby5291 #24](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/24).)
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
- Tariffs that publish only one payment method (e.g. FreePhase, direct debit only) no longer lose all their rates. (From @stevekirtley's integration, [#10](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/10); reported by @mungojam.)
- Imported cost statistics are no longer rounded to the penny every half hour. (Found by @wildsurfer, who also submitted a fix to Octopus Energy; fixed in @stevekirtley's integration after his [#30](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/30).)
- Tariffs EDF temporarily hides after launching a new version (including half-hourly tariffs such as Go Electric) are priced from the account agreement instead of going unknown. (Approach from @stevekirtley's integration, [#23](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/23) and [#32](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/32).)

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
- Direct debit prices: rates and standing charges used the (higher) non direct debit price. (Filtering ported from @BottlecapDave's Octopus Energy integration.)
- Export tariff rates and standing charge (EDF refuses its product endpoints for export tariffs).

### Added
- Meter reading sensors list every register in a `registers` attribute; quarantined readings are skipped.

## 1.9.8.5 (2026-09-24)

### Added
- `run_graphql_query` service: read-only, admin-only GraphQL queries against the EDF API for debugging. (Based on @BottlecapDave's Octopus Energy service, [commit 0fccec8c](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/commit/0fccec8c).)

## 1.9.8.4 (2026-09-24)

### Fixed
- Reconfigure reload deprecation (Home Assistant 2026.12). (Octopus Energy fix by @hCoureau, [#1843](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/issues/1843).)
- Restored attributes could revert state/device class changes. (Octopus Energy fix by @BottlecapDave, [#1830](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/issues/1830).)
- Token retrieval backs off after server errors instead of retrying on every request. (Octopus Energy fix by @alekc, [commit 43218368](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/commit/43218368).)

## 1.9.8.3 (2026-09-24)

### Fixed
- "Invalid credentials" when the password contains `"` or `\`: credentials are sent as GraphQL variables. The email is trimmed. (Credentials fix from @Bobby5291's unmerged [PR #32](https://github.com/Bobby5291/HomeAssistant-EDF-UK/pull/32); reported by @ggodart in [#27](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/27).)
- Expected EDF errors (annual consumption not available) are logged quietly. (Reported by @ArcadePunks in [#24](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/24).)

### Added
- *EDF Auth Token Expiry* diagnostic sensor (disabled by default). (From @Bobby5291's [PR #32](https://github.com/Bobby5291/HomeAssistant-EDF-UK/pull/32).)

## 1.9.8.2 (2026-09-24)

### Fixed
- Meter readings (need EDF's internal meter ID; newest reading first).
- Last Payment (direct debit payments were never matched).
- Direct Debit Amount (was never fetched).

## 1.9.8.1 (2026-09-24)

First fork release, based on @Bobby5291's upstream `main` (v1.9.9b beta), which includes the Smart Charging coordinator fix diagnosed by @energizedev in [#28](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/28).

### Fixed
- Login token handling: valid refresh tokens were discarded, expired tokens kept in use, and the refresh lock didn't work. (Octopus Energy fixes by @BottlecapDave: [7fe91791](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/commit/7fe91791), [e7f59cc7](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/commit/e7f59cc7), [b7497b81](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/commit/b7497b81), [6b9d140a](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/commit/6b9d140a).)
- "No active tariff" repair never fired. (Matches @BottlecapDave's Octopus Energy implementation.)
- Invalid state class on money sensors.
