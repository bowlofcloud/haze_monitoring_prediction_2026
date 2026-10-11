from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from config import PROCESSED
from live_forecast import generate_forecast, refresh_recent_data

st.set_page_config(page_title="Singapore PSI outlook", page_icon="🌫️", layout="wide")


@st.cache_data(ttl=timedelta(hours=6), show_spinner="Refreshing recent API data and recalculating the forecast…")
def load_dashboard():
    saved_forecast_path = PROCESSED / "regional_psi_forecast.csv"
    if saved_forecast_path.exists():
        saved_forecast = pd.read_csv(saved_forecast_path)
        winners = saved_forecast.get("selected_model", pd.Series(dtype=str)).dropna()
        if winners.empty:
            raise ValueError("The saved forecast has no Part 5 selected_model. Run notebook part 5 and 6 first.")
        selected_model = winners.mode().iloc[0]
    else:
        raise FileNotFoundError("Saved Part 5 selection is missing. Run notebook parts 5 and 6 before launching the dashboard.")
    metadata = refresh_recent_data()
    table = pd.read_csv(PROCESSED / "model_table.csv", parse_dates=["date"])
    psi = pd.read_csv(PROCESSED / "psi_daily.csv", parse_dates=["date"])
    weather = pd.read_csv(PROCESSED / "weather_daily.csv", parse_dates=["date"])
    hotspots = pd.read_csv(PROCESSED / "hotspots_daily.csv", parse_dates=["date"])
    forecast, winner, rankings, input_date = generate_forecast(table, selected_model=selected_model)
    forecast.to_csv(PROCESSED / "regional_psi_forecast.csv", index=False)
    meta_path = PROCESSED / "live_refresh.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    return table, psi, weather, hotspots, forecast, winner, rankings, input_date, metadata


