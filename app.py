import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz
import os

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="NFL Odds Dashboard",
    page_icon="🏈",
    layout="wide",
    initial_sidebar_state="expanded",
)

BASE_URL = "https://api.the-odds-api.com/v4"
SPORT    = "americanfootball_nfl"

US_BOOKMAKERS = {
    "draftkings": "DraftKings",
    "fanduel": "FanDuel",
    "betmgm": "BetMGM",
    "caesars": "Caesars",
    "pointsbetus": "PointsBet US",
    "williamhill_us": "William Hill US",
    "betrivers": "BetRivers",
    "bovada": "Bovada",
    "betonlineag": "BetOnline.ag",
    "barstool": "Barstool",
}
EU_BOOKMAKERS = {
    "betfair": "Betfair",
    "unibet": "Unibet",
    "paddypower": "Paddy Power",
    "bet365": "Bet365",
    "skybet": "Sky Bet",
    "ladbrokes": "Ladbrokes",
    "coral": "Coral",
    "betway": "Betway",
    "888sport": "888sport",
    "sportingbet": "Sportingbet",
}
REGION_MAP = {
    "US (DraftKings, FanDuel…)": "us",
    "US Extended (PointsBet…)": "us2",
    "UK/EU": "uk,eu",
    "Все регионы": "us,us2,uk,eu",
}
MARKET_MAP = {
    "H2H (Moneyline)": "h2h",
    "Spreads (Handicap)": "spreads",
    "Totals (Over/Under)": "totals",
}

# ─────────────────────────────────────────────
#  HELPERS
# ─────────────────────────────────────────────

def american_to_decimal(american: float) -> float:
    if american >= 0:
        return round(american / 100 + 1, 4)
    else:
        return round(100 / abs(american) + 1, 4)

def decimal_to_implied(decimal_odds: float) -> float:
    if decimal_odds <= 0:
        return 0.0
    return round(1 / decimal_odds * 100, 2)

def no_vig_prob(probs: list[float]) -> list[float]:
    """Remove overround: divide each implied prob by sum."""
    total = sum(probs)
    if total == 0:
        return probs
    return [round(p / total * 100, 2) for p in probs]

def calc_value_edge(true_prob: float, decimal_odds: float) -> float:
    """EV edge = true_prob * decimal_odds - 1"""
    return round(true_prob / 100 * decimal_odds - 1, 4)

def get_odds(api_key: str, regions: str, markets: str):
    url = f"{BASE_URL}/sports/{SPORT}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
        "dateFormat": "iso",
    }
    r = requests.get(url, params=params, timeout=15)
    remaining = r.headers.get("x-requests-remaining", "?")
    used      = r.headers.get("x-requests-used", "?")
    if r.status_code == 200:
        return r.json(), remaining, used
    elif r.status_code == 401:
        st.error("❌ Неверный API ключ. Получить бесплатный ключ: https://the-odds-api.com")
        return None, None, None
    elif r.status_code == 422:
        st.error("❌ Неверные параметры запроса.")
        return None, None, None
    elif r.status_code == 429:
        st.error("❌ Превышен лимит запросов API.")
        return None, None, None
    else:
        st.error(f"❌ Ошибка API: {r.status_code} — {r.text[:200]}")
        return None, None, None

