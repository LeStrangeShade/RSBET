import streamlit as st
import pandas as pd
import requests
import os
import plotly.express as px

# --- CONFIGURATIE ---
st.set_page_config(page_title="Football Value Dashboard", layout="wide")

# --- API KEYS (via Streamlit secrets of environment) ---
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", os.getenv("ODDS_API_KEY", ""))
FOOTBALL_DATA_API_KEY = st.secrets.get("FOOTBALL_DATA_API_KEY", os.getenv("FOOTBALL_DATA_API_KEY", ""))
FOOTBALL_DATA_BASE_URL = "https://api.football-data.org/v4/"

SPORTS = {
    "Eredivisie":       "soccer_netherlands_eredivisie",
    "Champions League": "soccer_uefa_champs_league",
    "Premier League":   "soccer_epl",
    "La Liga":          "soccer_spain_la_liga",
    "Bundesliga":       "soccer_germany_bundesliga",
}

LEAGUE_CODES = {
    "Eredivisie":       "DED",
    "Champions League": "CL",
    "Premier League":   "PL",
    "La Liga":          "PD",
    "Bundesliga":       "BL1",
}

# --- ODDS API ---
def fetch_live_unibet_odds(sport: str):
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {
        "api_key": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "bookmakers": "unibet",
        "oddsFormat": "decimal",
    }
    try:
        r = requests.get(url, params=params, timeout=20)
    except requests.RequestException as exc:
        st.error(f"Netwerkfout: {exc}")
        return None

    if r.status_code != 200:
        st.error(f"Odds API fout {r.status_code}: {r.text[:300]}")
        return None

    data = r.json()
    if not data:
        st.warning("Geen aankomende wedstrijden gevonden. De ronde is waarschijnlijk al gespeeld.")
        return None
    return data


def process_odds_to_df(json_data) -> pd.DataFrame:
    matches = []
    for game in json_data:
        home_team = game.get("home_team")
        away_team = game.get("away_team")
        unibet = next((b for b in game.get("bookmakers", []) if b.get("key") == "unibet"), None)
        if not (home_team and away_team and unibet):
            continue
        outcomes = unibet.get("markets", [{}])[0].get("outcomes", [])
        by_name = {o.get("name"): o.get("price") for o in outcomes}
        odd_home = by_name.get(home_team)
        odd_away = by_name.get(away_team)
        odd_draw = by_name.get("Draw")
        if not (odd_home and odd_away and odd_draw):
            continue
        matches.append({
            "Wedstrijd":  f"{home_team} vs {away_team}",
            "Odd_Home":   odd_home,
            "Odd_Draw":   odd_draw,
            "Odd_Away":   odd_away,
            "Starttijd":  game.get("commence_time"),
        })
    return pd.DataFrame(matches)


# --- FOOTBALL-DATA.ORG ---
def get_historical_results(league_code: str = "DED") -> pd.DataFrame:
    if not FOOTBALL_DATA_API_KEY:
        st.warning("Geen FOOTBALL_DATA_API_KEY gevonden in secrets.")
        return pd.DataFrame()

    url = f"{FOOTBALL_DATA_BASE_URL}competitions/{league_code}/matches"
    headers = {"X-Auth-Token": FOOTBALL_DATA_API_KEY}
    try:
        r = requests.get(url, headers=headers, params={"status": "FINISHED"}, timeout=20)
    except requests.RequestException as exc:
        st.error(f"Netwerkfout: {exc}")
        return pd.DataFrame()

    if r.status_code == 404:
        st.error(f"Competitiecode '{league_code}' niet gevonden (404).")
        return pd.DataFrame()
    if r.status_code != 200:
        st.error(f"Football-data fout {r.status_code}: {r.text[:300]}")
        return pd.DataFrame()

    results = []
    for m in r.json().get("matches", []):
        winner_raw = m.get("score", {}).get("winner")
        winner = {"HOME_TEAM": "Home", "AWAY_TEAM": "Away"}.get(winner_raw, "Draw")
        results.append({
            "Datum":      m.get("utcDate"),
            "Home":       m.get("homeTeam", {}).get("name"),
            "Away":       m.get("awayTeam", {}).get("name"),
            "Home_Goals": m.get("score", {}).get("fullTime", {}).get("home"),
            "Away_Goals": m.get("score", {}).get("fullTime", {}).get("away"),
            "Winner":     winner,
        })

    df = pd.DataFrame(results)
    if not df.empty:
        df["Datum"] = pd.to_datetime(df["Datum"], errors="coerce")
        df = df.sort_values("Datum")
    return df


# --- UI ---
st.title("? Football Analytics & Value Finder")
st.markdown("Bron: *The Odds API* (live odds) + *football-data.org* (historisch)")

st.sidebar.header("Filters")
league      = st.sidebar.selectbox("Competitie", list(SPORTS.keys()))
min_value   = st.sidebar.slider("Minimale Value", 0.0, 0.5, 0.05, step=0.01)
edge_home   = st.sidebar.slider("Model edge Home (%)", -10.0, 10.0, 2.0, step=0.5)
edge_draw   = st.sidebar.slider("Model edge Draw (%)", -10.0, 10.0, 0.0, step=0.5)
edge_away   = st.sidebar.slider("Model edge Away (%)", -10.0, 10.0, -2.0, step=0.5)

