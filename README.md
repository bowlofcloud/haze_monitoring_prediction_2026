# Singapore Regional PSI and Haze Monitoring

This project combines Singapore air-quality observations, weather reanalysis, and satellite fire-hotspot data to explore haze patterns and forecast 24-hour PSI for the next three days in Singapore's North, South, East, West, and Central regions.

The workflow downloads and prepares daily data, builds lagged predictors, compares a basic and a nonlinear regional forecasting model, and produces a three-day forecast table with prediction intervals and visualizations. The analysis is exploratory: the forecasts are not official NEA advisories.

## What the analysis does

The notebook explores:

- Daily PSI history and the timing of unhealthy episodes.
- The relationship between recent Sumatra/Borneo hotspot counts and next-day PSI.
- Dry-season PSI and unhealthy-day rates by wind direction and wind-speed quartile.
- Fire detections near the worst observed haze day, including a map with Natural Earth country boundaries.
- Regional PSI forecasts for t+1 through t+3 using the seven daily observations from t-6 through t.
- Horizon-specific walk-forward RMSE, confidence scores (historical share of predictions within 10 PSI), and 80%/95% prediction intervals.

Parts 5 and 6 refresh the API-backed daily tables before modeling, then use the seven daily observations from t-6 through t to predict PSI at t+1, t+2, and t+3. Part 5 compares a regularized linear Gaussian GLM (5a) with a nonlinear extension (5b) using identical five-fold chronological validation for all five regions and all three horizons, with a purge gap equal to the horizon. Both models tune ridge regularization inside each training fold. Part 5b adds log and squared terms and same-day interactions among PSI, wind, hotspots, and rain. Predictors include regional PSI, wind direction components and speed, hotspot counts by source region, rainfall, and humidity. Part 3 also compares dry-season PSI and unhealthy-day rates across wind direction and daily maximum wind-speed quartiles.

## Data sources

