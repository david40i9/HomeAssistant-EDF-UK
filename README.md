# EDF UK Integration for Home Assistant
[![Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fdavid40i9%2FHomeAssistant-EDF-UK%2Fmain%2Fcustom_components%2Fedf_energy%2Fmanifest.json&query=%24.version&label=version&style=for-the-badge)](FORK_CHANGES.md)
[![GitHub Stars](https://img.shields.io/github/stars/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](https://github.com/david40i9/HomeAssistant-EDF-UK/stargazers)
[![GitHub Watchers](https://img.shields.io/github/watchers/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](https://github.com/david40i9/HomeAssistant-EDF-UK/watchers)
[![GitHub Forks](https://img.shields.io/github/forks/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](https://github.com/david40i9/HomeAssistant-EDF-UK/network)
[![License](https://img.shields.io/github/license/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz/)

A custom Home Assistant integration for retrieving and monitoring EDF UK smart meter energy data directly within Home Assistant.

This is a maintained fork of [Bobby5291/HomeAssistant-EDF-UK](https://github.com/Bobby5291/HomeAssistant-EDF-UK), with fixes for authentication, meter readings, payments and several upstream issues. See [FORK_CHANGES.md](FORK_CHANGES.md) for the full list.

---

## Features

- EDF UK account integration (balances, direct debit, last payment, tariffs, contract end dates)
- Electricity (import and export) and gas rates, standing charges and cost tracking, using your direct debit prices where they apply
- Meter register readings for electricity (import and export) and gas, including every register on multi-rate meters
- Previous-day consumption and cost for the Home Assistant Energy Dashboard
- EDF Smart Charging (EV) support (not yet widely tested)

---

## Current Status

### 🚧 Work in Progress

This integration is still under development. You may encounter:

- Breaking changes
- Missing features
- API changes on EDF's side
- Limited documentation

Some data depends on your EDF account. For example, EDF doesn't provide annual consumption estimates for newer accounts, or live smart meter telemetry for some meters. These are logged quietly and the related sensors stay unknown or unavailable.

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Open the menu (⋮) and choose **Custom repositories**
3. Add this repository with the category `Integration`:

```text
https://github.com/david40i9/HomeAssistant-EDF-UK
```

4. Download **EDF Energy**
5. Restart Home Assistant

If you already have the original Bobby5291 repository installed through HACS, remove it from HACS first (this keeps your EDF integration entry and entities), then add this one.

### Manual Installation

1. Copy the `custom_components/edf_energy` directory into your Home Assistant `custom_components` folder
2. Restart Home Assistant

---

## Configuration

Add the integration from the Home Assistant UI:

```text
Settings → Devices & Services → Add Integration → EDF Energy
```

You will need:

- Your EDF UK account email and password
- Your EDF account number

### Debugging service

`edf_energy.run_graphql_query` runs a read-only GraphQL query against the EDF API using the integration's login and returns the raw response. It's intended for diagnosing API problems: admin-only, queries only (no mutations), and limited to once a minute. Call it from Developer Tools → Actions:

```yaml
action: edf_energy.run_graphql_query
data:
  account_id: A-12345678
  query: "query ($acc: String!) { account(accountNumber: $acc) { balance } }"
  variables:
    acc: A-12345678
```

---

## Support

- **Bugs:** please [open an issue](https://github.com/david40i9/HomeAssistant-EDF-UK/issues) and include a diagnostics download (Settings → Devices & Services → EDF Energy → ⋮ → Download diagnostics). Account and meter identifiers are redacted.
- **Questions and ideas:** use [Discussions](https://github.com/david40i9/HomeAssistant-EDF-UK/discussions).

Contributions, bug reports and testing are all appreciated, particularly from Smart Charging (EV) users.

---

## Refer a Friend

If you're switching to EDF, you can use this referral link:

https://edfenergy.com/quote/refer-a-friend/smoke-broom-457

---

## Credits

- **[Bobby5291](https://github.com/Bobby5291)** created the original [EDF UK integration](https://github.com/Bobby5291/HomeAssistant-EDF-UK) that this fork is based on.
- **[BottlecapDave](https://github.com/BottlecapDave)** wrote the [Home Assistant Octopus Energy integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy). The EDF integration is heavily inspired by, and partially based on, it, and several fixes in this fork are ported from it. See [NOTICE](NOTICE).
- Thanks to everyone who reported issues upstream with detailed logs.

---

## Disclaimer

This project is unofficial and is not affiliated with or endorsed by:

- EDF Energy UK
- Octopus Energy
- Home Assistant

Use at your own risk.

---

## License

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

```text
Copyright 2026 Bobby5291
Modifications copyright 2026 david40i9
```

Portions are derived from HomeAssistant-OctopusEnergy under the MIT License. See [NOTICE](NOTICE).
