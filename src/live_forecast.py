"""Recent API refresh and Part 5 model selection for the Streamlit dashboard."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from sklearn.impute import SimpleImputer
from sklearn.linear_model import TweedieRegressor
from sklearn.metrics import mean_squared_error
from sklearn.model_selection import TimeSeriesSplit
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from pygam import LinearGAM, s

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from config import PROCESSED, RAW, SG_LAT, SG_LON, START_DATE  # noqa: E402

load_dotenv(ROOT / ".env")


def _load_streamlit_secrets():
    """Expose Community Cloud secrets as environment variables used by the downloaders."""
    try:
        import streamlit as st
        if not st.runtime.exists():
            return
        for name in ("FIRMS_MAP_KEY", "DATA_GOV_SG_API_KEY"):
            if name not in os.environ and name in st.secrets:
                os.environ[name] = str(st.secrets[name])
    except Exception:
        # Streamlit secrets are optional locally; .env remains the local source.
        return


_load_streamlit_secrets()
REGIONS = ["north", "south", "east", "west", "central"]
PREDICTORS = [f"psi_{r}" for r in REGIONS] + ["wind_from_east", "wind_from_north", "wind_speed_max", "hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula", "rain_mm", "humidity_mean"]
LOG_PREDICTORS = {f"psi_{r}" for r in REGIONS} | {"wind_speed_max", "hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula", "rain_mm", "humidity_mean"}
MODEL_LABELS = ["5a GLM", "5b Nonlinear GLM"]
LEGACY_MODEL_LABELS = ["5b Quadratic", "5c Log GLM", "5d GAM"]
GLM_ALPHA_GRID = (0.1, 1.0, 10.0)
NONLINEAR_ALPHA_GRID = (0.1, 1.0, 10.0, 100.0)


def _load_script(filename, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _merge_csv(path, incoming, key="date"):
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    merged = pd.concat([old, incoming], ignore_index=True)
    merged["date"] = pd.to_datetime(merged["date"]).dt.strftime("%Y-%m-%d")
    merged = merged.drop_duplicates(subset=key, keep="last").sort_values("date")
    merged = merged[merged["date"] >= START_DATE]
    merged.to_csv(path, index=False)
    return merged


def _merge_recent_points(path, incoming, cutoff):
    """Keep a bounded point-level FIRMS map cache; daily counts retain full history."""
    incoming = incoming.copy()
    incoming["date"] = pd.to_datetime(incoming.date).dt.strftime("%Y-%m-%d")
    incoming = incoming[incoming.date >= cutoff]
    temp_path = path.with_suffix(".tmp")
    wrote = False
    if path.exists():
        for chunk in pd.read_csv(path, chunksize=200_000):
            chunk["date"] = pd.to_datetime(chunk.date).dt.strftime("%Y-%m-%d")
            chunk = chunk[chunk.date >= cutoff]
            if not chunk.empty:
                chunk.to_csv(temp_path, index=False, mode="w" if not wrote else "a", header=not wrote)
                wrote = True
    if not incoming.empty:
        incoming.to_csv(temp_path, index=False, mode="w" if not wrote else "a", header=not wrote)
        wrote = True
    if wrote:
        combined = pd.read_csv(temp_path)
        combined = combined.drop_duplicates(subset=["date", "latitude", "longitude", "frp"], keep="last")
        combined.to_csv(temp_path, index=False)
        temp_path.replace(path)
    else:
        pd.DataFrame(columns=incoming.columns).to_csv(temp_path, index=False)
        temp_path.replace(path)


def refresh_recent_data():
    """Update recent PSI, weather and hotspot observations; retain 2019 onward."""
    started = datetime.now().astimezone()
    psi = _load_script("1_get_psi.py", "psi_downloader")
    today = date.today()
    psi_rows = []
    for back in range(10, -1, -1):
        day = (today - timedelta(days=back)).isoformat()
        payload = psi.fetch_day(day)
        (psi.CACHE / f"{day}.json").write_text(json.dumps(payload))
        psi_rows.append(psi.summarise_day(day, payload))
        time.sleep(0.15)
    psi_updates = pd.DataFrame(psi_rows).dropna(subset=["psi_max"])
    if not psi_updates.empty:
        _merge_csv(PROCESSED / "psi_daily.csv", psi_updates)

    # Forecast endpoint has recent observed/nowcast weather; ERA5 archive lags by days.
    response = requests.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": SG_LAT, "longitude": SG_LON,
        "daily": "precipitation_sum,wind_speed_10m_max,wind_direction_10m_dominant,temperature_2m_max,relative_humidity_2m_mean",
        "past_days": 7, "forecast_days": 1, "timezone": "Asia/Singapore",
    }, timeout=60)
    response.raise_for_status()
    weather = pd.DataFrame(response.json()["daily"]).rename(columns={
        "time": "date", "precipitation_sum": "rain_mm", "wind_speed_10m_max": "wind_speed_max",
        "wind_direction_10m_dominant": "wind_dir", "temperature_2m_max": "temp_max",
        "relative_humidity_2m_mean": "humidity_mean",
    })
    _merge_csv(PROCESSED / "weather_daily.csv", weather)

    firms_key = os.getenv("FIRMS_MAP_KEY")
    if firms_key:
        hs = _load_script("3_get_hotspots.py", "hotspot_downloader")
        recent_start = (today - timedelta(days=4)).isoformat()
        (hs.CACHE / f"VIIRS_SNPP_NRT_{recent_start}.csv").unlink(missing_ok=True)
        points = hs.fetch_chunk(firms_key, "VIIRS_SNPP_NRT", recent_start)
        if not points.empty:
            points = points.drop_duplicates(subset=["latitude", "longitude", "acq_date", "acq_time"])
            if "confidence" in points and points["confidence"].dtype == object:
                points = points[points.confidence.str.lower() != "l"]
            points["region"] = [hs.classify_region(la, lo) for la, lo in zip(points.latitude, points.longitude)]
            points["date"] = pd.to_datetime(points.acq_date).dt.strftime("%Y-%m-%d")
            daily = points.pivot_table(index="date", columns="region", values="latitude", aggfunc="count", fill_value=0).add_prefix("hotspots_").reset_index()
        else:
            points = pd.DataFrame(columns=["date", "latitude", "longitude", "frp", "region"])
            daily = pd.DataFrame(columns=["date", "hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula"])
        for col in ["hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula"]:
            if col not in daily:
                daily[col] = 0
        recent_dates = pd.date_range(recent_start, today, freq="D").strftime("%Y-%m-%d")
        daily = pd.DataFrame({"date": recent_dates}).merge(daily, on="date", how="left").fillna(0)
        _merge_csv(PROCESSED / "hotspots_daily.csv", daily[["date", "hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula"]])
        _merge_recent_points(PROCESSED / "hotspots_points.csv",
                             points[["date", "latitude", "longitude", "frp", "region"]],
                             (today - timedelta(days=179)).isoformat())

    _load_script("4_build_dataset.py", "dataset_builder").main()
    # Remove any stale processed rows before 2019 if imported from older caches.
    for filename in ["psi_daily.csv", "weather_daily.csv", "hotspots_daily.csv", "model_table.csv"]:
        path = PROCESSED / filename
        frame = pd.read_csv(path)
        frame["date"] = pd.to_datetime(frame.date).dt.strftime("%Y-%m-%d")
        frame[frame.date >= START_DATE].to_csv(path, index=False)
    points_path = PROCESSED / "hotspots_points.csv"
    if points_path.exists() and not firms_key:
        _merge_recent_points(points_path,
                             pd.DataFrame(columns=["date", "latitude", "longitude", "frp", "region"]),
                             (today - timedelta(days=179)).isoformat())
    cache_cutoff = today - timedelta(days=10)
    for folder in [RAW / "psi", RAW / "firms"]:
        if folder.exists():
            for item in folder.iterdir():
                stamp = item.stem.rsplit("_", 1)[-1]
                if item.is_file() and len(stamp) == 10:
                    if stamp < START_DATE or (folder.name == "psi" and stamp < cache_cutoff.isoformat()):
                        item.unlink(missing_ok=True)
    # The processed daily weather table is sufficient for training; discard the
    # one-shot full-range API response cache so it cannot grow stale or duplicate it.
    (RAW / "weather_openmeteo.json").unlink(missing_ok=True)
    return {"refreshed_at": datetime.now().astimezone().isoformat(),
            "psi_latest_date": psi_rows[-1]["date"], "firms_configured": bool(firms_key),
            "started_at": started.isoformat()}


def _features(frame):
    source = frame.sort_values("date").reset_index(drop=True).copy()
    names, log_names = [], []
    for lag in range(6, -1, -1):
        for predictor in PREDICTORS:
            feature = f"{predictor}_lag{lag}"
            source[feature] = source[predictor].shift(lag)
            names.append(feature)
            if predictor in LOG_PREDICTORS:
                log_names.append(feature)
    return source, names, log_names


def _transform(x, label, log_names):
    result = x.copy()
    if label in ("5c Log GLM", "5b Nonlinear GLM"):
        result[log_names] = np.log1p(result[log_names].clip(lower=0))
    return result


def _expand_nonlinear_terms(values, feature_names):
    """Add quadratic terms and same-day PSI/weather/fire interactions."""
    values = np.asarray(values, dtype=float)
    terms = [values, values ** 2]
    index = {name: i for i, name in enumerate(feature_names)}
    interactions = []
    for lag in range(6, -1, -1):
        psi_indices = [index[f"psi_{region}_lag{lag}"] for region in REGIONS]
        mean_psi = values[:, psi_indices].mean(axis=1)
        wind = values[:, index[f"wind_speed_max_lag{lag}"]]
        rain = values[:, index[f"rain_mm_lag{lag}"]]
        hotspots = values[:, [index[f"hotspots_{source}_lag{lag}"]
                              for source in ("sumatra", "borneo", "peninsula")]].sum(axis=1)
        interactions.extend([mean_psi * wind, mean_psi * hotspots,
                             wind * hotspots, mean_psi * rain])
    terms.extend(interactions)
    return np.column_stack(terms)


def _model(label, alpha=0.0, feature_names=None):
    if label == "5d GAM":
        return None
    steps = [SimpleImputer(strategy="median"), StandardScaler()]
    if label == "5b Nonlinear GLM":
        steps.extend([
            FunctionTransformer(_expand_nonlinear_terms,
                                kw_args={"feature_names": feature_names}, validate=False),
            StandardScaler(),
        ])
    if label == "5b Quadratic":
        steps.extend([FunctionTransformer(lambda values: np.column_stack((values, values ** 2)), validate=False), StandardScaler()])
    steps.append(TweedieRegressor(power=0, link="identity", alpha=alpha, max_iter=10000 if label == "5b Quadratic" else 2000, tol=1e-7))
    return make_pipeline(*steps)


def _fit(label, x, y, alpha=0.0):
    transformed = _transform(x, label, _fit.log_names)
    if label == "5d GAM":
        imputer = SimpleImputer(strategy="median")
        x_values = imputer.fit_transform(transformed)
        terms = s(0, n_splines=6)
        for index in range(1, x_values.shape[1]):
            terms += s(index, n_splines=6)
        return imputer, LinearGAM(terms, lam=0.6, max_iter=100).fit(x_values, y)
    return _model(label, alpha=alpha, feature_names=_fit.feature_names).fit(transformed, y)


def _predict(label, fitted, x):
    transformed = _transform(x, label, _fit.log_names)
    if label == "5d GAM":
        imputer, model = fitted
        return model.predict(imputer.transform(transformed))
    return fitted.predict(transformed)


def _select_glm_alpha(x, y, horizon):
    """Choose ridge strength using chronological folds inside the training window."""
    splitter = TimeSeriesSplit(n_splits=2, gap=horizon)
    scores = []
    for alpha in GLM_ALPHA_GRID:
        fold_errors = []
        for train_i, valid_i in splitter.split(x):
            model = _model("5a GLM", alpha=alpha).fit(x.iloc[train_i], y.iloc[train_i])
            prediction = model.predict(x.iloc[valid_i])
            fold_errors.extend(y.iloc[valid_i].to_numpy() - prediction)
        scores.append((float(np.sqrt(np.mean(np.square(fold_errors)))), alpha))
    return min(scores)[1]


def _select_nonlinear_alpha(x, y, horizon):
    """Tune nonlinear-model ridge strength using inner chronological folds."""
    splitter = TimeSeriesSplit(n_splits=2, gap=horizon)
    scores = []
    for alpha in NONLINEAR_ALPHA_GRID:
        fold_errors = []
        for train_i, valid_i in splitter.split(x):
            model = _fit("5b Nonlinear GLM", x.iloc[train_i], y.iloc[train_i], alpha=alpha)
            prediction = _predict("5b Nonlinear GLM", model, x.iloc[valid_i])
            fold_errors.extend(y.iloc[valid_i].to_numpy() - prediction)
        scores.append((float(np.sqrt(np.mean(np.square(fold_errors)))), alpha))
    return min(scores)[1]


def generate_forecast(model_table, selected_model=None):
    """Use the saved Part 5 winner and calibrate its live forecast from walk-forward residuals."""
    source, features, log_names = _features(model_table)
    _fit.log_names = log_names
    _fit.feature_names = features
    sample_sets, scores = {}, []
    for horizon in (1, 2, 3):
        for region in REGIONS:
            target = f"psi_{region}"
            samples = source[["date", *features]].copy()
            samples["target_date"] = samples.date + pd.Timedelta(days=horizon)
            target_history = source[["date", target]].rename(columns={"date": "target_date"})
            samples = samples.merge(target_history, on="target_date", how="left").dropna(subset=[*features, target]).reset_index(drop=True)
            splits = list(TimeSeriesSplit(n_splits=5, gap=horizon).split(samples))
            sample_sets[(region, horizon)] = (samples, splits)
            for label in (MODEL_LABELS if selected_model is None else []):
                actual, predicted = [], []
                for train_i, test_i in splits:
                    train, test = samples.iloc[train_i], samples.iloc[test_i]
                    if label == "5a GLM":
                        alpha = _select_glm_alpha(train[features], train[target], horizon)
                    elif label == "5b Nonlinear GLM":
                        alpha = _select_nonlinear_alpha(train[features], train[target], horizon)
                    else:
                        alpha = 0.0
                    model = _fit(label, train[features], train[target], alpha=alpha)
                    predicted.extend(_predict(label, model, test[features]))
                    actual.extend(test[target].to_numpy())
                scores.append({"model": label, "region": region, "horizon": horizon,
                               "rmse": mean_squared_error(actual, predicted) ** 0.5})
    if selected_model is None:
        metrics = pd.DataFrame(scores)
        mean_rmse = metrics.groupby("model").rmse.mean().sort_values()
        selected = mean_rmse.index[0]
    else:
        if selected_model not in MODEL_LABELS + LEGACY_MODEL_LABELS:
            raise ValueError(f"Unknown Part 5 model in saved forecast: {selected_model}")
        selected = selected_model
        mean_rmse = pd.Series(dtype=float)
    latest = source.dropna(subset=features).iloc[-1]
    anchor = pd.Timestamp(latest.date)
    rows = []
    for horizon in (1, 2, 3):
        for region in REGIONS:
            samples, splits = sample_sets[(region, horizon)]
            target = f"psi_{region}"
            residuals = []
            for train_i, test_i in splits:
                train, test = samples.iloc[train_i], samples.iloc[test_i]
                if selected == "5a GLM":
                    alpha = _select_glm_alpha(train[features], train[target], horizon)
                elif selected == "5b Nonlinear GLM":
                    alpha = _select_nonlinear_alpha(train[features], train[target], horizon)
                else:
                    alpha = 0.0
                model = _fit(selected, train[features], train[target], alpha=alpha)
                pred = _predict(selected, model, test[features])
                residuals.extend(test[target].to_numpy() - pred)
            if selected == "5a GLM":
                alpha = _select_glm_alpha(samples[features], samples[target], horizon)
            elif selected == "5b Nonlinear GLM":
                alpha = _select_nonlinear_alpha(samples[features], samples[target], horizon)
            else:
                alpha = 0.0
            model = _fit(selected, samples[features], samples[target], alpha=alpha)
            prediction = float(_predict(selected, model, source.loc[[latest.name], features])[0])
            q025, q10, q90, q975 = np.quantile(residuals, [0.025, 0.10, 0.90, 0.975])
            rows.append({"forecast_date": (anchor + pd.Timedelta(days=horizon)).date().isoformat(),
                         "horizon_days": horizon, "region": region.title(), "selected_model": selected,
                         "predicted_psi": round(max(0, prediction), 1),
                         "walkforward_rmse_psi": round(float(np.sqrt(np.mean(np.square(residuals)))), 1),
                         "confidence_score_pct": round(100 * float(np.mean(np.abs(residuals) <= 10)), 1),
                         "confidence_80_lower": round(max(0, prediction + q10), 1),
                         "confidence_80_upper": round(max(0, prediction + q90), 1),
                         "confidence_95_lower": round(max(0, prediction + q025), 1),
                         "confidence_95_upper": round(max(0, prediction + q975), 1),
                         "glm_alpha": alpha if selected in ("5a GLM", "5b Nonlinear GLM") else np.nan})
    return pd.DataFrame(rows), selected, mean_rmse, anchor
