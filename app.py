# -*- coding: utf-8 -*-
import streamlit as st
import pandas as pd
import requests
import plotly.express as px

# --- CONFIGURATIE ---
st.set_page_config(page_title="Eredivisie Smart Bet Analyzer", layout="wide")

# --- API KEYS ---
FOOTBALL_API_KEY = st.secrets.get("FOOTBALL_API_KEY", st.secrets.get("FOOTBALL_DATA_API_KEY", ""))
ODDS_API_KEY = st.secrets.get("ODDS_API_KEY", "")


@st.cache_data(ttl=3600)
def get_historical_stats(league_code="DED"):
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
    data = []
    for m in res.json().get("matches", []):
        data.append({
            "Home":      m["homeTeam"]["name"],
            "Away":      m["awayTeam"]["name"],
            "HomeGoals": m["score"]["fullTime"]["home"],
            "AwayGoals": m["score"]["fullTime"]["away"],
            "Winner":    m["score"]["winner"],
        })
    return pd.DataFrame(data)


def calculate_probabilities(df, home_team, away_team):
    home_games = df[df["Home"] == home_team]
    away_games = df[df["Away"] == away_team]
    if len(home_games) >= 3:
        prob_home = len(home_games[home_games["Winner"] == "HOME_TEAM"]) / len(home_games)
    else:
        prob_home = 0.40
    if len(away_games) >= 3:
        prob_away = len(away_games[away_games["Winner"] == "AWAY_TEAM"]) / len(away_games)
    else:
        prob_away = 0.30
    prob_draw = max(1 - prob_home - prob_away, 0.05)
    total = prob_home + prob_draw + prob_away
    return {
        "home": round(prob_home / total, 3),
        "draw": round(prob_draw / total, 3),
        "away": round(prob_away / total, 3),
    }


@st.cache_data(ttl=600)
def get_unibet_odds(sport="soccer_netherlands_eredivisie"):
    if not ODDS_API_KEY:
        st.error("Geen ODDS_API_KEY gevonden in secrets.")
        return []
    url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
    params = {"api_key": ODDS_API_KEY, "regions": "eu", "markets": "h2h",
              "bookmakers": "unibet", "oddsFormat": "decimal"}
    res = requests.get(url, params=params, timeout=20)
    if res.status_code != 200:
        st.error(f"Odds API fout {res.status_code}: {res.text[:300]}")
        return []
    data = res.json()
    if not data:
        st.warning("Geen aankomende wedstrijden gevonden. De ronde is waarschijnlijk al gespeeld.")
    return data


@st.cache_data(ttl=3600)
def get_top_scorers(league_code="DED"):
    if not FOOTBALL_API_KEY:
        return {}
    url = f"https://api.football-data.org/v4/competitions/{league_code}/scorers"
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    res = requests.get(url, headers=headers, timeout=20)
    if res.status_code != 200:
        return {}
    scorer_dict = {}
    for s in res.json().get("scorers", []):
        team_name   = s["team"]["name"]
        player_name = s["player"]["name"]
        goals       = s.get("numberOfGoals", s.get("goals", 0))
        scorer_dict[team_name] = {"name": player_name, "goals": goals}
    return scorer_dict


# --- UI ---
st.title("Eredivisie Smart Bet Analyzer")
st.markdown("**Bron:** football-data.org (historie) + The Odds API (live Unibet odds)")

SPORTS_MAP = {
    "Eredivisie":       ("DED", "soccer_netherlands_eredivisie"),
    "Premier League":   ("PL",  "soccer_epl"),
    "La Liga":          ("PD",  "soccer_spain_la_liga"),
    "Champions League": ("CL",  "soccer_uefa_champs_league"),
    "Bundesliga":       ("BL1", "soccer_germany_bundesliga"),
}

st.sidebar.header("Instellingen")
league      = st.sidebar.selectbox("Competitie", list(SPORTS_MAP.keys()))
min_edge    = st.sidebar.slider("Minimale Edge voor VALUE", 0.0, 0.3, 0.05, step=0.01)
run_analyse = st.sidebar.button("Start Analyse")

league_code, sport_key = SPORTS_MAP[league]

