from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd


STATES = ["NSW", "VIC", "QLD", "SA", "WA", "NT", "TAS"]

STATE_SERIES = {
    "NSW": ("retailNswUlp", "NSW State Average"),
    "VIC": ("retailVicUlp", "Victorian State Average"),
    "QLD": ("retailQldUlp", "Queensland State Average"),
    "SA": ("retailSaUlp", "South Australian State Average"),
    "WA": ("retailWaUlp", "Western Australian State Average"),
    "NT": ("retailNtUlp", "Northern Territory State Average"),
    "TAS": ("retailTasUlp", "Tasmanian State Average"),
}

STATE_PAGE_URLS = {
    "NSW": "https://aip.com.au/pricing/ULP/NSW/nsw-state-average",
    "VIC": "https://aip.com.au/pricing/ULP/VIC/victorian-state-average",
    "QLD": "https://www.aip.com.au/pricing/ULP/QLD/queensland-state-average",
    "SA": "https://www.aip.com.au/index.php/pricing/ULP/SA/south-australian-state-average",
    "WA": "https://aip.com.au/pricing/ULP/WA/western-australian-state-average",
    "NT": "https://aip.com.au/pricing/ULP/NT/northern-territory-state-average",
    "TAS": "https://aip.com.au/pricing/ULP/TAS/tasmanian-state-average",
}


@dataclass
class ScrapeResult:
    rows: pd.DataFrame
    source_urls: list[str]
    scraped_at: str


def api_url(call: str, location: str) -> str:
    return (
        "https://www.aip.com.au/aip-api-request?api-path=public/api"
        f"&call={quote(call)}&location={quote(location)}"
    )


def extract_series(call: str, location: str, column_name: str) -> pd.DataFrame:
    request = Request(api_url(call, location), headers={"User-Agent": "Macromonitor petrol price scraper"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    try:
        data = payload["series"][0]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Could not find chart data for {column_name}") from exc

    series = pd.DataFrame(data, columns=["week_ending", column_name])
    series["week_ending"] = pd.to_datetime(series["week_ending"], unit="ms").dt.normalize()
    series[column_name] = series[column_name].astype(float).round(1)
    return series


def scrape_latest_state_petrol_prices() -> ScrapeResult:
    frames: list[pd.DataFrame] = []
    failures: dict[str, str] = {}

    for state in STATES:
        call, location = STATE_SERIES[state]
        try:
            frames.append(extract_series(call, location, state))
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
        source_urls=[api_url(*STATE_SERIES[state]) for state in STATES],
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