def parse_odds_to_df(events: list, market_key: str) -> pd.DataFrame:
    rows = []
    for ev in events:
        home = ev["home_team"]
        away = ev["away_team"]
        try:
            dt = datetime.fromisoformat(ev["commence_time"].replace("Z", "+00:00"))
            dt_msk = dt.astimezone(pytz.timezone("Europe/Moscow"))
            time_str = dt_msk.strftime("%d.%m %H:%M МСК")
        except Exception:
            time_str = ev.get("commence_time", "—")

        for bm in ev.get("bookmakers", []):
            bk_key   = bm["key"]
            bk_title = bm.get("title", bk_key)
            for mkt in bm.get("markets", []):
                if mkt["key"] != market_key:
                    continue
                outcomes = {o["name"]: o["price"] for o in mkt["outcomes"]}

                if market_key == "h2h":
                    row = {
                        "Матч": f"{away} @ {home}",
                        "Время": time_str,
                        "Букмекер": bk_title,
                        "Хозяева": home,
                        "Гости": away,
                        "Odds Хозяева (Am)": outcomes.get(home),
                        "Odds Гости (Am)": outcomes.get(away),
                        "Odds Draw (Am)": outcomes.get("Draw"),
                        "_bk_key": bk_key,
                        "_event_id": ev["id"],
                    }
                elif market_key == "spreads":
                    # find home/away in outcomes
                    home_out = next((o for o in mkt["outcomes"] if o["name"] == home), None)
                    away_out = next((o for o in mkt["outcomes"] if o["name"] == away), None)
                    row = {
                        "Матч": f"{away} @ {home}",
                        "Время": time_str,
                        "Букмекер": bk_title,
                        "Хозяева": home,
                        "Гости": away,
                        "Спред Хозяева": home_out.get("point") if home_out else None,
                        "Odds Хозяева (Am)": home_out.get("price") if home_out else None,
                        "Спред Гости": away_out.get("point") if away_out else None,
                        "Odds Гости (Am)": away_out.get("price") if away_out else None,
                        "_bk_key": bk_key,
                        "_event_id": ev["id"],
                    }
                elif market_key == "totals":
                    over_out  = next((o for o in mkt["outcomes"] if o["name"] == "Over"), None)
                    under_out = next((o for o in mkt["outcomes"] if o["name"] == "Under"), None)
                    row = {
                        "Матч": f"{away} @ {home}",
                        "Время": time_str,
                        "Букмекер": bk_title,
                        "Хозяева": home,
                        "Гости": away,
                        "Тотал Линия": over_out.get("point") if over_out else None,
                        "Odds Over (Am)": over_out.get("price") if over_out else None,
                        "Odds Under (Am)": under_out.get("price") if under_out else None,
                        "_bk_key": bk_key,
                        "_event_id": ev["id"],
                    }
                else:
                    row = {}

                rows.append(row)
    return pd.DataFrame(rows)

def compute_value_bets(df: pd.DataFrame, market_key: str, min_edge_pct: float) -> pd.DataFrame:
    """
    Рассчитывает no-vig вероятности и EV edge для каждой позиции.
    Для H2H: используем лучший коэфф из всех букмекеров как базу справедливых odds.
    """
    value_rows = []

    if market_key != "h2h":
        return pd.DataFrame()

    # Группируем по матчу
    for match, grp in df.groupby("Матч"):
        home = grp["Хозяева"].iloc[0]
        away = grp["Гости"].iloc[0]
        time_str = grp["Время"].iloc[0]

        for _, row in grp.iterrows():
            home_am = row.get("Odds Хозяева (Am)")
            away_am = row.get("Odds Гости (Am)")
            if home_am is None or away_am is None:
                continue
            try:
                home_am = float(home_am)
                away_am = float(away_am)
            except (TypeError, ValueError):
                continue

            home_dec = american_to_decimal(home_am)
            away_dec = american_to_decimal(away_am)

            home_impl = decimal_to_implied(home_dec)
            away_impl = decimal_to_implied(away_dec)

            # No-vig fair probs
            draw_am = row.get("Odds Draw (Am)")
            if draw_am:
                try:
                    draw_dec = american_to_decimal(float(draw_am))
                    draw_impl = decimal_to_implied(draw_dec)
                    fair = no_vig_prob([home_impl, away_impl, draw_impl])
                    home_fair, away_fair = fair[0], fair[1]
                except Exception:
                    fair = no_vig_prob([home_impl, away_impl])
                    home_fair, away_fair = fair[0], fair[1]
            else:
                fair = no_vig_prob([home_impl, away_impl])
                home_fair, away_fair = fair[0], fair[1]

            home_edge = calc_value_edge(home_fair, home_dec)
            away_edge = calc_value_edge(away_fair, away_dec)

            if home_edge * 100 >= min_edge_pct:
                value_rows.append({
                    "Матч": match,
                    "Время": time_str,
                    "Букмекер": row["Букмекер"],
                    "Исход": f"✅ {home}",
                    "Odds (Am)": f"+{int(home_am)}" if home_am >= 0 else str(int(home_am)),
                    "Odds (Dec)": home_dec,
                    "Implied %": f"{home_impl}%",
                    "No-Vig Fair %": f"{home_fair}%",
                    "EV Edge %": f"+{home_edge*100:.2f}%",
                    "_edge": home_edge * 100,
                })
            if away_edge * 100 >= min_edge_pct:
                value_rows.append({
                    "Матч": match,
                    "Время": time_str,
                    "Букмекер": row["Букмекер"],
                    "Исход": f"✅ {away}",
                    "Odds (Am)": f"+{int(away_am)}" if away_am >= 0 else str(int(away_am)),
                    "Odds (Dec)": away_dec,
                    "Implied %": f"{away_impl}%",
                    "No-Vig Fair %": f"{away_fair}%",
                    "EV Edge %": f"+{away_edge*100:.2f}%",
                    "_edge": away_edge * 100,
                })

    if value_rows:
        vdf = pd.DataFrame(value_rows).sort_values("_edge", ascending=False).reset_index(drop=True)
        vdf.index += 1
        return vdf.drop(columns=["_edge"])
    return pd.DataFrame()

