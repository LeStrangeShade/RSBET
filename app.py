import streamlit as st
import pandas as pd
import requests
import os
import plotly.express as px

# --- CONFIGURATIE ---
st.set_page_config(page_title="Football Value Dashboard", layout="wide")

# --- API CONFIGURATIE ---
# Zet ODDS_API_KEY in Streamlit secrets of als environment variable.
API_KEY = st.secrets.get("ODDS_API_KEY", os.getenv("ODDS_API_KEY", ""))
FOOTBALL_DATA_API_KEY = st.secrets.get("FOOTBALL_DATA_API_KEY", os.getenv("FOOTBALL_DATA_API_KEY", ""))
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4/"
SPORTS = {
    "Eredivisie": "soccer_netherlands_eredivisie",
    "Champions League": "soccer_uefa_champs_league",
    "Premier League": "soccer_epl",
    "La Liga": "soccer_spain_la_liga",
}

# football-data.org league codes (https://www.football-data.org/coverage)
LEAGUE_CODES = {
    "Eredivisie": "ED",
    "Champions League": "CL",
    "Premier League": "PL",
    "La Liga": "PD",
}
REGIONS = "eu"
MARKETS = "h2h"
BOOKMAKERS = "unibet"


def fetch_live_unibet_odds(sport: str):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "api_key": API_KEY,
        "regions": REGIONS,
        "markets": MARKETS,
        "bookmakers": BOOKMAKERS,
        "oddsFormat": "decimal",
    }

    try:
        response = requests.get(url, params=params, timeout=20)
    except requests.RequestException as exc:
        st.error(f"Netwerkfout bij ophalen API: {exc}")
        return None

    if response.status_code != 200:
        st.error(f"Fout bij ophalen API: {response.status_code}")
        return None

    return response.json()


def process_odds_to_df(json_data) -> pd.DataFrame:
    matches = []
    for game in json_data:
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        unibet_data = next((b for b in game.get("bookmakers", []) if b.get("key") == "unibet"), None)

        if not (home_team and away_team and unibet_data):
            continue

        outcomes = unibet_data.get("markets", [{}])[0].get("outcomes", [])
        odds_by_name = {o.get("name"): o.get("price") for o in outcomes}

        odd_home = odds_by_name.get(home_team)
        odd_away = odds_by_name.get(away_team)
        odd_draw = odds_by_name.get("Draw")

        if odd_home is None or odd_away is None or odd_draw is None:
            continue

        matches.append(
            {
                "Wedstrijd": f"{home_team} vs {away_team}",
                "Odd_Home": odd_home,
                "Odd_Away": odd_away,
                "Odd_Draw": odd_draw,
                "Starttijd": game.get("commence_time"),
            }
        )

    return pd.DataFrame(matches)


def get_historical_results_v2(league_code: str = "ED") -> pd.DataFrame:
    if not FOOTBALL_DATA_API_KEY:
        st.warning("Geen football-data API key gevonden. Zet FOOTBALL_DATA_API_KEY in secrets of environment.")
        return pd.DataFrame()

    url = f"{FOOTBALL_DATA_BASE_URL}competitions/{league_code}/matches"
    params = {"status": "FINISHED"}
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=20)
    except requests.RequestException as exc:
        st.error(f"Netwerkfout bij ophalen historische data: {exc}")
        return pd.DataFrame()

    if response.status_code != 200:
        st.error(f"Fout bij ophalen historische data: {response.status_code}")
        return pd.DataFrame()

    data = response.json().get("matches", [])
    results = []
    for match in data:
        winner_raw = match.get("score", {}).get("winner")
        if winner_raw == "HOME_TEAM":
            winner = "Home"
        elif winner_raw == "AWAY_TEAM":
            winner = "Away"
        else:
            winner = "Draw"

        results.append(
            {
                "Datum": match.get("utcDate"),
                "Home": match.get("homeTeam", {}).get("name"),
                "Away": match.get("awayTeam", {}).get("name"),
                "Home_Goals": match.get("score", {}).get("fullTime", {}).get("home"),
                "Away_Goals": match.get("score", {}).get("fullTime", {}).get("away"),
                "Winner": winner,
            }
        )

    hist_df = pd.DataFrame(results)
    if not hist_df.empty:
        hist_df["Datum"] = pd.to_datetime(hist_df["Datum"], errors="coerce")
        hist_df = hist_df.sort_values("Datum")
    return hist_df


# --- UI LAYOUT ---
st.title("⚽ Football Analytics & Value Finder")
st.markdown("Analyse van wedstrijden op basis van historische data en live Unibet odds.")

# Sidebar voor filters
st.sidebar.header("Filters")
league = st.sidebar.selectbox("Selecteer Competitie", list(SPORTS.keys()))
min_value = st.sidebar.slider("Minimale Value drempel", 0.0, 0.5, 0.05, step=0.01)
edge_home = st.sidebar.slider("Model edge Home (%)", -10.0, 10.0, 2.0, step=0.5)
edge_draw = st.sidebar.slider("Model edge Draw (%)", -10.0, 10.0, 0.0, step=0.5)
edge_away = st.sidebar.slider("Model edge Away (%)", -10.0, 10.0, -2.0, step=0.5)

if not API_KEY:
    st.warning("Geen odds API key gevonden. Zet ODDS_API_KEY in .streamlit/secrets.toml of als environment variable.")


# Live update sectie
st.subheader("Live Unibet Odds")
if st.button("Update Live Odds"):
    if not API_KEY:
        st.error("Live odds ophalen kan niet zonder ODDS_API_KEY.")
    else:
        st.session_state["raw_data"] = fetch_live_unibet_odds(SPORTS[league])
        st.session_state["selected_league"] = league