| Source | Data used | Access |
|---|---|---|
| [data.gov.sg](https://data.gov.sg) / NEA | Hourly regional 24-hour PSI and PM2.5 | Free API; API key is optional but speeds up downloads |
| [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) | Daily Singapore weather, including wind, rain, temperature, and humidity | Free; no key required |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) | VIIRS S-NPP satellite fire detections around Sumatra, Peninsular Malaysia, and Borneo | Free MAP_KEY required for API downloads |
| [Natural Earth](https://www.naturalearthdata.com/) and [OpenStreetMap Nominatim](https://nominatim.org/) | Country boundaries and Singapore outline used in notebook maps | Public datasets/services; internet required for map cells |

The study period begins on 1 January 2019 and, by default, continues through the latest date available to each source. PSI and weather availability may differ at the most recent dates.

## Installation and API keys

Use Python 3.10 or newer, then install the project, notebook, and dashboard dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install geopandas
```

The notebook kernel and Streamlit app must use the same Python environment where these packages are installed. `geopandas` is used for notebook map visualizations.

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

## Run the live dashboard

From the project root, install requirements and start the local app:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The dashboard refreshes recent PSI and weather data on launch and every six hours while open. NASA FIRMS hotspot updates require `FIRMS_MAP_KEY` in `.env`; PSI and weather refresh without that key. Each refresh merges newer observations into the historical daily tables and keeps data from 1 January 2019 onward for the model comparison. Raw PSI downloads are limited to the recent refresh window, and the point-level FIRMS map cache is limited to 180 days; daily history remains available for training. Because you chose to preserve the full 2019 onward model history, its daily row count grows by about one row per day rather than staying fixed. The app uses the Part 5 winner recorded in the saved forecast and recalibrates that model's three-day forecast with current history. To select a different winner after changing data or model settings, rerun notebook parts 5 and 6. Press **Refresh data now** to bypass the six-hour cache.

### Publish on Streamlit Community Cloud

Community Cloud deploys from a GitHub repository. Push the app files to the branch you want to deploy, then create an app at [share.streamlit.io](https://share.streamlit.io) with `app.py` as the entrypoint. In **Advanced settings → Secrets**, add any API keys the app should use, for example:

```toml
FIRMS_MAP_KEY = "your_nasa_firms_map_key"
DATA_GOV_SG_API_KEY = "your_data_gov_sg_api_key"
```

Do not commit `.env` or `secrets.toml`; Community Cloud reads secrets from the app settings. Choose the app's sharing visibility in Community Cloud settings. After deployment, its `streamlit.app` URL can be shared. The app refreshes its data in the cloud when it runs; Community Cloud's local filesystem is ephemeral, so refreshed files are not a permanent archive.

Weather for the latest days comes from Open-Meteo's forecast API because its historical archive is published with a delay. Check the displayed input date to see the last complete seven-day feature window used for a particular forecast. The displayed confidence score and 95% range are based on historical walk-forward errors and do not guarantee an individual forecast.

## Forecast models

Part 5 compares two models independently for each Singapore region:

| Part | Model | Approach |
|---|---|---|
| 5a | Gaussian GLM | Regularized linear baseline with an identity link and out-of-fold residual diagnostics |
| 5b | Nonlinear Gaussian GLM | Adds `log1p` transforms, squared terms, and same-day PSI-weather-fire interactions; includes out-of-fold residual diagnostics |

Part 5 compares 5a and 5b using five chronological `TimeSeriesSplit` folds for each region and horizon, with a purge gap matching the forecast horizon. It selects the model with the lowest mean RMSE across the 15 region/horizon combinations. Both models tune ridge alpha inside the training data without using the outer test fold; Part 6 repeats tuning within each calibration fold and for the final fit. Part 6 uses the Part 5 winner by region and horizon with the same seven-day input window; it reports horizon-specific walk-forward RMSE, 80%/95% prediction intervals, and a within-10-PSI confidence score from held-out residuals. These are historical validation estimates, not guarantees of future performance. PSI severity episodes are rare, and high readings may still be underpredicted.

Model scores and the selected model are recalculated from refreshed data whenever the notebook Parts 5 and 6 are rerun. The nonlinear extension may improve accuracy but is selected only when its chronological validation RMSE is lower.

The Singapore map colors regions and labels them with the selected model's t+1 PSI prediction and a severity category. Its five-zone polygons are approximate Voronoi partitions around representative locations, not official PSI monitoring boundaries. The trend chart shows the previous seven days of observed PSI and the next three forecast days; the thicker line is the average across the five regions. The confidence score is the historical share of walk-forward predictions within 10 PSI, while the prediction intervals are empirical ranges; neither guarantees the accuracy of an individual forecast.

## Generated files

| File | Description |
|---|---|
| `data/processed/psi_daily.csv` | Daily island-wide summaries and PSI maxima for each of the five regions |
| `data/processed/weather_daily.csv` | Daily Singapore weather observations |
| `data/processed/hotspots_daily.csv` | Daily fire counts by source region |
| `data/processed/hotspots_points.csv` | Individual hotspot detections used in maps; ignored by Git because it can be large |
| `data/processed/model_table.csv` | Merged daily feature and target table |
| `data/processed/regional_psi_forecast.csv` | Part 5 selected-model predictions for three forecast horizons by region, with 80% and 95% prediction intervals |
| `figures/regional_psi_forecast_map.png` | Selected-model regional PSI forecast map |
| `figures/regional_psi_forecast_trend.png` | Seven-day regional PSI history and forecast chart |
| `figures/glm_residual_diagnostics.png` | Five-fold out-of-fold residual diagnostics for the Gaussian GLM, with horizons distinguished |
| `figures/nonlinear_glm_residual_diagnostics.png` | Five-fold out-of-fold residual diagnostics for the nonlinear Gaussian GLM |
| `figures/psi_by_wind_and_speed.png` | Dry-season PSI by wind direction and daily maximum wind-speed quartile |

Raw downloads under `data/raw/` are cached locally and excluded from Git.

## Repository layout

```text
src/           Numbered download, dataset-building scripts, and config.py
notebooks/     Exploratory analysis, model evaluation, and forecasts
requirements.txt
data/          Raw caches and generated processed data
figures/       Generated plots
```
