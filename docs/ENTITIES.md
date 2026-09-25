# Entities reference

Everything the EDF Energy integration exposes in Home Assistant: sensors, binary sensors, events, controls, services and repairs.

- **Names** follow the patterns below. `{account}` is your account number (e.g. `A-12345678`), `{mpan}`/`{mprn}` your meter point numbers and `{serial}` the meter serial number.
- **Export meters** get the same electricity entities as import, with `Export` in the name (e.g. *EDF Export Electricity Current Rate*).
- **Money** is in GBP. Rates are in GBP/kWh (pounds, so 28.6p shows as `0.286`), except the Free Phase Dynamic colour rates which are in p/kWh.
- **Disabled by default** entities can be enabled from the entity's settings.

Some data depends on what EDF provides for your account, noted under each section.

---

## Account

One set per EDF account.

| Entity | Type | Unit | What it shows | Useful attributes |
|---|---|---|---|---|
| EDF Account Balance ({account}) | sensor | GBP | Current account balance (positive = in credit) | `last_updated` |
| EDF Projected Balance ({account}) | sensor | GBP | Balance EDF projects for your next review | |
| EDF Overdue Balance ({account}) | sensor | GBP | Amount overdue | |
| EDF Recommended DD Adjustment ({account}) | sensor | GBP | Direct debit change EDF recommends (unknown if none) | `should_review_payments` |
| EDF Direct Debit Amount ({account}) | sensor | GBP | Your current direct debit | `payment_day`, `status` |
| EDF Last Payment ({account}) | sensor | GBP | Most recent payment received | `posted_date`, `title` |
| EDF Next Payment ({account}) | sensor | GBP | Next scheduled payment | `date`, `method`, `upcoming` (next three payments) |
| EDF Last Statement ({account}) | sensor | GBP | Charges on your most recent statement (bill) | `from_date`, `to_date`, `issued_date`, `payment_due_date`, `opening_balance`, `closing_balance`, `credits`, `is_final` |
| EDF Suggested Direct Debit ({account}) | sensor | GBP | Direct debit EDF's payment review suggests (unknown if EDF doesn't give one) | `minimum_amount` |
| EDF Rewards ({account}) | sensor | GBP | Total rewards on the account, such as refer-a-friend payments (0 if none) | `rewards` (date, scheme, amount, status), `referrals_created` |
| EDF Campaigns ({account}) | sensor | | Number of EDF campaigns the account is enrolled in | `campaigns` (name, slug, start and expiry dates) |
| EDF Account Is Overdue ({account}) | binary sensor | | On when the account has an overdue balance | `overdue_balance_gbp` |
| EDF Direct Debit Needs Review ({account}) | binary sensor | | On when EDF suggests reviewing your direct debit | `recommended_adjustment_gbp` |
| EDF Can Renew Tariff ({account}) | binary sensor | | On when you can renew or switch tariff | |

The payment, statement and reward sensors update hourly. Addresses, names and referral codes are deliberately not fetched.

## Tariffs and contracts

One set per meter point (MPAN/MPRN).

| Entity | Type | What it shows | Useful attributes |
|---|---|---|---|
| EDF Electricity Tariff ({mpan}) | sensor | Tariff name, e.g. *Go Electric 12m* | `tariff_code`, `product_code`, `display_name`, `valid_from`, `valid_to` |
| EDF Electricity Tariff Type ({mpan}) | sensor | Tariff type: Standard, Economy 7, EV, Smart / Half-Hourly, Dynamic / FreePhase, Prepay or Export | `tariff_code` |
| EDF Electricity Contract End ({mpan}) | sensor (date) | When the current contract ends | `contract_start`, `tariff_code`, `rolling_contract` |
| EDF Gas Contract End ({mprn}) | sensor (date) | When the gas contract ends (unknown for rolling/variable tariffs) | `contract_start`, `tariff_code`, `rolling_contract` |

## Electricity

