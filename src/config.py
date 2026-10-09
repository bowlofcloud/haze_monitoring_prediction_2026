"""Shared settings for the haze project. Change the dates here if you want a different window."""
from pathlib import Path

# Project folders
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "figures"

# Study period. 2019 is included because it had a major haze episode (Sept 2019),
# which gives the model unhealthy days to learn from.
START_DATE = "2019-01-01"
END_DATE = None  # None = up to yesterday

# Singapore centre point (used for the weather download)
SG_LAT, SG_LON = 1.3521, 103.8198

# Bounding box for fire hotspots: west, south, east, north (longitude/latitude)
# Covers Sumatra, Peninsular Malaysia and Borneo (Kalimantan, Sarawak, Sabah).
HOTSPOT_BBOX = (95.0, -6.5, 119.5, 7.5)

# "Unhealthy" threshold for the 24-hour PSI (NEA band: 101-200 is Unhealthy)
UNHEALTHY_PSI = 100

for folder in (RAW, PROCESSED, FIGURES):
    folder.mkdir(parents=True, exist_ok=True)
