from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd


STATES = ["NSW", "VIC", "QLD", "SA", "WA", "NT", "TAS"]

STATE_PAGE_URLS = {
    "NSW": "https://aip.com.au/pricing/petrol/new-south-wales-act-retail-petrol-prices/nsw-state-average/",
    "VIC": "https://aip.com.au/pricing/petrol/victorian-retail-petrol-prices/victorian-state-average/",
    "QLD": "https://aip.com.au/pricing/petrol/queensland-retail-petrol-prices/queensland-state-average/",
    "SA": "https://aip.com.au/pricing/petrol/south-australian-retail-petrol-prices/south-australian-state-average/",
    "WA": "https://aip.com.au/pricing/petrol/western-australian-retail-petrol-prices/western-australian-state-average/",
    "NT": "https://aip.com.au/pricing/petrol/northern-territory-retail-petrol-prices/northern-territory-state-average/",
    "TAS": "https://aip.com.au/pricing/petrol/tasmania-retail-petrol-prices/tasmanian-state-average/",
}

STATE_SERIES_NAMES = {
    "NSW": "NSW State Average",
    "VIC": "Victorian State Average",
    "QLD": "Queensland State Average",
    "SA": "South Australian State Average",
    "WA": "Western Australian State Average",
    "NT": "Northern Territory State Average",
    "TAS": "Tasmanian State Average",
}

CHART_SERIES_PATTERN = re.compile(
    r"const\s+chartSeries\s*=\s*(\[.*?\]);\s*const\s+chartTitle",
    flags=re.DOTALL,
)


@dataclass
class ScrapeResult:
    rows: pd.DataFrame
    source_urls: list[str]
    scraped_at: str


def extract_chart_series(html: str, series_name: str, column_name: str) -> pd.DataFrame:
    match = CHART_SERIES_PATTERN.search(html)
    if not match:
        raise ValueError(f"Could not find AIP chartSeries data for {column_name}")

    try:
        chart_series = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"AIP returned invalid chartSeries JSON for {column_name}") from exc

    selected = next(
        (
            series
            for series in chart_series
            if str(series.get("name", "")).casefold() == series_name.casefold()
        ),
        chart_series[0] if chart_series else None,
    )
    if not selected or not selected.get("data"):
        raise ValueError(f"AIP returned no chart points for {column_name}")

    series = pd.DataFrame(selected["data"], columns=["week_ending", column_name])
    series["week_ending"] = (
        pd.to_datetime(series["week_ending"], unit="ms", utc=True)
        .dt.tz_convert(None)
        .dt.normalize()
    )
    series[column_name] = pd.to_numeric(series[column_name], errors="coerce")
    if series[column_name].isna().any():
        raise ValueError(f"AIP returned missing or non-numeric prices for {column_name}")
    series[column_name] = series[column_name].round(1)
    return series.drop_duplicates("week_ending", keep="last").sort_values("week_ending")


def extract_series(url: str, series_name: str, column_name: str) -> pd.DataFrame:
    request = Request(url, headers={"User-Agent": "Macromonitor petrol price scraper"})
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")
    return extract_chart_series(html, series_name, column_name)


def scrape_latest_state_petrol_prices() -> ScrapeResult:
    frames: list[pd.DataFrame] = []
    failures: dict[str, str] = {}

    for state in STATES:
        try:
            frames.append(extract_series(STATE_PAGE_URLS[state], STATE_SERIES_NAMES[state], state))
        except Exception as exc:
            failures[state] = str(exc)

    if failures:
        details = "; ".join(f"{state}: {error}" for state, error in failures.items())
        raise RuntimeError(f"Refresh aborted. Failed states: {details}")

    rows = frames[0]
    for frame in frames[1:]:
        rows = rows.merge(frame, on="week_ending", how="inner")
    if rows.empty:
        raise RuntimeError("Refresh aborted. AIP state series did not share any week-ending dates.")

    rows["month_start"] = rows["week_ending"].values.astype("datetime64[M]")
    rows = rows[["month_start", "week_ending", *STATES]].sort_values("week_ending")

    return ScrapeResult(
        rows=rows,
        source_urls=[STATE_PAGE_URLS[state] for state in STATES],
        scraped_at=datetime.now().isoformat(timespec="seconds"),
    )


def load_prices(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["month_start"] = pd.to_datetime(df["month_start"])
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    return df.sort_values("week_ending")


def save_prices(df: pd.DataFrame, csv_path: Path, xlsx_path: Path) -> None:
    output = df.sort_values("week_ending").copy()
    output[STATES] = output[STATES].round(1)
    output["month_start"] = output["month_start"].dt.date
    output["week_ending"] = output["week_ending"].dt.date
    output.to_csv(csv_path, index=False)
    output.to_excel(xlsx_path, index=False)


def merge_latest(existing: pd.DataFrame, scraped_rows: pd.DataFrame) -> tuple[pd.DataFrame, str, int]:
    latest = existing["week_ending"].max()
    newer_rows = scraped_rows[scraped_rows["week_ending"] > latest]
    matching_latest = scraped_rows[scraped_rows["week_ending"] == latest]

    if not newer_rows.empty:
        combined = pd.concat([existing, newer_rows], ignore_index=True)
        return combined, "appended", len(newer_rows)
    if not matching_latest.empty:
        updated = existing[existing["week_ending"] != latest]
        return pd.concat([updated, matching_latest], ignore_index=True), "overwrote_latest", 1
    return existing, "ignored_older", 0
