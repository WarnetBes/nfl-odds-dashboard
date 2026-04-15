import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Sports Odds Dashboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_URL = "https://api.the-odds-api.com/v4"

# Sport catalogue
SPORTS_CATALOGUE = {
    "🏈 NFL": {
        "key": "americanfootball_nfl",
        "has_draw": False,
        "markets": ["H2H (Moneyline)", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#00b4d8",
        "emoji": "🏈",
    },
    "⚽ EPL (English Premier League)": {
        "key": "soccer_epl",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#4ade80",
        "emoji": "⚽",
    },
    "⚽ La Liga (Spain)": {
        "key": "soccer_spain_la_liga",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#4ade80",
        "emoji": "⚽",
    },
    "⚽ Bundesliga (Germany)": {
        "key": "soccer_germany_bundesliga",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#4ade80",
        "emoji": "⚽",
    },
    "⚽ Serie A (Italy)": {
        "key": "soccer_italy_serie_a",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#4ade80",
        "emoji": "⚽",
    },
    "⚽ Ligue 1 (France)": {
        "key": "soccer_france_ligue_one",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#4ade80",
        "emoji": "⚽",
    },
    "⚽ UEFA Champions League": {
        "key": "soccer_uefa_champs_league",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#facc15",
        "emoji": "⚽",
    },
    "⚽ UEFA Europa League": {
        "key": "soccer_uefa_europa_league",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#f97316",
        "emoji": "⚽",
    },
    "⚽ MLS (USA)": {
        "key": "soccer_usa_mls",
        "has_draw": True,
        "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#4ade80",
        "emoji": "⚽",
    },
    "🏀 NBA": {
        "key": "basketball_nba",
        "has_draw": False,
        "markets": ["H2H (Moneyline)", "Spreads (Handicap)", "Totals (Over/Under)"],
        "color": "#f97316",
        "emoji": "🏀",
    },
}

MARKET_KEY_MAP = {
    "H2H (Moneyline)": "h2h",
    "H2H / 1X2": "h2h",
    "Spreads (Handicap)": "spreads",
    "Totals (Over/Under)": "totals",
}

REGION_MAP = {
    "US (DraftKings, FanDuel…)": "us",
    "US Extended (PointsBet…)": "us2",
    "UK": "uk",
    "EU (Pinnacle, Unibet…)": "eu",
    "UK + EU": "uk,eu",
    "Все регионы": "us,us2,uk,eu",
}

US_BOOKMAKERS  = ["DraftKings","FanDuel","BetMGM","Caesars","BetOnline.ag","William Hill US",
                  "BetRivers","Bovada","PointsBet US","Barstool"]
EU_BOOKMAKERS  = ["Betfair","Unibet","Paddy Power","Bet365","Sky Bet","Ladbrokes",
                  "Coral","Betway","888sport","Pinnacle","1xBet"]

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def american_to_decimal(american: float) -> float:
    if american >= 0:
        return round(american / 100 + 1, 4)
    return round(100 / abs(american) + 1, 4)

def decimal_to_implied(d: float) -> float:
    return round(1 / d * 100, 2) if d > 0 else 0.0

def no_vig_prob(probs: list) -> list:
    total = sum(probs)
    return [round(p / total * 100, 2) for p in probs] if total else probs

def ev_edge(fair_prob: float, decimal_odds: float) -> float:
    return round(fair_prob / 100 * decimal_odds - 1, 4)

def fmt_american(v) -> str:
    try:
        f = float(v)
        return f"+{int(f)}" if f >= 0 else str(int(f))
    except Exception:
        return str(v)

def local_time(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.astimezone(pytz.timezone("Europe/Moscow")).strftime("%d.%m %H:%M МСК")
    except Exception:
        return iso_str

def get_odds(api_key: str, sport_key: str, regions: str, market_key: str):
    r = requests.get(
        f"{BASE_URL}/sports/{sport_key}/odds",
        params=dict(apiKey=api_key, regions=regions, markets=market_key,
                    oddsFormat="american", dateFormat="iso"),
        timeout=15,
    )
    remaining = r.headers.get("x-requests-remaining", "?")
    used      = r.headers.get("x-requests-used", "?")
    if r.status_code == 200:
        return r.json(), remaining, used
    elif r.status_code == 401:
        st.error("❌ Неверный API ключ. Получи бесплатный: https://the-odds-api.com")
    elif r.status_code == 422:
        st.error("❌ Неверные параметры запроса.")
    elif r.status_code == 429:
        st.error("❌ Лимит API исчерпан.")
    else:
        st.error(f"❌ Ошибка {r.status_code}: {r.text[:200]}")
    return None, None, None


def parse_to_df(events: list, market_key: str, has_draw: bool) -> pd.DataFrame:
    rows = []
    for ev in events:
        home = ev["home_team"]
        away = ev["away_team"]
        t    = local_time(ev.get("commence_time", ""))
        for bm in ev.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                if mkt["key"] != market_key:
                    continue
                oc = {o["name"]: o for o in mkt["outcomes"]}
                base = {"Матч": f"{away} @ {home}", "Время": t,
                        "Букмекер": bm.get("title", bm["key"]),
                        "Хозяева": home, "Гости": away,
                        "_event_id": ev["id"]}
                if market_key == "h2h":
                    row = {**base,
                           "Odds Хозяева (Am)": oc.get(home, {}).get("price"),
                           "Odds Гости (Am)":   oc.get(away, {}).get("price"),
                           "Odds Ничья (Am)":   oc.get("Draw", {}).get("price") if has_draw else None}
                elif market_key == "spreads":
                    ho = oc.get(home, {})
                    ao = oc.get(away, {})
                    row = {**base,
                           "Спред Хозяева": ho.get("point"),
                           "Odds Хозяева (Am)": ho.get("price"),
                           "Спред Гости": ao.get("point"),
                           "Odds Гости (Am)": ao.get("price")}
                elif market_key == "totals":
                    ov = next((o for o in mkt["outcomes"] if o["name"] == "Over"), {})
                    un = next((o for o in mkt["outcomes"] if o["name"] == "Under"), {})
                    row = {**base,
                           "Тотал Линия": ov.get("point"),
                           "Odds Over (Am)": ov.get("price"),
                           "Odds Under (Am)": un.get("price")}
                else:
                    continue
                rows.append(row)
    return pd.DataFrame(rows)


def compute_value_bets(df: pd.DataFrame, has_draw: bool, min_edge_pct: float) -> pd.DataFrame:
    rows = []
    for _, r in df.iterrows():
        h_am = r.get("Odds Хозяева (Am)")
        a_am = r.get("Odds Гости (Am)")
        if h_am is None or a_am is None or str(h_am) == "nan" or str(a_am) == "nan":
            continue
        try:
            h_dec = american_to_decimal(float(h_am))
            a_dec = american_to_decimal(float(a_am))
            h_impl = decimal_to_implied(h_dec)
            a_impl = decimal_to_implied(a_dec)
            d_am = r.get("Odds Ничья (Am)")
            if has_draw and d_am and str(d_am) != "nan":
                d_dec  = american_to_decimal(float(d_am))
                d_impl = decimal_to_implied(d_dec)
                nv = no_vig_prob([h_impl, a_impl, d_impl])
                outcomes = [(r["Хозяева"], h_dec, h_impl, nv[0], fmt_american(h_am)),
                            (r["Гости"],   a_dec, a_impl, nv[1], fmt_american(a_am)),
                            ("Ничья",      d_dec, d_impl, nv[2], fmt_american(d_am))]
            else:
                nv = no_vig_prob([h_impl, a_impl])
                outcomes = [(r["Хозяева"], h_dec, h_impl, nv[0], fmt_american(h_am)),
                            (r["Гости"],   a_dec, a_impl, nv[1], fmt_american(a_am))]
            for name, dec, impl, fair, am_str in outcomes:
                edge = ev_edge(fair, dec) * 100
                if edge >= min_edge_pct:
                    rows.append({
                        "Матч":           r["Матч"],
                        "Время":          r["Время"],
                        "Букмекер":       r["Букмекер"],
                        "Исход":          f"✅ {name}",
                        "Odds (Am)":      am_str,
                        "Odds (Dec)":     dec,
                        "Implied %":      f"{impl}%",
                        "No-Vig Fair %":  f"{fair}%",
                        "EV Edge %":      f"+{edge:.2f}%",
                        "_edge":          edge,
                    })
        except Exception:
            continue
    if rows:
        vdf = pd.DataFrame(rows).sort_values("_edge", ascending=False).reset_index(drop=True)
        vdf.index += 1
        return vdf.drop(columns=["_edge"])
    return pd.DataFrame()


# ─────────────────────────────────────────────
#  DEMO DATA
# ─────────────────────────────────────────────
def make_demo(sport_key: str, has_draw: bool) -> list:
    if sport_key == "americanfootball_nfl":
        return [
            {"id":"d1","sport_key":sport_key,"commence_time":"2025-09-07T20:20:00Z",
             "home_team":"Kansas City Chiefs","away_team":"Baltimore Ravens","bookmakers":[
                {"key":"draftkings","title":"DraftKings","markets":[
                    {"key":"h2h","outcomes":[{"name":"Kansas City Chiefs","price":-145},{"name":"Baltimore Ravens","price":122}]},
                    {"key":"spreads","outcomes":[{"name":"Kansas City Chiefs","price":-110,"point":-3.0},{"name":"Baltimore Ravens","price":-110,"point":3.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-108,"point":47.5},{"name":"Under","price":-112,"point":47.5}]}]},
                {"key":"fanduel","title":"FanDuel","markets":[
                    {"key":"h2h","outcomes":[{"name":"Kansas City Chiefs","price":-150},{"name":"Baltimore Ravens","price":128}]},
                    {"key":"spreads","outcomes":[{"name":"Kansas City Chiefs","price":-112,"point":-3.0},{"name":"Baltimore Ravens","price":-108,"point":3.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":47.5},{"name":"Under","price":-110,"point":47.5}]}]},
                {"key":"betmgm","title":"BetMGM","markets":[
                    {"key":"h2h","outcomes":[{"name":"Kansas City Chiefs","price":-140},{"name":"Baltimore Ravens","price":118}]},
                    {"key":"spreads","outcomes":[{"name":"Kansas City Chiefs","price":-110,"point":-3.5},{"name":"Baltimore Ravens","price":-110,"point":3.5}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-105,"point":47.5},{"name":"Under","price":-115,"point":47.5}]}]}]},
            {"id":"d2","sport_key":sport_key,"commence_time":"2025-09-08T17:00:00Z",
             "home_team":"Dallas Cowboys","away_team":"Philadelphia Eagles","bookmakers":[
                {"key":"draftkings","title":"DraftKings","markets":[
                    {"key":"h2h","outcomes":[{"name":"Dallas Cowboys","price":135},{"name":"Philadelphia Eagles","price":-158}]},
                    {"key":"spreads","outcomes":[{"name":"Dallas Cowboys","price":-110,"point":3.5},{"name":"Philadelphia Eagles","price":-110,"point":-3.5}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-112,"point":46.5},{"name":"Under","price":-108,"point":46.5}]}]},
                {"key":"fanduel","title":"FanDuel","markets":[
                    {"key":"h2h","outcomes":[{"name":"Dallas Cowboys","price":130},{"name":"Philadelphia Eagles","price":-155}]},
                    {"key":"spreads","outcomes":[{"name":"Dallas Cowboys","price":-108,"point":3.5},{"name":"Philadelphia Eagles","price":-112,"point":-3.5}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":46.5},{"name":"Under","price":-110,"point":46.5}]}]},
                {"key":"caesars","title":"Caesars","markets":[
                    {"key":"h2h","outcomes":[{"name":"Dallas Cowboys","price":140},{"name":"Philadelphia Eagles","price":-162}]},
                    {"key":"spreads","outcomes":[{"name":"Dallas Cowboys","price":-110,"point":3.0},{"name":"Philadelphia Eagles","price":-110,"point":-3.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-108,"point":46.5},{"name":"Under","price":-112,"point":46.5}]}]}]},
        ]
    elif sport_key in ("soccer_epl","soccer_spain_la_liga","soccer_germany_bundesliga",
                       "soccer_italy_serie_a","soccer_france_ligue_one",
                       "soccer_uefa_champs_league","soccer_uefa_europa_league","soccer_usa_mls"):
        teams = {
            "soccer_epl":                  [("Arsenal","Chelsea"),("Liverpool","Manchester City")],
            "soccer_spain_la_liga":        [("Real Madrid","Barcelona"),("Atletico Madrid","Sevilla")],
            "soccer_germany_bundesliga":   [("Bayern Munich","Borussia Dortmund"),("RB Leipzig","Bayer Leverkusen")],
            "soccer_italy_serie_a":        [("Inter Milan","AC Milan"),("Juventus","Napoli")],
            "soccer_france_ligue_one":     [("PSG","Marseille"),("Lyon","Monaco")],
            "soccer_uefa_champs_league":   [("Real Madrid","Manchester City"),("Bayern Munich","Arsenal")],
            "soccer_uefa_europa_league":   [("Roma","Ajax"),("Tottenham","Frankfurt")],
            "soccer_usa_mls":              [("LA Galaxy","LAFC"),("Inter Miami","NYC FC")],
        }
        pairs = teams.get(sport_key, [("Team A","Team B")])
        events = []
        for i, (home, away) in enumerate(pairs):
            events.append({
                "id": f"soc_{i}","sport_key":sport_key,
                "commence_time": f"2025-04-20T{14+i*4:02d}:00:00Z",
                "home_team":home,"away_team":away,"bookmakers":[
                    {"key":"bet365","title":"Bet365","markets":[
                        {"key":"h2h","outcomes":[{"name":home,"price":-130},{"name":away,"price":320},{"name":"Draw","price":265}]},
                        {"key":"spreads","outcomes":[{"name":home,"price":-110,"point":-0.5},{"name":away,"price":-110,"point":0.5}]},
                        {"key":"totals","outcomes":[{"name":"Over","price":-115,"point":2.5},{"name":"Under","price":-105,"point":2.5}]}]},
                    {"key":"unibet","title":"Unibet","markets":[
                        {"key":"h2h","outcomes":[{"name":home,"price":-125},{"name":away,"price":310},{"name":"Draw","price":260}]},
                        {"key":"spreads","outcomes":[{"name":home,"price":-108,"point":-0.5},{"name":away,"price":-112,"point":0.5}]},
                        {"key":"totals","outcomes":[{"name":"Over","price":-112,"point":2.5},{"name":"Under","price":-108,"point":2.5}]}]},
                    {"key":"draftkings","title":"DraftKings","markets":[
                        {"key":"h2h","outcomes":[{"name":home,"price":-135},{"name":away,"price":330},{"name":"Draw","price":270}]},
                        {"key":"spreads","outcomes":[{"name":home,"price":-110,"point":-0.5},{"name":away,"price":-110,"point":0.5}]},
                        {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":2.5},{"name":"Under","price":-110,"point":2.5}]}]}]})
        return events
    elif sport_key == "basketball_nba":
        return [
            {"id":"nba1","sport_key":sport_key,"commence_time":"2025-04-20T23:00:00Z",
             "home_team":"Los Angeles Lakers","away_team":"Golden State Warriors","bookmakers":[
                {"key":"draftkings","title":"DraftKings","markets":[
                    {"key":"h2h","outcomes":[{"name":"Los Angeles Lakers","price":-118},{"name":"Golden State Warriors","price":100}]},
                    {"key":"spreads","outcomes":[{"name":"Los Angeles Lakers","price":-110,"point":-2.0},{"name":"Golden State Warriors","price":-110,"point":2.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-108,"point":224.5},{"name":"Under","price":-112,"point":224.5}]}]},
                {"key":"fanduel","title":"FanDuel","markets":[
                    {"key":"h2h","outcomes":[{"name":"Los Angeles Lakers","price":-120},{"name":"Golden State Warriors","price":102}]},
                    {"key":"spreads","outcomes":[{"name":"Los Angeles Lakers","price":-110,"point":-2.0},{"name":"Golden State Warriors","price":-110,"point":2.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":224.5},{"name":"Under","price":-110,"point":224.5}]}]},
                {"key":"betmgm","title":"BetMGM","markets":[
                    {"key":"h2h","outcomes":[{"name":"Los Angeles Lakers","price":-115},{"name":"Golden State Warriors","price":97}]},
                    {"key":"spreads","outcomes":[{"name":"Los Angeles Lakers","price":-112,"point":-2.0},{"name":"Golden State Warriors","price":-108,"point":2.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-105,"point":225.0},{"name":"Under","price":-115,"point":225.0}]}]}]},
            {"id":"nba2","sport_key":sport_key,"commence_time":"2025-04-21T01:30:00Z",
             "home_team":"Boston Celtics","away_team":"Miami Heat","bookmakers":[
                {"key":"draftkings","title":"DraftKings","markets":[
                    {"key":"h2h","outcomes":[{"name":"Boston Celtics","price":-240},{"name":"Miami Heat","price":198}]},
                    {"key":"spreads","outcomes":[{"name":"Boston Celtics","price":-110,"point":-6.0},{"name":"Miami Heat","price":-110,"point":6.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":211.5},{"name":"Under","price":-110,"point":211.5}]}]},
                {"key":"fanduel","title":"FanDuel","markets":[
                    {"key":"h2h","outcomes":[{"name":"Boston Celtics","price":-235},{"name":"Miami Heat","price":194}]},
                    {"key":"spreads","outcomes":[{"name":"Boston Celtics","price":-112,"point":-6.0},{"name":"Miami Heat","price":-108,"point":6.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-108,"point":212.0},{"name":"Under","price":-112,"point":212.0}]}]},
                {"key":"caesars","title":"Caesars","markets":[
                    {"key":"h2h","outcomes":[{"name":"Boston Celtics","price":-245},{"name":"Miami Heat","price":202}]},
                    {"key":"spreads","outcomes":[{"name":"Boston Celtics","price":-110,"point":-6.5},{"name":"Miami Heat","price":-110,"point":6.5}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":211.5},{"name":"Under","price":-110,"point":211.5}]}]}]},
            {"id":"nba3","sport_key":sport_key,"commence_time":"2025-04-21T02:00:00Z",
             "home_team":"Denver Nuggets","away_team":"Phoenix Suns","bookmakers":[
                {"key":"draftkings","title":"DraftKings","markets":[
                    {"key":"h2h","outcomes":[{"name":"Denver Nuggets","price":-175},{"name":"Phoenix Suns","price":148}]},
                    {"key":"spreads","outcomes":[{"name":"Denver Nuggets","price":-110,"point":-4.5},{"name":"Phoenix Suns","price":-110,"point":4.5}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-112,"point":228.0},{"name":"Under","price":-108,"point":228.0}]}]},
                {"key":"fanduel","title":"FanDuel","markets":[
                    {"key":"h2h","outcomes":[{"name":"Denver Nuggets","price":-178},{"name":"Phoenix Suns","price":150}]},
                    {"key":"spreads","outcomes":[{"name":"Denver Nuggets","price":-110,"point":-4.5},{"name":"Phoenix Suns","price":-110,"point":4.5}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-110,"point":228.0},{"name":"Under","price":-110,"point":228.0}]}]},
                {"key":"betmgm","title":"BetMGM","markets":[
                    {"key":"h2h","outcomes":[{"name":"Denver Nuggets","price":-170},{"name":"Phoenix Suns","price":144}]},
                    {"key":"spreads","outcomes":[{"name":"Denver Nuggets","price":-112,"point":-4.0},{"name":"Phoenix Suns","price":-108,"point":4.0}]},
                    {"key":"totals","outcomes":[{"name":"Over","price":-108,"point":228.5},{"name":"Under","price":-112,"point":228.5}]}]}]},
        ]
    return []


# ─────────────────────────────────────────────
#  CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
.sport-badge {
    display:inline-block; padding:3px 12px; border-radius:20px;
    font-weight:700; font-size:0.9rem; margin-bottom:6px;
}
.nfl-badge   { background:#00b4d820; color:#00b4d8; border:1px solid #00b4d8; }
.soccer-badge{ background:#4ade8020; color:#4ade80; border:1px solid #4ade80; }
.nba-badge   { background:#f9731620; color:#f97316; border:1px solid #f97316; }
.ucl-badge   { background:#facc1520; color:#facc15; border:1px solid #facc15; }
.main-title  { font-size:2rem; font-weight:800;
               background:linear-gradient(135deg,#a78bfa,#38bdf8);
               -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
div[data-testid="stDataFrame"] { border-radius:10px; overflow:hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Настройки")
    st.divider()

    api_key = st.text_input(
        "🔑 API Ключ (The Odds API)",
        type="password",
        placeholder="Вставь ключ или оставь пустым для демо",
        help="Бесплатно: https://the-odds-api.com (500 запросов/мес)",
    )

    sport_label = st.selectbox("🏆 Вид спорта / Лига", list(SPORTS_CATALOGUE.keys()))
    sport_cfg   = SPORTS_CATALOGUE[sport_label]
    has_draw    = sport_cfg["has_draw"]

    region_label = st.selectbox("📍 Регион букмекеров", list(REGION_MAP.keys()))

    market_label = st.selectbox("📊 Рынок", sport_cfg["markets"])
    market_key   = MARKET_KEY_MAP[market_label]

    all_bm = US_BOOKMAKERS + EU_BOOKMAKERS
    default_bm = ["DraftKings","FanDuel","BetMGM"] if not has_draw else ["Bet365","Unibet","DraftKings"]
    selected_bm = st.multiselect("🏦 Букмекеры", all_bm, default=default_bm)

    st.divider()
    min_edge = st.slider("💎 Мин. EV Edge % для value bets",
                         0.0, 15.0, 1.0, 0.5)
    st.divider()
    fetch_btn = st.button("🔄 Загрузить данные", use_container_width=True, type="primary")
    st.divider()
    st.caption("📡 [The Odds API](https://the-odds-api.com)")

# ─────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────
st.markdown('<div class="main-title">🏆 Sports Odds Dashboard</div>', unsafe_allow_html=True)
st.caption("NFL · Football (Soccer) · NBA — Живые коэффициенты, Value Bets, Сравнение букмекеров")
st.divider()

# ─────────────────────────────────────────────
#  SESSION STATE
# ─────────────────────────────────────────────
for k in ("events","remaining","used","demo_mode","last_sport","last_market"):
    if k not in st.session_state:
        st.session_state[k] = None

# ─────────────────────────────────────────────
#  FETCH
# ─────────────────────────────────────────────
if fetch_btn:
    st.session_state.last_sport  = sport_label
    st.session_state.last_market = market_label
    if not api_key:
        st.info("💡 API ключ не введён — показываю демо-данные. Получи бесплатный ключ на [the-odds-api.com](https://the-odds-api.com)", icon="ℹ️")
        st.session_state.events    = make_demo(sport_cfg["key"], has_draw)
        st.session_state.remaining = "demo"
        st.session_state.used      = "demo"
        st.session_state.demo_mode = True
    else:
        with st.spinner(f"Загружаю {sport_label} · {market_label}…"):
            events, rem, used = get_odds(api_key, sport_cfg["key"], REGION_MAP[region_label], market_key)
        if events is not None:
            st.session_state.events    = events
            st.session_state.remaining = rem
            st.session_state.used      = used
            st.session_state.demo_mode = False
            st.success(f"✅ {len(events)} матчей загружено | Запросов осталось: {rem}")

events = st.session_state.events

# ─────────────────────────────────────────────
#  WELCOME SCREEN
# ─────────────────────────────────────────────
if events is None:
    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        ### 🏈 NFL
        - Moneyline · Spreads · Totals
        - DraftKings, FanDuel, BetMGM…
        """)
    with col2:
        st.markdown("""
        ### ⚽ Football / Soccer
        - EPL · La Liga · Bundesliga
        - Serie A · Ligue 1 · UCL · UEL
        - **1X2 с Ничьей + No-Vig**
        """)
    with col3:
        st.markdown("""
        ### 🏀 NBA
        - Moneyline · Spreads · Totals
        - Все ведущие американские книги
        """)
    st.info("👈 Выбери вид спорта, рынок и нажми **Загрузить данные** — API ключ необязателен (есть демо-режим).")
    st.stop()

# ─────────────────────────────────────────────
#  FILTER BY BOOKMAKER
# ─────────────────────────────────────────────
filtered = []
for ev in events:
    bms = [b for b in ev.get("bookmakers", [])
           if not selected_bm or b.get("title") in selected_bm]
    if bms:
        filtered.append({**ev, "bookmakers": bms})

if not filtered:
    st.warning("⚠️ Нет матчей по выбранным фильтрам.")
    st.stop()

df = parse_to_df(filtered, market_key, has_draw)
if df.empty:
    st.warning(f"⚠️ Нет данных для рынка «{market_label}».")
    st.stop()

# ─────────────────────────────────────────────
#  METRICS ROW
# ─────────────────────────────────────────────
demo_tag = " *(демо)*" if st.session_state.demo_mode else ""
cur_sport = st.session_state.last_sport or sport_label

# Badge color
if "NBA" in cur_sport:
    badge_cls = "nba-badge"
elif "Champions" in cur_sport:
    badge_cls = "ucl-badge"
elif any(x in cur_sport for x in ("EPL","Liga","Bundesliga","Serie","Ligue","Europa","MLS")):
    badge_cls = "soccer-badge"
else:
    badge_cls = "nfl-badge"

st.markdown(f'<span class="sport-badge {badge_cls}">{cur_sport}</span>', unsafe_allow_html=True)
st.markdown(f"### {market_label}{demo_tag}")

c1, c2, c3, c4 = st.columns(4)
c1.metric("🏟 Матчей",     df["Матч"].nunique())
c2.metric("🏦 Букмекеров", df["Букмекер"].nunique())
c3.metric("📋 Линий",      len(df))
c4.metric("📡 API осталось", st.session_state.remaining)

st.divider()

# ─────────────────────────────────────────────
#  TABS
# ─────────────────────────────────────────────
tab_table, tab_chart, tab_value = st.tabs([
    "📋 Таблица коэффициентов",
    "📊 Сравнение букмекеров",
    "💎 Value Bets",
])

# ── TAB 1: TABLE ──────────────────────────────
with tab_table:
    match_opts = ["Все матчи"] + sorted(df["Матч"].unique().tolist())
    sel = st.selectbox("Фильтр по матчу", match_opts, key="t1_match")
    show = df[df["Матч"] == sel] if sel != "Все матчи" else df
    show = show[[c for c in show.columns if not c.startswith("_")]]
    st.dataframe(show, use_container_width=True, hide_index=True,
                 height=min(500, 56 + len(show)*35))
    csv = show.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Скачать CSV", csv,
        f"odds_{sport_cfg['key']}_{market_key}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )

# ── TAB 2: CHARTS ─────────────────────────────
with tab_chart:
    matches = sorted(df["Матч"].unique().tolist())
    sel2 = st.selectbox("Выбери матч", matches, key="t2_match")
    mdf  = df[df["Матч"] == sel2].copy()
    home_t = mdf["Хозяева"].iloc[0]
    away_t = mdf["Гости"].iloc[0]
    color  = sport_cfg["color"]

    DARK = dict(plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a", font_color="#e2e8f0")

    if market_key == "h2h":
        # --- Decimal odds bar chart ---
        def safe_dec(col):
            return mdf[col].apply(
                lambda x: american_to_decimal(float(x)) if x is not None and str(x) != "nan" else None)

        fig = go.Figure()
        pairs = [(home_t, "Odds Хозяева (Am)", color),
                 (away_t, "Odds Гости (Am)",  "#f97316")]
        if has_draw:
            pairs.append(("Ничья", "Odds Ничья (Am)", "#facc15"))

        for name, col, clr in pairs:
            dec_vals = safe_dec(col)
            am_texts = mdf[col].apply(lambda x: fmt_american(x) if x is not None and str(x)!="nan" else "")
            fig.add_trace(go.Bar(name=name, x=mdf["Букмекер"], y=dec_vals,
                                 marker_color=clr, text=am_texts, textposition="outside"))
        fig.update_layout(title=f"Decimal Odds — {sel2}", barmode="group",
                          xaxis_title="Букмекер", yaxis_title="Decimal Odds", height=420, **DARK)
        st.plotly_chart(fig, use_container_width=True)

        # --- No-vig probability bar chart ---
        prob_rows = []
        for _, row in mdf.iterrows():
            try:
                h_am = float(row["Odds Хозяева (Am)"])
                a_am = float(row["Odds Гости (Am)"])
                h_impl = decimal_to_implied(american_to_decimal(h_am))
                a_impl = decimal_to_implied(american_to_decimal(a_am))
                d_am = row.get("Odds Ничья (Am)")
                if has_draw and d_am and str(d_am) != "nan":
                    d_impl = decimal_to_implied(american_to_decimal(float(d_am)))
                    nv = no_vig_prob([h_impl, a_impl, d_impl])
                    prob_rows.append({"Букмекер": row["Букмекер"],
                                      home_t: nv[0], away_t: nv[1], "Ничья": nv[2]})
                else:
                    nv = no_vig_prob([h_impl, a_impl])
                    prob_rows.append({"Букмекер": row["Букмекер"],
                                      home_t: nv[0], away_t: nv[1]})
            except Exception:
                continue

        if prob_rows:
            pf = pd.DataFrame(prob_rows)
            fig2 = go.Figure()
            cols_probs = [(home_t, color), (away_t, "#f97316")]
            if has_draw:
                cols_probs.append(("Ничья", "#facc15"))
            for name, clr in cols_probs:
                if name in pf.columns:
                    fig2.add_trace(go.Bar(
                        name=name, x=pf["Букмекер"], y=pf[name],
                        marker_color=clr,
                        text=pf[name].apply(lambda x: f"{x:.1f}%"),
                        textposition="outside",
                    ))
            fig2.update_layout(title="No-Vig вероятности (%)", barmode="group",
                               xaxis_title="Букмекер", yaxis_title="%",
                               yaxis_range=[0, 105], height=400, **DARK)
            st.plotly_chart(fig2, use_container_width=True)

        # --- Best odds summary ---
        st.markdown("##### 🏆 Лучшие коэффициенты")
        best_rows = []
        cols_check = [(home_t, "Odds Хозяева (Am)"), (away_t, "Odds Гости (Am)")]
        if has_draw:
            cols_check.append(("Ничья", "Odds Ничья (Am)"))
        for name, col in cols_check:
            sub = mdf[["Букмекер", col]].dropna()
            sub = sub[sub[col].apply(lambda x: str(x) != "nan")]
            if sub.empty: continue
            sub = sub.copy()
            sub["_dec"] = sub[col].apply(lambda x: american_to_decimal(float(x)))
            best = sub.loc[sub["_dec"].idxmax()]
            am_v = float(best[col])
            dec_v = american_to_decimal(am_v)
            best_rows.append({
                "Исход": name,
                "Лучший букмекер": best["Букмекер"],
                "Odds (Am)": fmt_american(am_v),
                "Decimal": dec_v,
                "Implied %": f"{decimal_to_implied(dec_v):.1f}%",
            })
        if best_rows:
            st.dataframe(pd.DataFrame(best_rows), use_container_width=True, hide_index=True)

    elif market_key == "spreads":
        fig = go.Figure()
        for name, col, clr in [(home_t, "Odds Хозяева (Am)", color), (away_t, "Odds Гости (Am)", "#f97316")]:
            dec_vals = mdf[col].apply(lambda x: american_to_decimal(float(x)) if x is not None and str(x)!="nan" else None)
            fig.add_trace(go.Bar(name=name, x=mdf["Букмекер"], y=dec_vals, marker_color=clr))
        fig.update_layout(title=f"Spread Odds — {sel2}", barmode="group", height=420, **DARK)
        st.plotly_chart(fig, use_container_width=True)
        # Spread lines
        sdf = mdf[["Букмекер","Спред Хозяева","Спред Гости"]].dropna()
        if not sdf.empty:
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(x=sdf["Букмекер"],
                y=sdf["Спред Хозяева"].astype(float),
                mode="lines+markers+text", name=home_t,
                line=dict(color=color, width=2), marker=dict(size=9),
                text=sdf["Спред Хозяева"].astype(float).apply(lambda x: f"{x:+.1f}"),
                textposition="top center"))
            fig3.add_trace(go.Scatter(x=sdf["Букмекер"],
                y=sdf["Спред Гости"].astype(float),
                mode="lines+markers+text", name=away_t,
                line=dict(color="#f97316", width=2), marker=dict(size=9),
                text=sdf["Спред Гости"].astype(float).apply(lambda x: f"{x:+.1f}"),
                textposition="bottom center"))
            fig3.update_layout(title="Линии спреда по букмекерам", height=320, **DARK)
            st.plotly_chart(fig3, use_container_width=True)

    elif market_key == "totals":
        ov_dec = mdf["Odds Over (Am)"].apply(lambda x: american_to_decimal(float(x)) if x is not None and str(x)!="nan" else None)
        un_dec = mdf["Odds Under (Am)"].apply(lambda x: american_to_decimal(float(x)) if x is not None and str(x)!="nan" else None)
        fig = go.Figure()
        fig.add_trace(go.Bar(name="Over",  x=mdf["Букмекер"], y=ov_dec, marker_color="#22c55e"))
        fig.add_trace(go.Bar(name="Under", x=mdf["Букмекер"], y=un_dec, marker_color="#ef4444"))
        fig.update_layout(title=f"Totals Odds — {sel2}", barmode="group", height=420, **DARK)
        st.plotly_chart(fig, use_container_width=True)
        # Total line
        tdf = mdf[["Букмекер","Тотал Линия"]].dropna()
        if not tdf.empty:
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(x=tdf["Букмекер"],
                y=tdf["Тотал Линия"].astype(float),
                mode="lines+markers+text", name="Тотал",
                line=dict(color="#a855f7", width=2), marker=dict(size=9),
                text=tdf["Тотал Линия"].astype(float).apply(str),
                textposition="top center"))
            fig4.update_layout(title="Линии тотала", height=300, **DARK)
            st.plotly_chart(fig4, use_container_width=True)

# ── TAB 3: VALUE BETS ─────────────────────────
with tab_value:
    st.markdown("#### 💎 Value Bets — ставки с положительным EV")

    if market_key != "h2h":
        st.info("ℹ️ Value Bet расчёт работает для рынка **H2H / 1X2**. Переключи рынок в боковой панели.")
    else:
        methodology = """
**Методология (No-Vig EV):**
1. `Implied %` = |odds| / (|odds| + 100) × 100 — для фаворита  
   или 100 / (odds + 100) × 100 — для аутсайдера  
2. `No-Vig Fair %` = implied / Σ(все implied) × 100 — убираем маржу  
3. `EV Edge` = fair_prob × decimal_odds − 1  
4. Если EV Edge ≥ порогу — ✅ Value Bet
"""
        if has_draw:
            methodology += "\n> ⚽ **Football**: расчёт трёхисходников — Хозяева / Ничья / Гости"
        st.info(methodology)

        vdf = compute_value_bets(df, has_draw, min_edge)

        if vdf.empty:
            st.warning(f"Нет value bets с EV Edge ≥ {min_edge}%. Попробуй снизить порог или выбрать больше букмекеров.")
        else:
            st.success(f"✅ Найдено value bets: **{len(vdf)}** (EV Edge ≥ {min_edge}%)")
            st.dataframe(vdf, use_container_width=True,
                         height=min(600, 60 + len(vdf)*38))
            csv_v = vdf.to_csv(index=True).encode("utf-8")
            st.download_button("⬇️ Скачать Value Bets CSV", csv_v,
                               f"value_bets_{sport_cfg['key']}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                               mime="text/csv")

        # EV scatter across all matches
        st.divider()
        st.markdown("##### EV Edge (хозяева) по матчам и букмекерам")
        ev_rows = []
        for _, row in df.iterrows():
            h_am = row.get("Odds Хозяева (Am)")
            a_am = row.get("Odds Гости (Am)")
            if h_am is None or a_am is None or str(h_am)=="nan" or str(a_am)=="nan":
                continue
            try:
                h_dec  = american_to_decimal(float(h_am))
                a_dec  = american_to_decimal(float(a_am))
                h_impl = decimal_to_implied(h_dec)
                a_impl = decimal_to_implied(a_dec)
                d_am   = row.get("Odds Ничья (Am)")
                if has_draw and d_am and str(d_am)!="nan":
                    nv = no_vig_prob([h_impl, a_impl, decimal_to_implied(american_to_decimal(float(d_am)))])
                else:
                    nv = no_vig_prob([h_impl, a_impl])
                edge_h = ev_edge(nv[0], h_dec) * 100
                ev_rows.append({"Матч": row["Матч"], "Букмекер": row["Букмекер"],
                                 "EV Хозяева %": round(edge_h, 2)})
            except Exception:
                continue
        if ev_rows:
            evf = pd.DataFrame(ev_rows)
            fig_ev = px.scatter(
                evf, x="Букмекер", y="EV Хозяева %", color="Матч",
                size=evf["EV Хозяева %"].abs() + 1,
                hover_data=["Матч","Букмекер","EV Хозяева %"],
                title="EV Edge Хозяева (%) — все матчи",
                template="plotly_dark", height=420,
            )
            fig_ev.add_hline(y=0, line_dash="dash", line_color="#ef4444",
                             annotation_text="EV = 0 (нет преимущества)")
            fig_ev.update_layout(plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a")
            st.plotly_chart(fig_ev, use_container_width=True)

# ─────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────
st.divider()
st.caption(
    "Данные: [The Odds API](https://the-odds-api.com) · "
    "Только для образовательных целей. Ставки на спорт сопряжены с риском потери средств."
)
