# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


st.set_page_config(page_title="Elite Football Analytics", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

    .main {
        background:
            radial-gradient(1000px 400px at 10% -20%, rgba(56, 139, 253, 0.18), transparent 60%),
            radial-gradient(900px 360px at 95% 0%, rgba(35, 134, 54, 0.16), transparent 55%),
            #0d1117;
        color: #e6edf3;
    }

    h1, h2, h3 {
        font-family: 'Space Grotesk', sans-serif !important;
        letter-spacing: 0.02em;
    }

    p, span, label, div {
        font-family: 'IBM Plex Sans', sans-serif !important;
    }

    [data-testid='stMetric'] {
        background: linear-gradient(180deg, #161b22 0%, #11161d 100%);
        border: 1px solid #30363d;
        border-radius: 14px;
        padding: 14px;
    }

    .top-advice-card {
        background: linear-gradient(140deg, #238636 0%, #2ea043 100%);
        border: 1px solid rgba(255, 255, 255, 0.22);
        border-left: 5px solid #ffffff;
        border-radius: 14px;
        padding: 16px;
        margin-bottom: 14px;
        color: #ffffff;
        box-shadow: 0 10px 24px rgba(35, 134, 54, 0.33);
    }

    .section-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.16rem;
        margin-bottom: 0.55rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


FOOTBALL_API_KEY = st.secrets.get("FOOTBALL_API_KEY", st.secrets.get("FOOTBALL_DATA_API_KEY", ""))
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

SPORTS_MAP = {
    "Eredivisie": ("DED", "soccer_netherlands_eredivisie"),
    "Premier League": ("PL", "soccer_epl"),
    "La Liga": ("PD", "soccer_spain_la_liga"),
    "Champions League": ("CL", "soccer_uefa_champs_league"),
    "Bundesliga": ("BL1", "soccer_germany_bundesliga"),
}


def parse_commence_time(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


@st.cache_data(ttl=3600)
def get_historical_stats(league_code):
    if not FOOTBALL_API_KEY:
        st.error("Geen FOOTBALL_API_KEY gevonden in secrets.")
        return pd.DataFrame()
    url = f"https://api.football-data.org/v4/competitions/{league_code}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    res = requests.get(url, headers=headers, params={"status": "FINISHED"}, timeout=20)
    if res.status_code == 404:
        st.error(f"Competitiecode '{league_code}' niet gevonden (404).")
        return pd.DataFrame()
    if res.status_code != 200:
        st.error(f"Football-data fout {res.status_code}: {res.text[:300]}")
        return pd.DataFrame()

    rows = []
    for match in res.json().get("matches", []):
        rows.append(
            {
                "Home": match["homeTeam"]["name"],
                "Away": match["awayTeam"]["name"],
                "HomeGoals": match["score"]["fullTime"]["home"],
                "AwayGoals": match["score"]["fullTime"]["away"],
                "Winner": match["score"]["winner"],
            }
        )
    return pd.DataFrame(rows)


def calculate_probabilities(df, home_team, away_team):
    home_games = df[df["Home"] == home_team]
    away_games = df[df["Away"] == away_team]

    prob_home = (
        len(home_games[home_games["Winner"] == "HOME_TEAM"]) / len(home_games)
        if len(home_games) >= 3
        else 0.40
    )
    prob_away = (
        len(away_games[away_games["Winner"] == "AWAY_TEAM"]) / len(away_games)
        if len(away_games) >= 3
        else 0.30
    )
    prob_draw = max(1 - prob_home - prob_away, 0.05)
    total = prob_home + prob_draw + prob_away

    return {
        "home": round(prob_home / total, 3),
        "draw": round(prob_draw / total, 3),
        "away": round(prob_away / total, 3),
    }


@st.cache_data(ttl=600)
def get_unibet_odds(sport_key):
    if not ODDS_API_KEY:
        st.error("Geen ODDS_API_KEY gevonden in secrets.")
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/"
    params = {
        "api_key": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "bookmakers": "unibet",
        "oddsFormat": "decimal",
    }
    res = requests.get(url, params=params, timeout=20)
    if res.status_code != 200:
        st.error(f"Odds API fout {res.status_code}: {res.text[:300]}")
        return []
    data = res.json()
    if not data:
        st.warning("Geen aankomende wedstrijden gevonden. De ronde is waarschijnlijk al gespeeld.")
    return data


@st.cache_data(ttl=3600)
def get_top_scorers(league_code):
    if not FOOTBALL_API_KEY:
        return {}
    url = f"https://api.football-data.org/v4/competitions/{league_code}/scorers"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    res = requests.get(url, headers=headers, timeout=20)
    if res.status_code != 200:
        return {}

    scorer_dict = {}
    for scorer in res.json().get("scorers", []):
        team_name = scorer["team"]["name"]
        player_name = scorer["player"]["name"]
        goals = scorer.get("numberOfGoals", scorer.get("goals", 0))
        scorer_dict[team_name] = {"name": player_name, "goals": goals}
    return scorer_dict


def get_analysis_data(league_code, sport_key):
    now_utc = datetime.now(timezone.utc)
    max_window = now_utc + timedelta(days=7)

    df_hist = get_historical_stats(league_code)
    if df_hist.empty:
        return df_hist, pd.DataFrame(), [], {}, 0

    live_odds = get_unibet_odds(sport_key)
    top_scorers = get_top_scorers(league_code)

    results = []
    match_details = []
    skipped_outside_window = 0

    for match in live_odds:
        kickoff = parse_commence_time(match.get("commence_time"))
        if not kickoff or kickoff < now_utc or kickoff > max_window:
            skipped_outside_window += 1
            continue

        home = match.get("home_team")
        away = match.get("away_team")
        if not home or not away:
            continue

        unibet_data = next((b for b in match.get("bookmakers", []) if b.get("key") == "unibet"), None)
        if not unibet_data or not unibet_data.get("markets"):
            continue

        outcomes = unibet_data["markets"][0].get("outcomes", [])
        by_name = {o.get("name"): o.get("price") for o in outcomes}
        unibet_home = by_name.get(home)
        unibet_draw = by_name.get("Draw")
        unibet_away = by_name.get(away)
        if not (unibet_home and unibet_away):
            continue

        probs = calculate_probabilities(df_hist, home, away)
        fair_home = round(1 / probs["home"], 2) if probs["home"] > 0 else None
        fair_draw = round(1 / probs["draw"], 2) if probs["draw"] > 0 else None
        fair_away = round(1 / probs["away"], 2) if probs["away"] > 0 else None

        edge_home = round((unibet_home / fair_home) - 1, 3) if fair_home else 0
        edge_draw = round(((unibet_draw or 0) / fair_draw) - 1, 3) if fair_draw and unibet_draw else 0
        edge_away = round((unibet_away / fair_away) - 1, 3) if fair_away else 0

        max_edge = max(edge_home, edge_draw, edge_away)
        best_bet = "Home" if max_edge == edge_home else ("Draw" if max_edge == edge_draw else "Away")

        results.append(
            {
                "Wedstrijd": f"{home} vs {away}",
                "Home Team": home,
                "Away Team": away,
                "Kickoff": kickoff,
                "Starttijd": kickoff.astimezone().strftime("%Y-%m-%d %H:%M"),
                "Unibet Home": unibet_home,
                "Unibet Draw": unibet_draw,
                "Unibet Away": unibet_away,
                "Model Kans Home": probs["home"],
                "Model Kans Draw": probs["draw"],
                "Model Kans Away": probs["away"],
                "Fair Odd Home": fair_home,
                "Fair Odd Draw": fair_draw,
                "Fair Odd Away": fair_away,
                "Edge Home": edge_home,
                "Edge Draw": edge_draw,
                "Edge Away": edge_away,
                "Max Edge": max_edge,
                "Beste Bet": best_bet,
            }
        )

        match_details.append(
            {
                "home": home,
                "away": away,
                "probs": probs,
                "unibet_home": unibet_home,
                "unibet_away": unibet_away,
                "edge_home": edge_home,
                "edge_away": edge_away,
                "kickoff": kickoff,
            }
        )

    result_df = pd.DataFrame(results)
    if not result_df.empty:
        result_df = result_df.sort_values("Kickoff", ascending=True).reset_index(drop=True)

    return df_hist, result_df, match_details, top_scorers, skipped_outside_window


if "analysis" not in st.session_state:
    st.session_state.analysis = None

with st.sidebar:
    st.header("Dashboard Settings")
    selected_league = st.selectbox("Competitie", list(SPORTS_MAP.keys()))
    min_edge = st.slider("Minimale Edge Drempel", 0.0, 0.30, 0.05, step=0.01)

    start_analysis = st.button("Start Analyse", use_container_width=True)
    if st.button("Ververs Live Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.analysis = None
        st.rerun()


league_code, sport_key = SPORTS_MAP[selected_league]

if start_analysis:
    with st.spinner("Data ophalen en moderne analyse opbouwen..."):
        analysis_data = get_analysis_data(league_code, sport_key)
    st.session_state.analysis = {
        "league": selected_league,
        "league_code": league_code,
        "sport_key": sport_key,
        "payload": analysis_data,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


st.title("Elite Football Analytics")
st.markdown("Realtime value-dashboard op basis van historische prestaties en Unibet odds.")
st.markdown("---")

if not st.session_state.analysis:
    st.info("Kies je competitie in de sidebar en klik op Start Analyse.")
    st.stop()

df_hist, res_df, match_details, top_scorers, skipped_outside_window = st.session_state.analysis["payload"]

if res_df.empty:
    st.warning("Geen wedstrijden met bruikbare odds gevonden voor de komende 7 dagen.")
    st.stop()

display_df = res_df.copy()
display_df["Status"] = display_df["Max Edge"].apply(lambda x: "VALUE" if x > min_edge else "Geen value")
value_bets = display_df[display_df["Status"] == "VALUE"]

st.markdown('<div class="section-title">Top Value Alerts (Komende 7 dagen)</div>', unsafe_allow_html=True)
top_alerts = (
    display_df[display_df["Status"] == "VALUE"]
    .sort_values("Max Edge", ascending=False)
    .head(3)
)

top_cols = st.columns(3)
for idx in range(3):
    with top_cols[idx]:
        if idx < len(top_alerts):
            row = top_alerts.iloc[idx]
            model_prob = row["Model Kans Home"] if row["Beste Bet"] == "Home" else (
                row["Model Kans Draw"] if row["Beste Bet"] == "Draw" else row["Model Kans Away"]
            )
            advised_odd = row["Unibet Home"] if row["Beste Bet"] == "Home" else (
                row["Unibet Draw"] if row["Beste Bet"] == "Draw" else row["Unibet Away"]
            )
            st.markdown(
                f"""
                <div class="top-advice-card">
                    <div style="font-size:0.78rem; opacity:0.82;">TOP ADVIES #{idx + 1}</div>
                    <div style="font-size:1.08rem; margin-top:2px;">{row['Wedstrijd']}</div>
                    <div style="font-size:1.45rem; margin-top:9px;">Edge: +{row['Max Edge'] * 100:.1f}%</div>
                    <div style="margin-top:8px; opacity:0.92;">Bet: {row['Beste Bet']}</div>
                    <hr style="margin:10px 0; border-color: rgba(255,255,255,0.25);">
                    <div style="display:flex; justify-content:space-between; gap:8px; font-size:0.92rem;">
                        <span>Kans: {model_prob:.0%}</span>
                        <span>Odd: {advised_odd}</span>
                    </div>
                    <div style="margin-top:8px; font-size:0.8rem; opacity:0.85;">Start: {row['Starttijd']}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                """
                <div style="background:#161b22; border:1px dashed #30363d; border-radius:14px; padding:16px; min-height:190px;">
                    Nog geen extra top-alert in deze league.
                </div>
                """,
                unsafe_allow_html=True,
            )

metric_cols = st.columns(4)
metric_cols[0].metric("Totaal wedstrijden", len(display_df))
metric_cols[1].metric("Value bets", len(value_bets))
metric_cols[2].metric("Hoogste Edge", f"{display_df['Max Edge'].max():.1%}")
metric_cols[3].metric("Gefilterd buiten 7 dagen", skipped_outside_window)

st.markdown("---")
st.markdown('<div class="section-title">Alle Geanalyseerde Wedstrijden</div>', unsafe_allow_html=True)
tab_table, tab_matrix = st.tabs(["Tabel Weergave", "Risico Matrix"])

with tab_table:
    table_df = display_df[
        [
            "Wedstrijd",
            "Starttijd",
            "Beste Bet",
            "Unibet Home",
            "Unibet Draw",
            "Unibet Away",
            "Model Kans Home",
            "Model Kans Draw",
            "Model Kans Away",
            "Edge Home",
            "Edge Draw",
            "Edge Away",
            "Max Edge",
            "Status",
        ]
    ].copy()

    table_df["Edge Score"] = (table_df["Max Edge"] * 100).round(1)
    st.dataframe(
        table_df,
        column_config={
            "Model Kans Home": st.column_config.NumberColumn("Kans Home", format="%.0f%%"),
            "Model Kans Draw": st.column_config.NumberColumn("Kans Draw", format="%.0f%%"),
            "Model Kans Away": st.column_config.NumberColumn("Kans Away", format="%.0f%%"),
            "Edge Home": st.column_config.NumberColumn("Edge Home", format="%.1f%%"),
            "Edge Draw": st.column_config.NumberColumn("Edge Draw", format="%.1f%%"),
            "Edge Away": st.column_config.NumberColumn("Edge Away", format="%.1f%%"),
            "Max Edge": st.column_config.NumberColumn("Max Edge", format="%.1f%%"),
            "Edge Score": st.column_config.ProgressColumn(
                "Edge Score",
                min_value=0.0,
                max_value=30.0,
                format="%.1f%%",
            ),
        },
        use_container_width=True,
        hide_index=True,
    )

with tab_matrix:
    matrix_df = display_df.copy()
    matrix_df["Best Prob"] = matrix_df.apply(
        lambda row: row["Model Kans Home"] if row["Beste Bet"] == "Home" else (
            row["Model Kans Draw"] if row["Beste Bet"] == "Draw" else row["Model Kans Away"]
        ),
        axis=1,
    )
    fig = px.scatter(
        matrix_df,
        x="Best Prob",
        y="Max Edge",
        text="Wedstrijd",
        size="Max Edge",
        color="Max Edge",
        color_continuous_scale="RdYlGn",
        title=f"Risk vs Reward Matrix - {selected_league}",
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis_title="Model Win Probability",
        yaxis_title="Max Edge",
    )
    fig.add_hline(y=min_edge, line_dash="dot", line_color="#2ea043")
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.markdown('<div class="section-title">Speler Impact Per Wedstrijd</div>', unsafe_allow_html=True)
st.caption("Toggle per team: als de topscorer afwezig is, wordt de teamkans met 10% verlaagd en de edge opnieuw berekend.")

for md in match_details:
    home = md["home"]
    away = md["away"]
    star_home = top_scorers.get(home)
    star_away = top_scorers.get(away)
    home_label = f"{star_home['name']} ({star_home['goals']} goals)" if star_home else "Onbekend"
    away_label = f"{star_away['name']} ({star_away['goals']} goals)" if star_away else "Onbekend"

    with st.expander(f"{home} vs {away} - {md['kickoff'].astimezone().strftime('%Y-%m-%d %H:%M')}"):
        col_home, col_away = st.columns(2)

        with col_home:
            st.markdown(f"**Topspeler thuis:** {home_label}")
            missing_home = st.toggle(
                f"Is topscorer van {home} afwezig?",
                key=f"absent_home_{home}_{away}",
            )
            home_prob = md["probs"]["home"]
            if missing_home:
                home_prob *= 0.90
                st.warning(f"Aangepaste thuiskans: {home_prob:.0%}")
            adjusted_home_fair = 1 / home_prob if home_prob > 0 else None
            adjusted_home_edge = (
                round((md["unibet_home"] / adjusted_home_fair) - 1, 3)
                if adjusted_home_fair and md["unibet_home"]
                else 0
            )
            st.metric(
                "Aangepaste Edge Home",
                f"{adjusted_home_edge:.1%}",
                delta=f"{adjusted_home_edge - md['edge_home']:+.1%}",
            )

        with col_away:
            st.markdown(f"**Topspeler uit:** {away_label}")
            missing_away = st.toggle(
                f"Is topscorer van {away} afwezig?",
                key=f"absent_away_{home}_{away}",
            )
            away_prob = md["probs"]["away"]
            if missing_away:
                away_prob *= 0.90
                st.warning(f"Aangepaste uitkans: {away_prob:.0%}")
            adjusted_away_fair = 1 / away_prob if away_prob > 0 else None
            adjusted_away_edge = (
                round((md["unibet_away"] / adjusted_away_fair) - 1, 3)
                if adjusted_away_fair and md["unibet_away"]
                else 0
            )
            st.metric(
                "Aangepaste Edge Away",
                f"{adjusted_away_edge:.1%}",
                delta=f"{adjusted_away_edge - md['edge_away']:+.1%}",
            )

with st.expander("Historische sample (laatste 10)"):
    st.dataframe(df_hist.tail(10), use_container_width=True, hide_index=True)
