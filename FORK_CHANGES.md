# Fork changes

This fork of [Bobby5291/HomeAssistant-EDF-UK](https://github.com/Bobby5291/HomeAssistant-EDF-UK) is based on upstream `main` (the `v1.9.9b` beta plus the NOTICE file) with extra fixes on top. Fork version: **2.1.0** (shown in Home Assistant under the integration's details). See [CHANGELOG.md](CHANGELOG.md) for the version-by-version history.

## 2.0.0: new internal name `edf_energy_uk`

From 2.0.0 the integration's internal name (domain) is `edf_energy_uk` instead of `edf_energy`, so it can run alongside [stevekirtley's EDF Energy integration](https://github.com/stevekirtley/HomeAssistant-EDFEnergy), which uses `edf_energy`. This is a breaking change:

- The integration must be removed and added again (as **EDF Energy UK**). Entity names are unchanged, so entity IDs normally come back the same.
- The debugging service is now `edf_energy_uk.run_graphql_query`, and rate events are `edf_energy_uk_electricity_*` / `edf_energy_uk_gas_*`.
- Energy dashboard statistics are now `edf_energy_uk:…`; re-select them in the Energy dashboard.
- Diagnostics only include this integration's entities (previously any entity with `edf_energy` in its unique ID).

## Fixes added in this fork

### Authentication (ported from HomeAssistant-OctopusEnergy)

These address intermittent `401 Cannot authenticate with provided Kraken token` errors and "using cached data" warnings.

- **Valid refresh token was discarded.** The expiry check was inverted (`>=` instead of `<`), so the refresh token was thrown away while still valid and every refresh fell back to a full email/password login.
- **Expired token kept in use.** When fetching a new token failed, the integration only raised an error if the *old token was still valid* (`>` instead of `<`). With an expired token it logged and carried on, so every following request failed with 401.
- **Refresh lock did not work.** A class-level `threading.RLock` was used in async code. It does not stop coroutines on the event loop thread from running together, so several refreshes could race and invalidate each other's tokens. Replaced with a per-instance `asyncio.Lock`.
- **Token lifetime read from the token.** Expiry now comes from the JWT `exp` claim instead of assuming one hour (falls back to one hour if it can't be decoded).
- **Recover after a 401.** A rejected token and refresh token are cleared, so the next update re-authenticates cleanly instead of reusing a token the server has rejected.
- **Cloudfront 403s** ("The request could not be satisfied") are treated as server errors rather than authentication failures.
- **REST calls never refreshed the token (the main cause of the 401s).** Octopus Energy authenticates its REST endpoints with an API key; the EDF port switched them to the GraphQL login token but didn't refresh it first. Rates, standing charges and consumption therefore used whatever token was cached, and once it expired they got `401 Cannot authenticate with provided Kraken token` until a GraphQL call happened to refresh it. Every REST call now refreshes the token first, like the GraphQL calls do.
- **Back off after server errors when logging in.** If fetching a token fails with a server error, retries wait 1, 2, 4, 8, 16, then 30 minutes, resetting after a success. Without this, every request retried a full email/password login, which keeps Kraken's rate limit tripped. Octopus Energy fix by @alekc.

Octopus's "API key invalid" lockout was deliberately not ported: with email/password login, a single failed login would stop the integration until Home Assistant restarts.

### Repairs and sensors

- **"No active tariff" repair issue never fired.** The async helpers were passed as plain callbacks and called without `await`, creating coroutines that never ran. The rates refresh now awaits them, as Octopus Energy does.
- **Invalid state class on money sensors.** Day Rate, Night Rate, Last Payment and Direct Debit Amount used `measurement` with the `monetary` device class, which Home Assistant rejects with a warning. Changed to `total`.

### Meter readings, payments and direct debit (found by querying the Kraken GraphQL schema)

- **Meter readings.** `electricityMeterReadings` / `gasMeterReadings` need the Kraken *internal meter id* as `meterId`. Serial numbers return `KT-CT-7899` ("internal error") and MPAN/MPRN return `KT-CT-1111` (unauthorised). The account query now requests each meter's `id`, and the client maps (MPAN/MPRN, serial) to that id. It's a compound key because import and export meters can share a serial number. Readings come back newest first, so the query uses `first: 5`; the beta's `last: 5` returned the oldest readings.
- **Last Payment.** EDF marks direct debit payments `isCredit: false`, so filtering on `isCredit` never found a payment. Payments are now identified by their GraphQL type (`__typename == "Payment"`).
- **Direct Debit Amount.** This was never fetched. It now comes from the account's active `paymentSchedules` entry (`paymentAmount` in pence, plus `paymentDay`).
- The internal meter id is removed from the diagnostics download, alongside the existing device id redaction.
- **All registers exposed.** Meter reading sensors keep the first register as their state and add a `registers` attribute listing every register (e.g. day and night on Economy 7 meters). Readings EDF has quarantined as suspect are skipped.

### Rates and standing charges (found with the GraphQL query service)

- **Direct debit prices.** EDF's product endpoints return separate direct debit and non direct debit prices, and the integration mixed them, typically ending up with the higher non direct debit price. On one account this overstated gas at 7.57p/kWh and 36.7p/day against the 7.19p/kWh and 28.78p/day actually charged. Octopus Energy's filtering was ported, and the integration picks direct debit prices automatically when the account has an active direct debit.
- **Export tariffs.** EDF refuses the REST product endpoints for export tariffs with a `401`, so export rate, standing charge and export cost sensors were permanently unknown. The account query now also fetches the unit rate and standing charge on each agreement, and the integration falls back to those when the product endpoints won't serve a tariff.
- **401s from product endpoints no longer discard the login.** Those refusals are about the product, not the token, so they no longer clear the token and force a new email/password login. Many of the "Cannot authenticate with provided Kraken token" warnings seen on accounts with export came from here.

### Fixes from Octopus Energy's issue tracker

The EDF integration was copied from Octopus Energy around v18.2/v18.3 (May 2026). Every Octopus fix since then was reviewed; these applied to shared code:

- **[#1843](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/issues/1843) Reconfigure reload deprecation.** Reconfiguring used `async_update_reload_and_abort` alongside an update listener, which Home Assistant warns about and stops supporting in 2026.12. It now uses `async_update_and_abort` and leaves the reload to the listener. Fix by @hCoureau.
- **[#1830](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/issues/1830) State and device class changes not applied.** Sensors restore their previous attributes after a restart, which could carry an old `state_class`/`device_class` forward. These two keys are no longer restored.
- **Token back-off after server errors**, as above.
- **`edf_energy_uk.run_graphql_query` service** (ported from Octopus). Runs a GraphQL query against the EDF API using the integration's existing login and returns the raw response, which makes diagnosing API changes possible without code changes. Unlike Octopus's version it is read-only (mutations are rejected) and admin-only; like Octopus's it is limited to once a minute.

Already present or not applicable: statistics `mean_type` (#1630/#1653), cost rounding accuracy (#1704), token refresh fixes, Cloudfront 403 handling (#1781), `async_get_device` deprecation (not used), multiple gas meter records (#1672, EDF sets up each meter separately), day/night time-window fix (EDF fetches day and night rates separately).

### Upstream issues addressed

- **[#27](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/27) Invalid credentials on setup.** Login now passes credentials as GraphQL variables instead of pasting them into the query text, ported from Bobby's unmerged [PR #32](https://github.com/Bobby5291/HomeAssistant-EDF-UK/pull/32), so a password containing `"` or `\` no longer breaks the query. The email address is trimmed, and `KT-CT-1138` is reported as invalid credentials rather than an unknown error.
- **[#28](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/28) / [#30](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/30) Smart Charging never starts / entities missing.** Fixed in the upstream beta, which this fork includes.
- **[#24](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/24) Log spam and unknown sensors.** Meter readings, `grossAmount`, the EAC state class and the manifest version are fixed (see above). Expected EDF responses (`KT-GB-4039` live telemetry not available, `KT-CT-1111` annual consumption) are logged at debug instead of repeating as warnings; annual gas now gets the same handling as electricity. Diagnostics keep a `has_device_id` flag instead of dropping the field.
- From PR #32: a disabled-by-default **EDF Auth Token Expiry** diagnostic sensor.

### Fixes learned from stevekirtley/HomeAssistant-EDFEnergy

Found by reading the issues and code of [stevekirtley's EDF integration](https://github.com/stevekirtley/HomeAssistant-EDFEnergy) (MIT):

- **Direct debit filter too strict** ([#10](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/10)). If a tariff publishes only one payment method (e.g. FreePhase Dynamic is direct debit only) and it isn't the account's, every rate was discarded. The other method is now only excluded when the preferred one is actually present.
- **Imported cost statistics rounded every half hour to the penny** ([#30](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/30)), which can put a day's imported cost several percent out. Costs now accumulate at full precision and are rounded once per statistic. Found by @wildsurfer, who also submitted a fix to Octopus Energy; stevekirtley fixed it in his integration.
- **Hidden tariffs** ([#23](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/23), [#32](https://github.com/stevekirtley/HomeAssistant-EDFEnergy/issues/32)). When EDF launches a new version of a tariff it hides the old one from the pricing API for a week or two, and customers still on it get unknown rates. The agreement-rate fallback (added for export tariffs) now also covers half-hourly tariffs such as Go Electric, using the current day's dated rate bands on the agreement, plus prepay tariffs.

### Smart Charging (EV)

- **Missing sensors.** *EDF Intelligent Current State* and *EDF Intelligent Dispatches Last Retrieved* were written and imported but never created, and weren't `SensorEntity` subclasses. They're now proper sensors and are created when a Smart Charging device is present.

### Documentation

- **[docs/ENTITIES.md](docs/ENTITIES.md)** lists every entity, attribute, event, service and repair, generated from the code, plus Energy dashboard setup.

### Recorder

- **Current Rate attributes too large.** The full `all_rates`/`applicable_rates` lists pushed the Current Rate sensors' attributes over Home Assistant's 16KB limit, so the recorder dropped them with a warning. Those two lists are now excluded from the recorder; they're still available on the live entity.

### Tidy-up: removed what can't work, fixed Tariff Type

- **Removed live consumption.** The *Supports live consumption* option and its sensors (Current Demand, Current Consumption, Current Total Consumption, Current Accumulative Consumption/Cost, Current Total Export) relied on `smartMeterTelemetry`, which EDF doesn't provide for any account (`KT-GB-4039`, confirmed with EDF by stevekirtley and reported on Bobby5291's #24). Existing config entries keep the option in their stored data, which is simply ignored.
- **Removed Daily Cost sensors** (electricity, export, gas). They add up *today's* consumption, and EDF only publishes consumption a day or more later for every account, so they could never have a value. Weekly and Monthly Cost are unchanged.
- **Kept** the annual consumption sensors, flat-tariff next/previous rates and export consumption, which work for some accounts or tariffs even when they don't for this one.
- **Fixed Electricity Tariff Type**, which was always Unknown: the tariff-code pattern (from Octopus) didn't allow the underscores in EDF product codes. It now uses the tariff type EDF reports on the agreement (Go Electric → EV, export → Export, day/night → Economy 7), with the corrected pattern as a fallback.

### Thanks

- **@Bobby5291** for the original EDF UK integration and the credentials fix in PR #32.
- **@BottlecapDave** and the Octopus Energy contributors, including **@hCoureau** and **@alekc**, for the fixes ported here.
- **@stevekirtley** for his EDF integration, his issue discussions and his confirmations with EDF.
- **@wildsurfer**, **@mungojam**, **@ArcadePunks**, **@ggodart** and **@energizedev** for the reports and diagnoses these fixes build on.

### Packaging

- `hacs.json` installs from the repository contents instead of a release zip, since the fork has no releases.

## Included from upstream beta (v1.9.8b / v1.9.9b, not in stable v1.9.7)

- **Meter readings** use a GraphQL `electricityMeterReadings` / `gasMeterReadings` query, replacing the REST `/readings/` endpoint that now returns 405. (This fork fixes the meter id and ordering; see above.)
- **Account transactions** query `amounts { gross }` (the `grossAmount` field no longer exists). Confirmed against the live schema.
- **Annual consumption**: expected `AUTHORIZATION` / `KT-CT-1111` failures for new accounts are logged at debug level instead of as warnings.
- **Annual consumption sensors** (EAC/AQ) use state class `total` to match the energy device class.
- **Intelligent/EV coordinator** now starts (missing import and a `hass.data` key collision fixed).

## Not yet resolved

- Annual consumption (EAC/AQ) returns `KT-CT-1111` ("not authorised") for some accounts, including one on EDF since 2023, so it may not be available to customer logins at all. The sensors are kept for accounts where it works.
- Day/night (Economy 7) tariffs can't be priced from the account agreement when EDF hides the product, as the agreement doesn't include the time bands.
- Rate and standing charge sensors still use `monetary` + `total`. Octopus Energy v19 moved them to `measurement` for min/max/average statistics; that change would make Home Assistant ask to delete their existing statistics, so it hasn't been made.