# ---- LIVE ODDS ----
st.subheader("Live Unibet Odds")
if st.button("Update Live Odds"):
    if not ODDS_API_KEY:
        st.error("Geen ODDS_API_KEY in secrets.")
    else:
        st.session_state["raw_data"]        = fetch_live_unibet_odds(SPORTS[league])
        st.session_state["selected_league"] = league

raw_data        = st.session_state.get("raw_data")
selected_league = st.session_state.get("selected_league", league)

if not raw_data:
    st.info("Klik op 'Update Live Odds' om odds op te halen.")
else:
    df = process_odds_to_df(raw_data)
    if df.empty:
        st.warning("Geen Unibet odds beschikbaar voor deze competitie.")
    else:
        # Implied kansen normaliseren
        for col, odd in [("Implied_Home", "Odd_Home"), ("Implied_Draw", "Odd_Draw"), ("Implied_Away", "Odd_Away")]:
            df[col] = 1 / df[odd]
        implied_sum = df["Implied_Home"] + df["Implied_Draw"] + df["Implied_Away"]
        for col, imp in [("Book_Prob_Home", "Implied_Home"), ("Book_Prob_Draw", "Implied_Draw"), ("Book_Prob_Away", "Implied_Away")]:
            df[col] = df[imp] / implied_sum

        # Modelkansen met edge + hernormaliseren
        df["Model_Prob_Home"] = (df["Book_Prob_Home"] + edge_home / 100).clip(lower=0.01)
        df["Model_Prob_Draw"] = (df["Book_Prob_Draw"] + edge_draw / 100).clip(lower=0.01)
        df["Model_Prob_Away"] = (df["Book_Prob_Away"] + edge_away / 100).clip(lower=0.01)
        msum = df["Model_Prob_Home"] + df["Model_Prob_Draw"] + df["Model_Prob_Away"]
        df["Model_Prob_Home"] /= msum
        df["Model_Prob_Draw"] /= msum
        df["Model_Prob_Away"] /= msum

        # Value berekening
        df["Value_Home"] = (df["Model_Prob_Home"] * df["Odd_Home"] - 1).round(3)
        df["Value_Draw"] = (df["Model_Prob_Draw"] * df["Odd_Draw"] - 1).round(3)
        df["Value_Away"] = (df["Model_Prob_Away"] * df["Odd_Away"] - 1).round(3)
        df["Max_Value"]  = df[["Value_Home", "Value_Draw", "Value_Away"]].max(axis=1)

        # Beste bet kolom
        best_map = {0: "Home", 1: "Draw", 2: "Away"}
        df["Beste Bet"] = df[["Value_Home", "Value_Draw", "Value_Away"]].idxmax(axis=1).map({
            "Value_Home": "? Home", "Value_Draw": "? Draw", "Value_Away": "? Away"
        })
        df.loc[df["Max_Value"] <= 0.05, "Beste Bet"] = "? Overslaan"

        filtered = df[df["Max_Value"] >= min_value].copy()

        col1, col2, col3 = st.columns(3)
        col1.metric("Wedstrijden", len(filtered))
        col2.metric("Hoogste Value", f"{filtered['Max_Value'].max() * 100:.1f}%" if not filtered.empty else "n.v.t.")
        col3.metric("Bookmaker", "Unibet")

        st.divider()
        st.subheader(f"Analyse: {selected_league}")

        def highlight_value(val):
            return "background-color: lightgreen" if val > 0.05 else "background-color: white"

        if filtered.empty:
            st.warning("Geen wedstrijden boven de value-drempel.")
        else:
            cols = ["Wedstrijd", "Starttijd", "Odd_Home", "Odd_Draw", "Odd_Away",
                    "Model_Prob_Home", "Model_Prob_Draw", "Model_Prob_Away",
                    "Value_Home", "Value_Draw", "Value_Away", "Max_Value", "Beste Bet"]
            st.dataframe(
                filtered[cols].style.applymap(highlight_value, subset=["Value_Home", "Value_Draw", "Value_Away", "Max_Value"]),
                use_container_width=True,
            )

            fig = px.bar(filtered, x="Wedstrijd",
                         y=["Model_Prob_Home", "Model_Prob_Draw", "Model_Prob_Away"],
                         barmode="group", title="Modelkansen per wedstrijd")
            st.plotly_chart(fig, use_container_width=True)

# ---- HISTORISCHE DATA ----
st.divider()
st.subheader("Historische Resultaten")
if st.button("Update Historische Resultaten"):
    st.session_state["history_data"]   = get_historical_results(LEAGUE_CODES[league])
    st.session_state["history_league"] = league

df_history     = st.session_state.get("history_data")
history_league = st.session_state.get("history_league", league)

if df_history is None:
    st.info("Klik op 'Update Historische Resultaten' om data te laden.")
elif df_history.empty:
    st.warning("Geen historische resultaten gevonden.")
else:
    st.write(f"Laatste 5 resultaten - {history_league}:")
    st.dataframe(df_history.tail(5), use_container_width=True)

# ---- SPELER IMPACT ----
with st.expander("?? Speler Impact"):
    st.write("Hier komt de data over geblesseerde spelers en hun invloed op de winstkans.")
    st.info("Voorbeeld: Haaland speelt niet ? winstkans Man City verlaagd met 4.2%.")
