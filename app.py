from __future__ import annotations

import base64
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
    themes = {
        "White": {"background": "#ffffff", "surface": "#f8fafc", "text": "#1f2937", "accent": "#2563eb", "border": "#dce3eb", "grid": "#e6eaf0", "decor": "☁️　✨　🌈"},
        "Beige": {"background": "#f5f0e6", "surface": "#fffaf0", "text": "#40372b", "accent": "#a76e3c", "border": "#e4d7c5", "grid": "#e6dac9", "decor": "🌼　☀️　🍃"},
        "Baby blue": {"background": "#eaf5ff", "surface": "#f7fbff", "text": "#24384a", "accent": "#4b91c4", "border": "#c9e1f3", "grid": "#d9e9f5", "decor": "☁️　🌤️　💧"},
        "Baby purple": {"background": "#f2edff", "surface": "#fbf9ff", "text": "#3d3154", "accent": "#8a6ccf", "border": "#ded4f5", "grid": "#e7def6", "decor": "🌙　✨　☁️"},
    }
    st.session_state.setdefault("page_theme", "White")
    st.session_state.setdefault("page_avatar", "Duck")
    current_theme = themes[st.session_state.page_theme]
    header, theme_col, avatar_col = st.columns([4.5, 2.1, 1.2], vertical_alignment="center")
    with header:
        st.title("Singapore regional PSI outlook")
        st.caption("Live observations and a three-day, region-level forecast")
        st.markdown(
            f"<div style='background:{current_theme['surface']};"
            f"border:1px solid {current_theme['border']};"
            f"border-radius:12px;padding:5px 12px;letter-spacing:3px;width:max-content'>"
            f"{current_theme['decor']}</div>",
            unsafe_allow_html=True,
        )
    with theme_col:
        st.caption("Colour theme")
        swatches = st.columns(4, gap="small")
        swatch_colors = {"White": "#ffffff", "Beige": "#eadcc8", "Baby blue": "#b9e1fb", "Baby purple": "#d7c5fa"}
        swatch_css = []
        for index, (theme_name, swatch_color) in enumerate(swatch_colors.items()):
            swatch_key = f"theme_pick_{theme_name.lower().replace(' ', '_')}"
            active_ring = f"0 0 0 3px {themes[theme_name]['accent']}" if st.session_state.page_theme == theme_name else "0 1px 4px #26323835"
            swatch_css.append(
                f".st-key-{swatch_key} button{{width:32px!important;height:32px!important;min-height:32px!important;"
                f"padding:0!important;border-radius:50%!important;background:{swatch_color}!important;"
                f"border:1px solid #77808b!important;box-shadow:{active_ring}!important;font-size:0!important;}}"
                f".st-key-{swatch_key} button:hover{{transform:scale(1.1);}}"
            )
            if swatches[index].button("●", key=swatch_key, help=f"{theme_name} theme"):
                st.session_state.page_theme = theme_name
                st.rerun()
        st.markdown(f"<style>{''.join(swatch_css)}</style>", unsafe_allow_html=True)
        selected_theme = st.session_state.page_theme
        theme_accent = themes[selected_theme]["accent"]
    with avatar_col:
        st.caption("Choose an avatar")
        avatar_buttons = st.columns(3, gap="small")
        avatar_css = []
        for index, animal in enumerate(["Duck", "Dog", "Cat"]):
            avatar_key = f"avatar_pick_{animal.lower()}"
            image_path = ROOT / "assets" / "avatars" / f"{animal.lower()}_good.png"
            image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
            ring = f"0 0 0 3px {theme_accent}" if st.session_state.page_avatar == animal else "0 1px 4px #26323835"
            avatar_css.append(
                f".st-key-{avatar_key} button{{width:42px!important;height:42px!important;min-height:42px!important;"
                f"padding:0!important;border-radius:12px!important;background-image:url(data:image/png;base64,{image_data})!important;"
                f"background-size:cover!important;background-position:center!important;border:1px solid #77808b!important;"
                f"box-shadow:{ring}!important;font-size:0!important;color:transparent!important;}}"
            )
            if avatar_buttons[index].button(" ", key=avatar_key, help=f"Select {animal}"):
                st.session_state.page_avatar = animal
                st.rerun()
        selected_avatar = st.session_state.page_avatar
    theme = themes[selected_theme]
    st.markdown(f"""
    <style>
      .stApp {{ background: {theme['background']}; color: {theme['text']}; }}
      [data-testid="stHeader"] {{ background: {theme['background']}; }}
      [data-testid="stMetric"] {{ background: {theme['surface']}; border: 1px solid {theme['border']}; border-radius: 12px; padding: 10px 14px; }}
      div.stButton > button {{ border-color: {theme['accent']}; color: {theme['accent']}; border-radius: 9px; }}
      div.stButton > button:hover {{ background: {theme['accent']}; color: white; }}
      {''.join(avatar_css)}
    </style>
    """, unsafe_allow_html=True)
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
    overall_category = str(pd.cut(
        [day_forecast.predicted_psi.max()], [-1, 50, 100, 200, 300, float("inf")],
        labels=["Good", "Moderate", "Unhealthy", "Very Unhealthy", "Hazardous"],
    )[0])
    avatar_actions = {
        "Good": "Out and about with a cap and backpack.",
        "Moderate": "Light jacket and stay hydrated.",
        "Unhealthy": "Mask on and hood up.",
        "Very Unhealthy": "Full protection: mask and goggles.",
        "Hazardous": "Stay indoors and rest.",
    }
    map_title, avatar_panel = st.columns([2.5, 1.2], vertical_alignment="center")
    with map_title:
        st.subheader(f"Predicted regional PSI — {selected_date:%A, %d %B %Y}")
    with avatar_panel:
        avatar_col, action_col = st.columns([1, 2.1], vertical_alignment="center")
        avatar_category_slug = overall_category.lower().replace(" ", "_")
        avatar_path = ROOT / "assets" / "avatars" / f"{selected_avatar.lower()}_{avatar_category_slug}.png"
        avatar_col.image(str(avatar_path), width=105)
        action_col.markdown(
            f"<div style='background:{theme['surface']};border:1px solid {theme['border']};"
            f"border-radius:14px;padding:10px 12px;color:{theme['text']};'>"
            f"<b>{overall_category}</b><br><span style='font-size:13px'>{avatar_actions[overall_category]}</span></div>",
            unsafe_allow_html=True,
        )

    # Plotly's MapLibre renderer uses public OpenStreetMap tiles directly, so
    # no extra Folium package is needed in local or hosted environments.
    map_figure = go.Figure()
    card_positions = {
        "North": (1.435, 103.815), "West": (1.345, 103.665),
        "Central": (1.345, 103.815), "East": (1.345, 103.965), "South": (1.235, 103.815),
    }
    category_colors = {
        "Good": "#55b881", "Moderate": "#ffbf3c", "Unhealthy": "#f88138",
        "Very Unhealthy": "#ec4d6a", "Hazardous": "#9457b4",
    }
    category_text_colors = {
        "Good": "#ffffff", "Moderate": "#493400", "Unhealthy": "#ffffff",
        "Very Unhealthy": "#ffffff", "Hazardous": "#ffffff",
    }
    for row in day_forecast.itertuples():
        lat, lon = card_positions[row.region]
        category = str(row.severity)
        category_color = category_colors[category]
        # Four-corner polygons create compact rectangular cards with colored
        # outlines; separate text layers keep the confidence range smaller.
        card_lon, card_lat = 0.060, 0.032
        map_figure.add_trace(go.Scattermap(
            lon=[lon-card_lon, lon+card_lon, lon+card_lon, lon-card_lon, lon-card_lon],
            lat=[lat-card_lat, lat-card_lat, lat+card_lat, lat+card_lat, lat-card_lat],
            mode="lines", fill="toself", fillcolor=category_color,
            line={"color": "#ffffff", "width": 2.5},
            hoverinfo="skip", showlegend=False,
        ))
        map_figure.add_trace(go.Scattermap(
            lon=[lon], lat=[lat+0.010], mode="text",
            text=[f"{row.predicted_psi:.0f} PSI · {category}"],
            textfont={"size": 12, "color": category_text_colors[category]}, textposition="middle center",
            hoverinfo="skip", showlegend=False,
        ))
        map_figure.add_trace(go.Scattermap(
            lon=[lon], lat=[lat-0.013], mode="text",
            text=[f"95%: {row.confidence_95_lower:.0f}–{row.confidence_95_upper:.0f} PSI"],
            textfont={"size": 9, "color": category_text_colors[category]}, textposition="middle center",
            hoverinfo="skip", showlegend=False,
        ))
    map_figure.update_layout(
        height=500, margin={"l": 0, "r": 0, "t": 0, "b": 0},
        map={"style": "open-street-map", "fitbounds": "locations", "center": {"lat": 1.3521, "lon": 103.8198}, "zoom": 10.5},
        paper_bgcolor=theme["background"], uirevision="singapore-psi-map-fit-v2",
    )
    map_column, advisory_column = st.columns([2.6, 1.35], gap="large", vertical_alignment="top")
    with map_column:
        st.plotly_chart(map_figure, width="stretch", config={"scrollZoom": True})
    with advisory_column:
        st.markdown("#### Health advisory")
        st.caption("MOH guidance for healthy persons")
        haze_scale = [
            ("Good", "0–50 PSI"), ("Moderate", "51–100 PSI"),
            ("Unhealthy", "101–200 PSI"), ("Very Unhealthy", "201–300 PSI"),
            ("Hazardous", "301+ PSI"),
        ]
        for level, psi_range in haze_scale:
            st.markdown(
                f"<div style='background:{category_colors[level]};color:{category_text_colors[level]};"
                f"padding:5px 9px;margin:4px 0;border-radius:8px;font-size:13px'>"
                f"<b>{level}</b> &nbsp; {psi_range}</div>",
                unsafe_allow_html=True,
            )
        guidance = {
            "Good": "Normal activities.",
            "Moderate": "Normal activities.",
            "Unhealthy": "Reduce prolonged or strenuous outdoor exertion.",
            "Very Unhealthy": "Avoid prolonged or strenuous outdoor exertion.",
            "Hazardous": "Minimise outdoor activity.",
        }
        for row in day_forecast.itertuples():
            category = str(row.severity)
            st.markdown(
                f"<div style='background:{category_colors[category]}22;"
                f"border-left:5px solid {category_colors[category]};border-radius:7px;"
                f"padding:7px 9px;margin:7px 0;color:{theme['text']};font-size:13px'>"
                f"<b>{row.region} · {row.predicted_psi:.0f} PSI · {category}</b><br>"
                f"{guidance[category]}</div>",
                unsafe_allow_html=True,
            )
        st.caption("Older adults, children, pregnant women, and people with chronic heart or lung conditions may need stricter precautions.")
        st.markdown("[Full Singapore MOH haze advisory](https://www.moh.gov.sg/others/haze/)")
    st.caption("Forecast information boxes are positioned approximately over Singapore's five monitoring regions.")

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
        last_observation = history.iloc[-1]
        connected_dates = [last_observation.date, *regional.forecast_date.tolist()]
        connected_values = [last_observation[region_cols[region]], *regional.predicted_psi.tolist()]
        chart.add_trace(go.Scatter(x=connected_dates, y=connected_values,
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
    avg_dates = [history.date.iloc[-1], *by_horizon.forecast_date.tolist()]
    avg_values = [historic_avg.iloc[-1], *by_horizon.predicted.tolist()]
    chart.add_trace(go.Scatter(x=avg_dates, y=avg_values, mode="lines+markers",
                               name="Singapore average (forecast)", line={"color": "#202020", "width": 3.5, "dash": "dash"}))
    chart.add_vline(x=selected_date, line_dash="dot", line_color="#777777")
    chart.update_layout(height=430, xaxis_title="Date", yaxis_title="24-hour PSI", hovermode="x unified",
                        legend={"orientation": "h", "y": -0.25}, margin={"t": 15, "b": 100},
                        paper_bgcolor=theme["background"], plot_bgcolor=theme["surface"],
                        font={"color": theme["text"]})
    chart.update_yaxes(rangemode="tozero", gridcolor=theme["grid"])
    st.plotly_chart(chart, width="stretch")
    st.caption("The shaded band shows the mean of the five regional 95% lower and upper bounds; it is a visual summary, not a separately calibrated interval for the island-wide average.")

    st.subheader("Forecast confidence and method")
    st.write(f"**Selected Part 5 model:** {best_model} (lowest mean five-fold chronological RMSE across all five regions and three horizons).")
    summary_columns = ["region", "predicted_psi", "confidence_95_lower", "confidence_95_upper", "walkforward_rmse_psi", "confidence_score_pct", "severity"]
    if "glm_alpha" in day_forecast and day_forecast.glm_alpha.notna().any():
        summary_columns.append("glm_alpha")
    selected_summary = day_forecast[summary_columns].rename(columns={
        "region": "Region", "predicted_psi": "Predicted PSI", "confidence_95_lower": "95% lower",
        "confidence_95_upper": "95% upper", "walkforward_rmse_psi": "Historical RMSE (PSI)",
        "confidence_score_pct": "Within 10 PSI in validation (%)", "severity": "Category",
        "glm_alpha": "Tuned GLM alpha",
    })
    st.dataframe(selected_summary, hide_index=True, width="stretch")
    with st.expander("Model parameters and input features"):
        st.markdown(
            f"""- Forecast lead: **t+{selected_horizon}**, for **{selected_date:%d %b %Y}**.
- Input window: daily data from **{(input_date - timedelta(days=6)):%d %b %Y}** through **{input_date:%d %b %Y}**.
- Predictors (each supplied for seven daily lags): five regional PSI values; eastward and northward wind-direction components; maximum wind speed; Sumatra, Borneo and Peninsular Malaysia hotspot counts; rainfall; and mean humidity.
        - Model choice: **{best_model}**, carried forward from Part 5's saved forecast selection. Re-run notebook parts 5 and 6 to compare and choose again after changing data or model settings.
- Both models tune ridge regularization inside chronological training folds; the selected alpha is shown in the regional results table. The 5b model also includes log and squared predictor terms and PSI-weather-fire interactions.
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