Per electricity meter. Import and export meters both get these.

### Rates

Prices are the ones you're charged: direct debit prices when your account pays by direct debit. When EDF won't publish a tariff's prices (export tariffs, and tariffs it hides for a week or two after launching a new version), they come from the prices EDF applies to your account instead.

| Entity | Type | Unit | What it shows | Useful attributes |
|---|---|---|---|---|
| EDF Electricity Current Rate ({serial}/{mpan}) | sensor | GBP/kWh | Price for the current half hour | `start`, `end`, `tariff`, `current_day_min_rate`, `current_day_max_rate`, `current_day_average_rate`, `applicable_rates` |
| EDF Electricity Next Rate ({serial}/{mpan}) | sensor | GBP/kWh | The next *different* price and when it starts. Unknown on flat tariffs, as there is no change coming | `start`, `end` |
| EDF Electricity Previous Rate ({serial}/{mpan}) | sensor | GBP/kWh | The last different price. Unknown on flat tariffs | `start`, `end` |
| EDF Electricity Day Rate ({serial}/{mpan}) | sensor | GBP/kWh | The peak (highest) rate on two-rate tariffs; the single rate on flat tariffs | `night_rate`, `is_economy_7`, `tariff_code` |
| EDF Electricity Night Rate ({serial}/{mpan}) | sensor | GBP/kWh | The off-peak (lowest) rate | `day_rate`, `is_economy_7`, `tariff_code` |
| EDF Electricity Standing Charge ({serial}/{mpan}) | sensor | GBP | Daily standing charge | `start`, `end`, `tariff_code` |
| EDF Electricity Off Peak ({serial}/{mpan}) | binary sensor | | On during the cheapest rate periods | `current_start`, `current_end`, `next_start`, `next_end` |
| EDF Electricity Cheapest 1h / 2h / 3h ({serial}/{mpan}) | binary sensor | | On during the cheapest continuous 1, 2 or 3 hour window in the known rates. Useful for timing appliances | `target_start`, `target_end`, `average_rate`, `min_rate`, `max_rate`, `rates_in_period` |
| EDF Electricity Next Day Rates Available ({serial}/{mpan}) | binary sensor | | On once tomorrow's rates are published | `next_day_min_rate`, `next_day_max_rate`, `next_day_rate_count` |

**Free Phase Dynamic tariffs** get colour-coded sensors instead of Day/Night Rate:

| Entity | Unit | What it shows |
|---|---|---|
| EDF Dynamic Current Period ({serial}/{mpan}) | | Current colour band: green, amber or red |
| EDF Dynamic Today Green / Amber / Red Rate ({serial}/{mpan}) | p/kWh | Today's price for each band |
| EDF Dynamic Tomorrow Green / Amber / Red Rate ({serial}/{mpan}) | p/kWh | Tomorrow's price for each band, once published |

### Consumption and cost

EDF's half-hourly data usually arrives a day or two late, so the "previous" sensors cover the most recent *complete* UK day EDF has published (every half hour present), not necessarily yesterday. Check the `start`/`end` attributes for the exact period. Export meters read their data from EDF's smart meter measurements, as EDF's usual consumption endpoint returns nothing for export.

If all the consumption sensors stay unknown, check the *Smart Meter Data Frequency* diagnostic sensor: half-hourly data needs `HALF_HOURLY`.

