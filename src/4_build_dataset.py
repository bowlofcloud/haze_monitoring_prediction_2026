"""
Step 4: Merge PSI, weather and hotspots into one modelling table and create features.

Run:  python src/build_dataset.py
Output: data/processed/model_table.csv

Each row is one day. Regional target columns contain the next day's highest
24-hour PSI for Singapore's north, south, east, west and central regions. The
overall binary unhealthy target is retained for descriptive analysis.
"""
import numpy as np
import pandas as pd

from config import PROCESSED, UNHEALTHY_PSI

PSI_REGIONS = ["north", "south", "east", "west", "central"]


def main():
    psi = pd.read_csv(PROCESSED / "psi_daily.csv", parse_dates=["date"])
    wx = pd.read_csv(PROCESSED / "weather_daily.csv", parse_dates=["date"])
    hs = pd.read_csv(PROCESSED / "hotspots_daily.csv", parse_dates=["date"])

    # A complete calendar so that "yesterday" and "tomorrow" are always one day apart
    days = pd.date_range(psi.date.min(), psi.date.max(), freq="D")
    df = pd.DataFrame({"date": days})
    df = df.merge(psi, on="date", how="left").merge(wx, on="date", how="left").merge(hs, on="date", how="left")

    # No hotspot row on a day = no fires detected (within the period the hotspot data covers)
    hs_cols = ["hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula"]
    covered = df.date.between(hs.date.min(), hs.date.max())
    df.loc[covered, hs_cols] = df.loc[covered, hs_cols].fillna(0)

    # --- Air quality features ---
    df["psi_yesterday"] = df.psi_max.shift(1)
    df["psi_change"] = df.psi_max - df.psi_yesterday
    for region in PSI_REGIONS:
        col = f"psi_{region}"
        df[f"{col}_change"] = df[col] - df[col].shift(1)

    # --- Fire features (log scale because counts range from 0 to thousands) ---
    for region in ["sumatra", "borneo"]:
        col = f"hotspots_{region}"
        df[f"{col}_3d"] = df[col].rolling(3, min_periods=1).sum()
        df[f"log_{col}_3d"] = np.log1p(df[f"{col}_3d"])

    # --- Wind features ---
    # wind_dir is where the wind comes FROM. Smoke from Sumatra arrives on
    # south-westerly/westerly winds; smoke from Borneo on south-easterly/easterly winds.
    rad = np.deg2rad(df.wind_dir)
    df["wind_from_east"] = np.sin(rad)    # +1 = from the east, -1 = from the west
    df["wind_from_north"] = np.cos(rad)   # +1 = from the north, -1 = from the south
    df["wind_from_sumatra"] = df.wind_dir.between(200, 290).astype(float)
    df["wind_from_borneo"] = df.wind_dir.between(70, 160).astype(float)
    df.loc[df.wind_dir.isna(), ["wind_from_sumatra", "wind_from_borneo"]] = np.nan

    # Interaction: fires only matter if the wind is blowing their smoke towards us
    df["sumatra_fires_x_wind"] = df.log_hotspots_sumatra_3d * df.wind_from_sumatra
    df["borneo_fires_x_wind"] = df.log_hotspots_borneo_3d * df.wind_from_borneo

    # --- Rain ---
    df["rain_3d"] = df.rain_mm.rolling(3, min_periods=1).sum()

    df["month"] = df.date.dt.month

    # --- Target: is tomorrow unhealthy? ---
    df["psi_tomorrow"] = df.psi_max.shift(-1)
    for region in PSI_REGIONS:
        df[f"psi_{region}_tomorrow"] = df[f"psi_{region}"].shift(-1)
    df["unhealthy_tomorrow"] = (df.psi_tomorrow > UNHEALTHY_PSI).astype(float)
    df.loc[df.psi_tomorrow.isna(), "unhealthy_tomorrow"] = np.nan

    df.to_csv(PROCESSED / "model_table.csv", index=False)
    regional_targets = [f"psi_{region}_tomorrow" for region in PSI_REGIONS]
    usable = df.dropna(subset=regional_targets + ["wind_dir"])
    print(f"Saved data/processed/model_table.csv: {len(df)} days, {len(usable)} usable for modelling")
    print(f"Regional PSI targets: {', '.join(regional_targets)}")
    print(f"Unhealthy days (PSI > {UNHEALTHY_PSI}): {int((df.psi_max > UNHEALTHY_PSI).sum())}")
    print(df.assign(year=df.date.dt.year).groupby("year")
            .apply(lambda g: int((g.psi_max > UNHEALTHY_PSI).sum()), include_groups=False)
            .rename("unhealthy_days").to_string())


if __name__ == "__main__":
    main()