@st.fragment(run_every=timedelta(hours=6))
def render_dashboard():
    st.title("Singapore regional PSI outlook")
    st.caption("Live observations and a three-day, region-level forecast")
    if st.button("Refresh data now", type="secondary"):
        load_dashboard.clear()

    try:
        with st.spinner("Loading live data and fitting the forecast model…"):
            table, psi_daily, weather_daily, hotspots_daily, forecast, best_model, model_ranking, input_date, metadata = load_dashboard()
    except Exception as exc:
        st.error(f"Could not refresh the APIs or calculate a new forecast: {exc}")
        meta_path = PROCESSED / "live_refresh.json"
        if not (PROCESSED / "model_table.csv").exists():
            st.stop()
        st.warning("Showing the saved data, which may be out of date. Check API keys and network access, then refresh.")
        metadata = json.loads(meta_path.read_text()) if meta_path.exists() else {"refreshed_at": "Not available"}
        table = pd.read_csv(PROCESSED / "model_table.csv", parse_dates=["date"])
        psi_daily = pd.read_csv(PROCESSED / "psi_daily.csv", parse_dates=["date"])
        weather_daily = pd.read_csv(PROCESSED / "weather_daily.csv", parse_dates=["date"])
        hotspots_daily = pd.read_csv(PROCESSED / "hotspots_daily.csv", parse_dates=["date"])
        forecast = pd.read_csv(PROCESSED / "regional_psi_forecast.csv")
        best_model = str(forecast.selected_model.iloc[0])
        model_ranking = pd.Series(dtype=float)
        input_date = pd.to_datetime(table.date.max())

    try:
        refresh_time = pd.Timestamp(metadata["refreshed_at"]).tz_convert("Asia/Singapore")
    except (KeyError, TypeError, ValueError):
        refresh_time = pd.Timestamp("1970-01-01", tz="Asia/Singapore")
    st.caption(f"Last successful refresh: {refresh_time.strftime('%d %b %Y, %H:%M SGT')}")

    latest_live = psi_daily.sort_values("date").dropna(subset=["psi_max"]).iloc[-1]
    latest_weather = weather_daily.sort_values("date").dropna(subset=["wind_speed_max"]).iloc[-1]
    latest_hotspots = hotspots_daily.sort_values("date").iloc[-1]
    live_cols = st.columns(5)
    live_cols[0].metric("Latest daily PSI maximum", f"{latest_live.psi_max:.0f}")
    live_cols[1].metric("Latest PSI date", latest_live.date.strftime("%d %b %Y"))
    live_cols[2].metric("Wind speed (daily max)", f"{latest_weather.wind_speed_max:.1f} km/h")
    live_cols[3].metric("Rainfall", f"{latest_weather.rain_mm:.1f} mm")
    hotspot_total = sum(float(latest_hotspots.get(name, 0) or 0) for name in ["hotspots_sumatra", "hotspots_borneo", "hotspots_peninsula"])
    live_cols[4].metric("FIRMS hotspots", f"{hotspot_total:.0f}")
    st.caption(f"Latest weather date: {latest_weather.date:%d %b %Y} · Latest hotspot date: {latest_hotspots.date:%d %b %Y} · Forecast input through: {input_date:%d %b %Y}")
    if not metadata.get("firms_configured"):
        st.info("NASA FIRMS fire data is not refreshing because FIRMS_MAP_KEY is not set. PSI and weather refresh independently.")

    forecast["forecast_date"] = pd.to_datetime(forecast.forecast_date)
    date_choices = forecast.loc[forecast.horizon_days.between(1, 3), "forecast_date"].drop_duplicates().sort_values().tolist()
    date_to_horizon = dict(zip(date_choices, range(1, len(date_choices) + 1)))
    selected_date = st.selectbox(
        "Select prediction date", date_choices,
        format_func=lambda value: f"{value:%A, %d %B %Y}  (t+{date_to_horizon[value]})",
    )
    selected_horizon = date_to_horizon[selected_date]
    day_forecast = forecast.loc[forecast.forecast_date == selected_date].copy()
    day_forecast["severity"] = pd.cut(
        day_forecast.predicted_psi, [-1, 50, 100, 200, 300, float("inf")],
        labels=["Good", "Moderate", "Unhealthy", "Very Unhealthy", "Hazardous"],
    )
    st.subheader(f"Predicted regional PSI — {selected_date:%A, %d %B %Y}")

    locations = {
        "North": (103.78, 1.43), "South": (103.83, 1.25),
        "East": (103.96, 1.35), "West": (103.65, 1.33),
        "Central": (103.82, 1.35),
    }
    color_scale = [[0, "#2d8a57"], [0.167, "#e2bd35"], [0.334, "#e78332"],
                   [0.667, "#c84642"], [1, "#7d3c98"]]
    geo = go.Figure(go.Scattergeo(
        lon=[locations[name][0] for name in day_forecast.region],
        lat=[locations[name][1] for name in day_forecast.region],
        text=[f"{row.region} · {row.predicted_psi:.0f} PSI" for row in day_forecast.itertuples()],
        customdata=day_forecast[["predicted_psi", "severity", "confidence_95_lower", "confidence_95_upper"]],
        mode="markers+text", textposition="top center", textfont={"size": 13, "color": "#202020"},
        marker={"size": 36, "color": day_forecast.predicted_psi, "colorscale": color_scale,
                "cmin": 0, "cmax": 300, "colorbar": {"title": "24-hour PSI"},
                "line": {"color": "white", "width": 1.5}},
        hovertemplate=("%{text}<br>Predicted PSI: %{customdata[0]:.1f}<br>"
                       "Category: %{customdata[1]}<br>95% range: %{customdata[2]:.1f}–%{customdata[3]:.1f}<extra></extra>"),
    ))
    geo.update_layout(
        height=500, margin={"l": 0, "r": 0, "t": 15, "b": 0},
        geo={"scope": "asia", "projection_type": "mercator", "showland": True,
             "landcolor": "#f0eee6", "showocean": True, "oceancolor": "#eaf2f5",
             "showcoastlines": True, "coastlinecolor": "#77766f",
             "lonaxis_range": [103.55, 104.08], "lataxis_range": [1.18, 1.5]},
    )
    map_column, advisory_column = st.columns([2.6, 1.35], gap="large", vertical_alignment="top")
    with map_column:
        st.plotly_chart(geo, width="stretch")
    with advisory_column:
        st.markdown("#### Health advisory")
        st.caption("MOH guidance for healthy persons")
        guidance = {
            "Good": "Normal activities.",
            "Moderate": "Normal activities.",
            "Unhealthy": "Reduce prolonged or strenuous outdoor exertion.",
            "Very Unhealthy": "Avoid prolonged or strenuous outdoor exertion.",
            "Hazardous": "Minimise outdoor activity.",
        }
        for row in day_forecast.itertuples():
            st.markdown(f"**{row.region} · {row.predicted_psi:.0f} PSI · {row.severity}**")
            st.caption(guidance[str(row.severity)])
        st.caption("Older adults, children, pregnant women, and people with chronic heart or lung conditions may need stricter precautions.")
        st.markdown("[Full Singapore MOH haze advisory](https://www.moh.gov.sg/others/haze/)")
    st.caption("Regional markers show approximate zone centres; the five monitoring regions are not official geographic boundaries.")

    st.subheader("PSI trend: previous 7 days and next 3 days")
    region_names = ["North", "South", "East", "West", "Central"]
    region_cols = {name: f"psi_{name.lower()}" for name in region_names}
    history = table.sort_values("date").dropna(subset=list(region_cols.values())).tail(7)
    chart = go.Figure()
    palette = dict(zip(region_names, ["#4285f4", "#db4437", "#f4b400", "#0f9d58", "#ab47bc"]))
    for region in region_names:
        chart.add_trace(go.Scatter(x=history.date, y=history[region_cols[region]], name=region,
                                   mode="lines+markers", line={"color": palette[region], "width": 1.2},
                                   opacity=0.42, legendgroup=region))
        regional = forecast.loc[forecast.region == region].sort_values("horizon_days")
        chart.add_trace(go.Scatter(x=regional.forecast_date, y=regional.predicted_psi,
                                   mode="lines+markers", name=f"{region} forecast",
                                   line={"color": palette[region], "width": 1.3, "dash": "dash"},
                                   opacity=0.65, legendgroup=region, showlegend=False))

    historic_avg = history[list(region_cols.values())].mean(axis=1)
    by_horizon = forecast.groupby("horizon_days", as_index=False).agg(
        predicted=("predicted_psi", "mean"), lower=("confidence_95_lower", "mean"),
        upper=("confidence_95_upper", "mean"), forecast_date=("forecast_date", "first"),
    )
    chart.add_trace(go.Scatter(x=by_horizon.forecast_date, y=by_horizon.upper, mode="lines",
                               line={"width": 0}, hoverinfo="skip", showlegend=False, name="95% upper"))
    chart.add_trace(go.Scatter(x=by_horizon.forecast_date, y=by_horizon.lower, mode="lines",
                               line={"width": 0}, fill="tonexty", fillcolor="rgba(32,32,32,0.16)",
                               name="Mean of regional 95% bounds"))
    chart.add_trace(go.Scatter(x=history.date, y=historic_avg, mode="lines+markers",
                               name="Singapore average (observed)", line={"color": "#202020", "width": 3.5}))
    chart.add_trace(go.Scatter(x=by_horizon.forecast_date, y=by_horizon.predicted, mode="lines+markers",
                               name="Singapore average (forecast)", line={"color": "#202020", "width": 3.5, "dash": "dash"}))
    chart.add_vline(x=selected_date, line_dash="dot", line_color="#777777")
    chart.update_layout(height=430, xaxis_title="Date", yaxis_title="24-hour PSI", hovermode="x unified",
                        legend={"orientation": "h", "y": -0.25}, margin={"t": 15, "b": 100})
    chart.update_yaxes(rangemode="tozero", gridcolor="#e6e6e6")
    st.plotly_chart(chart, width="stretch")
    st.caption("The shaded band shows the mean of the five regional 95% lower and upper bounds; it is a visual summary, not a separately calibrated interval for the island-wide average.")

    st.subheader("Forecast confidence and method")
    st.write(f"**Selected Part 5 model:** {best_model} (lowest mean five-fold chronological RMSE across all five regions and three horizons).")
    selected_summary = day_forecast[["region", "predicted_psi", "confidence_95_lower", "confidence_95_upper", "walkforward_rmse_psi", "confidence_score_pct", "severity"]].rename(columns={
        "region": "Region", "predicted_psi": "Predicted PSI", "confidence_95_lower": "95% lower",
        "confidence_95_upper": "95% upper", "walkforward_rmse_psi": "Historical RMSE (PSI)",
        "confidence_score_pct": "Within 10 PSI in validation (%)", "severity": "Category",
    })
    st.dataframe(selected_summary, hide_index=True, width="stretch")
    with st.expander("Model parameters and input features"):
        st.markdown(
            f"""- Forecast lead: **t+{selected_horizon}**, for **{selected_date:%d %b %Y}**.
- Input window: daily data from **{(input_date - timedelta(days=6)):%d %b %Y}** through **{input_date:%d %b %Y}**.
- Predictors (each supplied for seven daily lags): five regional PSI values; eastward and northward wind-direction components; maximum wind speed; Sumatra, Borneo and Peninsular Malaysia hotspot counts; rainfall; and mean humidity.
        - Model choice: **{best_model}**, carried forward from Part 5's saved forecast selection. Re-run notebook parts 5 and 6 to compare and choose again after changing data or model settings.
        - Validation: five chronological folds and a horizon-sized purge gap are used to estimate this model's errors for the prediction ranges.
- 95% range: 2.5th and 97.5th percentiles of held-out walk-forward residuals for the selected region and lead.
- Historical RMSE and the within-10-PSI percentage describe validation performance; they are not a probability guarantee for this individual prediction."""
        )
        if not model_ranking.empty:
            st.write("Mean cross-validated RMSE by model (PSI points):")
            st.dataframe(model_ranking.rename("Mean RMSE").to_frame().reset_index(names="Model"), hide_index=True, width="stretch")

    st.warning("Disclaimer: PSI forecasts are estimates for planning and exploration. They are by no means 100% accurate and are not official NEA advisories.")
    st.caption("Data are retained from 1 January 2019 onward to support chronological model validation. Recent observations are updated at launch and every six hours while the app is running.")


render_dashboard()
