# AIP retail petrol prices

Streamlit dashboard for weekly AIP retail petrol prices, matching the existing diesel app experience.

## Run locally

```powershell
pip install -r requirements.txt
streamlit run app.py
```

## Data

- `data/petrol_weekly_prices.csv`
- `data/petrol_weekly_prices.xlsx`

The refresh is all-or-nothing across Sydney, Canberra, Melbourne, Brisbane, Adelaide, Perth, Darwin, and Hobart. Newer weeks are appended. If AIP revises the latest existing week, that latest week is overwritten; older history is not silently rewritten.

Values are sourced from the `chartSeries` data embedded in AIP's current retail petrol pages and rounded to 1 decimal place in the CSV/XLSX outputs.

## State average app

Use `app_state.py` as the Streamlit main file to deploy the state-average version. It uses:

- `data/petrol_state_weekly_prices.csv`
- `data/petrol_state_weekly_prices.xlsx`