| Entity | Type | Unit | What it shows | Useful attributes |
|---|---|---|---|---|
| EDF Electricity Meter Reading ({serial}/{mpan}) | sensor | kWh | Latest meter register reading (customer, smart or estimated). Readings EDF has quarantined as suspect are skipped | `read_at`, `registers` (every register, e.g. day and night on Economy 7 meters) |
| EDF Electricity Previous Accumulative Consumption ({serial}/{mpan}) | sensor | kWh | Total consumption for the latest complete day. **Use this in the Energy dashboard** | `start`, `end`, `charges` (per half hour), `total` |
| EDF Electricity Previous Accumulative Cost ({serial}/{mpan}) | sensor | GBP | Cost for that day, including standing charge | `total_without_standing_charge`, `standing_charge`, `charges` |
| EDF Electricity Previous Peak / Off-Peak Consumption ({serial}/{mpan}) | sensor | kWh | That day's usage split by peak and off-peak rate | `is_economy_7` |
| EDF Electricity Previous Peak / Off-Peak Cost ({serial}/{mpan}) | sensor | GBP | That day's cost split by peak and off-peak rate | `is_economy_7` |
| EDF Electricity Weekly / Monthly Cost ({serial}/{mpan}) | sensor | GBP | Running cost for the current week and month, from the consumption EDF has published so far | `period_start` |


### Annual estimates

EDF's estimated annual consumption. EDF doesn't return these for every account (`KT-CT-1111`, "not authorised"); they then stay unknown and the error is logged quietly.

| Entity | What it shows |
|---|---|
| EDF Electricity EAC Standard / Day / Night ({mpan}) | Estimated annual consumption, in kWh |

## Gas

Per gas meter.

| Entity | Type | Unit | What it shows | Useful attributes |
|---|---|---|---|---|
| EDF Gas Current Rate ({serial}/{mprn}) | sensor | GBP/kWh | Current gas unit rate | `start`, `end`, `tariff`, `current_day_min_rate`, `current_day_max_rate` |
| EDF Gas Next / Previous Rate ({serial}/{mprn}) | sensor | GBP/kWh | Next/previous different rate. Unknown on flat tariffs | `start`, `end` |
| EDF Gas Standing Charge ({serial}/{mprn}) | sensor | GBP | Daily standing charge | `start`, `end`, `tariff_code` |
| EDF Gas Meter Reading ({serial}/{mprn}) | sensor | m³ | Latest meter reading | `read_at`, `registers` |
| EDF Gas Previous Accumulative Consumption ({serial}/{mprn}) | sensor | kWh | Latest published day's usage, converted to kWh. **Use this in the Energy dashboard** | `start`, `end`, `charges`, `total` |
| EDF Gas Previous Accumulative Consumption m³ ({serial}/{mprn}) | sensor | m³ | The same in cubic metres | `charges`, `total` |
| EDF Gas Previous Accumulative Cost ({serial}/{mprn}) | sensor | GBP | Cost for that day including standing charge | `total_without_standing_charge`, `standing_charge` |
| EDF Gas Weekly / Monthly Cost ({serial}/{mprn}) | sensor | GBP | Running cost for the current week and month, from the consumption EDF has published so far | `period_start` |
| EDF Gas Annual Quantity ({mprn}) | sensor | kWh | EDF's annual quantity estimate (unknown for newer accounts) | `supplier_name`, `aq_effective_from` |

## Smart Charging (EV)

Created only when you have EDF's Smart Charging bolt-on with a registered vehicle or charger.

| Entity | Type | What it does | Useful attributes |
|---|---|---|---|
| EDF Intelligent Current State ({account}) | sensor | Current smart charging state reported by EDF | `mode`, `is_suspended`, `is_bump_charging`, `target_percentage`, `target_time` |
| EDF Intelligent Off Peak ({account}) | binary sensor | On during off-peak, including smart charging slots EDF schedules outside normal off-peak | `planned_dispatch_active`, `current_state` |
| EDF Intelligent Smart Charge ({account}) | switch | Turns smart charging on or off | `current_state`, `is_suspended` |
| EDF Intelligent Bump Charge ({account}) | switch | Charge now, outside the schedule | `current_state` |
| EDF Intelligent Charge Target ({account}) | number | Target battery charge, in % | |
| EDF Intelligent Target Time ({account}) | select | Ready-by time, in 30 minute steps | |
| EDF Intelligent Target Time Input ({account}) | time | The same ready-by time as a time picker | |
| EDF Intelligent Rate Mode ({account}) | select | Smart charging mode | `current_state`, `is_suspended` |
| EDF Intelligent Planned Dispatches ({account}) | calendar | Upcoming smart charging slots | |
| EDF Intelligent Completed Dispatches ({account}) | calendar | Past smart charging slots | |

