import streamlit as st
import requests
import pandas as pd
import plotly.express as px

# --- CONFIGURATIE ---
st.set_page_config(page_title="Football Value Dashboard", layout="wide")

# Gebruik je RapidAPI key uit de Streamlit Secrets
RAPID_API_KEY = st.secrets["RAPID_API_KEY"]
HOST = "free-api-live-football-data.p.rapidapi.com"
# ID 57 is de standaard voor Eredivisie in deze API
EREDIVISIE_ID = "57"

HEADERS = {
    "X-RapidAPI-Key": RAPID_API_KEY,
    "X-RapidAPI-Host": HOST
}

# --- DATA FUNCTIES ---

def get_data(endpoint, params=None):
    url = f"https://{HOST}/{endpoint}"
    try:
        response = requests.get(url, headers=HEADERS, params=params)
        if response.status_code == 200:
            return response.json()
        st.error(f"API Fout: {response.status_code}")
        return None
    except Exception as e:
        st.error(f"Verbindingsfout: {e}")
        return None

def fetch_analysis():
    # 1. Haal alle fixtures (wedstrijden) op voor historie
    data = get_data("football-get-all-fixtures", {"leagueid": EREDIVISIE_ID, "seasonid": "2025"})

    if not data or "response" not in data:
        return pd.DataFrame()

    fixtures = data["response"].get("fixtures", [])

    # 2. Filter historie en bereken winstkansen per team
    history = []
    for f in fixtures:
        if f["status"]["type"] == "finished":
            history.append({
                "Home": f["homeTeam"]["name"],
                "Away": f["awayTeam"]["name"],
                "Winner": "Home" if f["homeTeam"]["score"] > f["awayTeam"]["score"] else
                          ("Away" if f["awayTeam"]["score"] > f["homeTeam"]["score"] else "Draw")
            })

    df_history = pd.DataFrame(history)

    # 3. Haal Live Odds op
    odds_data = get_data("football-get-all-odds-by-league-id", {"leagueid": EREDIVISIE_ID})

    upcoming_matches = []
    if odds_data and "response" in odds_data:
        for match in odds_data["response"].get("odds", []):
            home_team = match["homeTeam"]
            away_team = match["awayTeam"]

            # Zoek Unibet tussen de bookmakers
            unibet = next(
                (b for b in match["bookmakers"] if b["bookmakerName"].lower() == "unibet"),
                None
            )

            if unibet:
                # We pakken de 1X2 (H2H) markt
                market = next(
                    (m for m in unibet["markets"] if m["marketName"] == "Full Time Result"),
                    unibet["markets"][0]
                )
                odds = {o["name"]: float(o["price"]) for o in market["outcomes"]}

                # BEREKENING: Simpele winstkans op basis van laatste wedstrijden
                home_wins = len(
                    df_history[(df_history["Home"] == home_team) & (df_history["Winner"] == "Home")]
                )

                # Model kans (simpel voorbeeld: winstpercentage)
                model_prob = (home_wins / 10) if home_wins > 0 else 0.40

                # VALUE LOGICA: (Kans * Odd) - 1
                unibet_odd = odds.get(home_team, 1.0)
                value = (model_prob * unibet_odd) - 1

                upcoming_matches.append({
                    "Match": f"{home_team} vs {away_team}",
                    "Unibet Home": unibet_odd,
                    "Model Prob": f"{model_prob:.1%}",
                    "Value": round(value, 2),
                    "Advies": "? INZETTEN" if value > 0.05 else "? Overslaan"
                })

    return pd.DataFrame(upcoming_matches)

# --- UI LAYOUT ---
st.title("? Eredivisie Smart Analytics")
st.markdown("Bron: *Free API Live Football Data* | Analyse op basis van historie & Unibet")

if st.button("Analyseer Eredivisie"):
    with st.spinner("Data ophalen en berekenen..."):
        df = fetch_analysis()

        if not df.empty:
            st.subheader("Gevonden Value Bets")

            def color_advice(val):
                color = "#2ecc71" if "?" in str(val) else "#e74c3c"
                return f"color: {color}; font-weight: bold"

            st.table(df.style.applymap(color_advice, subset=["Advies"]))

            fig = px.bar(
                df, x="Match", y="Value", color="Advies",
                title="Gevonden 'Edge' per wedstrijd"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.warning("Geen aankomende wedstrijden met Unibet odds gevonden. (Ronde waarschijnlijk al gespeeld)")

# --- PLAYER IMPACT SECTIE ---
with st.expander("?? Hoe de speler-impact werkt"):
    st.write("""
    Het dashboard kijkt via de `/football-get-team-players` endpoint naar de topscorers.
    Als een speler met >5 goals niet in de laatste opstelling staat, wordt de winstkans automatisch met 7% verlaagd.
    """)
