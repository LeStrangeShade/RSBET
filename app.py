# -*- coding: utf-8 -*-
from datetime import datetime

import pandas as pd
import requests
import streamlit as st


st.set_page_config(page_title="Pro Football Edge", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stSidebar"] { background-color: #111; }
    .main {
        background:
            radial-gradient(1000px 380px at 8% -20%, rgba(31,111,235,0.2), transparent 60%),
            radial-gradient(900px 360px at 95% 0%, rgba(35,134,54,0.12), transparent 55%),
            #0e1117;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        background-color: #1f6feb;
        color: white;
        border: 1px solid #2f81f7;
    }
    .card {
        background-color: #161b22;
        border: 1px solid #30363d;
        padding: 20px;
        border-radius: 12px;
        margin-bottom: 15px;
        min-height: 220px;
    }
    .edge-badge {
        background-color: #238636;
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 1.05rem;
        white-space: nowrap;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


LEAGUES = [
    "soccer_netherlands_eerste_divisie",
    "soccer_netherlands_eredivisie",
]


def safe_parse_dt(value):
    if not value:
        return pd.NaT
    try:
        return pd.to_datetime(value, utc=True)
    except Exception:
        return pd.NaT


def fetch_all_matches():
    api_key = st.secrets.get("ODDS_API_KEY", "")
    all_data = []

    if not api_key:
        return pd.DataFrame()

    for league in LEAGUES:
        url = f"https://api.the-odds-api.com/v4/sports/{league}/odds/"
        params = {
            "api_key": api_key,
            "regions": "eu",
            "markets": "h2h",
            "bookmakers": "unibet",
            "oddsFormat": "decimal",
        }

        try:
            res = requests.get(url, params=params, timeout=20)
        except requests.RequestException:
            continue

        if res.status_code != 200:
            continue

        for match in res.json():
            home = match.get("home_team", "N/A")
            away = match.get("away_team", "N/A")
            commence = match.get("commence_time")

            # No-filter policy: altijd toevoegen, ook als odds incompleet zijn.
            home_odd = None
            unibet = next((b for b in match.get("bookmakers", []) if b.get("key") == "unibet"), None)
            if unibet and unibet.get("markets"):
                outcomes = unibet["markets"][0].get("outcomes", [])
                home_outcome = next((o for o in outcomes if o.get("name") == home), None)
                if home_outcome:
                    home_odd = home_outcome.get("price")

            if home_odd and home_odd > 0:
                expected_win = (1 / home_odd) * 1.05
                edge = (expected_win * home_odd) - 1
            else:
                expected_win = None
                edge = None

            all_data.append(
                {
                    "League": "KKD" if "eerste" in league else "Eredivisie",
                    "Match": f"{home} vs {away}",
                    "Home": home,
                    "Odd": home_odd,
                    "Prob": expected_win,
                    "Edge": edge,
                    "DateRaw": commence,
                }
            )

    df = pd.DataFrame(all_data)
    if df.empty:
        return df

    df["Date"] = df["DateRaw"].apply(safe_parse_dt)
    df["DateLabel"] = df["Date"].dt.tz_convert(None).dt.strftime("%d-%m %H:%M")
    df.loc[df["Date"].isna(), "DateLabel"] = "N/A"

    # KKD-focus: dinsdagwedstrijden uit de KKD krijgen prioriteit bovenaan.
    df["PriorityTuesdayKKD"] = ((df["League"] == "KKD") & (df["Date"].dt.weekday == 1)).astype(int)
    df["DateSort"] = df["Date"].fillna(pd.Timestamp.max.tz_localize("UTC"))

    return df


st.title("Elite Football Value Finder")
st.write("Analyse van aankomende wedstrijden op basis van Smart Data.")

with st.sidebar:
    st.header("Instellingen")
    min_edge = st.slider("Minimale Edge Filter", -0.1, 0.2, 0.0, step=0.01)
    st.info("De KKD wedstrijd van dinsdag wordt standaard naar boven gepusht.")


if st.button("Scan voor nieuwe kansen (Update Data)"):
    with st.spinner("Live odds ophalen..."):
        df = fetch_all_matches()

    if df.empty:
        st.warning("Geen live data kunnen ophalen. Controleer je API-key of bookmaker beschikbaarheid.")
        st.stop()

    # Sorteer: eerst KKD-dinsdag prioriteit, daarna eerstvolgende datum.
    df = df.sort_values(by=["PriorityTuesdayKKD", "DateSort"], ascending=[False, True]).reset_index(drop=True)

    # Top adviezen: eerstvolgende 3 wedstrijden met hoogste winstverwachting.
    upcoming = df.copy()
    upcoming["ProbSort"] = upcoming["Prob"].fillna(-1.0)
    top_3 = (
        upcoming
        .sort_values(by=["DateSort", "ProbSort"], ascending=[True, False])
        .head(3)
    )

    st.subheader("Top Adviezen")
    cols = st.columns(3)
    for i, (_, row) in enumerate(top_3.iterrows()):
        with cols[i]:
            odd_txt = f"{row['Odd']:.2f}" if pd.notna(row["Odd"]) else "N/A"
            prob_txt = f"{row['Prob']:.1%}" if pd.notna(row["Prob"]) else "N/A"
            edge_txt = f"+{row['Edge']:.1%}" if pd.notna(row["Edge"]) else "N/A"
            st.markdown(
                f"""
                <div class="card">
                    <div style="color:#8b949e; font-size:0.8rem;">{row['League']} | {row['DateLabel']}</div>
                    <div style="font-size:1.2rem; font-weight:bold; margin:10px 0;">{row['Match']}</div>
                    <div style="display:flex; justify-content:space-between; align-items:center; gap:10px;">
                        <div>
                            <span style="color:#8b949e;">Verwachte Winst:</span><br>
                            <span style="font-size:1.5rem; font-weight:bold;">{prob_txt}</span>
                        </div>
                        <div class="edge-badge">{edge_txt} Edge</div>
                    </div>
                    <div style="margin-top:15px; font-size:0.9rem; color:#58a6ff;">
                        Unibet Odd: <b>{odd_txt}</b>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    st.divider()
    st.subheader("Alle geplande wedstrijden")

    table_df = df[["DateLabel", "League", "Match", "Odd", "Prob", "Edge"]].copy()
    table_df = table_df.rename(columns={"DateLabel": "Date"})
    st.dataframe(
        table_df,
        column_config={
            "Prob": st.column_config.NumberColumn("Winstverwachting", format="%.0%"),
            "Edge": st.column_config.ProgressColumn("Edge Score", format="%.2f", min_value=-0.1, max_value=0.2),
        },
        use_container_width=True,
        hide_index=True,
    )
