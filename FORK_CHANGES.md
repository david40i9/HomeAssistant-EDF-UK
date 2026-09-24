# Fork changes

This fork of [Bobby5291/HomeAssistant-EDF-UK](https://github.com/Bobby5291/HomeAssistant-EDF-UK) is based on upstream `main` (the `v1.9.9b` beta plus the NOTICE file) with extra fixes on top. The integration domain is unchanged (`edf_energy`), so it can replace the upstream install without losing entities or history.

Fork version: **1.9.8.4** (shown in Home Assistant under the integration's details).

## Fixes added in this fork

### Authentication (ported from HomeAssistant-OctopusEnergy)

These address intermittent `401 Cannot authenticate with provided Kraken token` errors and "using cached data" warnings.

- **Valid refresh token was discarded.** The expiry check was inverted (`>=` instead of `<`), so the refresh token was thrown away while still valid and every refresh fell back to a full email/password login.
- **Expired token kept in use.** When fetching a new token failed, the integration only raised an error if the *old token was still valid* (`>` instead of `<`). With an expired token it logged and carried on, so every following request failed with 401.
- **Refresh lock did not work.** A class-level `threading.RLock` was used in async code. It does not stop coroutines on the event loop thread from running together, so several refreshes could race and invalidate each other's tokens. Replaced with a per-instance `asyncio.Lock`.
- **Token lifetime read from the token.** Expiry now comes from the JWT `exp` claim instead of assuming one hour (falls back to one hour if it can't be decoded).
- **Recover after a 401.** A rejected token and refresh token are cleared, so the next update re-authenticates cleanly instead of reusing a token the server has rejected.
- **Cloudfront 403s** ("The request could not be satisfied") are treated as server errors rather than authentication failures.

- **Back off after server errors when logging in.** If fetching a token fails with a server error, retries wait 1, 2, 4, 8, 16, then 30 minutes, resetting after a success. Without this, every request retried a full email/password login, which keeps Kraken's rate limit tripped.

Octopus's "API key invalid" lockout was deliberately not ported: with email/password login, a single failed login would stop the integration until Home Assistant restarts.

### Repairs and sensors

- **"No active tariff" repair issue never fired.** The async helpers were passed as plain callbacks and called without `await`, creating coroutines that never ran. The rates refresh now awaits them, as Octopus Energy does.
- **Invalid state class on money sensors.** Day Rate, Night Rate, Last Payment and Direct Debit Amount used `measurement` with the `monetary` device class, which Home Assistant rejects with a warning. Changed to `total`.

### Meter readings, payments and direct debit (found by querying the Kraken GraphQL schema)

- **Meter readings.** `electricityMeterReadings` / `gasMeterReadings` need the Kraken *internal meter id* as `meterId`. Serial numbers return `KT-CT-7899` ("internal error") and MPAN/MPRN return `KT-CT-1111` (unauthorised). The account query now requests each meter's `id`, and the client maps (MPAN/MPRN, serial) to that id. It's a compound key because import and export meters can share a serial number. Readings come back newest first, so the query uses `first: 5`; the beta's `last: 5` returned the oldest readings.
- **Last Payment.** EDF marks direct debit payments `isCredit: false`, so filtering on `isCredit` never found a payment. Payments are now identified by their GraphQL type (`__typename == "Payment"`).
- **Direct Debit Amount.** This was never fetched. It now comes from the account's active `paymentSchedules` entry (`paymentAmount` in pence, plus `paymentDay`).
- The internal meter id is removed from the diagnostics download, alongside the existing device id redaction.

### Fixes from Octopus Energy's issue tracker

The EDF integration was copied from Octopus Energy around v18.2/v18.3 (May 2026). Every Octopus fix since then was reviewed; these applied to shared code:

- **[#1843](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/issues/1843) Reconfigure reload deprecation.** Reconfiguring used `async_update_reload_and_abort` alongside an update listener, which Home Assistant warns about and stops supporting in 2026.12. It now uses `async_update_and_abort` and leaves the reload to the listener.
- **[#1830](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy/issues/1830) State and device class changes not applied.** Sensors restore their previous attributes after a restart, which could carry an old `state_class`/`device_class` forward. These two keys are no longer restored.
- **Token back-off after server errors**, as above.

Already present or not applicable: statistics `mean_type` (#1630/#1653), cost rounding accuracy (#1704), token refresh fixes, Cloudfront 403 handling (#1781), `async_get_device` deprecation (not used), multiple gas meter records (#1672, EDF sets up each meter separately), day/night time-window fix (EDF fetches day and night rates separately).

### Upstream issues addressed

- **[#27](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/27) Invalid credentials on setup.** Login now passes credentials as GraphQL variables instead of pasting them into the query text, ported from Bobby's unmerged [PR #32](https://github.com/Bobby5291/HomeAssistant-EDF-UK/pull/32), so a password containing `"` or `\` no longer breaks the query. The email address is trimmed, and `KT-CT-1138` is reported as invalid credentials rather than an unknown error.
- **[#28](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/28) / [#30](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/30) Smart Charging never starts / entities missing.** Fixed in the upstream beta, which this fork includes.
- **[#24](https://github.com/Bobby5291/HomeAssistant-EDF-UK/issues/24) Log spam and unknown sensors.** Meter readings, `grossAmount`, the EAC state class and the manifest version are fixed (see above). Expected EDF responses (`KT-GB-4039` live telemetry not available, `KT-CT-1111` annual consumption) are logged at debug instead of repeating as warnings; annual gas now gets the same handling as electricity. Diagnostics keep a `has_device_id` flag instead of dropping the field.
- From PR #32: a disabled-by-default **EDF Auth Token Expiry** diagnostic sensor.

### Packaging

- `hacs.json` installs from the repository contents instead of a release zip, since the fork has no releases.

## Included from upstream beta (v1.9.8b / v1.9.9b, not in stable v1.9.7)

- **Meter readings** use a GraphQL `electricityMeterReadings` / `gasMeterReadings` query, replacing the REST `/readings/` endpoint that now returns 405. (This fork fixes the meter id and ordering; see above.)
- **Account transactions** query `amounts { gross }` (the `grossAmount` field no longer exists). Confirmed against the live schema.
- **Annual consumption**: expected `AUTHORIZATION` / `KT-CT-1111` failures for new accounts are logged at debug level instead of as warnings.
- **Annual consumption sensors** (EAC/AQ) use state class `total` to match the energy device class.
- **Intelligent/EV coordinator** now starts (missing import and a `hass.data` key collision fixed).

## Not yet resolved

- Annual consumption (EAC/AQ) returns `KT-CT-1111` for some accounts; EDF indicates this is expected for newer accounts.
- Meter readings report the first register only. On multi-register (day/night) meters this is one of the two registers.
