# -*- coding: utf-8 -*-
from datetime import datetime, timedelta, timezone

import pandas as pd
import plotly.express as px
import requests
import streamlit as st


st.set_page_config(page_title="Multi-League Value Finder", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

    .main {
        background:
            radial-gradient(1100px 420px at 5% -20%, rgba(56, 139, 253, 0.2), transparent 60%),
            radial-gradient(1000px 380px at 100% 0%, rgba(35, 134, 54, 0.16), transparent 60%),
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
        background: linear-gradient(180deg, #161b22 0%, #10151d 100%);
        border: 1px solid #30363d;
        border-radius: 14px;
        padding: 14px;
    }

    .top-advice-card {
        background: linear-gradient(140deg, #1f6feb 0%, #0f1722 100%);
        border-left: 5px solid #2ea043;
        border-radius: 14px;
        border: 1px solid rgba(255, 255, 255, 0.14);
        color: #ffffff;
        padding: 18px;
        box-shadow: 0 10px 24px rgba(31, 111, 235, 0.28);
    }

    .section-title {
        font-family: 'Space Grotesk', sans-serif;
        font-size: 1.15rem;
        margin-bottom: 0.55rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


FOOTBALL_API_KEY = st.secrets.get("FOOTBALL_API_KEY", st.secrets.get("FOOTBALL_DATA_API_KEY", ""))
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")

SELECTED_LEAGUES = [
    "soccer_netherlands_eredivisie",
    "soccer_netherlands_eerste_divisie",
    "soccer_uefa_champs_league",
    "soccer_epl",
    "soccer_fifa_world_cup",
]

LEAGUE_META = {
    "soccer_netherlands_eredivisie": {"name": "Eredivisie", "code": "DED"},
    "soccer_netherlands_eerste_divisie": {"name": "Eerste Divisie", "code": "PPL"},
    "soccer_uefa_champs_league": {"name": "Champions League", "code": "CL"},
    "soccer_epl": {"name": "Premier League", "code": "PL"},
    "soccer_fifa_world_cup": {"name": "World Cup", "code": "WC"},
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
    if not FOOTBALL_API_KEY or not league_code:
        return pd.DataFrame()
    url = f"https://api.football-data.org/v4/competitions/{league_code}/matches"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    res = requests.get(url, headers=headers, params={"status": "FINISHED"}, timeout=20)
    if res.status_code != 200:
        return pd.DataFrame()

    rows = []
    for match in res.json().get("matches", []):
        rows.append(
            {
                "Home": match["homeTeam"]["name"],
                "Away": match["awayTeam"]["name"],
                "Winner": match["score"]["winner"],
            }
        )
    return pd.DataFrame(rows)


def calculate_probabilities(df, home_team, away_team):
    if df.empty:
        return {"home": 0.52, "draw": 0.23, "away": 0.25}

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


@st.cache_data(ttl=900)
def get_top_scorers(league_code):
    if not FOOTBALL_API_KEY or not league_code:
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


@st.cache_data(ttl=600)
def get_unibet_odds(sport):
    if not ODDS_API_KEY:
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "api_key": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "bookmakers": "unibet",
        "oddsFormat": "decimal",
    }
    res = requests.get(url, params=params, timeout=20)
    if res.status_code != 200:
        return []
    return res.json()


def fetch_all_league_odds(selected_sports):
    now_utc = datetime.now(timezone.utc)
    max_window = now_utc + timedelta(days=7)

    all_matches = []
    match_details = []
    league_hist_cache = {}
    league_scorer_cache = {}
    skipped_outside_window = 0

    for sport in selected_sports:
        meta = LEAGUE_META.get(sport, {"name": sport, "code": None})
        league_name = meta["name"]
        league_code = meta["code"]

        if league_code not in league_hist_cache:
            league_hist_cache[league_code] = get_historical_stats(league_code)
            league_scorer_cache[league_code] = get_top_scorers(league_code)

        df_hist = league_hist_cache[league_code]
        top_scorers = league_scorer_cache[league_code]
        odds_data = get_unibet_odds(sport)

        for match in odds_data:
            kickoff = parse_commence_time(match.get("commence_time"))
            if not kickoff or kickoff < now_utc or kickoff > max_window:
                skipped_outside_window += 1
                continue

            home = match.get("home_team")
            away = match.get("away_team")
            if not home or not away:
                continue

            unibet = next((b for b in match.get("bookmakers", []) if b.get("key") == "unibet"), None)
            if not unibet or not unibet.get("markets"):
                continue

            outcomes = unibet["markets"][0].get("outcomes", [])
            by_name = {o.get("name"): o.get("price") for o in outcomes}
            home_odd = by_name.get(home)
            draw_odd = by_name.get("Draw")
            away_odd = by_name.get(away)
            if not (home_odd and away_odd):
                continue

            probs = calculate_probabilities(df_hist, home, away)
            fair_home = round(1 / probs["home"], 2) if probs["home"] > 0 else None
            fair_draw = round(1 / probs["draw"], 2) if probs["draw"] > 0 else None
            fair_away = round(1 / probs["away"], 2) if probs["away"] > 0 else None

            edge_home = round((home_odd / fair_home) - 1, 3) if fair_home else 0
            edge_draw = round(((draw_odd or 0) / fair_draw) - 1, 3) if fair_draw and draw_odd else 0
            edge_away = round((away_odd / fair_away) - 1, 3) if fair_away else 0
            max_edge = max(edge_home, edge_draw, edge_away)
            best_bet = "Home" if max_edge == edge_home else ("Draw" if max_edge == edge_draw else "Away")

            all_matches.append(
                {
                    "League": league_name,
                    "Match": f"{home} vs {away}",
                    "Home Team": home,
                    "Away Team": away,
                    "Time": kickoff,
                    "Starttijd": kickoff.astimezone().strftime("%Y-%m-%d %H:%M"),
                    "Odd Home": home_odd,
                    "Odd Draw": draw_odd,
                    "Odd Away": away_odd,
                    "Prob Home": probs["home"],
                    "Prob Draw": probs["draw"],
                    "Prob Away": probs["away"],
                    "Edge Home": edge_home,
                    "Edge Draw": edge_draw,
                    "Edge Away": edge_away,
                    "Edge": max_edge,
                    "Best Bet": best_bet,
                }
            )

            match_details.append(
                {
                    "league": league_name,
                    "home": home,
                    "away": away,
                    "probs": probs,
                    "odds": {"home": home_odd, "away": away_odd},
                    "base_edges": {"home": edge_home, "away": edge_away},
                    "kickoff": kickoff,
                    "top_scorers": top_scorers,
                }
            )

    df = pd.DataFrame(all_matches)
    if not df.empty:
        df = df.sort_values(by="Edge", ascending=False).reset_index(drop=True)
    return df, match_details, skipped_outside_window


if "analysis" not in st.session_state:
    st.session_state.analysis = None

with st.sidebar:
    st.header("Dashboard Settings")
    min_edge = st.slider("Minimale Edge Drempel", 0.0, 0.30, 0.05, step=0.01)
    include_kkd = st.toggle("KKD meenemen", value=True)
    include_wk = st.toggle("WK 2026 meenemen", value=True)

    selected_sports = [
        sport
        for sport in SELECTED_LEAGUES
        if (include_kkd or sport != "soccer_netherlands_eerste_divisie")
        and (include_wk or sport != "soccer_fifa_world_cup")
    ]

    scan = st.button("Scan alle competities", use_container_width=True)
    if st.button("Ververs Live Data", use_container_width=True):
        st.cache_data.clear()
        st.session_state.analysis = None
        st.rerun()


if scan:
    with st.spinner("Bezig met scannen van Unibet odds over meerdere competities..."):
        scan_df, match_details, skipped = fetch_all_league_odds(selected_sports)
    st.session_state.analysis = {
        "df": scan_df,
        "details": match_details,
        "skipped": skipped,
        "selected_sports": selected_sports,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


st.title("Multi-League Value Finder")
st.markdown("Gecombineerde value scan over Eredivisie, KKD, Champions League, Premier League en WK 2026.")
st.markdown("---")

if not st.session_state.analysis:
    st.info("Klik op Scan alle competities om de beste kansen van de komende 7 dagen op te halen.")
    st.stop()

df = st.session_state.analysis["df"].copy()
match_details = st.session_state.analysis["details"]
skipped = st.session_state.analysis["skipped"]

if df.empty:
    st.warning("Geen actieve odds gevonden voor de geselecteerde competities in de komende 7 dagen.")
    st.stop()

df["Status"] = df["Edge"].apply(lambda x: "VALUE" if x > min_edge else "Geen value")
value_df = df[df["Status"] == "VALUE"]

st.markdown('<div class="section-title">Top Value Alerts (Komende 7 dagen)</div>', unsafe_allow_html=True)
top_bets = value_df.sort_values("Edge", ascending=False).head(3)

top_cols = st.columns(3)
for idx in range(3):
    with top_cols[idx]:
        if idx < len(top_bets):
            row = top_bets.iloc[idx]
            bet_prob = row["Prob Home"] if row["Best Bet"] == "Home" else (
                row["Prob Draw"] if row["Best Bet"] == "Draw" else row["Prob Away"]
            )
            bet_odd = row["Odd Home"] if row["Best Bet"] == "Home" else (
                row["Odd Draw"] if row["Best Bet"] == "Draw" else row["Odd Away"]
            )
            st.markdown(
                f"""
                <div class="top-advice-card">
                    <div style="font-size:0.78rem; opacity:0.82;">TOP ADVIES #{idx + 1}</div>
                    <div style="font-size:0.8rem; opacity:0.86; margin-top:3px;">{row['League']}</div>
                    <div style="font-size:1.06rem; margin-top:4px;">{row['Match']}</div>
                    <div style="font-size:1.45rem; margin-top:10px; color:#2ea043;">+{row['Edge'] * 100:.1f}% Edge</div>
                    <div style="margin-top:8px; opacity:0.92;">Bet: {row['Best Bet']}</div>
                    <hr style="margin:10px 0; border-color: rgba(255,255,255,0.25);">
                    <div style="display:flex; justify-content:space-between; gap:8px; font-size:0.92rem;">
                        <span>Kans: {bet_prob:.0%}</span>
                        <span>Odd: {bet_odd}</span>
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
                    Nog geen extra top-alert beschikbaar.
                </div>
                """,
                unsafe_allow_html=True,
            )

metric_cols = st.columns(5)
metric_cols[0].metric("Totaal wedstrijden", len(df))
metric_cols[1].metric("Value bets", len(value_df))
metric_cols[2].metric("Hoogste edge", f"{df['Edge'].max():.1%}")
metric_cols[3].metric("Competities", len(df['League'].unique()))
metric_cols[4].metric("Buiten 7 dagen gefilterd", skipped)

st.markdown("---")
st.markdown('<div class="section-title">Alle Geanalyseerde Wedstrijden</div>', unsafe_allow_html=True)
tab_table, tab_matrix = st.tabs(["Tabel Weergave", "Risico Matrix"])

with tab_table:
    table_df = df[["League", "Match", "Starttijd", "Best Bet", "Odd Home", "Odd Draw", "Odd Away", "Edge", "Status"]].copy()
    table_df["Edge Score"] = (table_df["Edge"] * 100).round(1)
    st.dataframe(
        table_df,
        column_config={
            "Edge": st.column_config.NumberColumn("Edge", format="%.1f%%"),
            "Edge Score": st.column_config.ProgressColumn("Value", min_value=-20.0, max_value=30.0, format="%.1f%%"),
        },
        use_container_width=True,
        hide_index=True,
    )

with tab_matrix:
    matrix_df = df.copy()
    matrix_df["Best Prob"] = matrix_df.apply(
        lambda row: row["Prob Home"] if row["Best Bet"] == "Home" else (
            row["Prob Draw"] if row["Best Bet"] == "Draw" else row["Prob Away"]
        ),
        axis=1,
    )
    fig = px.scatter(
        matrix_df,
        x="Best Prob",
        y="Edge",
        text="Match",
        size="Edge",
        color="Edge",
        color_continuous_scale="RdYlGn",
        title="Risk vs Reward Matrix (Multi-League)",
    )
    fig.update_traces(textposition="top center")
    fig.update_layout(
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        xaxis_title="Model Probability",
        yaxis_title="Edge",
    )
    fig.add_hline(y=min_edge, line_dash="dot", line_color="#2ea043")
    st.plotly_chart(fig, use_container_width=True)

st.markdown("---")
st.markdown('<div class="section-title">Speler Impact (Topscorer Afwezig)</div>', unsafe_allow_html=True)
st.caption("Per team kan je de topscorer-afwezigheid simuleren. Bij afwezigheid verlagen we de teamkans met 10%.")

for md in match_details:
    home = md["home"]
    away = md["away"]
    top_scorers = md["top_scorers"]
    star_home = top_scorers.get(home)
    star_away = top_scorers.get(away)
    label_home = f"{star_home['name']} ({star_home['goals']} goals)" if star_home else "Onbekend"
    label_away = f"{star_away['name']} ({star_away['goals']} goals)" if star_away else "Onbekend"

    with st.expander(f"{md['league']} - {home} vs {away} ({md['kickoff'].astimezone().strftime('%Y-%m-%d %H:%M')})"):
        col_home, col_away = st.columns(2)

        with col_home:
            st.markdown(f"**Topscorer thuis:** {label_home}")
            missing_home = st.toggle(f"Is topscorer van {home} afwezig?", key=f"abs_home_{home}_{away}_{md['league']}")
            home_prob = md["probs"]["home"]
            if missing_home:
                home_prob *= 0.90
            home_fair = 1 / home_prob if home_prob > 0 else None
            home_edge = round((md["odds"]["home"] / home_fair) - 1, 3) if home_fair else 0
            st.metric("Aangepaste Edge Home", f"{home_edge:.1%}", delta=f"{home_edge - md['base_edges']['home']:+.1%}")

        with col_away:
            st.markdown(f"**Topscorer uit:** {label_away}")
            missing_away = st.toggle(f"Is topscorer van {away} afwezig?", key=f"abs_away_{home}_{away}_{md['league']}")
            away_prob = md["probs"]["away"]
            if missing_away:
                away_prob *= 0.90
            away_fair = 1 / away_prob if away_prob > 0 else None
            away_edge = round((md["odds"]["away"] / away_fair) - 1, 3) if away_fair else 0
            st.metric("Aangepaste Edge Away", f"{away_edge:.1%}", delta=f"{away_edge - md['base_edges']['away']:+.1%}")
