from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd


CITIES = ["Sydney", "Canberra", "Melbourne", "Brisbane", "Adelaide", "Perth", "Darwin", "Hobart"]

CITY_CALL = {
    "Sydney": "retailNswUlp",
    "Canberra": "retailNswUlp",
    "Melbourne": "retailVicUlp",
    "Brisbane": "retailQldUlp",
    "Adelaide": "retailSaUlp",
    "Perth": "retailWaUlp",
    "Darwin": "retailNtUlp",
    "Hobart": "retailTasUlp",
}


@dataclass
class ScrapeResult:
    rows: pd.DataFrame
    source_urls: list[str]
    scraped_at: str


def _api_url(city: str) -> str:
    call = CITY_CALL[city]
    return (
        "https://www.aip.com.au/aip-api-request?api-path=public/api"
        f"&call={quote(call)}&location={quote(city)}"
    )


def _extract_city_series(city: str) -> pd.DataFrame:
    url = _api_url(city)
    request = Request(url, headers={"User-Agent": "Macromonitor petrol price scraper"})
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))

    try:
        data = payload["series"][0]["data"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Could not find chart data for {city}") from exc

    series = pd.DataFrame(data, columns=["week_ending", city])
    series["week_ending"] = pd.to_datetime(series["week_ending"], unit="ms").dt.normalize()
    series[city] = series[city].astype(float)
    return series


def scrape_latest_petrol_prices() -> ScrapeResult:
    city_frames: list[pd.DataFrame] = []
    failures: dict[str, str] = {}

    for city in CITIES:
        try:
            city_frames.append(_extract_city_series(city))
        except Exception as exc:
            failures[city] = str(exc)

    if failures:
        details = "; ".join(f"{city}: {error}" for city, error in failures.items())
        raise RuntimeError(f"Refresh aborted. Failed cities: {details}")

    rows = city_frames[0]
    for frame in city_frames[1:]:
        rows = rows.merge(frame, on="week_ending", how="inner")
    if rows.empty:
        raise RuntimeError("Refresh aborted. AIP city series did not share any week-ending dates.")

    rows["month_start"] = rows["week_ending"].values.astype("datetime64[M]")
    rows = rows[["month_start", "week_ending", *CITIES]].sort_values("week_ending")

    return ScrapeResult(
        rows=rows,
        source_urls=[_api_url(city) for city in CITIES],
        scraped_at=datetime.now().isoformat(timespec="seconds"),
    )


def load_prices(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["month_start"] = pd.to_datetime(df["month_start"])
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    return df.sort_values("week_ending")


def save_prices(df: pd.DataFrame, csv_path: Path, xlsx_path: Path) -> None:
    output = df.sort_values("week_ending").copy()
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
