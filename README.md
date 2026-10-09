# Singapore Regional PSI and Haze Monitoring

This project combines Singapore air-quality observations, weather reanalysis, and satellite fire-hotspot data to explore haze patterns and forecast next-day 24-hour PSI for Singapore's North, South, East, West, and Central regions.

The workflow downloads and prepares daily data, builds lagged predictors, compares four regional forecasting models, and produces a next-day forecast table and visualizations. The analysis is exploratory: the forecasts are not official NEA advisories.

## What the analysis does

The notebook explores:

- Daily PSI history and the timing of unhealthy episodes.
- The relationship between recent Sumatra/Borneo hotspot counts and next-day PSI.
- Dry-season PSI averages by wind direction.
- Fire detections near the worst observed haze day, including a map with Natural Earth country boundaries.
- Regional next-day PSI forecasts and their time-series validation errors.

For each forecast target, the model uses predictors from the three days before the target date: regional PSI, wind direction components and speed, hotspot counts by source region, rainfall, and humidity.

## Data sources

| Source | Data used | Access |
|---|---|---|
| [data.gov.sg](https://data.gov.sg) / NEA | Hourly regional 24-hour PSI and PM2.5 | Free API; API key is optional but speeds up downloads |
| [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) | Daily Singapore weather, including wind, rain, temperature, and humidity | Free; no key required |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) | VIIRS S-NPP satellite fire detections around Sumatra, Peninsular Malaysia, and Borneo | Free MAP_KEY required for API downloads |
| [Natural Earth](https://www.naturalearthdata.com/) and [OpenStreetMap Nominatim](https://nominatim.org/) | Country boundaries and Singapore outline used in notebook maps | Public datasets/services; internet required for map cells |

The study period begins on 1 January 2019 and, by default, continues through the latest date available to each source. PSI and weather availability may differ at the most recent dates.

## Installation and API keys

Use Python 3.10 or newer, then install the project and notebook dependencies:

```powershell
python -m pip install -r requirements.txt
python -m pip install pygam geopandas
```

The notebook kernel must use the same Python environment where these packages are installed. `pygam` is used for the generalized additive model; `geopandas` is used for map visualizations.

Create a `.env` file in the project root for API credentials:

```dotenv
FIRMS_MAP_KEY=your_nasa_firms_map_key
DATA_GOV_SG_API_KEY=your_data_gov_sg_api_key
```

Get a NASA FIRMS key from the [FIRMS MAP_KEY page](https://firms.modaps.eosdis.nasa.gov/api/map_key/). Get an optional data.gov.sg key by signing in to [data.gov.sg](https://data.gov.sg/). The `.env` file is ignored by Git; do not commit credentials.

## Run the pipeline

Run commands from the project root in this order:

```powershell
python src/1_get_psi.py
python src/2_get_weather.py
python src/3_get_hotspots.py
python src/4_build_dataset.py
```

The PSI downloader caches daily API responses, so it can resume and rebuild regional daily summaries without fetching already-cached dates again. If the FIRMS API is unavailable, manually downloaded country CSVs can be placed in `data/raw/firms_manual/`, then run:

```powershell
python src/3_get_hotspots.py --from-folder
```

Open `notebooks/haze_analysis.ipynb` and run it from top to bottom after the pipeline completes. Its map cells need internet access to retrieve boundary geometry.

## Forecast models

Part 5 compares four models independently for each Singapore region:

| Part | Model | Approach |
|---|---|---|
| 5a | Gaussian GLM | Linear baseline with an identity link; includes out-of-fold residual diagnostics |
| 5b | Quadratic Gaussian model | Adds squared predictor terms to represent curved effects |
| 5c | Log-transformed Gaussian model | Applies `log1p` to nonnegative predictors; signed wind-direction components remain unchanged |
| 5d | Gaussian GAM | Uses an additive spline for each predictor to model smooth nonlinear effects |

All models use five chronological `TimeSeriesSplit` folds with a one-row purge gap because each target is next-day PSI. The notebook compares pooled out-of-fold RMSE across regions and selects the model with the lowest mean regional RMSE. The fold scores are historical validation estimates, not a guarantee of future performance. PSI severity episodes are rare, and the Gaussian GLM residual plots show that extreme values can be underpredicted.

In the currently saved notebook run, with PSI data through 8 October 2026, mean regional RMSE is 7.20 PSI points for the Gaussian GLM, 7.43 for the GAM, 7.87 for the quadratic model, and 7.89 for the log-transformed model. The GLM is selected for the saved forecast. These figures change when data or model settings change; rerun the notebook for an updated comparison and forecast.

The Singapore map colors regions and labels them with the selected model's predicted PSI and a severity category. Its five-zone polygons are approximate Voronoi partitions around representative locations, not official PSI monitoring boundaries. The trend chart shows the previous seven days of observed PSI plus the selected-model forecast; the thicker line is the average across the five regions.

## Generated files

| File | Description |
|---|---|
| `data/processed/psi_daily.csv` | Daily island-wide summaries and PSI maxima for each of the five regions |
| `data/processed/weather_daily.csv` | Daily Singapore weather observations |
| `data/processed/hotspots_daily.csv` | Daily fire counts by source region |
| `data/processed/hotspots_points.csv` | Individual hotspot detections used in maps; ignored by Git because it can be large |
| `data/processed/model_table.csv` | Merged daily feature and target table |
| `data/processed/regional_psi_forecast.csv` | Selected-model and alternative next-day predictions by region |
| `figures/regional_psi_forecast_map.png` | Selected-model regional PSI forecast map |
| `figures/regional_psi_forecast_trend.png` | Seven-day regional PSI history and forecast chart |
| `figures/glm_residual_diagnostics.png` | Five-fold out-of-fold residual diagnostics for the Gaussian GLM |

Raw downloads under `data/raw/` are cached locally and excluded from Git.

## Repository layout

```text
src/           Numbered download, dataset-building scripts, and config.py
notebooks/     Exploratory analysis, model evaluation, and forecasts
requirements.txt
data/          Raw caches and generated processed data
figures/       Generated plots
```
