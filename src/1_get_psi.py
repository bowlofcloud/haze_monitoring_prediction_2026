"""
Step 1: Download Singapore's hourly 24-hour PSI readings from data.gov.sg (NEA)
and turn them into one row per day with regional and island-wide summaries.

Run:  python src/get_psi.py

- Each day's raw response is saved in data/raw/psi/ so you can stop and restart
  the script at any time; days already downloaded are skipped.
- data.gov.sg rate-limits requests without an API key. The script waits and
  retries automatically. For faster downloads, get a free key at
  https://data.gov.sg (sign in -> API keys) and set it before running:
      Mac/Linux:  export DATA_GOV_SG_API_KEY="your-key"
      Windows:    set DATA_GOV_SG_API_KEY=your-key
- Output: data/processed/psi_daily.csv
"""
import json
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

from config import END_DATE, PROCESSED, RAW, START_DATE

load_dotenv()

URLS = [
    "https://api-open.data.gov.sg/v2/real-time/api/psi",  # current API
    "https://api.data.gov.sg/v1/environment/psi",         # older API, used as a fallback
]
CACHE = RAW / "psi"
CACHE.mkdir(parents=True, exist_ok=True)
REGIONS = ["north", "south", "east", "west", "central"]


def fetch_day(day: str) -> dict:
    """Download all readings for one day (handles paging and rate limits)."""
    headers = {}
    if os.getenv("DATA_GOV_SG_API_KEY"):
        headers["x-api-key"] = os.environ["DATA_GOV_SG_API_KEY"]

    last_error = None
    for url in URLS:
        items, token = [], None
        try:
            while True:
                params = {"date": day}
                if token:
                    params["paginationToken"] = token
                for attempt in range(6):
                    r = requests.get(url, params=params, headers=headers, timeout=30)
                    if r.status_code == 429:  # too many requests -> wait and retry
                        time.sleep(5 * (attempt + 1))
                        continue
                    break
                r.raise_for_status()
                body = r.json()
                data = body.get("data", body)  # v2 wraps results in "data", v1 does not
                items.extend(data.get("items", []))
                token = data.get("paginationToken")
                if not token:
                    break
            return {"source": url, "items": items}
        except Exception as e:  # try the next URL
            last_error = e
    raise RuntimeError(f"Could not download PSI for {day}: {last_error}")


def summarise_day(day: str, payload: dict) -> dict:
    """Reduce a day's hourly readings to daily figures."""
    psi_vals, pm25_vals = [], []
    regional_psi_vals = {region: [] for region in REGIONS}
    for item in payload.get("items", []):
        readings = item.get("readings", {})
        psi = readings.get("psi_twenty_four_hourly", {})
        pm25 = readings.get("pm25_twenty_four_hourly", {})
        region_psi = [psi[r] for r in REGIONS if psi.get(r) is not None]
        for region in REGIONS:
            if psi.get(region) is not None:
                regional_psi_vals[region].append(psi[region])
        region_pm = [pm25[r] for r in REGIONS if pm25.get(r) is not None]
        if region_psi:
            psi_vals.append(max(region_psi))  # worst region at that hour
        if region_pm:
            pm25_vals.append(max(region_pm))
    return {
        "date": day,
        # Highest 24-hr PSI seen in any region at any hour of the day
        "psi_max": max(psi_vals) if psi_vals else None,
        # Average over the day of the worst-region reading
        "psi_mean": sum(psi_vals) / len(psi_vals) if psi_vals else None,
          **{f"psi_{region}": max(values) if values else None
              for region, values in regional_psi_vals.items()},
        "pm25_24h_max": max(pm25_vals) if pm25_vals else None,
        "n_readings": len(psi_vals),
    }


def main():
    start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    end = (datetime.strptime(END_DATE, "%Y-%m-%d").date() if END_DATE
           else date.today() - timedelta(days=1))
    days = [(start + timedelta(d)).isoformat() for d in range((end - start).days + 1)]

    rows = []
    for i, day in enumerate(days, 1):
        cache_file = CACHE / f"{day}.json"
        if cache_file.exists():
            payload = json.loads(cache_file.read_text())
        else:
            try:
                payload = fetch_day(day)
            except RuntimeError as e:
                print(e)
                continue
            cache_file.write_text(json.dumps(payload))
            time.sleep(0.3)  # be polite to the server
        rows.append(summarise_day(day, payload))
        if i % 100 == 0 or i == len(days):
            print(f"PSI: {i}/{len(days)} days processed")

    df = pd.DataFrame(rows)
    missing = df["psi_max"].isna().sum()
    df.to_csv(PROCESSED / "psi_daily.csv", index=False)
    print(f"Saved {len(df)} days to data/processed/psi_daily.csv ({missing} days with no readings)")


if __name__ == "__main__":
    main()