# ─────────────────────────────────────────────
#  CUSTOM CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 800;
        background: linear-gradient(135deg, #00b4d8, #0077b6);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        padding: 0.2rem 0;
    }
    .metric-card {
        background: linear-gradient(135deg, #1e3a5f, #0d1b2a);
        border: 1px solid #00b4d8;
        border-radius: 12px;
        padding: 1rem 1.4rem;
        text-align: center;
    }
    .metric-value { font-size: 2rem; font-weight: 800; color: #00b4d8; }
    .metric-label { font-size: 0.85rem; color: #a0aec0; margin-top: 0.2rem; }
    .value-bet-tag {
        background: #065f46;
        color: #6ee7b7;
        padding: 2px 8px;
        border-radius: 8px;
        font-size: 0.8rem;
        font-weight: 700;
    }
    div[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
    .stTabs [data-baseweb="tab"] { font-weight: 600; }
    .sidebar .sidebar-content { background: #0d1b2a; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Настройки")
    st.markdown("---")

    api_key = st.text_input(
        "🔑 The Odds API Key",
        type="password",
        placeholder="Вставьте ваш API ключ…",
        help="Получить бесплатно на https://the-odds-api.com (500 запросов/мес)",
    )

    st.markdown("**📍 Регион букмекеров**")
    region_label = st.selectbox(
        "Регион",
        list(REGION_MAP.keys()),
        index=0,
        label_visibility="collapsed",
    )

    st.markdown("**📊 Рынок**")
    market_label = st.selectbox(
        "Рынок",
        list(MARKET_MAP.keys()),
        index=0,
        label_visibility="collapsed",
    )

    st.markdown("**🏦 Фильтр по букмекерам**")
    all_bm_labels = list(US_BOOKMAKERS.values()) + list(EU_BOOKMAKERS.values())
    selected_bm = st.multiselect(
        "Букмекеры",
        options=all_bm_labels,
        default=["DraftKings", "FanDuel", "BetMGM"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("**💎 Value Bets**")
    min_edge = st.slider(
        "Минимальный EV Edge %",
        min_value=0.0, max_value=15.0, value=1.0, step=0.5,
        help="Минимальный положительный EV для отображения value bet",
    )

    st.markdown("---")
    fetch_btn = st.button("🔄 Загрузить коэффициенты", use_container_width=True, type="primary")

    st.markdown("---")
    st.caption("📡 Данные: [The Odds API](https://the-odds-api.com)")
    st.caption("🏈 Спорт: NFL (americanfootball_nfl)")

# ─────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────
col_logo, col_title = st.columns([1, 10])
with col_title:
    st.markdown('<div class="main-header">🏈 NFL Odds Dashboard</div>', unsafe_allow_html=True)
    st.caption("Живые коэффициенты · Value Bets · Сравнение букмекеров")

st.markdown("---")

# ─────────────────────────────────────────────
#  DEMO DATA (when no API key)
# ─────────────────────────────────────────────
DEMO_EVENTS = [
    {
        "id": "demo_001",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2025-09-07T20:20:00Z",
        "home_team": "Kansas City Chiefs",
        "away_team": "Baltimore Ravens",
        "bookmakers": [
            {"key": "draftkings", "title": "DraftKings", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "Kansas City Chiefs", "price": -145},
                     {"name": "Baltimore Ravens", "price": +122},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "Kansas City Chiefs", "price": -110, "point": -3.0},
                     {"name": "Baltimore Ravens", "price": -110, "point": 3.0},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -108, "point": 47.5},
                     {"name": "Under", "price": -112, "point": 47.5},
                 ]},
             ]},
            {"key": "fanduel", "title": "FanDuel", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "Kansas City Chiefs", "price": -150},
                     {"name": "Baltimore Ravens", "price": +128},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "Kansas City Chiefs", "price": -112, "point": -3.0},
                     {"name": "Baltimore Ravens", "price": -108, "point": 3.0},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -110, "point": 47.5},
                     {"name": "Under", "price": -110, "point": 47.5},
                 ]},
             ]},
            {"key": "betmgm", "title": "BetMGM", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "Kansas City Chiefs", "price": -140},
                     {"name": "Baltimore Ravens", "price": +118},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "Kansas City Chiefs", "price": -110, "point": -3.5},
                     {"name": "Baltimore Ravens", "price": -110, "point": 3.5},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -105, "point": 47.5},
                     {"name": "Under", "price": -115, "point": 47.5},
                 ]},
             ]},
        ],
    },
    {
        "id": "demo_002",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2025-09-08T17:00:00Z",
        "home_team": "Dallas Cowboys",
        "away_team": "Philadelphia Eagles",
        "bookmakers": [
            {"key": "draftkings", "title": "DraftKings", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "Dallas Cowboys", "price": +135},
                     {"name": "Philadelphia Eagles", "price": -158},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "Dallas Cowboys", "price": -110, "point": 3.5},
                     {"name": "Philadelphia Eagles", "price": -110, "point": -3.5},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -112, "point": 46.5},
                     {"name": "Under", "price": -108, "point": 46.5},
                 ]},
             ]},
            {"key": "fanduel", "title": "FanDuel", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "Dallas Cowboys", "price": +130},
                     {"name": "Philadelphia Eagles", "price": -155},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "Dallas Cowboys", "price": -108, "point": 3.5},
                     {"name": "Philadelphia Eagles", "price": -112, "point": -3.5},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -110, "point": 46.5},
                     {"name": "Under", "price": -110, "point": 46.5},
                 ]},
             ]},
            {"key": "caesars", "title": "Caesars", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "Dallas Cowboys", "price": +140},
                     {"name": "Philadelphia Eagles", "price": -162},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "Dallas Cowboys", "price": -110, "point": 3.0},
                     {"name": "Philadelphia Eagles", "price": -110, "point": -3.0},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -108, "point": 46.5},
                     {"name": "Under", "price": -112, "point": 46.5},
                 ]},
             ]},
        ],
    },
    {
        "id": "demo_003",
        "sport_key": "americanfootball_nfl",
        "commence_time": "2025-09-08T20:25:00Z",
        "home_team": "San Francisco 49ers",
        "away_team": "New York Jets",
        "bookmakers": [
            {"key": "draftkings", "title": "DraftKings", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "San Francisco 49ers", "price": -220},
                     {"name": "New York Jets", "price": +182},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "San Francisco 49ers", "price": -110, "point": -6.0},
                     {"name": "New York Jets", "price": -110, "point": 6.0},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -110, "point": 43.5},
                     {"name": "Under", "price": -110, "point": 43.5},
                 ]},
             ]},
            {"key": "fanduel", "title": "FanDuel", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "San Francisco 49ers", "price": -215},
                     {"name": "New York Jets", "price": +178},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "San Francisco 49ers", "price": -112, "point": -6.0},
                     {"name": "New York Jets", "price": -108, "point": 6.0},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -105, "point": 44.0},
                     {"name": "Under", "price": -115, "point": 44.0},
                 ]},
             ]},
            {"key": "betmgm", "title": "BetMGM", "last_update": "2025-09-07T15:00:00Z",
             "markets": [
                 {"key": "h2h", "outcomes": [
                     {"name": "San Francisco 49ers", "price": -225},
                     {"name": "New York Jets", "price": +188},
                 ]},
                 {"key": "spreads", "outcomes": [
                     {"name": "San Francisco 49ers", "price": -110, "point": -6.5},
                     {"name": "New York Jets", "price": -110, "point": 6.5},
                 ]},
                 {"key": "totals", "outcomes": [
                     {"name": "Over", "price": -108, "point": 43.5},
                     {"name": "Under", "price": -112, "point": 43.5},
                 ]},
             ]},
        ],
    },
]


