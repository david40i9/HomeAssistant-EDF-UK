# Dashboard examples

Cards you can paste into a dashboard (Edit dashboard → Add card → Manual). Replace `A-12345678` with your account number (lower case, dashes as underscores, as in your entity IDs) and the meter entity IDs with your own from *Settings → Entities*. They only use built-in cards.

## Latest statement (bill)

Shows your most recent statement line by line, with VAT, as a charge or a credit:

```yaml
type: markdown
content: |
  {% set e = 'sensor.edf_energy_a_12345678_last_statement' %}
  {% macro gbp(x) %}{{ ('−£' if x|float(0) < 0 else '£') ~ '%.2f'|format(x|float(0)|abs) }}{% endmacro %}
  {% if states(e) in ['unknown','unavailable'] %}No statement yet.{% else %}
  {% set total = states(e)|float(0) %}{% set credits = state_attr(e,'credits')|float(0) %}
  <h1>{{ gbp(total) }}</h1>

  <b>{{ 'Credited' if total < 0 else 'Charged' }}</b> for {{ as_timestamp(state_attr(e,'from_date'))|timestamp_custom('%-d %b') }} – {{ as_timestamp(state_attr(e,'to_date'))|timestamp_custom('%-d %b %Y') }} · issued {{ as_timestamp(state_attr(e,'issued_date'))|timestamp_custom('%a %-d %b') }}

  | | Before VAT | VAT | Total |
  |:--|--:|--:|--:|
  {% for l in state_attr(e,'lines') or [] %}| {{ l.title }}{{ ' (export credit)' if l.title == 'Electricity' and l.total|float(0) < 0 else '' }} | {{ gbp(l.net) }} | {{ gbp(l.vat) }} | {{ gbp(l.total) }} |
  {% endfor %}{% if credits %}| Credits | | | −£{{ '%.2f'|format(credits) }} |
  {% endif %}| **Statement** | **{{ gbp(state_attr(e,'charges_before_vat')) }}** | **{{ gbp(state_attr(e,'vat')) }}** | **{{ gbp(total) }}** |

  Balance {{ gbp(state_attr(e,'opening_balance')) }} → <b>{{ gbp(state_attr(e,'closing_balance')) }}</b>
  {% endif %}
```

Export payments carry no VAT and EDF posts them as a negative electricity line, so a statement that only covers export shows as a credit.

## Meter readings and where they came from

Shows each meter's latest reading, whether it was your reading, a smart reading or an estimate, and the usage since the reading before. Useful for spotting a smart meter that has stopped sending readings:

```yaml
type: markdown
content: |
  {% macro row(label, e, unit) %}{% set a = states[e].attributes if states[e] else {} %}| {{ label }} | **{{ states(e) }} {{ unit }}** | {{ a.reading_source or '—' }}{% if a.read_at %}, {{ as_timestamp(a.read_at)|timestamp_custom('%-d %b') }}{% endif %} | {% if a.usage_since_previous is not none and a.previous_read_at %}{{ a.usage_since_previous }} {{ unit }} since {{ as_timestamp(a.previous_read_at)|timestamp_custom('%-d %b') }} ({{ (a.previous_reading_source or '')|lower }}){% else %}—{% endif %} |{% endmacro %}
  | Meter | Reading | Source | Since previous |
  |:--|--:|:--|:--|
  {{ row('Electricity', 'sensor.YOUR_ELECTRICITY_METER_READING', 'kWh') }}
  {{ row('Gas', 'sensor.YOUR_GAS_METER_READING', 'm³') }}
```

## Upcoming payments

```yaml
type: markdown
content: |
  {% set u = state_attr('sensor.edf_energy_a_12345678_next_payment','upcoming') or [] %}
  | Date | Amount | Method |
  |:--|--:|:--|
  {% for p in u %}| {{ as_timestamp(p.date)|timestamp_custom('%a %-d %b %Y') }} | £{{ '%.2f'|format(p.amount) }} | {{ p.method|replace('_',' ')|title }} |
  {% endfor %}
```

See [ENTITIES.md](ENTITIES.md) for every attribute these cards use.
