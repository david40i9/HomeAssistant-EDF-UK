# EDF UK Integration for Home Assistant

> [!IMPORTANT]
> **Looking for an EDF integration?** [stevekirtley/HomeAssistant-EDFEnergy](https://github.com/stevekirtley/HomeAssistant-EDFEnergy) is the more mature and actively maintained EDF Energy integration, with tests, documentation and EDF extras such as free electricity sessions, Flextras, cost trackers and tariff comparison. **For most people, that's the one to use.**
>
> This fork is a personal project that fixes and extends [Bobby5291's integration](https://github.com/Bobby5291/HomeAssistant-EDF-UK). It includes a few things Steve's doesn't yet (account balance, payment and direct debit sensors, meter readings and a GraphQL debug service), which I hope to contribute there. The two can run side by side.

[![Version](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fraw.githubusercontent.com%2Fdavid40i9%2FHomeAssistant-EDF-UK%2Fmain%2Fcustom_components%2Fedf_energy_uk%2Fmanifest.json&query=%24.version&label=version&style=for-the-badge)](FORK_CHANGES.md)
[![GitHub Stars](https://img.shields.io/github/stars/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](https://github.com/david40i9/HomeAssistant-EDF-UK/stargazers)
[![GitHub Watchers](https://img.shields.io/github/watchers/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](https://github.com/david40i9/HomeAssistant-EDF-UK/watchers)
[![GitHub Forks](https://img.shields.io/github/forks/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](https://github.com/david40i9/HomeAssistant-EDF-UK/network)
[![License](https://img.shields.io/github/license/david40i9/HomeAssistant-EDF-UK.svg?style=for-the-badge)](LICENSE)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)](https://hacs.xyz/)

A custom Home Assistant integration for retrieving and monitoring EDF UK smart meter energy data directly within Home Assistant.

This is a personal fork of [Bobby5291/HomeAssistant-EDF-UK](https://github.com/Bobby5291/HomeAssistant-EDF-UK), with fixes for authentication, rates, meter readings, payments and several upstream issues. See [FORK_CHANGES.md](FORK_CHANGES.md) for the full list.

---

## Features

- EDF UK account integration (balances, direct debit, last payment, tariffs, contract end dates)
- Electricity (import and export) and gas rates, standing charges and cost tracking, using your direct debit prices where they apply
- Meter register readings for electricity (import and export) and gas, including every register on multi-rate meters
- Previous-day consumption and cost for the Home Assistant Energy Dashboard
- EDF Smart Charging (EV) support (not yet widely tested)

See **[docs/ENTITIES.md](docs/ENTITIES.md)** for every sensor, control, event and service the integration exposes, what each one means, and how to set up the Energy dashboard.

---

## Current Status

### 🚧 Work in Progress

This integration is still under development. You may encounter:

- Breaking changes
- Missing features
- API changes on EDF's side
- Limited documentation

Some data depends on your EDF account. For example, EDF doesn't return annual consumption estimates for every account, and those sensors then stay unknown. EDF doesn't provide live smart meter data at all; its half-hourly consumption data arrives a day or so later instead.

---

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Open the menu (⋮) and choose **Custom repositories**
3. Add this repository with the category `Integration`:

```text
https://github.com/david40i9/HomeAssistant-EDF-UK
```

4. Download **EDF Energy UK**
5. Restart Home Assistant

This integration's internal name is `edf_energy_uk`, so it can run alongside [stevekirtley's EDF Energy integration](https://github.com/stevekirtley/HomeAssistant-EDFEnergy) (`edf_energy`). Both log in to EDF separately.

**Moving from the original Bobby5291 integration** (`edf_energy`): delete the EDF Energy integration entry in *Settings → Devices & Services*, remove the Bobby5291 repository from HACS, then install this one and add **EDF Energy UK**. Entity names are unchanged, so entity IDs normally come back the same, but it's worth checking your automations and dashboards afterwards. Energy dashboard statistics get new IDs (`edf_energy_uk:…`), so re-select them there.

### Manual Installation

1. Copy the `custom_components/edf_energy_uk` directory into your Home Assistant `custom_components` folder
2. Restart Home Assistant

---

## Configuration

Add the integration from the Home Assistant UI:

```text
Settings → Devices & Services → Add Integration → EDF Energy UK
```

You will need:

- Your EDF UK account email and password
- Your EDF account number

### Debugging service

`edf_energy_uk.run_graphql_query` runs a read-only GraphQL query against the EDF API using the integration's login and returns the raw response. It's intended for diagnosing API problems: admin-only, queries only (no mutations), and limited to once a minute. Call it from Developer Tools → Actions:

```yaml
action: edf_energy_uk.run_graphql_query
data:
  account_id: A-12345678
  query: "query ($acc: String!) { account(accountNumber: $acc) { balance } }"
  variables:
    acc: A-12345678
```

---

## Support

- **Bugs:** please [open an issue](https://github.com/david40i9/HomeAssistant-EDF-UK/issues) and include a diagnostics download (Settings → Devices & Services → EDF Energy UK → ⋮ → Download diagnostics). Account and meter identifiers are redacted.
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
- **[stevekirtley](https://github.com/stevekirtley)** maintains a separate [EDF Energy integration](https://github.com/stevekirtley/HomeAssistant-EDFEnergy), also based on Octopus Energy, with EDF extras such as Sunday Saver and Power Perks. Worth a look.
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