# ─────────────────────────────────────────────
#  STATE
# ─────────────────────────────────────────────
if "events"    not in st.session_state: st.session_state.events    = None
if "remaining" not in st.session_state: st.session_state.remaining = None
if "used"      not in st.session_state: st.session_state.used      = None
if "demo_mode" not in st.session_state: st.session_state.demo_mode = False

# ─────────────────────────────────────────────
#  FETCH
# ─────────────────────────────────────────────
if fetch_btn:
    if not api_key:
        st.info("💡 API ключ не введён — показываю демо-данные. Получи бесплатный ключ на [the-odds-api.com](https://the-odds-api.com)", icon="ℹ️")
        st.session_state.events    = DEMO_EVENTS
        st.session_state.remaining = "demo"
        st.session_state.used      = "demo"
        st.session_state.demo_mode = True
    else:
        region_val = REGION_MAP[region_label]
        market_val = MARKET_MAP[market_label]
        with st.spinner("Загружаю коэффициенты…"):
            events, remaining, used = get_odds(api_key, region_val, market_val)
        if events is not None:
            st.session_state.events    = events
            st.session_state.remaining = remaining
            st.session_state.used      = used
            st.session_state.demo_mode = False
            st.success(f"✅ Загружено {len(events)} матчей | Запросов осталось: {remaining} | Использовано: {used}")