raw_data = st.session_state.get("raw_data")
selected_league = st.session_state.get("selected_league", league)

if not raw_data:
    st.info("Klik op 'Update Live Odds' om de laatste odds op te halen.")
else:
    df = process_odds_to_df(raw_data)
    if df.empty:
        st.warning("Geen odds-data beschikbaar voor deze competitie op dit moment.")
    else:
        # Bookmaker implied kansen (met overround), daarna normaliseren naar 1.0.
        df["Implied_Home"] = 1 / df["Odd_Home"]
        df["Implied_Draw"] = 1 / df["Odd_Draw"]
        df["Implied_Away"] = 1 / df["Odd_Away"]
        implied_sum = df["Implied_Home"] + df["Implied_Draw"] + df["Implied_Away"]

        df["Book_Prob_Home"] = df["Implied_Home"] / implied_sum
        df["Book_Prob_Draw"] = df["Implied_Draw"] / implied_sum
        df["Book_Prob_Away"] = df["Implied_Away"] / implied_sum

        # 3-way modelkansen: bookmaker baseline + eigen edge per uitkomst, daarna hernormaliseren.
        df["Model_Prob_Home"] = (df["Book_Prob_Home"] + (edge_home / 100)).clip(lower=0.01)
        df["Model_Prob_Draw"] = (df["Book_Prob_Draw"] + (edge_draw / 100)).clip(lower=0.01)
        df["Model_Prob_Away"] = (df["Book_Prob_Away"] + (edge_away / 100)).clip(lower=0.01)

        model_sum = df["Model_Prob_Home"] + df["Model_Prob_Draw"] + df["Model_Prob_Away"]
        df["Model_Prob_Home"] = df["Model_Prob_Home"] / model_sum
        df["Model_Prob_Draw"] = df["Model_Prob_Draw"] / model_sum
        df["Model_Prob_Away"] = df["Model_Prob_Away"] / model_sum

        # Fair odds en value volgens jouw formule per uitkomst.
        df["Fair_Odd_Home"] = (1 / df["Model_Prob_Home"]).round(2)
        df["Fair_Odd_Draw"] = (1 / df["Model_Prob_Draw"]).round(2)
        df["Fair_Odd_Away"] = (1 / df["Model_Prob_Away"]).round(2)

        df["Value_Home"] = (df["Model_Prob_Home"] * df["Odd_Home"] - 1).round(3)
        df["Value_Draw"] = (df["Model_Prob_Draw"] * df["Odd_Draw"] - 1).round(3)
        df["Value_Away"] = (df["Model_Prob_Away"] * df["Odd_Away"] - 1).round(3)
        df["Max_Value"] = df[["Value_Home", "Value_Draw", "Value_Away"]].max(axis=1)

        # Filter op minimale value
        filtered_df = df[df["Max_Value"] >= min_value].copy()

        # --- STATS SECTIE ---
        col1, col2, col3 = st.columns(3)
        col1.metric("Gevonden Wedstrijden", len(filtered_df))
        col2.metric(
            "Hoogste Value",
            f"{filtered_df['Max_Value'].max() * 100:.1f}%" if not filtered_df.empty else "n.v.t.",
        )
        col3.metric("Bookmaker", "Unibet")

        st.divider()

        # --- MAIN DASHBOARD ---
        st.subheader(f"Gedetailleerde Analyse: {selected_league}")

        # Styling van de tabel: highlight positieve value
        def highlight_value(val: float) -> str:
            color = "lightgreen" if val > 0.05 else "white"
            return f"background-color: {color}"

        if filtered_df.empty:
            st.warning("Geen wedstrijden gevonden met deze filters.")
        else:
            # Toon de data
            cols_to_show = [
                "Wedstrijd",
                "Starttijd",
                "Odd_Home",
                "Odd_Draw",
                "Odd_Away",
                "Model_Prob_Home",
                "Model_Prob_Draw",
                "Model_Prob_Away",
                "Value_Home",
                "Value_Draw",
                "Value_Away",
                "Max_Value",
            ]
            st.dataframe(
                filtered_df[cols_to_show].style.applymap(
                    highlight_value,
                    subset=["Value_Home", "Value_Draw", "Value_Away", "Max_Value"],
                ),
                use_container_width=True,
            )

            # Visualisatie van de kansen
            st.subheader("Kansverdeling Model (3-way)")
            fig = px.bar(
                filtered_df,
                x="Wedstrijd",
                y=["Model_Prob_Home", "Model_Prob_Draw", "Model_Prob_Away"],
                barmode="group",
                title="Winstkans volgens jouw model",
            )
            st.plotly_chart(fig, use_container_width=True)

st.divider()
st.subheader("Historische Resultaten")
if st.button("Update Historische Resultaten"):
    st.session_state["history_data"] = get_historical_results_v2(LEAGUE_CODES[league])
    st.session_state["history_league"] = league

df_history = st.session_state.get("history_data")
history_league = st.session_state.get("history_league", league)
if df_history is None:
    st.info("Klik op 'Update Historische Resultaten' om de laatste gespeelde duels te laden.")
elif df_history.empty:
    st.warning("Geen historische resultaten gevonden.")
else:
    st.write(f"Laatste resultaten {history_league}:")
    st.dataframe(df_history.tail(5), use_container_width=True)

# Voetnoot over spelers (Placeholder voor jouw volgende stap)
with st.expander("Bekijk Speler Impact"):
    st.write("Hier komt de data over geblesseerde spelers en hun invloed op de winstkans.")
    st.info("Opmerking: Haaland speelt niet bij Man City. Winstkans verlaagd met 4.2%.")
