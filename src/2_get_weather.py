"""
Step 2: Download daily weather for Singapore (rain, wind, temperature, humidity).

Run:  python src/get_weather.py

Source: Open-Meteo historical weather API (free, no key needed), which serves
ERA5 reanalysis data. This is used instead of the MSS station feeds because MSS
does not publish daily wind direction as a simple download.
Note: the most recent ~5 days may not be available yet.

Output: data/processed/weather_daily.csv
"""
import json
from datetime import date, timedelta

import pandas as pd
import requests

from config import END_DATE, PROCESSED, RAW, SG_LAT, SG_LON, START_DATE

URL = "https://archive-api.open-meteo.com/v1/archive"
DAILY_VARS = [
    "precipitation_sum",            # mm of rain
    "wind_speed_10m_max",           # km/h
    "wind_direction_10m_dominant",  # degrees the wind blows FROM (0 = north, 90 = east, 180 = south)
    "temperature_2m_max",           # deg C
    "relative_humidity_2m_mean",    # %
]


def main():
    end = END_DATE or (date.today() - timedelta(days=1)).isoformat()
    cache_file = RAW / "weather_openmeteo.json"
    if cache_file.exists():
        body = json.loads(cache_file.read_text())
    else:
        params = {
            "latitude": SG_LAT, "longitude": SG_LON,
            "start_date": START_DATE, "end_date": end,
            "daily": ",".join(DAILY_VARS),
            "timezone": "Asia/Singapore",
        }
        r = requests.get(URL, params=params, timeout=120)
        r.raise_for_status()
        body = r.json()
        cache_file.write_text(json.dumps(body))

    df = pd.DataFrame(body["daily"]).rename(columns={
        "time": "date",
        "precipitation_sum": "rain_mm",
        "wind_speed_10m_max": "wind_speed_max",
        "wind_direction_10m_dominant": "wind_dir",
        "temperature_2m_max": "temp_max",
        "relative_humidity_2m_mean": "humidity_mean",
    })
    df.to_csv(PROCESSED / "weather_daily.csv", index=False)
    print(f"Saved {len(df)} days to data/processed/weather_daily.csv "
          f"({df['date'].min()} to {df['date'].max()})")
    print("Tip: delete data/raw/weather_openmeteo.json to re-download with newer dates.")


if __name__ == "__main__":
    main()