# ─────────────────────────────────────────────
#  RENDER
# ─────────────────────────────────────────────
events = st.session_state.events

if events is None:
    # Welcome screen
    st.markdown("""
    ## 👋 Добро пожаловать в NFL Odds Dashboard

    Этот дашборд в реальном времени показывает:
    - 📊 **Живые коэффициенты** от DraftKings, FanDuel, BetMGM, Caesars и других
    - 🎯 **Value Bets** — ставки с положительным ожидаемым значением (EV > 0)
    - 📈 **Сравнение букмекеров** на интерактивных графиках
    - 🔢 **No-Vig вероятности** — честные шансы без маржи букмекера

    ### Как начать
    1. Введи **API ключ** в боковой панели (или оставь пустым для демо)
    2. Выбери **регион**, **рынок** и **букмекеров**
    3. Нажми **Загрузить коэффициенты**

    ### Получить бесплатный ключ
    👉 [the-odds-api.com](https://the-odds-api.com) — 500 запросов в месяц бесплатно
    """)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div class="metric-card">
            <div class="metric-value">40+</div>
            <div class="metric-label">Букмекеров</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown("""
        <div class="metric-card">
            <div class="metric-value">3</div>
            <div class="metric-label">Рынка (H2H, Spreads, Totals)</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown("""
        <div class="metric-card">
            <div class="metric-value">+EV</div>
            <div class="metric-label">Value Bet детектор</div>
        </div>
        """, unsafe_allow_html=True)
    st.stop()

# ── Фильтрация по букмекерам ─────────────────
market_key = MARKET_MAP[market_label]

# Применяем фильтр букмекеров к данным
filtered_events = []
for ev in events:
    ev_copy = dict(ev)
    bms = ev.get("bookmakers", [])
    if selected_bm:
        bms = [b for b in bms if b.get("title") in selected_bm]
    ev_copy["bookmakers"] = bms
    if bms:
        filtered_events.append(ev_copy)

if not filtered_events:
    st.warning("⚠️ Нет матчей по выбранным фильтрам. Попробуй изменить регион или букмекеров.")
    st.stop()

df = parse_odds_to_df(filtered_events, market_key)

if df.empty:
    st.warning(f"⚠️ Нет данных для рынка «{market_label}» с выбранными фильтрами.")
    st.stop()

# ── Метрики ─────────────────────────────────
demo_badge = " *(демо)*" if st.session_state.demo_mode else ""
st.markdown(f"### 📅 NFL Матчи{demo_badge} — {market_label}")

matches = df["Матч"].nunique()
bmakers = df["Букмекер"].nunique()
total_lines = len(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("🏈 Матчей", matches)
c2.metric("🏦 Букмекеров", bmakers)
c3.metric("📋 Линий", total_lines)
c4.metric("📡 API запросов осталось", st.session_state.remaining)

st.markdown("---")

tab_data, tab_compare, tab_value = st.tabs(["📋 Таблица коэффициентов", "📊 Сравнение букмекеров", "💎 Value Bets"])

# ─────────────────────────────────────────────
#  TAB 1: TABLE
# ─────────────────────────────────────────────
with tab_data:
    st.markdown(f"#### Коэффициенты: {market_label}")

    # Filter by match
    match_options = ["Все матчи"] + sorted(df["Матч"].unique().tolist())
    sel_match = st.selectbox("Фильтр по матчу", match_options)
    if sel_match != "Все матчи":
        show_df = df[df["Матч"] == sel_match].copy()
    else:
        show_df = df.copy()

    # Drop internal cols
    display_cols = [c for c in show_df.columns if not c.startswith("_")]
    show_df = show_df[display_cols]

    # Color positive/negative american odds
    st.dataframe(
        show_df,
        use_container_width=True,
        hide_index=True,
        height=min(400, 56 + len(show_df) * 35),
    )

    # Download button
    csv = show_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "⬇️ Скачать CSV",
        data=csv,
        file_name=f"nfl_odds_{market_key}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv",
    )

# ─────────────────────────────────────────────
#  TAB 2: COMPARE CHARTS
# ─────────────────────────────────────────────
with tab_compare:
    st.markdown("#### Сравнение коэффициентов по букмекерам")

    match_list = sorted(df["Матч"].unique().tolist())
    sel_match2 = st.selectbox("Выбери матч", match_list, key="match_compare")
    mdf = df[df["Матч"] == sel_match2].copy()

    if market_key == "h2h":
        home_team = mdf["Хозяева"].iloc[0]
        away_team = mdf["Гости"].iloc[0]

        # Convert american to decimal for chart
        mdf["Dec Хозяева"] = mdf["Odds Хозяева (Am)"].apply(
            lambda x: american_to_decimal(float(x)) if x is not None and str(x) != "nan" else None
        )
        mdf["Dec Гости"] = mdf["Odds Гости (Am)"].apply(
            lambda x: american_to_decimal(float(x)) if x is not None and str(x) != "nan" else None
        )

        fig = go.Figure()
        fig.add_trace(go.Bar(
            name=home_team,
            x=mdf["Букмекер"],
            y=mdf["Dec Хозяева"],
            marker_color="#00b4d8",
            text=mdf["Odds Хозяева (Am)"].apply(
                lambda x: (f"+{int(x)}" if float(x) >= 0 else str(int(x))) if x is not None and str(x) != "nan" else ""
            ),
            textposition="outside",
        ))
        fig.add_trace(go.Bar(
            name=away_team,
            x=mdf["Букмекер"],
            y=mdf["Dec Гости"],
            marker_color="#f97316",
            text=mdf["Odds Гости (Am)"].apply(
                lambda x: (f"+{int(x)}" if float(x) >= 0 else str(int(x))) if x is not None and str(x) != "nan" else ""
            ),
            textposition="outside",
        ))
        fig.update_layout(
            title=f"Decimal Odds: {sel_match2}",
            barmode="group",
            plot_bgcolor="#0d1b2a",
            paper_bgcolor="#0d1b2a",
            font_color="#e2e8f0",
            xaxis_title="Букмекер",
            yaxis_title="Decimal Odds",
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            height=420,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Implied probability radar
        st.markdown("##### Implied Probability (no-vig) по букмекерам")
        prob_rows = []
        for _, row in mdf.iterrows():
            home_am = row.get("Odds Хозяева (Am)")
            away_am = row.get("Odds Гости (Am)")
            if home_am is None or away_am is None or str(home_am) == "nan" or str(away_am) == "nan":
                continue
            h_dec = american_to_decimal(float(home_am))
            a_dec = american_to_decimal(float(away_am))
            h_impl = decimal_to_implied(h_dec)
            a_impl = decimal_to_implied(a_dec)
            nv = no_vig_prob([h_impl, a_impl])
            prob_rows.append({
                "Букмекер": row["Букмекер"],
                f"{home_team} (no-vig %)": nv[0],
                f"{away_team} (no-vig %)": nv[1],
            })

        if prob_rows:
            pf = pd.DataFrame(prob_rows)
            fig2 = go.Figure()
            fig2.add_trace(go.Bar(
                name=home_team,
                x=pf["Букмекер"],
                y=pf[f"{home_team} (no-vig %)"],
                marker_color="#00b4d8",
                text=pf[f"{home_team} (no-vig %)"].apply(lambda x: f"{x:.1f}%"),
                textposition="outside",
            ))
            fig2.add_trace(go.Bar(
                name=away_team,
                x=pf["Букмекер"],
                y=pf[f"{away_team} (no-vig %)"],
                marker_color="#f97316",
                text=pf[f"{away_team} (no-vig %)"].apply(lambda x: f"{x:.1f}%"),
                textposition="outside",
            ))
            fig2.update_layout(
                title="No-Vig вероятности победы",
                barmode="group",
                plot_bgcolor="#0d1b2a",
                paper_bgcolor="#0d1b2a",
                font_color="#e2e8f0",
                xaxis_title="Букмекер",
                yaxis_title="Вероятность %",
                yaxis_range=[0, 100],
                legend=dict(bgcolor="rgba(0,0,0,0)"),
                height=380,
            )
            st.plotly_chart(fig2, use_container_width=True)

    elif market_key == "spreads":
        fig = go.Figure()
        for team_col, odds_col, color in [
            ("Хозяева", "Odds Хозяева (Am)", "#00b4d8"),
            ("Гости", "Odds Гости (Am)", "#f97316"),
        ]:
            team = mdf[team_col].iloc[0]
            dec_vals = mdf[odds_col].apply(
                lambda x: american_to_decimal(float(x)) if x is not None and str(x) != "nan" else None
            )
            fig.add_trace(go.Bar(
                name=team,
                x=mdf["Букмекер"],
                y=dec_vals,
                marker_color=color,
            ))
        fig.update_layout(
            title=f"Spread Odds: {sel_match2}",
            barmode="group",
            plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a", font_color="#e2e8f0",
            height=420,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Spread line comparison
        st.markdown("##### Линии спреда по букмекерам")
        spread_data = mdf[["Букмекер", "Спред Хозяева", "Спред Гости"]].dropna()
        if not spread_data.empty:
            fig3 = go.Figure()
            fig3.add_trace(go.Scatter(
                x=spread_data["Букмекер"],
                y=spread_data["Спред Хозяева"].astype(float),
                mode="lines+markers+text",
                name=mdf["Хозяева"].iloc[0],
                line=dict(color="#00b4d8", width=2),
                marker=dict(size=10),
                text=spread_data["Спред Хозяева"].astype(float).apply(lambda x: f"{x:+.1f}"),
                textposition="top center",
            ))
            fig3.update_layout(
                title="Спред линии",
                plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a", font_color="#e2e8f0",
                height=320,
            )
            st.plotly_chart(fig3, use_container_width=True)

    elif market_key == "totals":
        fig = go.Figure()
        over_dec = mdf["Odds Over (Am)"].apply(
            lambda x: american_to_decimal(float(x)) if x is not None and str(x) != "nan" else None
        )
        under_dec = mdf["Odds Under (Am)"].apply(
            lambda x: american_to_decimal(float(x)) if x is not None and str(x) != "nan" else None
        )
        fig.add_trace(go.Bar(name="Over", x=mdf["Букмекер"], y=over_dec, marker_color="#22c55e"))
        fig.add_trace(go.Bar(name="Under", x=mdf["Букмекер"], y=under_dec, marker_color="#ef4444"))
        fig.update_layout(
            title=f"Totals Odds: {sel_match2}",
            barmode="group",
            plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a", font_color="#e2e8f0",
            height=420,
        )
        st.plotly_chart(fig, use_container_width=True)

        # Total line comparison
        totals_lines = mdf[["Букмекер", "Тотал Линия"]].dropna()
        if not totals_lines.empty:
            fig4 = go.Figure()
            fig4.add_trace(go.Scatter(
                x=totals_lines["Букмекер"],
                y=totals_lines["Тотал Линия"].astype(float),
                mode="lines+markers+text",
                name="Тотал",
                line=dict(color="#a855f7", width=2),
                marker=dict(size=10),
                text=totals_lines["Тотал Линия"].astype(float).apply(lambda x: str(x)),
                textposition="top center",
            ))
            fig4.update_layout(
                title="Линии тотала по букмекерам",
                plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a", font_color="#e2e8f0",
                height=300,
            )
            st.plotly_chart(fig4, use_container_width=True)

    # Best odds table
    st.markdown("##### 🏆 Лучшие коэффициенты")
    if market_key == "h2h":
        best_rows = []
        for team_col, odds_col in [("Хозяева", "Odds Хозяева (Am)"), ("Гости", "Odds Гости (Am)")]:
            sub = mdf[[team_col, "Букмекер", odds_col]].dropna()
            sub = sub[sub[odds_col].apply(lambda x: str(x) != "nan")]
            if sub.empty:
                continue
            sub["_dec"] = sub[odds_col].apply(lambda x: american_to_decimal(float(x)))
            best_idx = sub["_dec"].idxmax()
            best_row = sub.loc[best_idx]
            am_val = float(best_row[odds_col])
            best_rows.append({
                "Команда": best_row[team_col],
                "Лучший букмекер": best_row["Букмекер"],
                "Лучший Odds (Am)": f"+{int(am_val)}" if am_val >= 0 else str(int(am_val)),
                "Decimal": american_to_decimal(am_val),
                "Implied %": f"{decimal_to_implied(american_to_decimal(am_val))}%",
            })
        if best_rows:
            st.dataframe(pd.DataFrame(best_rows), use_container_width=True, hide_index=True)

# ─────────────────────────────────────────────
#  TAB 3: VALUE BETS
# ─────────────────────────────────────────────
with tab_value:
    st.markdown("#### 💎 Value Bets — ставки с положительным EV")

    if market_key != "h2h":
        st.info("ℹ️ Value Bet расчёт доступен для рынка **H2H (Moneyline)**. Переключи рынок в боковой панели.")
    else:
        st.markdown("""
        **Методология:**
        1. Конвертируем American Odds → Decimal → Implied %
        2. Убираем маржу букмекера (no-vig нормализация)
        3. Рассчитываем **EV Edge** = `fair_prob × decimal_odds − 1`
        4. Если EV > выбранного порога — это **Value Bet** ✅
        """)

        vdf = compute_value_bets(df, market_key, min_edge)

        if vdf.empty:
            st.info(f"Нет value bets с EV Edge ≥ {min_edge}%. Попробуй снизить порог или выбрать больше букмекеров.")
        else:
            st.success(f"✅ Найдено {len(vdf)} value bet(s) с EV Edge ≥ {min_edge}%")
            st.dataframe(vdf, use_container_width=True, hide_index=False, height=min(500, 56 + len(vdf) * 38))

        # EV visualization for all matches
        st.markdown("---")
        st.markdown("##### EV Edge по матчам и букмекерам")

        ev_rows = []
        for _, row in df[df["Матч"].notna()].iterrows():
            home_am = row.get("Odds Хозяева (Am)")
            away_am = row.get("Odds Гости (Am)")
            if home_am is None or away_am is None:
                continue
            try:
                h_dec = american_to_decimal(float(home_am))
                a_dec = american_to_decimal(float(away_am))
                h_impl = decimal_to_implied(h_dec)
                a_impl = decimal_to_implied(a_dec)
                nv = no_vig_prob([h_impl, a_impl])
                h_edge = calc_value_edge(nv[0], h_dec) * 100
                a_edge = calc_value_edge(nv[1], a_dec) * 100
                ev_rows.append({
                    "Матч": row["Матч"],
                    "Букмекер": row["Букмекер"],
                    "EV Хозяева %": round(h_edge, 2),
                    "EV Гости %": round(a_edge, 2),
                })
            except Exception:
                continue

        if ev_rows:
            evf = pd.DataFrame(ev_rows)
            fig_ev = px.scatter(
                evf,
                x="Букмекер",
                y="EV Хозяева %",
                color="Матч",
                size=evf["EV Хозяева %"].abs() + 1,
                hover_data=["Матч", "Букмекер", "EV Хозяева %", "EV Гости %"],
                title="EV Edge Хозяева (%) по букмекерам",
                template="plotly_dark",
                height=400,
            )
            fig_ev.add_hline(y=0, line_dash="dash", line_color="#ef4444", annotation_text="EV = 0")
            fig_ev.update_layout(
                plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a",
            )
            st.plotly_chart(fig_ev, use_container_width=True)

# ─────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Данные: [The Odds API](https://the-odds-api.com) · "
    "Этот дашборд создан исключительно в образовательных целях. "
    "Ставки на спорт сопряжены с риском потери средств."
)
