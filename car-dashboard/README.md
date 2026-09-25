# Company car dashboard

A single self-contained HTML page (`dashboard.html`) that analyses the company car list.

```bash
pip install pandas openpyxl
python build.py                     # reads Car_List.xlsx, writes dashboard.html
python build.py new_list.xlsx out.html
```

- `build.py` reads the first sheet, works out CO2, 2026/27 BIK %, battery kWh, estimated
  real-world mi/kWh and the 22kW-charger flag, then embeds the rows as JSON in
  `template.html`. It prints the columns, any rows that failed to parse, EVs with no
  efficiency estimate, and five spot checks. If a spot check fails, it exits non-zero.
- Every rate (tax year, income tax rate, treatment of negative contributions, NI, BIK bands,
  future EV rates, electricity price, mileage) can be edited in the page and recalculates live.
- Efficiency figures are **estimates**, set in `EFFICIENCY_RULES` in `build.py`. An EV that
  matches no rule is left blank and listed under "Data warnings".
- Chart.js loads from cdnjs. If it can't load, the tables, KPIs and shortlist still work.