if run_analyse:
    with st.spinner("Data ophalen en berekenen..."):
        df_hist     = get_historical_stats(league_code)
        live_odds   = get_unibet_odds(sport_key)
        top_scorers = get_top_scorers(league_code)

    if df_hist.empty:
        st.error("Geen historische data geladen. Controleer je FOOTBALL_API_KEY.")
        st.stop()

    results = []
    match_details = []
    for match in live_odds:
        home = match.get("home_team")
        away = match.get("away_team")
        unibet_data = next((b for b in match.get("bookmakers", []) if b.get("key") == "unibet"), None)
        if not unibet_data:
            continue
        outcomes  = unibet_data["markets"][0]["outcomes"]
        by_name   = {o["name"]: o["price"] for o in outcomes}
        unibet_home = by_name.get(home)
        unibet_draw = by_name.get("Draw")
        unibet_away = by_name.get(away)
        if not (unibet_home and unibet_away):
            continue

        probs     = calculate_probabilities(df_hist, home, away)
        fair_home = round(1 / probs["home"], 2) if probs["home"] > 0 else None
        fair_draw = round(1 / probs["draw"], 2) if probs["draw"] > 0 else None
        fair_away = round(1 / probs["away"], 2) if probs["away"] > 0 else None

        # Edge = (Unibet Odd / Fair Odd) - 1
        edge_home = round((unibet_home / fair_home) - 1, 3) if fair_home else 0
        edge_draw = round(((unibet_draw or 0) / fair_draw) - 1, 3) if fair_draw and unibet_draw else 0
        edge_away = round((unibet_away / fair_away) - 1, 3) if fair_away else 0
        max_edge  = max(edge_home, edge_draw, edge_away)
        beste_bet = "Home" if max_edge == edge_home else ("Draw" if max_edge == edge_draw else "Away")

        results.append({
            "Wedstrijd":       f"{home} vs {away}",
            "Starttijd":       match.get("commence_time", "")[:16].replace("T", " "),
            "Unibet Home":     unibet_home,
            "Unibet Draw":     unibet_draw,
            "Unibet Away":     unibet_away,
            "Model Kans Home": f"{probs['home']:.0%}",
            "Model Kans Draw": f"{probs['draw']:.0%}",
            "Model Kans Away": f"{probs['away']:.0%}",
            "Fair Odd Home":   fair_home,
            "Edge Home":       edge_home,
            "Edge Draw":       edge_draw,
            "Edge Away":       edge_away,
            "Max Edge":        max_edge,
            "Beste Bet":       beste_bet,
            "Status":          "VALUE" if max_edge > min_edge else "Geen value",
        })
        match_details.append({
            "home":        home,
            "away":        away,
            "probs":       probs,
            "unibet_home": unibet_home,
            "unibet_away": unibet_away,
            "edge_home":   edge_home,
            "edge_away":   edge_away,
            "fair_home":   fair_home,
            "fair_away":   fair_away,
        })

    if not results:
        st.warning("Geen aankomende wedstrijden met Unibet odds gevonden.")
        st.stop()

    res_df = pd.DataFrame(results)
    value_bets = res_df[res_df["Status"] == "VALUE"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Totaal wedstrijden", len(res_df))
    c2.metric("Value bets gevonden", len(value_bets))
    c3.metric("Hoogste Edge", f"{res_df['Max Edge'].max():.1%}")

    st.divider()
    st.subheader("Overzicht alle wedstrijden")

    def highlight_status(val):
        if val == "VALUE":
            return "background-color: #2ecc71; color: black; font-weight: bold"
        return "background-color: #e74c3c; color: white"

    def highlight_edge(val):
        try:
            return "background-color: lightgreen" if float(val) > min_edge else ""
        except (ValueError, TypeError):
            return ""

    st.dataframe(
        res_df.style
            .applymap(highlight_status, subset=["Status"])
            .applymap(highlight_edge, subset=["Edge Home", "Edge Draw", "Edge Away", "Max Edge"]),
        use_container_width=True,
    )

    st.subheader("Edge per wedstrijd")
    fig = px.bar(res_df, x="Wedstrijd", y=["Edge Home", "Edge Draw", "Edge Away"],
                 barmode="group",
                 color_discrete_map={"Edge Home": "#3498db", "Edge Draw": "#f39c12", "Edge Away": "#e74c3c"},
                 title=f"Gevonden edge t.o.v. Unibet - {league}")
    fig.add_hline(y=min_edge, line_dash="dash", line_color="green",
                  annotation_text=f"Value drempel ({min_edge:.0%})")
    st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("🔍 Speler Impact per wedstrijd")
    st.caption("Zet de toggle aan als de topscorer afwezig is. De edge wordt automatisch herberekend (−10%).")

    for md in match_details:
        h, a = md["home"], md["away"]
        star_home  = top_scorers.get(h)
        star_away  = top_scorers.get(a)
        label_home = f"{star_home['name']} ({star_home['goals']} goals)" if star_home else "Onbekend"
        label_away = f"{star_away['name']} ({star_away['goals']} goals)" if star_away else "Onbekend"

        with st.expander(f"📋 {h} vs {a}"):
            col1, col2 = st.columns(2)

            with col1:
                st.markdown(f"**Topscorer {h}:** {label_home}")
                missing_home = st.checkbox(
                    f"Afwezig: {star_home['name'].split()[0] if star_home else 'speler'}?",
                    key=f"miss_home_{h}",
                )
                prob_home = md["probs"]["home"]
                if missing_home:
                    prob_home *= 0.90
                    st.warning(f"Kans thuis verlaagd naar {prob_home:.0%}")
                adj_fair_home = 1 / prob_home if prob_home > 0 else None
                adj_edge_home = round((md["unibet_home"] / adj_fair_home) - 1, 3) if adj_fair_home and md["unibet_home"] else 0
                st.metric("Aangepaste Edge Thuis", f"{adj_edge_home:.1%}", delta=f"{adj_edge_home - md['edge_home']:+.1%}")

            with col2:
                st.markdown(f"**Topscorer {a}:** {label_away}")
                missing_away = st.checkbox(
                    f"Afwezig: {star_away['name'].split()[0] if star_away else 'speler'}?",
                    key=f"miss_away_{a}",
                )
                prob_away = md["probs"]["away"]
                if missing_away:
                    prob_away *= 0.90
                    st.warning(f"Kans uit verlaagd naar {prob_away:.0%}")
                adj_fair_away = 1 / prob_away if prob_away > 0 else None
                adj_edge_away = round((md["unibet_away"] / adj_fair_away) - 1, 3) if adj_fair_away and md["unibet_away"] else 0
                st.metric("Aangepaste Edge Uit", f"{adj_edge_away:.1%}", delta=f"{adj_edge_away - md['edge_away']:+.1%}")

    with st.expander("Bekijk historische data"):
        st.dataframe(df_hist.tail(10), use_container_width=True)

else:
    st.info("Selecteer een competitie en klik op **Start Analyse** in de sidebar.")
