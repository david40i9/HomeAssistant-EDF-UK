# Fork changes

This fork of [Bobby5291/HomeAssistant-EDF-UK](https://github.com/Bobby5291/HomeAssistant-EDF-UK) is based on upstream `main` (the `v1.9.9b` beta plus the NOTICE file) with extra fixes on top. The integration domain is unchanged (`edf_energy`), so it can replace the upstream install without losing entities or history.

Fork version: **1.9.8.1** (shown in Home Assistant under the integration's details).

## Fixes added in this fork

### Authentication (ported from HomeAssistant-OctopusEnergy)

These address intermittent `401 Cannot authenticate with provided Kraken token` errors and "using cached data" warnings.

- **Valid refresh token was discarded.** The expiry check was inverted (`>=` instead of `<`), so the refresh token was thrown away while still valid and every refresh fell back to a full email/password login.
- **Expired token kept in use.** When fetching a new token failed, the integration only raised an error if the *old token was still valid* (`>` instead of `<`). With an expired token it logged and carried on, so every following request failed with 401.
- **Refresh lock did not work.** A class-level `threading.RLock` was used in async code. It does not stop coroutines on the event loop thread from running together, so several refreshes could race and invalidate each other's tokens. Replaced with a per-instance `asyncio.Lock`.
- **Token lifetime read from the token.** Expiry now comes from the JWT `exp` claim instead of assuming one hour (falls back to one hour if it can't be decoded).
- **Recover after a 401.** A rejected token and refresh token are cleared, so the next update re-authenticates cleanly instead of reusing a token the server has rejected.
- **Cloudfront 403s** ("The request could not be satisfied") are treated as server errors rather than authentication failures.

Octopus's token-failure cooldown and "API key invalid" lockout were deliberately not ported: with email/password login, a single transient failure could stop the integration until Home Assistant restarts.

### Repairs and sensors

- **"No active tariff" repair issue never fired.** The async helpers were passed as plain callbacks and called without `await`, creating coroutines that never ran. The rates refresh now awaits them, as Octopus Energy does.
- **Invalid state class on money sensors.** Day Rate, Night Rate, Last Payment and Direct Debit Amount used `measurement` with the `monetary` device class, which Home Assistant rejects with a warning. Changed to `total`.

### Packaging

- `hacs.json` installs from the repository contents instead of a release zip, since the fork has no releases.

## Included from upstream beta (v1.9.8b / v1.9.9b, not in stable v1.9.7)

- **Meter readings** use a GraphQL `electricityMeterReadings` / `gasMeterReadings` query, replacing the REST `/readings/` endpoint that now returns 405.
- **Account transactions** query `amounts { gross }` (the `grossAmount` field no longer exists).
- **Annual consumption**: expected `AUTHORIZATION` / `KT-CT-1111` failures for new accounts are logged at debug level instead of as warnings.
- **Annual consumption sensors** (EAC/AQ) use state class `total` to match the energy device class.
- **Intelligent/EV coordinator** now starts (missing import and a `hass.data` key collision fixed).

## Not yet resolved

- The transactions field name (`amounts { gross }`) comes from upstream and has not been independently verified. If "Last Payment" stays unknown, this is the first place to look.