## Events

Event entities fire when new rate data is available. The rates are in the event data under `rates`, for use in automations and custom cards.

| Entity | Fires with |
|---|---|
| EDF Electricity Current Day Rates ({serial}/{mpan}) | Today's rates |
| EDF Electricity Next Day Rates ({serial}/{mpan}) | Tomorrow's rates, once published |
| EDF Electricity Previous Day Rates ({serial}/{mpan}) | Yesterday's rates |
| EDF Electricity Previous Consumption Rates ({serial}/{mpan}) | Rates used for the previous consumption calculation (disabled by default) |

The same data is also fired on the Home Assistant event bus as `edf_energy_uk_electricity_current_day_rates`, `edf_energy_uk_electricity_next_day_rates`, `edf_energy_uk_electricity_previous_day_rates`, `edf_energy_uk_electricity_previous_consumption_rates` and the `edf_energy_uk_gas_*` equivalents.

## Diagnostic entities

All disabled by default except *Smart Meter Data Frequency*. Enable them if you're troubleshooting.

| Entity | What it shows |
|---|---|
| EDF Smart Meter Data Frequency ({account}) | How often EDF may collect your smart meter readings. Half-hourly consumption and costs need `HALF_HOURLY`; `DAILY` or `MONTHLY` explains blank consumption sensors, and can be changed in your EDF account |
| EDF Account Last Retrieved ({account}) | When account data was last fetched |
| EDF Auth Token Expiry ({account}) | When the current EDF login token expires |
| EDF Electricity / Gas Rates Last Retrieved | When rates were last fetched |
| EDF Electricity / Gas Standing Charge Last Retrieved | When the standing charge was last fetched |
| EDF Electricity / Gas Consumption Last Retrieved | When consumption was last fetched |
| EDF Intelligent Dispatches Last Retrieved ({account}) | When smart charging slots were last fetched |

## Services

| Service | What it does |
|---|---|
| `edf_energy_uk.run_graphql_query` | Runs a read-only GraphQL query against the EDF API and returns the raw response. For debugging; admin-only, no mutations, once a minute. See the [README](../README.md#debugging-service). |

## Repairs

The integration raises these in **Settings → System → Repairs**:

| Repair | Meaning |
|---|---|
| Invalid credentials | EDF rejected your email or password. Reconfigure the integration. |
| Account not found | The account number isn't on your EDF login. |
| No active tariff | A meter has no active tariff (e.g. between contracts). Clears itself once a tariff is active. |
| Tariff rates empty | EDF returned no rates for a tariff. Usually temporary. |

## Energy dashboard

The integration imports EDF's half-hourly data as long-term statistics, backfilled to the correct hours. Use these statistics (not the sensors) in the Energy dashboard. In the pickers they're named without the "EDF" prefix:

| Energy dashboard slot | Statistic | Cost statistic |
|---|---|---|
| Grid consumption | *Electricity {serial} {mpan} Previous Accumulative Consumption* | *Use an entity tracking the total costs* → *Electricity {serial} {mpan} Previous Accumulative Cost* |
| Return to grid | *Electricity {serial} {mpan} Export Previous Accumulative Consumption* | *Electricity {serial} {mpan} Export Previous Accumulative Cost* |
| Gas consumption | *Gas {serial} {mprn} Previous Accumulative Consumption (kWh)* | *Gas {serial} {mprn} Previous Accumulative Cost* |

(Their IDs are `edf_energy_uk:electricity_{serial}_{mpan}_previous_accumulative_consumption` and so on.)

Because EDF's data arrives a day or two late, the dashboard fills in past days once the data is published, rather than updating live.
