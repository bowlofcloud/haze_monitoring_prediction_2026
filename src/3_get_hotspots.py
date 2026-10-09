"""
Step 3: Download satellite fire hotspots (NASA FIRMS, VIIRS S-NPP sensor) for
Sumatra and Borneo, and count them per day.

Before running:
  1. Get a free MAP_KEY at https://firms.modaps.eosdis.nasa.gov/api/map_key/
     (enter your email; the key arrives instantly).
  2. Set it:  Mac/Linux: export FIRMS_MAP_KEY="your-key"
              Windows:   set FIRMS_MAP_KEY=your-key

Run:  python src/get_hotspots.py

Plan B (if the API gives you trouble): download the yearly country files for
Indonesia and Malaysia (VIIRS S-NPP, CSV) from
https://firms.modaps.eosdis.nasa.gov/country/ , put the CSVs in
data/raw/firms_manual/ and run:  python src/get_hotspots.py --from-folder

Outputs:
  data/processed/hotspots_daily.csv   one row per day with counts per region
  data/processed/hotspots_points.csv  every hotspot (used for the map)
"""
import argparse
import io
import os
import sys
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from dotenv import load_dotenv

from config import END_DATE, HOTSPOT_BBOX, PROCESSED, RAW, START_DATE

load_dotenv()

API = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{bbox}/{days}/{start}"
DAYS_PER_CALL = 5          # FIRMS allows a short date range per request
RECENT_DAYS = 150          # the archive ("SP") lags a few months; use near-real-time ("NRT") for recent dates
CACHE = RAW / "firms"
CACHE.mkdir(parents=True, exist_ok=True)


def classify_region(lat, lon):
    """Rough split of the bounding box into Sumatra, Borneo and Peninsular Malaysia.
    The Sumatra / Peninsula boundary is a straight line through the Strait of Malacca,
    so a few coastal points may be mislabelled; that's fine for daily counts."""
    if lon >= 108.5:
        return "borneo"
    if lon <= 106.5:
        # line through the Strait of Malacca: from (100.0, 3.4) to (103.6, 1.3)
        strait_lat = 3.4 + (lon - 100.0) * (1.3 - 3.4) / (103.6 - 100.0)
        return "peninsula" if lat > strait_lat else "sumatra"
    return "other"


def fetch_chunk(key, source, start):
    cache_file = CACHE / f"{source}_{start}.csv"
    if cache_file.exists():
        return pd.read_csv(cache_file)
    bbox = ",".join(str(v) for v in HOTSPOT_BBOX)
    url = API.format(key=key, source=source, bbox=bbox, days=DAYS_PER_CALL, start=start)
    for attempt in range(5):
        r = requests.get(url, timeout=120)
        if r.status_code == 429 or "Exceeding allowed transaction limit" in r.text:
            time.sleep(60)
            continue
        break
    r.raise_for_status()
    if "Invalid MAP_KEY" in r.text:
        sys.exit("FIRMS says the MAP_KEY is invalid. Check FIRMS_MAP_KEY.")
    df = pd.read_csv(io.StringIO(r.text)) if r.text.strip() else pd.DataFrame()
    df.to_csv(cache_file, index=False)
    time.sleep(0.5)
    return df


def download_from_api():
    key = os.getenv("FIRMS_MAP_KEY")
    if not key:
        sys.exit("Set FIRMS_MAP_KEY first (see the instructions at the top of this file).")
    start = datetime.strptime(START_DATE, "%Y-%m-%d").date()
    end = (datetime.strptime(END_DATE, "%Y-%m-%d").date() if END_DATE
           else date.today() - timedelta(days=1))
    recent_cutoff = date.today() - timedelta(days=RECENT_DAYS)

    frames, chunk_starts = [], []
    d = start
    while d <= end:
        chunk_starts.append(d)
        d += timedelta(days=DAYS_PER_CALL)

    for i, cs in enumerate(chunk_starts, 1):
        sources = ["VIIRS_SNPP_SP"]
        if cs >= recent_cutoff:
            sources.append("VIIRS_SNPP_NRT")
        for src in sources:
            df = fetch_chunk(key, src, cs.isoformat())
            if len(df):
                frames.append(df)
        if i % 50 == 0 or i == len(chunk_starts):
            print(f"Hotspots: {i}/{len(chunk_starts)} requests done")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_from_folder():
    folder = RAW / "firms_manual"
    files = sorted(folder.glob("*.csv"))
    if not files:
        sys.exit(f"No CSV files found in {folder}")
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    w, s, e, n = HOTSPOT_BBOX
    return df[df.latitude.between(s, n) & df.longitude.between(w, e)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--from-folder", action="store_true",
                        help="read manually downloaded FIRMS CSVs instead of using the API")
    args = parser.parse_args()

    pts = load_from_folder() if args.from_folder else download_from_api()
    if pts.empty:
        sys.exit("No hotspot data retrieved.")

    pts = pts.drop_duplicates(subset=["latitude", "longitude", "acq_date", "acq_time"])
    # VIIRS confidence is 'l' (low), 'n' (nominal) or 'h' (high); drop low-confidence detections
    if "confidence" in pts.columns and pts["confidence"].dtype == object:
        pts = pts[pts["confidence"].str.lower() != "l"]
    pts["region"] = [classify_region(la, lo) for la, lo in zip(pts.latitude, pts.longitude)]
    pts["date"] = pd.to_datetime(pts["acq_date"]).dt.date.astype(str)

    keep = ["date", "latitude", "longitude", "frp", "region"]
    pts[[c for c in keep if c in pts.columns]].to_csv(PROCESSED / "hotspots_points.csv", index=False)

    daily = (pts.pivot_table(index="date", columns="region", values="latitude",
                             aggfunc="count", fill_value=0)
                .add_prefix("hotspots_").reset_index())
    for col in ["hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula"]:
        if col not in daily.columns:
            daily[col] = 0
    daily = daily[["date", "hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula"]]
    daily.to_csv(PROCESSED / "hotspots_daily.csv", index=False)
    print(f"Saved {len(pts):,} hotspots over {len(daily)} days to data/processed/")


if __name__ == "__main__":
    main()
