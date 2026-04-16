"""
Sports Odds Dashboard
━━━━━━━━━━━━━━━━━━━━
- NFL · Football (9 leagues) · NBA
- Живые коэффициенты (The Odds API)
- Auto-refresh каждые 5 минут
- Value Bets с EV Edge + Gmail-уведомления
- Live Scores (ESPN Public API)
- История ставок в Google Sheets
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import gspread
    from google.oauth2.service_account import Credentials as SACredentials
    GSPREAD_OK = True
except ImportError:
    GSPREAD_OK = False

# ── Импорт чистых функций из utils.py ────────
from utils import (
    build_betting_signals as _build_betting_signals_v2,
    compute_value_bets    as _compute_value_bets_v2,
    find_arb_in_group,
    arb_stakes,
    arb_percentage,
    kelly_stake,
    kelly_fraction,
    sport_ev_threshold,
    sharp_books_in_group,
    SPORT_EV_THRESHOLDS,
    fetch_historical_odds,
    parse_historical_to_df,
)

# ── Импорт auth модуля ──────────────────────
from auth import (
    run_auth_gate,
    render_user_badge,
    is_tab_locked,
    render_upgrade_banner,
    get_available_sports,
    apply_rows_limit,
    render_rows_limit_banner,
)

# ─────────────────────────────────────────────
#  PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Sports Odds Dashboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="collapsed",   # на мобиле sidebar свёрнут по умолчанию
    menu_items={
        "Get help": "https://the-odds-api.com",
        "About": "🏆 Sports Odds Dashboard — Value Bets & Arbitrage Scanner",
    }
)

# ── AUTH GATE — проверка входа ────────────
run_auth_gate()  # 🔒 Login required

# ─────────────────────────────────────────────
#  CONSTANTS
# ─────────────────────────────────────────────
ODDS_BASE    = "https://api.the-odds-api.com/v4"
ESPN_BASE    = "https://site.api.espn.com/apis/site/v2/sports"
AUTO_REFRESH = 300   # seconds (5 min)
VALUE_THRESHOLD = 5.0  # EV% for Gmail alerts

ESPN_LEAGUES = {
    "🏈 NFL":  {"path": "football/nfl",     "league_slug": "nfl",   "period_name": "Q"},
    "⚽ EPL":  {"path": "soccer/eng.1",     "league_slug": "eng.1", "period_name": "min"},
    "🏀 NBA":  {"path": "basketball/nba",   "league_slug": "nba",   "period_name": "Q"},
}

SPORTS_CATALOGUE = {
    "🏈 NFL":                        {"key": "americanfootball_nfl",          "has_draw": False, "color": "#00b4d8", "markets": ["H2H (Moneyline)", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ EPL (English Premier League)":{"key": "soccer_epl",                   "has_draw": True,  "color": "#4ade80", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ La Liga (Spain)":             {"key": "soccer_spain_la_liga",          "has_draw": True,  "color": "#4ade80", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ Bundesliga (Germany)":        {"key": "soccer_germany_bundesliga",     "has_draw": True,  "color": "#4ade80", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ Serie A (Italy)":             {"key": "soccer_italy_serie_a",          "has_draw": True,  "color": "#4ade80", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ Ligue 1 (France)":            {"key": "soccer_france_ligue_one",       "has_draw": True,  "color": "#4ade80", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ UEFA Champions League":       {"key": "soccer_uefa_champs_league",     "has_draw": True,  "color": "#facc15", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ UEFA Europa League":          {"key": "soccer_uefa_europa_league",     "has_draw": True,  "color": "#f97316", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "⚽ MLS (USA)":                   {"key": "soccer_usa_mls",                "has_draw": True,  "color": "#4ade80", "markets": ["H2H / 1X2", "Spreads (Handicap)", "Totals (Over/Under)"]},
    "🏀 NBA":                         {"key": "basketball_nba",               "has_draw": False, "color": "#f97316", "markets": ["H2H (Moneyline)", "Spreads (Handicap)", "Totals (Over/Under)"]},
}

MARKET_KEY_MAP = {
    "H2H (Moneyline)": "h2h",
    "H2H / 1X2":       "h2h",
    "Spreads (Handicap)": "spreads",
    "Totals (Over/Under)": "totals",
}

REGION_MAP = {
    "US (DraftKings, FanDuel…)": "us",
    "US Extended":               "us2",
    "UK":                        "uk",
    "EU (Pinnacle, Unibet…)":    "eu",
    "UK + EU":                   "uk,eu",
    "Все регионы":               "us,us2,uk,eu",
}

US_BM = ["DraftKings","FanDuel","BetMGM","Caesars","BetOnline.ag","William Hill US","BetRivers","Bovada","PointsBet US","Barstool"]
EU_BM = ["Betfair","Unibet","Paddy Power","Bet365","Sky Bet","Ladbrokes","Coral","Betway","888sport","Pinnacle","1xBet"]

MSK = pytz.timezone("Europe/Moscow")

# ─────────────────────────────────────────────
#  CSS — PREMIUM MOBILE-FIRST
# ─────────────────────────────────────────────
st.markdown("""
<style>
/* ── Google Fonts ───────────────────────────── */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

/* ── Global ─────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* ── Viewport meta override for mobile ─────── */
* { box-sizing: border-box; }

/* ── Main container max-width for large screens */
.block-container {
    max-width: 1200px !important;
    padding: 1rem 1rem 4rem !important;  /* bottom pad for mobile nav */
}

/* ── Sidebar ─────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0d1b2a 0%, #0f2137 100%) !important;
    border-right: 1px solid #1e3a5f !important;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 {
    color: #a78bfa; font-size: 1rem; font-weight: 700; letter-spacing: .5px;
}

/* ── Title gradient ───────────────────────────── */
.main-title {
    font-size: clamp(1.5rem, 5vw, 2.4rem);
    font-weight: 900;
    background: linear-gradient(135deg, #a78bfa 0%, #38bdf8 50%, #4ade80 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.2;
    letter-spacing: -.5px;
}
.subtitle {
    font-size: clamp(.75rem, 2.5vw, .9rem);
    color: #64748b;
    margin-top: 2px;
    letter-spacing: .3px;
}

/* ── Metric cards ────────────────────────────── */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #1e293b, #0f1f33);
    border: 1px solid #1e3a5f;
    border-radius: 14px;
    padding: 12px 16px !important;
    transition: border-color .2s, transform .1s;
}
[data-testid="stMetric"]:hover {
    border-color: #a78bfa;
    transform: translateY(-1px);
}
[data-testid="stMetricValue"] {
    font-size: clamp(1.2rem, 4vw, 1.8rem) !important;
    font-weight: 800 !important;
    color: #e2e8f0 !important;
}
[data-testid="stMetricLabel"] {
    font-size: .75rem !important;
    color: #64748b !important;
    text-transform: uppercase;
    letter-spacing: .5px;
}

/* ── Tabs ────────────────────────────────────── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: #0d1b2a;
    border-radius: 14px;
    padding: 4px;
    gap: 2px;
    border: 1px solid #1e3a5f;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none;
    flex-wrap: nowrap;
}
[data-testid="stTabs"] [data-baseweb="tab-list"]::-webkit-scrollbar { display:none; }
[data-testid="stTabs"] [role="tab"] {
    background: transparent;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: clamp(.75rem, 2.2vw, .875rem);
    font-weight: 600;
    color: #64748b;
    white-space: nowrap;
    min-width: fit-content;
    transition: all .2s;
    border: none !important;
}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
    background: linear-gradient(135deg, #7c3aed, #2563eb) !important;
    color: #fff !important;
    box-shadow: 0 2px 12px rgba(124,58,237,.4);
}
[data-testid="stTabs"] [role="tab"]:hover:not([aria-selected="true"]) {
    background: #1e293b;
    color: #e2e8f0;
}

/* ── Buttons ─────────────────────────────────── */
[data-testid="stButton"] > button {
    border-radius: 12px !important;
    font-weight: 600 !important;
    font-size: .9rem !important;
    transition: all .2s !important;
    min-height: 44px !important;   /* touch target 44px */
}
[data-testid="stButton"] > button[kind="primary"] {
    background: linear-gradient(135deg, #7c3aed, #2563eb) !important;
    border: none !important;
    box-shadow: 0 4px 16px rgba(124,58,237,.35) !important;
}
[data-testid="stButton"] > button[kind="primary"]:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(124,58,237,.5) !important;
}
[data-testid="stButton"] > button[kind="secondary"] {
    background: #1e293b !important;
    border: 1px solid #334155 !important;
    color: #e2e8f0 !important;
}

/* ── Inputs ──────────────────────────────────── */
[data-testid="stTextInput"] > div > input,
[data-testid="stNumberInput"] > div > input,
[data-testid="stSelectbox"] > div > div {
    border-radius: 10px !important;
    border: 1px solid #334155 !important;
    background: #0f1f33 !important;
    color: #e2e8f0 !important;
    font-size: .9rem !important;
    min-height: 44px !important;
}
[data-testid="stSlider"] {
    padding-top: 4px;
}

/* ── DataFrames ──────────────────────────────── */
[data-testid="stDataFrame"] {
    border-radius: 14px;
    overflow: hidden;
    border: 1px solid #1e3a5f;
}
[data-testid="stDataFrame"] table {
    font-size: clamp(.75rem, 2vw, .875rem) !important;
}

/* ── Live dot animation ──────────────────────── */
.live-dot {
    display: inline-block; width: 9px; height: 9px;
    border-radius: 50%; background: #22c55e;
    box-shadow: 0 0 8px #22c55e;
    animation: pulse 1.4s infinite;
    margin-right: 6px; vertical-align: middle;
}
@keyframes pulse {
    0%,100%{ opacity:1; transform:scale(1); }
    50%{ opacity:.4; transform:scale(1.4); }
}

/* ── Score cards ─────────────────────────────── */
.score-card {
    background: linear-gradient(135deg, #1e3a5f 0%, #0d1b2a 100%);
    border: 1px solid #334155;
    border-radius: 16px;
    padding: 16px 20px;
    margin-bottom: 12px;
    transition: border-color .2s, transform .15s;
}
.score-card:hover { transform: translateY(-2px); border-color: #475569; }
.score-live  { border-color: #22c55e !important; box-shadow: 0 0 16px rgba(34,197,94,.12); }
.score-final { border-color: #475569 !important; opacity: .85; }
.score-pre   { border-color: #3b82f6 !important; }
.team-name   { font-size: clamp(.85rem,2.5vw,1rem); font-weight: 700; color: #e2e8f0; }
.team-score  { font-size: clamp(1.3rem,4vw,1.8rem); font-weight: 900; color: #00b4d8; font-variant-numeric: tabular-nums; }
.status-live { color: #22c55e; font-size: .78rem; font-weight: 700; text-transform: uppercase; letter-spacing: .5px; }
.status-fin  { color: #64748b; font-size: .78rem; }
.status-pre  { color: #60a5fa; font-size: .78rem; }

/* ── Timer bar ───────────────────────────────── */
.timer-bar {
    background: #1e293b;
    border-radius: 10px;
    padding: 8px 14px;
    font-size: .82rem;
    color: #94a3b8;
    border: 1px solid #334155;
}

/* ── Bet signal cards ────────────────────────── */
.bet-card {
    border-radius: 16px;
    padding: 18px 20px;
    margin-bottom: 14px;
    transition: transform .15s;
}
.bet-card:hover { transform: translateY(-2px); }

/* ── Value badge ─────────────────────────────── */
.value-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 20px;
    font-size: .75rem;
    font-weight: 700;
    background: linear-gradient(135deg,#065f46,#047857);
    color: #4ade80;
}

/* ── Mobile ─────────────────────────────────── */
@media (max-width: 768px) {
    .block-container { padding: .75rem .75rem 3.5rem !important; }

    /* Metric cards: wrap nicely in a 2-col grid */
    [data-testid="stMetricValue"] { font-size: 1.25rem !important; }
    [data-testid="stMetricLabel"] { font-size: .7rem !important; }
    [data-testid="stMetric"] { padding: 10px 12px !important; }

    /* Allow columns to wrap — 2-per-row on phone */
    [data-testid="column"] {
        min-width: calc(50% - 8px) !important;
        flex: 1 1 calc(50% - 8px) !important;
    }

    /* Larger touch targets for buttons */
    [data-testid="stButton"] > button {
        min-height: 48px !important;
        font-size: .9rem !important;
        border-radius: 14px !important;
    }

    /* Scrollable tabs, smaller font */
    [data-testid="stTabs"] [data-baseweb="tab-list"] {
        padding: 3px;
        border-radius: 12px;
        gap: 1px;
    }
    [data-testid="stTabs"] [role="tab"] {
        padding: 6px 10px;
        font-size: .76rem;
    }

    /* Dataframe horizontal scroll */
    [data-testid="stDataFrame"] {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
    }

    /* Inputs full-width */
    [data-testid="stTextInput"],
    [data-testid="stNumberInput"],
    [data-testid="stSelectbox"] { width: 100% !important; }

    /* Score cards compact */
    .score-card { padding: 12px 14px; }
    .team-name  { font-size: .85rem; }
    .team-score { font-size: 1.3rem; }

    /* Bet cards compact */
    .bet-card { padding: 14px 16px; }

    /* Header compact */
    .main-title { letter-spacing: -.3px; }
}

/* ── Very small screens (≤ 480px) ───────────── */
@media (max-width: 480px) {
    [data-testid="stTabs"] [role="tab"] {
        padding: 5px 8px;
        font-size: .72rem;
    }
    [data-testid="stMetricValue"] { font-size: 1.1rem !important; }
    .block-container { padding: .5rem .5rem 3rem !important; }
}

/* ── Expander ────────────────────────────────── */
[data-testid="stExpander"] {
    border-radius: 12px !important;
    border: 1px solid #1e3a5f !important;
    background: #0d1b2a !important;
}

/* ── Alerts / info boxes ─────────────────────── */
[data-testid="stAlert"] {
    border-radius: 12px !important;
}

/* ── Divider ─────────────────────────────────── */
hr { border-color: #1e3a5f !important; margin: 1rem 0 !important; }

/* ── Scrollbar (desktop) ─────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0d1b2a; }
::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #475569; }

/* ── Progress bar (auto-refresh) ────────────── */
[data-testid="stProgress"] > div > div {
    background: linear-gradient(90deg, #7c3aed, #38bdf8) !important;
    border-radius: 4px !important;
}
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  LIGHT THEME CSS (applied dynamically after session_state is ready)
# ─────────────────────────────────────────────
LIGHT_CSS = """
<style>
/* ── LIGHT THEME — CSS VARIABLES ───────────────────── */
:root {
  --card-bg:       #ffffff;
  --card-bg2:      #f1f5f9;
  --card-border:   #cbd5e1;
  --text-primary:  #1e293b;
  --text-secondary:#475569;
  --text-muted:    #64748b;
  --surface:       #f8fafc;
  --surface2:      #f1f5f9;
}

html, body, [class*="css"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.stApp, .main {
    background-color: #f8fafc !important;
    color: #1e293b !important;
}
.block-container { background-color: #f8fafc !important; }

/* All text everywhere */
p, span, div, label, li, h1, h2, h3, h4, h5, h6,
[data-testid="stMarkdownContainer"],
[data-testid="stMarkdownContainer"] p,
[data-testid="stMarkdownContainer"] span {
    color: #1e293b !important;
}

/* Sidebar */
[data-testid="stSidebar"],
[data-testid="stSidebar"] > div {
    background: linear-gradient(180deg, #f1f5f9 0%, #e2e8f0 100%) !important;
    border-right: 1px solid #cbd5e1 !important;
}
[data-testid="stSidebar"] * { color: #1e293b !important; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h2 { color: #7c3aed !important; }

/* Metric cards */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #ffffff, #f1f5f9) !important;
    border: 1px solid #cbd5e1 !important;
}
[data-testid="stMetric"]:hover  { border-color: #7c3aed !important; }
[data-testid="stMetricValue"]   { color: #1e293b !important; }
[data-testid="stMetricLabel"]   { color: #64748b !important; }
[data-testid="stMetricDelta"]   { color: #16a34a !important; }

/* Tabs */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: #f1f5f9 !important;
    border: 1px solid #cbd5e1 !important;
}
[data-testid="stTabs"] [role="tab"]                              { color: #475569 !important; }
[data-testid="stTabs"] [role="tab"]:hover:not([aria-selected="true"]) {
    background: #e2e8f0 !important; color: #1e293b !important;
}

/* Inputs / selects */
[data-testid="stTextInput"] > div,
[data-testid="stTextInput"] > div > input,
[data-testid="stNumberInput"] > div,
[data-testid="stNumberInput"] > div > input,
[data-testid="stSelectbox"] > div > div,
[data-testid="stMultiSelect"] > div,
[data-testid="stRadio"] {
    background: #ffffff !important;
    border-color: #cbd5e1 !important;
    color: #1e293b !important;
}
input, select, textarea { color: #1e293b !important; background: #fff !important; }

/* DataFrame */
[data-testid="stDataFrame"] { border: 1px solid #cbd5e1 !important; }
[data-testid="stDataFrame"] * { color: #1e293b !important; }

/* Score / bet cards — CSS class overrides */
.score-card {
    background: linear-gradient(135deg, #f1f5f9 0%, #ffffff 100%) !important;
    border-color: #cbd5e1 !important; color: #1e293b !important;
}
.team-name  { color: #1e293b !important; }
.team-score { color: #2563eb !important; }
.status-fin { color: #64748b !important; }
.status-pre { color: #2563eb !important; }
.bet-card * { color: #1e293b !important; }

/* ── INLINE BET/SIGNAL CARDS (hardcoded backgrounds) ──────────── */
/* Override dark card backgrounds injected via st.markdown */
[data-testid="stMarkdownContainer"] > div > div[style*="background:#1e293b"],
[data-testid="stMarkdownContainer"] > div > div[style*="background:#1a1a2e"],
[data-testid="stMarkdownContainer"] > div > div[style*="background:#0d2a1a"],
[data-testid="stMarkdownContainer"] > div > div[style*="background:#2a1a00"],
[data-testid="stMarkdownContainer"] > div > div[style*="background:#0d1b2a"],
[data-testid="stMarkdownContainer"] > div > div[style*="background:#111827"],
[data-testid="stMarkdownContainer"] > div > div[style*="background:#0f172a"],
[data-testid="stMarkdownContainer"] > div > div[style*="background:#0f1f33"] {
    background: #ffffff !important;
    border-color: #cbd5e1 !important;
    color: #1e293b !important;
}
[data-testid="stMarkdownContainer"] div[style*="color:#94a3b8"],
[data-testid="stMarkdownContainer"] div[style*="color:#64748b"],
[data-testid="stMarkdownContainer"] span[style*="color:#94a3b8"],
[data-testid="stMarkdownContainer"] span[style*="color:#64748b"] {
    color: #475569 !important;
}
[data-testid="stMarkdownContainer"] div[style*="color:#e2e8f0"],
[data-testid="stMarkdownContainer"] span[style*="color:#e2e8f0"] {
    color: #1e293b !important;
}
/* Sub-cell cards in signals */
[data-testid="stMarkdownContainer"] div[style*="border-radius:8px"] {
    background: #f1f5f9 !important;
    color: #1e293b !important;
}
[data-testid="stMarkdownContainer"] div[style*="border-radius:8px"] div {
    color: #1e293b !important;
}
/* Progress bars in cards */
[data-testid="stMarkdownContainer"] div[style*="background:#0f172a"] {
    background: #e2e8f0 !important;
}

/* Expander */
[data-testid="stExpander"] {
    background: #f1f5f9 !important;
    border: 1px solid #cbd5e1 !important;
}
[data-testid="stExpander"] * { color: #1e293b !important; }

/* Alert */
[data-testid="stAlert"]   { background: #eff6ff !important; color: #1e3a8a !important; }
[data-testid="stAlert"] * { color: #1e3a8a !important; }

/* Divider + scrollbar */
hr { border-color: #e2e8f0 !important; }
::-webkit-scrollbar-track { background: #f1f5f9 !important; }
::-webkit-scrollbar-thumb { background: #cbd5e1 !important; }

/* Timer bar + subtitle */
.subtitle   { color: #475569 !important; }
.timer-bar  { background: #f1f5f9 !important; border-color: #cbd5e1 !important; color: #475569 !important; }
.value-badge { background: linear-gradient(135deg,#d1fae5,#a7f3d0) !important; color: #065f46 !important; }
.live-dot   { box-shadow: 0 0 8px #16a34a !important; }

/* Toggle + checkbox */
[data-testid="stToggle"] * { color: #1e293b !important; }

/* Caption / small text */
[data-testid="stCaptionContainer"] * { color: #64748b !important; }

/* Select dropdown open */
[data-baseweb="popover"] [role="option"] {
    background: #ffffff !important; color: #1e293b !important;
}
[data-baseweb="popover"] [role="option"]:hover {
    background: #f1f5f9 !important;
}
</style>
"""

# ─────────────────────────────────────────────
#  HELPERS — MATH
# ─────────────────────────────────────────────
def american_to_decimal(v: float) -> float:
    return round(v/100+1, 4) if v >= 0 else round(100/abs(v)+1, 4)

def decimal_to_implied(d: float) -> float:
    return round(1/d*100, 2) if d > 0 else 0.0

def no_vig_prob(probs: list) -> list:
    t = sum(probs)
    return [round(p/t*100, 2) for p in probs] if t else probs

def ev_edge(fair: float, dec: float) -> float:
    return round(fair/100*dec - 1, 4)

def fmt_am(v) -> str:
    try:
        f = float(v)
        return f"+{int(f)}" if f >= 0 else str(int(f))
    except Exception:
        return str(v)

def local_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso.replace("Z","+00:00"))
        return dt.astimezone(MSK).strftime("%d.%m %H:%M МСК")
    except Exception:
        return iso

# ─────────────────────────────────────────────
#  HELPERS — ODDS API
# ─────────────────────────────────────────────
@st.cache_data(ttl=AUTO_REFRESH, show_spinner=False)
def fetch_odds(api_key: str, sport_key: str, regions: str, market_key: str):
    r = requests.get(
        f"{ODDS_BASE}/sports/{sport_key}/odds",
        params=dict(apiKey=api_key, regions=regions, markets=market_key,
                    oddsFormat="american", dateFormat="iso"),
        timeout=15,
    )
    remaining = r.headers.get("x-requests-remaining","?")
    used      = r.headers.get("x-requests-used","?")
    if r.status_code == 200:
        return r.json(), remaining, used
    return None, remaining, used

def parse_to_df(events, market_key, has_draw):
    rows = []
    for ev in events:
        home, away = ev["home_team"], ev["away_team"]
        t = local_time(ev.get("commence_time",""))
        for bm in ev.get("bookmakers",[]):
            for mkt in bm.get("markets",[]):
                if mkt["key"] != market_key: continue
                oc = {o["name"]: o for o in mkt["outcomes"]}
                base = {"Матч": f"{away} @ {home}", "Время": t,
                        "Букмекер": bm.get("title",bm["key"]),
                        "Хозяева": home, "Гости": away, "_event_id": ev["id"]}
                if market_key == "h2h":
                    row = {**base,
                           "Odds Хозяева (Am)": oc.get(home,{}).get("price"),
                           "Odds Гости (Am)":   oc.get(away,{}).get("price"),
                           "Odds Ничья (Am)":   oc.get("Draw",{}).get("price") if has_draw else None}
                elif market_key == "spreads":
                    ho, ao = oc.get(home,{}), oc.get(away,{})
                    row = {**base,
                           "Спред Хозяева": ho.get("point"), "Odds Хозяева (Am)": ho.get("price"),
                           "Спред Гости":   ao.get("point"), "Odds Гости (Am)":   ao.get("price")}
                elif market_key == "totals":
                    ov = next((o for o in mkt["outcomes"] if o["name"]=="Over"), {})
                    un = next((o for o in mkt["outcomes"] if o["name"]=="Under"), {})
                    row = {**base, "Тотал Линия": ov.get("point"),
                           "Odds Over (Am)": ov.get("price"), "Odds Under (Am)": un.get("price")}
                else: continue
                rows.append(row)
    return pd.DataFrame(rows)

# [REMOVED: old inline def build_betting_signals(df: pd.DataFrame, has_dr]


# [REMOVED: old inline def compute_value_bets(df, has_draw, min_edge_pct)]

# ─────────────────────────────────────────────
#  HELPERS — GMAIL
# ─────────────────────────────────────────────
def send_gmail_alert(sender_email: str, sender_password: str, recipient: str,
                     vdf: pd.DataFrame, sport_label: str):
    """Отправляет HTML письмо с таблицей value bets через Gmail SMTP."""
    if vdf.empty: return False, "Нет value bets для отправки"
    try:
        rows_html = ""
        for _, row in vdf.iterrows():
            rows_html += f"""
            <tr>
              <td>{row['Матч']}</td>
              <td>{row['Время']}</td>
              <td>{row['Букмекер']}</td>
              <td><b>{row['Исход']}</b></td>
              <td>{row['Odds (Am)']}</td>
              <td>{row['Odds (Dec)']}</td>
              <td>{row['Implied %']}</td>
              <td>{row['No-Vig Fair %']}</td>
              <td style="color:#4ade80;font-weight:bold">{row['EV Edge %']}</td>
            </tr>"""
        now_str = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
        html = f"""
        <html><body style="font-family:Arial,sans-serif;background:#0d1b2a;color:#e2e8f0;padding:20px">
          <h2 style="color:#00b4d8">🏆 Sports Odds Dashboard — Value Bets Alert</h2>
          <p>Обнаружены ставки с положительным EV ≥ {VALUE_THRESHOLD}% · {sport_label} · {now_str}</p>
          <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px;background:#1e3a5f">
            <thead style="background:#0077b6;color:#fff">
              <tr>
                <th>Матч</th><th>Время</th><th>Букмекер</th><th>Исход</th>
                <th>Odds (Am)</th><th>Decimal</th><th>Implied %</th>
                <th>No-Vig %</th><th>EV Edge %</th>
              </tr>
            </thead>
            <tbody>{rows_html}</tbody>
          </table>
          <p style="margin-top:16px;color:#94a3b8;font-size:11px">
            ⚠️ Только в образовательных целях. Ставки сопряжены с риском.
          </p>
        </body></html>"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🎯 Value Bets Alert — {sport_label} — EV ≥ {VALUE_THRESHOLD}%"
        msg["From"]    = sender_email
        msg["To"]      = recipient
        msg.attach(MIMEText(html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as srv:
            srv.login(sender_email, sender_password)
            srv.sendmail(sender_email, recipient, msg.as_string())
        return True, f"✅ Письмо отправлено на {recipient}"
    except smtplib.SMTPAuthenticationError:
        return False, "❌ Ошибка авторизации Gmail. Проверь email и App Password."
    except Exception as e:
        return False, f"❌ Ошибка отправки: {e}"

# ─────────────────────────────────────────────
#  HELPERS — GOOGLE SHEETS
# ─────────────────────────────────────────────

GSHEETS_SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_HEADERS = [
    "Дата", "Время МСК", "Спорт", "Матч", "Букмекер",
    "Исход", "Odds (Am)", "Odds (Dec)", "Implied %",
    "No-Vig Fair %", "EV Edge %",
]


def get_gspread_client():
    """Создаёт авторизованный gspread клиент из st.secrets."""
    if not GSPREAD_OK:
        return None, "gspread не установлен"
    try:
        sa_info = dict(st.secrets["gcp_service_account"])
        creds = SACredentials.from_service_account_info(sa_info, scopes=GSHEETS_SCOPES)
        client = gspread.authorize(creds)
        return client, None
    except KeyError:
        return None, "Секрет gcp_service_account не найден в st.secrets"
    except Exception as e:
        return None, f"Ошибка авторизации: {e}"


def get_or_create_sheet(client, spreadsheet_url: str, sheet_name: str = "ValueBets"):
    """Открывает таблицу и возвращает нужный лист, создаёт если не существует."""
    try:
        wb = client.open_by_url(spreadsheet_url)
    except gspread.SpreadsheetNotFound:
        return None, f"Таблица не найдена: {spreadsheet_url}\nРасшарь её с service account email."
    except Exception as e:
        return None, f"Ошибка открытия таблицы: {e}"

    # Найти или создать лист
    try:
        ws = wb.worksheet(sheet_name)
    except gspread.WorksheetNotFound:
        ws = wb.add_worksheet(title=sheet_name, rows=2000, cols=len(SHEET_HEADERS))
        ws.append_row(SHEET_HEADERS, value_input_option="USER_ENTERED")
        # Форматирование заголовка
        try:
            ws.format("A1:K1", {
                "backgroundColor": {"red": 0.0, "green": 0.47, "blue": 0.84},
                "textFormat": {"bold": True, "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}},
            })
        except Exception:
            pass
    return ws, None


def log_value_bets_to_sheets(vdf: pd.DataFrame, sport_label: str, spreadsheet_url: str) -> tuple:
    """Добавляет найденные value bets в Google Sheets. Возвращает (ok, message, count)."""
    if vdf.empty:
        return False, "Нет данных для логирования", 0

    client, err = get_gspread_client()
    if err:
        return False, err, 0

    ws, err = get_or_create_sheet(client, spreadsheet_url)
    if err:
        return False, err, 0

    now = datetime.now(MSK)
    date_str = now.strftime("%d.%m.%Y")
    time_str = now.strftime("%H:%M")

    rows_to_add = []
    for _, row in vdf.iterrows():
        rows_to_add.append([
            date_str,
            time_str,
            sport_label,
            row.get("Матч", ""),
            row.get("Букмекер", ""),
            str(row.get("Исход", "")).replace("✅ ", ""),
            str(row.get("Odds (Am)", "")),
            str(row.get("Odds (Dec)", "")),
            str(row.get("Implied %", "")),
            str(row.get("No-Vig Fair %", "")),
            str(row.get("EV Edge %", "")),
        ])

    try:
        ws.append_rows(rows_to_add, value_input_option="USER_ENTERED")
        return True, f"✅ Записано {len(rows_to_add)} строк в Google Sheets", len(rows_to_add)
    except Exception as e:
        return False, f"Ошибка записи: {e}", 0


def read_history_from_sheets(spreadsheet_url: str, sheet_name: str = "ValueBets") -> tuple:
    """Читает историю из Google Sheets, возвращает (df, error)."""
    client, err = get_gspread_client()
    if err:
        return pd.DataFrame(), err

    ws, err = get_or_create_sheet(client, spreadsheet_url, sheet_name)
    if err:
        return pd.DataFrame(), err

    try:
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame(columns=SHEET_HEADERS), None
        return pd.DataFrame(data), None
    except Exception as e:
        return pd.DataFrame(), f"Ошибка чтения: {e}"


# ─────────────────────────────────────────────
#  HELPERS — PDF EXPORT
# ─────────────────────────────────────────────

def generate_pdf_report(
    vdf: pd.DataFrame,
    sport_label: str,
    bankroll: float = 1000.0,
) -> bytes:
    """
    Генерирует PDF-отчёт с:
      - Логотипом / заголовком
      - Сводными метриками (кол-во ставок, avg EV, макс EV)
      - Таблицей value bets
      - Горизонтальной bar-диаграммой EV Edge %
    Возвращает bytes PDF-файла.
    """
    import io
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        HRFlowable, KeepTogether,
    )
    from reportlab.graphics.shapes import Drawing, Rect, String, Line
    from reportlab.graphics.charts.barcharts import HorizontalBarChart
    from reportlab.graphics import renderPDF
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=15*mm, bottomMargin=15*mm,
        title=f"Value Bets Report — {sport_label}",
        author="Sports Odds Dashboard",
    )

    # ── Palette ────────────────────────────────────────
    C_BG     = colors.HexColor("#0d1b2a")
    C_ACCENT = colors.HexColor("#00b4d8")
    C_GREEN  = colors.HexColor("#4ade80")
    C_AMBER  = colors.HexColor("#fbbf24")
    C_TEXT   = colors.HexColor("#e2e8f0")
    C_MUTED  = colors.HexColor("#94a3b8")
    C_ROW1   = colors.HexColor("#1e293b")
    C_ROW2   = colors.HexColor("#0f172a")
    C_HEAD   = colors.HexColor("#0077b6")

    styles   = getSampleStyleSheet()
    style_h1 = ParagraphStyle(
        "H1", parent=styles["Normal"],
        fontSize=22, textColor=C_ACCENT,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
        spaceAfter=2*mm,
    )
    style_h2 = ParagraphStyle(
        "H2", parent=styles["Normal"],
        fontSize=13, textColor=C_TEXT,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
        spaceBefore=4*mm, spaceAfter=2*mm,
    )
    style_sub = ParagraphStyle(
        "Sub", parent=styles["Normal"],
        fontSize=9, textColor=C_MUTED,
        fontName="Helvetica", alignment=TA_LEFT,
        spaceAfter=4*mm,
    )
    style_cell = ParagraphStyle(
        "Cell", parent=styles["Normal"],
        fontSize=7.5, textColor=C_TEXT,
        fontName="Helvetica", alignment=TA_LEFT,
        leading=10,
    )
    style_cell_green = ParagraphStyle(
        "CellGreen", parent=style_cell,
        textColor=C_GREEN, fontName="Helvetica-Bold",
    )
    style_cell_head = ParagraphStyle(
        "CellHead", parent=style_cell,
        textColor=colors.white, fontName="Helvetica-Bold",
        alignment=TA_CENTER,
    )

    now_str = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
    story   = []

    # ── Header block ────────────────────────────────────
    story.append(Paragraph("🏆 Sports Odds Dashboard", style_h1))
    story.append(Paragraph(
        f"Value Bets Report · {sport_label} · {now_str} · Банкролл: ${bankroll:,.0f}",
        style_sub,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=C_ACCENT, spaceAfter=4*mm))

    # ── Summary metrics ─────────────────────────────────
    def _parse_ev(s):
        try:
            return float(str(s).replace("+","").replace("%",""))
        except Exception:
            return 0.0

    ev_vals  = vdf["EV Edge %"].apply(_parse_ev) if "EV Edge %" in vdf.columns else pd.Series(dtype=float)
    cnt      = len(vdf)
    avg_ev   = ev_vals.mean() if not ev_vals.empty else 0.0
    max_ev   = ev_vals.max()  if not ev_vals.empty else 0.0
    bk_cnt   = vdf["Букмекер"].nunique() if "Букмекер" in vdf.columns else 0

    metrics_data = [
        [Paragraph("Всего ставок", style_cell_head),
         Paragraph("Ср. EV Edge",  style_cell_head),
         Paragraph("Макс EV Edge", style_cell_head),
         Paragraph("Букмекеров",   style_cell_head)],
        [Paragraph(f"{cnt}",           style_h2),
         Paragraph(f"+{avg_ev:.1f}%",  style_cell_green),
         Paragraph(f"+{max_ev:.1f}%",  style_cell_green),
         Paragraph(f"{bk_cnt}",        style_h2)],
    ]
    pw = doc.width
    metrics_tbl = Table(metrics_data, colWidths=[pw/4]*4, rowHeights=[8*mm, 12*mm])
    metrics_tbl.setStyle(TableStyle([
        ("BACKGROUND",   (0,0), (-1,0),  C_HEAD),
        ("BACKGROUND",   (0,1), (-1,1),  C_ROW1),
        ("ALIGN",        (0,0), (-1,-1), "CENTER"),
        ("VALIGN",       (0,0), (-1,-1), "MIDDLE"),
        ("GRID",         (0,0), (-1,-1), 0.4, C_MUTED),
        ("ROUNDEDCORNERS", [3]),
    ]))
    story.append(metrics_tbl)
    story.append(Spacer(1, 5*mm))

    # ── Value Bets Table ─────────────────────────────────
    story.append(Paragraph("📋 Список Value Bets", style_h2))

    # Колонки для таблицы
    show_cols = ["Матч", "Время", "Букмекер", "Исход", "Odds (Am)",
                 "Odds (Dec)", "Implied %", "No-Vig Fair %", "EV Edge %"]
    # Добавляем Kelly если есть
    kelly_col = next((c for c in vdf.columns if "Kelly Stake" in c), None)
    if kelly_col:
        show_cols.append(kelly_col)
    show_cols = [c for c in show_cols if c in vdf.columns]

    # Ширины колонок (суммарно = doc.width)
    col_w_map = {
        "Матч":        55*mm,
        "Время":       22*mm,
        "Букмекер":    28*mm,
        "Исход":       32*mm,
        "Odds (Am)":   18*mm,
        "Odds (Dec)":  18*mm,
        "Implied %":   18*mm,
        "No-Vig Fair %": 22*mm,
        "EV Edge %":   20*mm,
    }
    if kelly_col:
        col_w_map[kelly_col] = 24*mm
    col_widths = [col_w_map.get(c, 20*mm) for c in show_cols]

    # Масштабируем чтобы влезло
    total_w = sum(col_widths)
    if total_w > pw:
        scale = pw / total_w
        col_widths = [w * scale for w in col_widths]

    # Header row
    tbl_data = [[Paragraph(c, style_cell_head) for c in show_cols]]

    # Data rows
    for i, (_, row) in enumerate(vdf.iterrows()):
        tr = []
        for c in show_cols:
            val = str(row.get(c, ""))
            if c == "EV Edge %":
                tr.append(Paragraph(val, style_cell_green))
            else:
                tr.append(Paragraph(val, style_cell))
        tbl_data.append(tr)

    vbet_tbl = Table(tbl_data, colWidths=col_widths, repeatRows=1)
    row_colors = [("BACKGROUND", (0, i+1), (-1, i+1),
                   C_ROW1 if i % 2 == 0 else C_ROW2)
                  for i in range(len(vdf))]
    vbet_tbl.setStyle(TableStyle([
        ("BACKGROUND",  (0,0), (-1,0),  C_HEAD),
        ("TEXTCOLOR",   (0,0), (-1,0),  colors.white),
        ("ALIGN",       (0,0), (-1,0),  "CENTER"),
        ("VALIGN",      (0,0), (-1,-1), "MIDDLE"),
        ("GRID",        (0,0), (-1,-1), 0.3, colors.HexColor("#334155")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [C_ROW1, C_ROW2]),
        ("FONTSIZE",    (0,0), (-1,-1), 7.5),
        ("TOPPADDING",  (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",(0,0),(-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 4),
    ] + row_colors))
    story.append(vbet_tbl)
    story.append(Spacer(1, 6*mm))

    # ── EV Edge Bar Chart ────────────────────────────────
    if not ev_vals.empty and cnt > 0:
        story.append(Paragraph("📊 График EV Edge %", style_h2))

        # Берём топ-15 по EV
        chart_df = vdf.copy()
        chart_df["_ev"] = ev_vals.values
        chart_df = chart_df.nlargest(min(15, cnt), "_ev")

        labels  = []
        ev_data = []
        for _, r in chart_df.iterrows():
            match_short = str(r.get("Матч", ""))[:28]
            bk_short    = str(r.get("Букмекер", ""))[:12]
            outcome     = str(r.get("Исход", "")).replace("✅ ", "")
            labels.append(f"{match_short} [{bk_short}] {outcome}")
            ev_data.append(r["_ev"])

        chart_h  = max(80, len(labels) * 14)
        chart_w  = min(float(pw), 220*mm)
        drawing  = Drawing(chart_w, chart_h + 20)

        bc = HorizontalBarChart()
        bc.x         = 5
        bc.y         = 10
        bc.height    = chart_h
        bc.width     = chart_w - 10
        bc.data      = [ev_data]
        bc.bars[0].fillColor      = C_GREEN
        bc.bars[0].strokeColor    = C_ACCENT
        bc.bars[0].strokeWidth    = 0.4
        bc.valueAxis.valueMin     = 0
        bc.valueAxis.valueMax     = max(ev_data) * 1.15 if ev_data else 10
        bc.valueAxis.labels.fontSize  = 7
        bc.valueAxis.labels.fillColor = C_MUTED
        bc.categoryAxis.labels.fontSize  = 6.5
        bc.categoryAxis.labels.fillColor = C_TEXT
        bc.categoryAxis.labels.dx        = -4
        bc.categoryAxis.categoryNames    = labels
        bc.categoryAxis.labels.boxAnchor = "e"
        bc.categoryAxis.labels.textAnchor = "end"
        bc.barSpacing = 1
        bc.groupSpacing = 3
        drawing.add(bc)
        story.append(drawing)

    # ── Footer ───────────────────────────────────────────
    story.append(Spacer(1, 4*mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_MUTED))
    story.append(Paragraph(
        "⚠️ Только в образовательных целях. Ставки сопряжены с риском потери средств. "
        "Данные: The Odds API (the-odds-api.com)",
        ParagraphStyle("footer", parent=styles["Normal"],
                       fontSize=7, textColor=C_MUTED, alignment=TA_CENTER),
    ))

    doc.build(story)
    return buf.getvalue()


# ─────────────────────────────────────────────
#  HELPERS — ESPN LIVE SCORES
# ─────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)   # кешируем на 1 мин
def fetch_scores(league_path: str) -> list:
    url = f"{ESPN_BASE}/{league_path}/scoreboard"
    try:
        r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            return r.json().get("events", [])
    except Exception:
        pass
    return []

def render_score_card(event: dict, period_name: str):
    comp   = event.get("competitions",[{}])[0]
    status = comp.get("status", event.get("status",{}))
    st_type = status.get("type", {})
    state   = st_type.get("state","pre")          # pre / in / post
    detail  = st_type.get("detail","")
    clock   = status.get("displayClock","")
    period  = status.get("period", 0)
    competitors = comp.get("competitors",[])

    # sort: home last in ESPN = index 0 is away
    home = next((c for c in competitors if c.get("homeAway")=="home"), {})
    away = next((c for c in competitors if c.get("homeAway")=="away"), {})

    home_name  = home.get("team",{}).get("displayName","—")
    away_name  = away.get("team",{}).get("displayName","—")
    home_score = home.get("score","—")
    away_score = away.get("score","—")
    home_abbr  = home.get("team",{}).get("abbreviation","")
    away_abbr  = away.get("team",{}).get("abbreviation","")

    # Venue & broadcast
    venue    = comp.get("venue",{}).get("fullName","")
    city     = comp.get("venue",{}).get("address",{}).get("city","")
    bcast    = comp.get("broadcasts",[])
    bcast_str= ", ".join(b.get("names",[""])[0] for b in bcast if b.get("names")) if bcast else ""

    # Playoff note
    notes    = comp.get("notes",[])
    note_str = notes[0].get("headline","") if notes else ""

    # Status styling
    if state == "in":
        card_cls   = "score-live"
        status_cls = "status-live"
        live_dot   = '<span class="live-dot"></span>'
        if period_name == "min":
            status_str = f"{live_dot}{clock}'"
        else:
            status_str = f"{live_dot}{period_name}{period} · {clock}"
    elif state == "post":
        card_cls   = "score-final"
        status_cls = "status-fin"
        live_dot   = ""
        status_str = f"🏁 {detail}"
    else:
        card_cls   = "score-pre"
        status_cls = "status-pre"
        live_dot   = ""
        try:
            dt = datetime.fromisoformat(event.get("date","").replace("Z","+00:00"))
            status_str = "📅 " + dt.astimezone(MSK).strftime("%d.%m %H:%M МСК")
        except Exception:
            status_str = f"📅 {detail}"

    note_html = f'<div style="font-size:.78rem;color:#facc15;margin-bottom:4px">{note_str}</div>' if note_str else ""
    venue_html = f'<div style="font-size:.75rem;color:#64748b">{venue}{", "+city if city else ""}{" · "+bcast_str if bcast_str else ""}</div>' if venue else ""

    html = f"""
    <div class="score-card {card_cls}">
      {note_html}
      <div style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div class="team-name">{away_name} <span style="color:#64748b;font-size:.8rem">{away_abbr}</span></div>
          <div class="team-name" style="margin-top:4px">{home_name} <span style="color:#64748b;font-size:.8rem">{home_abbr}</span></div>
        </div>
        <div style="text-align:right">
          <div class="team-score">{away_score}</div>
          <div class="team-score">{home_score}</div>
        </div>
      </div>
      <div style="margin-top:8px;display:flex;justify-content:space-between;align-items:center">
        <span class="{status_cls}">{status_str}</span>
        {venue_html}
      </div>
    </div>"""
    st.markdown(html, unsafe_allow_html=True)

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
        teams_map = {
            "soccer_epl":                [("Arsenal","Chelsea"),("Liverpool","Manchester City")],
            "soccer_spain_la_liga":      [("Real Madrid","Barcelona"),("Atletico Madrid","Sevilla")],
            "soccer_germany_bundesliga": [("Bayern Munich","Borussia Dortmund"),("RB Leipzig","Bayer Leverkusen")],
            "soccer_italy_serie_a":      [("Inter Milan","AC Milan"),("Juventus","Napoli")],
            "soccer_france_ligue_one":   [("PSG","Marseille"),("Lyon","Monaco")],
            "soccer_uefa_champs_league": [("Real Madrid","Manchester City"),("Bayern Munich","Arsenal")],
            "soccer_uefa_europa_league": [("Roma","Ajax"),("Tottenham","Frankfurt")],
            "soccer_usa_mls":            [("LA Galaxy","LAFC"),("Inter Miami","NYC FC")],
        }
        pairs = teams_map.get(sport_key,[("Team A","Team B")])
        evs = []
        for i,(home,away) in enumerate(pairs):
            evs.append({"id":f"s{i}","sport_key":sport_key,
                "commence_time":f"2025-04-20T{14+i*4:02d}:00:00Z",
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
        return evs
    elif sport_key == "basketball_nba":
        return [
            {"id":"n1","sport_key":sport_key,"commence_time":"2025-04-20T23:00:00Z",
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
            {"id":"n2","sport_key":sport_key,"commence_time":"2025-04-21T01:30:00Z",
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
        ]
    return []

# ─────────────────────────────────────────────
#  SESSION STATE INIT
# ─────────────────────────────────────────────
# Persistent API key — priority:
# 1. Streamlit Cloud App Secrets (st.secrets["ODDS_API_KEY"]) — never resets
# 2. Environment variable ODDS_API_KEY  — for CI / local .env
# 3. Manual sidebar input              — fallback / local dev
import os as _os
_env_api_key = (
    (st.secrets.get("ODDS_API_KEY", "") if hasattr(st, "secrets") else "")
    or _os.environ.get("ODDS_API_KEY", "")
)

defaults = {
    "events": None, "remaining": None, "used": None,
    "demo_mode": False, "last_sport": None, "last_market": None,
    "last_fetch_ts": 0, "auto_refresh": True,
    "gmail_sent_ids": set(),   # track already-alerted value bets
    "saved_api_key": _env_api_key,  # pre-filled from Secrets/env; empty = manual
    "selected_bm_state": [],   # persisted bookmaker selection
    "sport_filter": "Все",    # sport category filter
    "theme": "dark",           # dark | light — сохраняется между сессиями
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v
# Re-inject env key if session was reset while env key exists
if not st.session_state.saved_api_key and _env_api_key:
    st.session_state.saved_api_key = _env_api_key

# ─────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Настройки")

    # ── Тема ────────────────────────────────
    render_user_badge()  # 👤 User info + logout
    _theme_cols = st.columns(2)
    with _theme_cols[0]:
        _dark_btn  = st.button("🌑 Тёмная",  use_container_width=True,
                               type="primary" if st.session_state.theme=="dark"  else "secondary",
                               key="btn_theme_dark")
    with _theme_cols[1]:
        _light_btn = st.button("☀️ Светлая", use_container_width=True,
                               type="primary" if st.session_state.theme=="light" else "secondary",
                               key="btn_theme_light")
    if _dark_btn:  st.session_state.theme = "dark"
    if _light_btn: st.session_state.theme = "light"
    st.divider()

    # ── Odds API ──────────────────────────────
    _key_from_cloud = bool(_env_api_key)
    if _key_from_cloud:
        st.success("🔑 API ключ подключён автоматически")
        st.caption("Задан через Streamlit Secrets — ввод не нужен")
        _typed_key = ""
    else:
        _typed_key = st.text_input("🔑 The Odds API Key", type="password",
            value=st.session_state.saved_api_key,
            placeholder="Пусто = демо-режим",
            help="https://the-odds-api.com — 500 запросов/мес бесплатно")
    # Persist key across reruns (manual input valid only in this session)
    if _typed_key:
        st.session_state.saved_api_key = _typed_key
    api_key = st.session_state.saved_api_key
    if api_key and not _key_from_cloud:
        st.caption("✅ API ключ сохранён в сессии")

    # ── Sport / League filter ─────────────────
    SPORT_FILTER_OPTIONS = ["Все", "🌐 Все виды спорта", "⚽ Только Football", "🏈 Только NFL", "🏀 Только NBA"]
    sport_filter = st.radio(
        "🎯 Фильтр спорта",
        SPORT_FILTER_OPTIONS,
        index=SPORT_FILTER_OPTIONS.index(st.session_state.sport_filter)
              if st.session_state.sport_filter in SPORT_FILTER_OPTIONS else 0,
        horizontal=True,
    )
    st.session_state.sport_filter = sport_filter

    # Build visible sport list based on filter
    ALL_SPORT_KEYS = list(SPORTS_CATALOGUE.keys())
    if sport_filter == "⚽ Только Football":
        _visible_sports = [k for k in ALL_SPORT_KEYS if k.startswith("⚽")]
    elif sport_filter == "🏈 Только NFL":
        _visible_sports = [k for k in ALL_SPORT_KEYS if k.startswith("🏈")]
    elif sport_filter == "🏀 Только NBA":
        _visible_sports = [k for k in ALL_SPORT_KEYS if k.startswith("🏀")]
    else:
        _visible_sports = ALL_SPORT_KEYS

    # В режиме «Все виды спорта» selectbox отключён
    _fetch_all_mode = (sport_filter == "🌐 Все виды спорта")
    sport_label  = st.selectbox(
        "🏆 Вид спорта / Лига", _visible_sports,
        disabled=_fetch_all_mode,
        help="В режиме «Все виды спорта» выбор лиги отключён" if _fetch_all_mode else None,
    )
    sport_cfg    = SPORTS_CATALOGUE[sport_label]
    has_draw     = sport_cfg["has_draw"]

    # Кнопка «Загрузить ВСЕ лиги» — только в режиме 🌐
    fetch_all_btn = False
    if _fetch_all_mode:
        st.info(
            "🌐 Загрузит **все 10 лиг** за один клик (~10 API запросов)",
            icon="ℹ️",
        )
        fetch_all_btn = st.button(
            "🔍 Загрузить ВСЕ лиги",
            use_container_width=True,
            type="primary",
            key="fetch_all_btn",
        )
    region_label = st.selectbox("📍 Регион", list(REGION_MAP.keys()))
    market_label = st.selectbox("📊 Рынок", sport_cfg["markets"])
    market_key   = MARKET_KEY_MAP[market_label]

    # ── Bookmakers ────────────────────────────
    ALL_BM = US_BM + EU_BM
    st.markdown("🏦 **Букмекеры**")
    _bm_cols = st.columns(3)
    with _bm_cols[0]:
        if st.button("✔️ Все", use_container_width=True, key="bm_all"):
            st.session_state.selected_bm_state = list(ALL_BM)
    with _bm_cols[1]:
        if st.button("🇺🇸 US", use_container_width=True, key="bm_us"):
            st.session_state.selected_bm_state = list(US_BM)
    with _bm_cols[2]:
        if st.button("🇪🇺 EU", use_container_width=True, key="bm_eu"):
            st.session_state.selected_bm_state = list(EU_BM)

    # Default on first load based on sport
    if not st.session_state.selected_bm_state:
        st.session_state.selected_bm_state = (
            ["DraftKings","FanDuel","BetMGM"] if not has_draw
            else ["Bet365","Unibet","DraftKings"]
        )

    selected_bm = st.multiselect(
        "Выбери букмекеров", ALL_BM,
        default=[b for b in st.session_state.selected_bm_state if b in ALL_BM],
        key="bm_multiselect",
    )
    st.session_state.selected_bm_state = selected_bm

    st.divider()

    # ── Auto-refresh ──────────────────────────
    st.markdown("**🔄 Авто-обновление**")
    auto_on = st.toggle("Каждые 5 минут", value=st.session_state.auto_refresh)
    st.session_state.auto_refresh = auto_on

    # ── Value bets ────────────────────────────
    st.divider()
    min_edge = st.slider("💎 Мин. EV Edge %", 0.0, 15.0, 1.0, 0.5)

    # ── Gmail alerts ──────────────────────────
    st.divider()
    st.markdown("**📧 Gmail-уведомления** *(EV ≥ 5%)*")
    gmail_on   = st.toggle("Включить уведомления", value=False)
    gmail_from = st.text_input("Gmail отправителя", placeholder="your@gmail.com",
                               help="Нужен App Password (не обычный пароль)")
    gmail_pass = st.text_input("App Password Gmail", type="password",
                               help="Настройки → Безопасность → Пароли приложений")
    gmail_to   = st.text_input("Получатель", placeholder="recipient@example.com",
                               value="mezhavikins@yandex.ru")
    if st.button("📤 Тест письма", use_container_width=True):
        if gmail_from and gmail_pass and gmail_to:
            ok, msg = send_gmail_alert(gmail_from, gmail_pass, gmail_to,
                                       pd.DataFrame([{"Матч":"Test Match","Время":"15.04 10:00 МСК",
                                           "Букмекер":"DraftKings","Исход":"✅ Team A",
                                           "Odds (Am)":"+150","Odds (Dec)":2.5,
                                           "Implied %":"40%","No-Vig Fair %":"47%",
                                           "EV Edge %":"+17.50%"}]),
                                       sport_label)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
        else:
            st.warning("Заполни email и App Password")

    # ── Google Sheets ────────────────────
    st.divider()
    st.markdown("⚡ **Google Sheets** — История ставок**")
    gsheets_on = st.toggle("Авто-логирование value bets", value=False, key="gsheets_on")

    # URL читаем из secrets или из поля
    _default_url = ""
    try:
        _default_url = st.secrets.get("GSHEET_URL", "")
    except Exception:
        pass
    gsheet_url = st.text_input(
        "URL Google Таблицы",
        value=_default_url,
        placeholder="https://docs.google.com/spreadsheets/d/.../edit",
        help="Расшарь таблицу с service account email из секретов",
    )
    # Store URL in session_state so History tab can access it
    st.session_state["gsheet_url"] = gsheet_url
    col_gs1, col_gs2 = st.columns(2)
    with col_gs1:
        if st.button("📝 Записать сейчас", use_container_width=True, key="gs_write_now"):
            st.session_state["gs_write_triggered"] = True
    with col_gs2:
        if st.button("📖 Читать", use_container_width=True, key="gs_read_now"):
            st.session_state["gs_read_triggered"] = True

    st.divider()
    st.markdown("**💰 Управление банкроллом**")
    bankroll = st.number_input(
        "Банкролл ($)", min_value=10.0, max_value=1_000_000.0,
        value=float(st.session_state.get("bankroll", 1000.0)),
        step=100.0, format="%.0f",
        help="Используется для расчёта Kelly Stake в Сигналах и Value Bets",
    )
    st.session_state["bankroll"] = bankroll
    fetch_btn = st.button("🔄 Загрузить коэффициенты", use_container_width=True, type="primary")

    # ── PDF экспорт ──────────────────────────
    st.divider()
    st.markdown("**📄 Экспорт отчёта**")
    _pdf_vdf = st.session_state.get("vdf_all_cached", pd.DataFrame())
    _pdf_empty = _pdf_vdf.empty if hasattr(_pdf_vdf, 'empty') else True
    if _pdf_empty:
        st.caption("⚠️ Сначала загрузи коэффициенты — появятся value bets")
    else:
        _pdf_sport = st.session_state.get("sport_label_cached", "Спорт")
        _pdf_broll = st.session_state.get("bankroll", 1000.0)
        with st.spinner("📄 Генерируем PDF…"):
            try:
                _pdf_bytes = generate_pdf_report(_pdf_vdf, _pdf_sport, _pdf_broll)
                _pdf_name  = (
                    f"value_bets_{_pdf_sport.lower().replace(' ','_')}_"
                    f"{datetime.now(MSK).strftime('%Y%m%d_%H%M')}.pdf"
                )
                st.download_button(
                    label=f"📥 Скачать PDF ({len(_pdf_vdf)} ставок)",
                    data=_pdf_bytes,
                    file_name=_pdf_name,
                    mime="application/pdf",
                    use_container_width=True,
                    key="pdf_download_btn",
                )
            except Exception as _pdf_err:
                st.error(f"❌ PDF: {_pdf_err}")

    # ── Диагностика подключений ───────────────
    st.divider()
    st.markdown("**🔌 Диагностика подключений**")
    if st.button("🩺 Проверить подключения", use_container_width=True, key="diag_btn"):
        # --- The Odds API ---
        _diag_key = (
            st.session_state.get("api_key", "")
            or (st.secrets.get("ODDS_API_KEY", "") if hasattr(st, "secrets") else "")
            or _os.environ.get("ODDS_API_KEY", "")
        )
        with st.spinner("Проверяем The Odds API…"):
            if not _diag_key:
                st.error("❌ The Odds API: ключ не задан")
            else:
                try:
                    _r = requests.get(
                        f"{ODDS_BASE}/sports",
                        params={"apiKey": _diag_key},
                        timeout=8,
                    )
                    if _r.status_code == 200:
                        _remaining = _r.headers.get("x-requests-remaining", "?")
                        st.success(f"✅ The Odds API: OK — осталось {_remaining} запросов")
                    elif _r.status_code == 401:
                        st.error("❌ The Odds API: неверный ключ (401)")
                    else:
                        st.warning(f"⚠️ The Odds API: статус {_r.status_code}")
                except Exception as _e:
                    st.error(f"❌ The Odds API: {_e}")

        # --- Gmail ---
        _diag_gmail_from = st.session_state.get("diag_gmail_from", gmail_from if 'gmail_from' in dir() else "")
        _diag_gmail_pass = st.session_state.get("diag_gmail_pass", gmail_pass if 'gmail_pass' in dir() else "")
        _diag_gmail_to   = st.session_state.get("diag_gmail_to",   gmail_to   if 'gmail_to'   in dir() else "")
        # Fallback to secrets
        if not _diag_gmail_from:
            try:
                _diag_gmail_from = st.secrets.get("GMAIL_SENDER", "")
                _diag_gmail_pass = st.secrets.get("GMAIL_APP_PASSWORD", "") or st.secrets.get("GMAIL_PASSWORD", "")
                _diag_gmail_to   = st.secrets.get("GMAIL_TO", "")
            except Exception:
                pass
        with st.spinner("Проверяем Gmail SMTP…"):
            if not _diag_gmail_from or not _diag_gmail_pass:
                st.warning("⚠️ Gmail: email или App Password не заполнены")
            else:
                try:
                    import smtplib as _smtplib
                    with _smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as _srv:
                        _srv.login(_diag_gmail_from, _diag_gmail_pass)
                    st.success(f"✅ Gmail: авторизация OK ({_diag_gmail_from})")
                except _smtplib.SMTPAuthenticationError:
                    st.error("❌ Gmail: ошибка авторизации — проверь App Password")
                except Exception as _e:
                    st.error(f"❌ Gmail: {_e}")

        # --- Google Sheets ---
        _diag_gsheet_url = st.session_state.get("gsheet_url", "")
        with st.spinner("Проверяем Google Sheets…"):
            if not _diag_gsheet_url:
                st.warning("⚠️ Google Sheets: URL не задан")
            else:
                _gs_client, _gs_err = get_gspread_client()
                if _gs_client is None:
                    st.error(f"❌ Google Sheets: {_gs_err}")
                else:
                    try:
                        _sh = _gs_client.open_by_url(_diag_gsheet_url)
                        st.success(f"✅ Google Sheets: OK — '{_sh.title}'")
                    except Exception as _e:
                        st.error(f"❌ Google Sheets: {_e}")

    st.divider()
    st.caption("📡 [The Odds API](https://the-odds-api.com) · [ESPN API](https://site.api.espn.com)")

# ─────────────────────────────────────────────
#  THEME APPLICATION + PWA INJECTION
# ─────────────────────────────────────────────
_current_theme = st.session_state.get("theme", "dark")
_is_light = (_current_theme == "light")
if _is_light:
    st.markdown(LIGHT_CSS, unsafe_allow_html=True)

# ── Theme-aware palette for inline HTML cards ─────────────────
# All inline st.markdown cards use these vars so they flip with the theme
T = {
    "bg":         "#ffffff"  if _is_light else "#1e293b",
    "bg2":        "#f1f5f9"  if _is_light else "#0d1b2a",
    "bg_dark":    "#e2e8f0"  if _is_light else "#0f172a",
    "border":     "#cbd5e1"  if _is_light else "#334155",
    "text":       "#1e293b"  if _is_light else "#e2e8f0",
    "text2":      "#475569"  if _is_light else "#94a3b8",
    "muted":      "#64748b"  if _is_light else "#64748b",
    # Signal card backgrounds
    "sharp_bg":   "#f3e8ff"  if _is_light else "#1a1a2e",
    "strong_bg":  "#dcfce7"  if _is_light else "#0d2a1a",
    "moderate_bg":"#fef9c3"  if _is_light else "#2a1a00",
    "weak_bg":    "#dbeafe"  if _is_light else "#0d1b2a",
    "none_bg":    "#f8fafc"  if _is_light else "#111827",
    "none_text":  "#64748b"  if _is_light else "#94a3b8",
    # Kelly cell
    "kelly_bg":   "#ede9fe"  if _is_light else "#2d1f5e",
    "kelly_brd":  "border:1px solid #7c3aed;",
    "kelly_text": "#5b21b6"  if _is_light else "#c4b5fd",
    # Arb card
    "arb_bg":     "#f0fdf4"  if _is_light else "#0a2a1a",
    "arb_brd":    "#16a34a"  if _is_light else "#22c55e",
}

# PWA meta-теги + SW регистрация (через Streamlit в body, браузер подхватывает)
st.markdown("""
<link rel="manifest" href="https://sports-odds-dashboard.warnetbesholin.workers.dev/manifest.json" />
<meta name="mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-capable" content="yes" />
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
<meta name="apple-mobile-web-app-title" content="OddsDash" />
<meta name="theme-color" content="#0d1b2a" id="pwa-theme-color" />
<link rel="apple-touch-icon" href="https://sports-odds-dashboard.warnetbesholin.workers.dev/icons/apple-touch-icon.png" />
<script>
  // Register Service Worker from Cloudflare Worker
  (function() {
    var SW_URL = 'https://sports-odds-dashboard.warnetbesholin.workers.dev/sw.js';
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register(SW_URL)
          .then(function(r){ console.log('[PWA] SW ok', r.scope); })
          .catch(function(e){ console.warn('[PWA] SW failed', e); });
      });
    }
    // Тема в meta theme-color
    var tc = document.getElementById('pwa-theme-color');
    if (tc) tc.content = localStorage.getItem('odds_theme_color') || '#0d1b2a';
  })();
</script>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────
st.markdown(
    f'<div class="main-title">🏆 Sports Odds Dashboard</div>'
    f'<div class="subtitle">NFL · Football · NBA &nbsp;·&nbsp; Live Odds &nbsp;·&nbsp; Value Bets &nbsp;·&nbsp; Arbitrage &nbsp;·&nbsp; Live Scores</div>',
    unsafe_allow_html=True
)

# Auto-refresh countdown bar
now_ts = time.time()
elapsed = now_ts - st.session_state.last_fetch_ts
remaining_s = max(0, AUTO_REFRESH - elapsed)
if st.session_state.auto_refresh and st.session_state.events is not None:
    pct = int((AUTO_REFRESH - remaining_s) / AUTO_REFRESH * 100)
    col_prog, col_timer = st.columns([7,3])
    with col_prog:
        st.progress(pct, text=f"Следующее обновление через {int(remaining_s//60)}м {int(remaining_s%60)}с")
    with col_timer:
        st.markdown(f'<div class="timer-bar">🕐 Обновлено: {datetime.now(MSK).strftime("%H:%M:%S МСК")}</div>',
                    unsafe_allow_html=True)

# ── Mobile quick-load bar (visible on phone without opening sidebar) ──
_mob_col1, _mob_col2, _mob_col3 = st.columns([3, 2, 1])
with _mob_col1:
    st.caption(f"🏆 **{sport_label}** · {market_label}")
with _mob_col2:
    st.caption(f"📍 {region_label} · 🏦 {len(selected_bm) if selected_bm else 'все'} букмекеров")
with _mob_col3:
    mobile_fetch_btn = st.button("⚡", help="Загрузить коэффициенты", use_container_width=True, key="mob_fetch")

st.divider()

# ─────────────────────────────────────────────
#  AUTO-REFRESH TRIGGER
# ─────────────────────────────────────────────
# В обычном режиме _fetch_all_mode и fetch_all_btn могут быть не объявлены
_fetch_all_mode = locals().get("_fetch_all_mode", False) or st.session_state.get("_fetch_all_mode", False)
fetch_all_btn   = locals().get("fetch_all_btn", False)
should_fetch = fetch_btn or mobile_fetch_btn
if (st.session_state.auto_refresh
        and st.session_state.events is not None
        and elapsed >= AUTO_REFRESH):
    should_fetch = True

# ─────────────────────────────────────────────
#  FETCH ODDS
# ─────────────────────────────────────────────
if fetch_all_btn:
    # ── Режим «Все виды спорта» — загружаем все лиги последовательно ──────────
    st.session_state.last_sport  = "🌐 Все виды спорта"
    st.session_state.last_market = market_label
    st.session_state.demo_mode   = False
    _all_events   = []
    _min_rem      = None
    _total_used   = 0
    _all_sport_names = list(SPORTS_CATALOGUE.keys())
    _prog = st.progress(0, text="Загружаем лиги…")
    for _si, _sl in enumerate(_all_sport_names):
        _sc = SPORTS_CATALOGUE[_sl]
        _mk = "h2h"  # для «Все» всегда H2H
        _prog.progress(int((_si / len(_all_sport_names)) * 100),
                       text=f"Загружаю {_sl} ({_si+1}/{len(_all_sport_names)})…")
        if not api_key:
            _evts = make_demo(_sc["key"], _sc["has_draw"])
        else:
            _evts, _rem, _used = fetch_odds(api_key, _sc["key"], REGION_MAP[region_label], _mk)
            if _evts is None:
                _evts = []
            try:
                if _min_rem is None or (str(_rem).isdigit() and int(_rem) < int(_min_rem)):
                    _min_rem = _rem
                _total_used += int(_used) if str(_used).isdigit() else 0
            except Exception:
                pass
        # Тегируем события тегом лиги для отображения
        for _ev in (_evts or []):
            _ev["_sport_label"] = _sl
            _ev["_has_draw"]    = _sc["has_draw"]
        _all_events.extend(_evts or [])
    _prog.progress(100, text=f"✅ Загружено {len(_all_events)} матчей из {len(_all_sport_names)} лиг")
    st.session_state.events       = _all_events
    st.session_state.remaining    = _min_rem or ("demo" if not api_key else "?")
    st.session_state.used         = str(_total_used) if _total_used else "demo"
    if not api_key:
        st.session_state.demo_mode = True
    st.session_state["_fetch_all_active"] = True
    st.session_state.last_fetch_ts = time.time()

elif should_fetch:
    st.session_state["_fetch_all_active"] = False
    # ── Обычная загрузка одной лиги ───────────────────────────────────────────
    st.session_state.last_sport  = sport_label
    st.session_state.last_market = market_label
    if not api_key:
        st.info("💡 Демо-режим (API ключ не введён). Получи бесплатно: [the-odds-api.com](https://the-odds-api.com)", icon="ℹ️")
        st.session_state.events    = make_demo(sport_cfg["key"], has_draw)
        st.session_state.remaining = "demo"
        st.session_state.used      = "demo"
        st.session_state.demo_mode = True
    else:
        with st.spinner(f"Загружаю {sport_label} · {market_label}…"):
            events, rem, used = fetch_odds(api_key, sport_cfg["key"], REGION_MAP[region_label], market_key)
        if events is not None:
            st.session_state.events    = events
            st.session_state.remaining = rem
            st.session_state.used      = used
            st.session_state.demo_mode = False
    st.session_state.last_fetch_ts = time.time()
    # Google Sheets auto-log on fresh data
    if st.session_state.get("gsheets_on", False) and market_key == "h2h":
        _gs_auto_url = st.session_state.get("gsheet_url", "")
        if _gs_auto_url and st.session_state.events:
            _auto_filt = [{**ev,"bookmakers":[b for b in ev.get("bookmakers",[]) if not selected_bm or b.get("title") in selected_bm]}
                          for ev in st.session_state.events]
            _auto_filt = [e for e in _auto_filt if e["bookmakers"]]
            _auto_df = parse_to_df(_auto_filt, "h2h", has_draw)
            if not _auto_df.empty:
                _auto_vdf = _compute_value_bets_v2(_auto_df, has_draw, min_edge, sport_cfg["key"], bankroll)
                if not _auto_vdf.empty:
                    _ok_gs, _msg_gs = log_value_bets_to_sheets(_auto_vdf, sport_label,
                                                                _gs_auto_url)
                    if _ok_gs:
                        st.toast(f"📊 Google Sheets: записано {len(_auto_vdf)} value bets", icon="✅")
    # Gmail alert check on fresh data
    if gmail_on and gmail_from and gmail_pass and gmail_to and st.session_state.events:
        filt = [{**ev,"bookmakers":[b for b in ev.get("bookmakers",[]) if not selected_bm or b.get("title") in selected_bm]}
                for ev in st.session_state.events]
        filt = [e for e in filt if e["bookmakers"]]
        tmp_df = parse_to_df(filt, "h2h", has_draw)
        if not tmp_df.empty:
            vdf_alert = _compute_value_bets_v2(tmp_df, has_draw, VALUE_THRESHOLD, sport_cfg["key"], bankroll)
            if not vdf_alert.empty:
                alert_key = frozenset(vdf_alert["Матч"].tolist())
                if alert_key not in st.session_state.gmail_sent_ids:
                    ok, msg = send_gmail_alert(gmail_from, gmail_pass, gmail_to, vdf_alert, sport_label)
                    if ok:
                        st.session_state.gmail_sent_ids.add(alert_key)
                        st.toast(f"📧 Gmail alert отправлен! Value bets: {len(vdf_alert)}", icon="✅")
                    else:
                        st.toast(msg, icon="❌")

# ─────────────────────────────────────────────
#  SCHEDULE NEXT RERUN
# ─────────────────────────────────────────────
if st.session_state.auto_refresh and st.session_state.events is not None:
    elapsed_now = time.time() - st.session_state.last_fetch_ts
    wait_ms = max(1000, int((AUTO_REFRESH - elapsed_now) * 1000))
    st.markdown(f"""
    <script>
    setTimeout(function(){{window.location.reload()}}, {wait_ms});
    </script>
    """, unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  WELCOME SCREEN
# ─────────────────────────────────────────────
if st.session_state.events is None:
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown("### 🏈 NFL\n- Moneyline · Spreads · Totals\n- DraftKings, FanDuel…")
    with col2:
        st.markdown("### ⚽ Football\n- EPL · La Liga · Bundesliga\n- Serie A · UCL · UEL · MLS\n- 1X2 + Ничья")
    with col3:
        st.markdown("### 🏀 NBA\n- Moneyline · Spreads · Totals\n- Все крупные US книги")
    with col4:
        st.markdown("### 📺 Live Scores\n- ESPN Public API\n- NFL · EPL · NBA\n- Обновление каждые 60с")
    st.info("👈 Настрой параметры в боковой панели и нажми **Загрузить коэффициенты**.")
    st.stop()

# ─────────────────────────────────────────────
#  BUILD DF
# ─────────────────────────────────────────────
filtered_events = []
for ev in st.session_state.events:
    bms = [b for b in ev.get("bookmakers",[]) if not selected_bm or b.get("title") in selected_bm]
    if bms:
        filtered_events.append({**ev, "bookmakers": bms})

if not filtered_events:
    st.warning("⚠️ Нет матчей по выбранным фильтрам.")
    st.stop()

# В режиме «Все лиги» парсим каждую лигу с её own has_draw
if st.session_state.get("_fetch_all_active"):
    _dfs = []
    for _sl_name in SPORTS_CATALOGUE:
        _sc_cfg = SPORTS_CATALOGUE[_sl_name]
        _sl_evts = [e for e in filtered_events if e.get("_sport_label") == _sl_name]
        if _sl_evts:
            _sdf = parse_to_df(_sl_evts, "h2h", _sc_cfg["has_draw"])
            if not _sdf.empty:
                _sdf["_sport_label"] = _sl_name
                _dfs.append(_sdf)
    df = pd.concat(_dfs, ignore_index=True) if _dfs else pd.DataFrame()
    # Для совместимости с остальным кодом — has_draw=False (смешанный режим)
    has_draw = False
    market_key = "h2h"
else:
    df = parse_to_df(filtered_events, market_key, has_draw)

if df.empty:
    st.warning(f"⚠️ Нет данных для рынка «{market_label}».")
    st.stop()

# ─────────────────────────────────────────────
#  METRICS
# ─────────────────────────────────────────────
cur_sport = st.session_state.last_sport or sport_label
demo_tag  = " *(демо)*" if st.session_state.demo_mode else ""
vdf_all   = _compute_value_bets_v2(df, has_draw, min_edge, sport_cfg["key"], bankroll) if market_key == "h2h" else pd.DataFrame()
vbets_cnt = len(vdf_all)
# Кешируем для PDF-экспорта из сайдбара
if not vdf_all.empty:
    st.session_state["vdf_all_cached"]     = vdf_all
    st.session_state["sport_label_cached"] = sport_label

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("🏟 Матчей",      df["Матч"].nunique())
c2.metric("🏦 Букмекеров",  df["Букмекер"].nunique())
c3.metric("📋 Линий",       len(df))
c4.metric("💎 Value Bets",  vbets_cnt, delta=f"EV≥{min_edge}%" if vbets_cnt else None,
          delta_color="normal" if vbets_cnt else "off")
c5.metric("📡 API осталось", st.session_state.remaining)
st.divider()

# ─────────────────────────────────────────────
#  TABS
# ─────────────────────────────────────────────
tab_signals, tab_arb, tab_table, tab_chart, tab_value, tab_live, tab_hist_odds, tab_history, tab_bankroll, tab_ai = st.tabs([
    "🎯 Сигналы",
    "⚡ Арбитраж",
    "📋 Коэффициенты",
    "📊 Сравнение букмекеров",
    "💎 Value Bets",
    "📺 Live Scores",
    "📈 Исторические коэфф.",
    "📊 История ставок",
    "💰 Статистика банкролла",
    "🤖 AI Анализ",
])

DARK = dict(plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a", font_color="#e2e8f0")

# ── TAB 0: BETTING SIGNALS v2 (Sharp EV + Kelly ¼ Stake) ─────────────────
with tab_signals:
    st.markdown("#### 🎯 На кого ставить — Sharp EV сигналы + Spreads/Totals анализ")

    if market_key == "spreads":
        # ── SPREADS СИГНАЛЫ: лучший спред и наименьшая маржа по каждому матчу
        st.markdown("**📊 Spreads — анализ линий и маржи**")
        spread_signals = []
        for match, grp in df.groupby("Матч"):
            home_t = grp["Хозяева"].iloc[0]
            away_t = grp["Гости"].iloc[0]
            time_s = grp["Время"].iloc[0]
            rows = []
            for _, r in grp.iterrows():
                try:
                    h_price = float(r["Odds Хозяева (Am)"])
                    a_price = float(r["Odds Гости (Am)"])
                    h_dec = american_to_decimal(h_price)
                    a_dec = american_to_decimal(a_price)
                    h_pt  = float(r.get("Спред Хозяева", 0) or 0)
                    a_pt  = float(r.get("Спред Гости", 0) or 0)
                    # No-vig implied probs
                    h_impl = decimal_to_implied(h_dec)
                    a_impl = decimal_to_implied(a_dec)
                    nv     = no_vig_prob([h_impl, a_impl])
                    # EV edge vs -110 standard (-110 = 52.38% impl)
                    h_ev = round(nv[0]/100 * h_dec - 1, 4)
                    a_ev = round(nv[1]/100 * a_dec - 1, 4)
                    # Total margin (vig) = sum of implied - 100
                    margin = round(h_impl + a_impl - 100, 2)
                    rows.append({
                        "Букмекер": r["Букмекер"],
                        "h_dec": h_dec, "a_dec": a_dec,
                        "h_pt": h_pt,   "a_pt": a_pt,
                        "h_ev": h_ev,   "a_ev": a_ev,
                        "margin": margin,
                        "h_nv": nv[0],  "a_nv": nv[1],
                    })
                except Exception:
                    continue
            if not rows:
                continue
            # Find best spread (lowest margin + highest EV)
            best = min(rows, key=lambda x: x["margin"])
            # Best EV side
            if best["h_ev"] >= best["a_ev"]:
                rec_team, rec_odds, rec_pt, rec_ev, rec_nv = home_t, fmt_am(round((best["h_dec"]-1)*100)), best["h_pt"], best["h_ev"], best["h_nv"]
            else:
                rec_team, rec_odds, rec_pt, rec_ev, rec_nv = away_t, fmt_am(round((best["a_dec"]-1)*100)), best["a_pt"], best["a_ev"], best["a_nv"]
            signal_str = "🟢 ПОЛОЖИТЕЛЬНЫЙ" if rec_ev > 0 else ("🟡 НЕЙТРАЛЬНЫЙ" if rec_ev > -0.01 else "🔴 ОТРИЦАТЕЛЬНЫЙ")
            ev_c = ("#16a34a" if _is_light else "#4ade80") if rec_ev > 0 else ("#ca8a04" if _is_light else "#fde68a") if rec_ev > -0.01 else ("#dc2626" if _is_light else "#f87171")
            spread_signals.append({
                "Матч": match, "Время": time_s,
                "Сигнал": signal_str,
                "Ставить на": f"{rec_team} ({rec_pt:+.1f})",
                "Оддс (Am)": rec_odds,
                "EV Edge": f"{rec_ev*100:+.2f}%",
                "No-Vig %": f"{rec_nv:.1f}%",
                "Маржа (vig)": f"{best['margin']:+.2f}%",
                "Лучший БМ": best["Букмекер"],
                "_ev": rec_ev, "_ev_c": ev_c,
            })
        if spread_signals:
            for ss in sorted(spread_signals, key=lambda x: -x["_ev"]):
                ev_c = ss["_ev_c"]
                card_c = T['strong_bg'] if ss["_ev"] > 0 else T['moderate_bg'] if ss["_ev"] > -0.01 else T['none_bg']
                brd_c  = ("#16a34a" if _is_light else "#4ade80") if ss["_ev"] > 0 else ("#ca8a04" if _is_light else "#fde68a") if ss["_ev"] > -0.01 else T['border']
                st.markdown(f"""
<div style="background:{card_c};border:2px solid {brd_c};border-radius:12px;padding:14px 18px;margin-bottom:10px">
  <div style="font-size:11px;color:{T['text2']}">{ss['Матч']} &middot; {ss['Время']}</div>
  <div style="font-size:18px;font-weight:800;color:{ev_c};margin:4px 0">{ss['Сигнал']} — {ss['Ставить на']}</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px;margin-top:8px">
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">🏦 Оддс</div>
      <div style="font-size:14px;font-weight:700;color:{ev_c}">{ss['Оддс (Am)']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">💰 EV Edge</div>
      <div style="font-size:14px;font-weight:700;color:{ev_c}">{ss['EV Edge']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">📉 No-Vig %</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{ss['No-Vig %']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">📊 Маржа (vig)</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{ss['Маржа (vig)']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">🏦 Лучший БМ</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{ss['Лучший БМ']}</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)
        else:
            st.warning("Недостаточно данных для Spreads-сигналов.")

    elif market_key == "totals":
        # ── TOTALS СИГНАЛЫ: Over/Under анализ с No-Vig EV
        st.markdown("**📏 Totals — Over/Under анализ линий**")
        total_signals = []
        for match, grp in df.groupby("Матч"):
            time_s = grp["Время"].iloc[0]
            rows_t = []
            for _, r in grp.iterrows():
                try:
                    ov_am = float(r["Odds Over (Am)"])
                    un_am = float(r["Odds Under (Am)"])
                    line  = float(r.get("Тотал Линия", 0) or 0)
                    ov_d  = american_to_decimal(ov_am)
                    un_d  = american_to_decimal(un_am)
                    ov_i  = decimal_to_implied(ov_d)
                    un_i  = decimal_to_implied(un_d)
                    nv    = no_vig_prob([ov_i, un_i])
                    ov_ev = round(nv[0]/100 * ov_d - 1, 4)
                    un_ev = round(nv[1]/100 * un_d - 1, 4)
                    margin = round(ov_i + un_i - 100, 2)
                    # Line dispersion across books (higher = softer line)
                    rows_t.append({
                        "Букмекер": r["Букмекер"],
                        "line": line,
                        "ov_d": ov_d, "un_d": un_d,
                        "ov_ev": ov_ev, "un_ev": un_ev,
                        "margin": margin,
                        "ov_nv": nv[0], "un_nv": nv[1],
                        "ov_am": fmt_am(ov_am), "un_am": fmt_am(un_am),
                    })
                except Exception:
                    continue
            if not rows_t:
                continue
            best_t = min(rows_t, key=lambda x: x["margin"])
            # Line movement: min vs max line across books
            all_lines = [r["line"] for r in rows_t if r["line"]]
            line_range = f"{min(all_lines):.1f}–{max(all_lines):.1f}" if len(set(all_lines)) > 1 else f"{best_t['line']:.1f}"
            if best_t["ov_ev"] >= best_t["un_ev"]:
                rec = "OVER"; rec_odds = best_t["ov_am"]; rec_ev = best_t["ov_ev"]; rec_nv = best_t["ov_nv"]
            else:
                rec = "UNDER"; rec_odds = best_t["un_am"]; rec_ev = best_t["un_ev"]; rec_nv = best_t["un_nv"]
            signal_str = "🟢 ТОТАЛ" if rec_ev > 0 else "🔴 ОТРИЦАТЕЛЬНЫЙ"
            ev_c = ("#16a34a" if _is_light else "#4ade80") if rec_ev > 0 else ("#dc2626" if _is_light else "#f87171")
            total_signals.append({
                "Матч": match, "Время": time_s,
                "Сигнал": signal_str,
                "Ставить": f"{rec} {best_t['line']:.1f}",
                "Оддс (Am)": rec_odds,
                "EV Edge": f"{rec_ev*100:+.2f}%",
                "No-Vig %": f"{rec_nv:.1f}%",
                "Маржа": f"{best_t['margin']:+.2f}%",
                "Линия": line_range,
                "Лучший БМ": best_t["Букмекер"],
                "_ev": rec_ev, "_ev_c": ev_c,
            })
        if total_signals:
            for ts in sorted(total_signals, key=lambda x: -x["_ev"]):
                ev_c  = ts["_ev_c"]
                card_c = T['strong_bg'] if ts["_ev"] > 0 else T['none_bg']
                brd_c  = ("#16a34a" if _is_light else "#22c55e") if ts["_ev"] > 0 else T['border']
                st.markdown(f"""
<div style="background:{card_c};border:2px solid {brd_c};border-radius:12px;padding:14px 18px;margin-bottom:10px">
  <div style="font-size:11px;color:{T['text2']}">{ts['Матч']} &middot; {ts['Время']}</div>
  <div style="font-size:18px;font-weight:800;color:{ev_c};margin:4px 0">{ts['Сигнал']} — {ts['Ставить']}</div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:6px;margin-top:8px">
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">🏦 Оддс</div>
      <div style="font-size:14px;font-weight:700;color:{ev_c}">{ts['Оддс (Am)']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">💰 EV Edge</div>
      <div style="font-size:14px;font-weight:700;color:{ev_c}">{ts['EV Edge']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">📉 No-Vig %</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{ts['No-Vig %']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">📊 Маржа</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{ts['Маржа']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">📍 Линия</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{ts['Линия']}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:6px 10px">
      <div style="font-size:10px;color:{T['muted']}">🏦 Лучший БМ</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{ts['Лучший БМ']}</div>
    </div>
  </div>
</div>""", unsafe_allow_html=True)
        else:
            st.warning("Недостаточно данных для Totals-сигналов.")

    else:  # h2h
        sdf = _build_betting_signals_v2(df, has_draw, sport_cfg["key"])
        if sdf.empty:
            st.warning("Недостаточно данных для генерации сигналов. Загрузи коэффициенты сначала.")
        else:
            # Legend
            st.markdown(
                """
<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:12px">
  <span style="background:#1a1a2e;border:2px solid #a78bfa;color:#a78bfa;padding:4px 12px;border-radius:20px;font-weight:700">⚡ SHARP (Pinnacle EV)</span>
  <span style="background:#065f46;color:#4ade80;padding:4px 12px;border-radius:20px;font-weight:700">🟢 СИЛЬНЫЙ (&ge;70 conf)</span>
  <span style="background:#713f12;color:#fde68a;padding:4px 12px;border-radius:20px;font-weight:700">🟡 УМЕРЕННЫЙ (&ge;40 conf)</span>
  <span style="background:#1e3a5f;color:#93c5fd;padding:4px 12px;border-radius:20px;font-weight:700">🔵 СЛАБЫЙ (EV&gt;0)</span>
  <span style="background:var(--surface2,#1e293b);color:#64748b;padding:4px 12px;border-radius:20px">⚪ НЕТ</span>
</div>""",
                unsafe_allow_html=True,
            )

            for _, sig in sdf.iterrows():
                conf       = int(sig["_conf"]) if "_conf" in sig.index else 0
                edge_val   = float(sig["_edge"]) if "_edge" in sig.index else 0.0
                signal_str = str(sig["Сигнал"])
                is_sharp   = str(sig.get("Sharp Reference", "")).startswith("⚡")

                if is_sharp:
                    card_bg, border, text_clr = T['sharp_bg'],    "#a78bfa", "#7c3aed" if _is_light else "#a78bfa"
                elif conf >= 70:
                    card_bg, border, text_clr = T['strong_bg'],   "#16a34a" if _is_light else "#4ade80", "#166534" if _is_light else "#4ade80"
                elif conf >= 40:
                    card_bg, border, text_clr = T['moderate_bg'], "#ca8a04" if _is_light else "#fde68a", "#78350f" if _is_light else "#fde68a"
                elif edge_val > 0:
                    card_bg, border, text_clr = T['weak_bg'],     "#3b82f6", "#1d4ed8" if _is_light else "#93c5fd"
                else:
                    card_bg, border, text_clr = T['none_bg'],     T['border'], T['none_text']

                kelly_pct_str = str(sig.get("Kelly ¼ %", "0.00%"))
                try:
                    kelly_pct_val = float(kelly_pct_str.replace("%", ""))
                    kelly_dollar  = round(bankroll * kelly_pct_val / 100, 2)
                except Exception:
                    kelly_pct_val = 0.0
                    kelly_dollar  = 0.0

                sharp_badge = (
                    '<span style="background:#7c3aed;color:#fff;border-radius:6px;'
                    'padding:2px 8px;font-size:11px;margin-left:8px">⚡ Sharp EV</span>'
                ) if is_sharp else ""

                kelly_cell_bg  = T['kelly_bg']   if kelly_dollar > 0 else T['bg']
                kelly_cell_brd = T['kelly_brd']  if kelly_dollar > 0 else ""
                kelly_color    = T['kelly_text'] if kelly_dollar > 0 else T['muted']
                ev_color       = ("#16a34a" if _is_light else "#4ade80") if edge_val > 0 else ("#dc2626" if _is_light else "#f87171")
                ref_color      = "#7c3aed" if (is_sharp and _is_light) else ("#a78bfa" if is_sharp else T['text2'])

                st.markdown(f"""
<div style="background:{card_bg};border:2px solid {border};border-radius:12px;padding:16px 20px;margin-bottom:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div>
      <div style="font-size:11px;color:{T['text2']};margin-bottom:2px">{sig["Матч"]} &middot; {sig["Время"]}{sharp_badge}</div>
      <div style="font-size:20px;font-weight:800;color:{text_clr}">{signal_str} — СТАВИТЬ: {sig["На кого ставить"]}</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:22px;font-weight:900;color:{text_clr}">{sig["Odds (Am)"]}</div>
      <div style="font-size:12px;color:{T['text2']}">{sig["Odds (Dec)"]:.2f} децимал</div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:12px">
    <div style="background:{T['bg2']};border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:{T['muted']}">🏦 Лучший букмекер</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{sig["Лучший букмекер"]}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:{T['muted']}">💰 EV Edge</div>
      <div style="font-size:14px;font-weight:700;color:{ev_color}">{sig["EV Edge %"]}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:{T['muted']}">📉 No-Vig Fair</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{sig["No-Vig Fair %"]}</div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:{T['muted']}">🤝 Консенсус</div>
      <div style="font-size:14px;font-weight:700;color:{T['text']}">{sig["Консенсус книг"]}</div>
    </div>
    <div style="background:{kelly_cell_bg};{kelly_cell_brd}border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:{T['muted']}">📈 Kelly ¼ Ставка</div>
      <div style="font-size:14px;font-weight:700;color:{kelly_color}">${kelly_dollar:.2f} <span style="font-size:11px;color:{T['muted']}">({kelly_pct_str})</span></div>
    </div>
    <div style="background:{T['bg2']};border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:{T['muted']}">📊 Референс</div>
      <div style="font-size:14px;font-weight:700;color:{ref_color}">{sig.get("Sharp Reference", "Консенсус")}</div>
    </div>
  </div>
  <div style="margin-top:10px">
    <div style="font-size:10px;color:{T['muted']};margin-bottom:4px">Уверенность сигнала: {conf}/100</div>
    <div style="background:{T['bg_dark']};border-radius:4px;height:8px;overflow:hidden">
      <div style="background:{border};height:8px;width:{conf}%;border-radius:4px;transition:width .4s"></div>
    </div>
  </div>
  {'<div style="font-size:11px;color:' + T['muted'] + ';margin-top:8px">🔄 ' + str(sig["Другие исходы"]) + '</div>' if sig["Другие исходы"] else ''}
</div>""", unsafe_allow_html=True)

            # Bar chart
            _conf_vals = sdf["_conf"].tolist()
            _is_sharp  = [str(s).startswith("⚡") for s in sdf.get("Sharp Reference", [""] * len(sdf))]
            bar_colors = [
                "#a78bfa" if sharp else
                "#4ade80" if c >= 70 else
                "#fde68a" if c >= 40 else
                "#93c5fd" if c > 0 else "#475569"
                for c, sharp in zip(_conf_vals, _is_sharp)
            ]
            fig_sig = go.Figure(go.Bar(
                x=sdf["На кого ставить"] + " (" + sdf["Матч"] + ")",
                y=_conf_vals,
                marker_color=bar_colors,
                text=sdf["EV Edge %"].tolist(),
                textposition="outside",
            ))
            fig_sig.update_layout(
                title="Уверенность сигнала v2 (фиолетовый = Sharp Pinnacle EV)",
                xaxis_title="Исход", yaxis_title="Уверенность (0–100)",
                yaxis_range=[0, 115],
                height=380, **DARK,
            )
            st.plotly_chart(fig_sig, use_container_width=True)

# ── TAB 1: ARBITRAGE (Surebet Finder) ────────────────────────────────────
with tab_arb:
    st.markdown("#### ⚡ Арбитраж — автопоиск суребетов по всем матчам")
    if market_key != "h2h":
        st.info("ℹ️ Арбитражный поиск работает только для рынка **H2H / 1X2**.")
    else:
        # ── Параметры ─────────────────────────────────────────────────────
        arb_col1, arb_col2 = st.columns([2, 1])
        with arb_col1:
            arb_bankroll = st.number_input(
                "💰 Банкролл для арбитража ($)",
                min_value=10.0, max_value=1_000_000.0,
                value=float(st.session_state.get("bankroll", 1000.0)),
                step=100.0, format="%.0f",
                key="arb_bankroll_input",
                help="Сумма, которую распределим между букмекерами для гарантированной прибыли",
            )
        with arb_col2:
            st.markdown(
                "<div style='background:#1e293b;border-radius:8px;padding:12px;margin-top:24px'>"
                "<div style='font-size:11px;color:#64748b'>Формула Arb%</div>"
                "<div style='font-size:13px;color:#e2e8f0'>1 − Σ(1/D<sub>i</sub>)</div>"
                "<div style='font-size:11px;color:#94a3b8;margin-top:4px'>Если > 0 — гарантированная прибыль</div>"
                "</div>",
                unsafe_allow_html=True,
            )

        # ── Фильтр ликвидности ─────────────────────────────────────────────
        st.markdown("**🔒 Фильтр ликвидности**")
        liq_col1, liq_col2, liq_col3 = st.columns(3)
        with liq_col1:
            liq_enabled = st.checkbox(
                "Скрывать суребеты выше лимита", value=True, key="liq_enabled",
                help="Суребеты где ставка превышает лимит букмекера будут скрыты"
            )
        with liq_col2:
            liq_limit = st.number_input(
                "Лимит ставки ($)", min_value=10.0, max_value=50000.0,
                value=500.0, step=50.0, key="liq_limit",
                help="Типичный лимит: мягкие BK $200-$500, шарп $2000+"
            )
        with liq_col3:
            liq_warn_pct = st.slider(
                "Предупреждение при >% лимита", min_value=50, max_value=100, value=80,
                key="liq_warn_pct",
                help="Предупреждать если ставка > X% от лимита"
            )
        # Типичные лимиты по данным публичных источников
        BM_LIMITS = {
            "draftkings": 2000, "fanduel": 2000, "betmgm": 1500,
            "caesars": 1500, "pointsbet": 1000, "bet365": 500,
            "unibet": 500, "williamhill": 500, "betway": 300,
            "pinnacle": 10000, "bookmaker": 5000, "betfair": 3000,
            "circa": 50000, "matchbook": 2000,
        }
        def get_bm_limit(bm_name):
            key = str(bm_name).lower().replace(" ", "").replace(".", "")
            return float(BM_LIMITS.get(key, liq_limit))

        # ── Поиск арбитражей по всем матчам ──────────────────────────────
        arb_results = []
        for match_name, grp in df.groupby("Матч"):
            result = find_arb_in_group(grp, has_draw)
            if result is not None:
                arb_results.append({
                    "match":      match_name,
                    "time":       grp["Время"].iloc[0],
                    "arb_pct":    result["arb_pct"],
                    "outcomes":   result["outcomes"],
                })

        # ── Применяем фильтр ликвидности ────────────────────────────────────
        liq_hidden = []
        liq_ok = []
        for _arb in arb_results:
            _outcomes = _arb["outcomes"]
            _dec_list = [v["dec"] for v in _outcomes.values()]
            _stakes   = arb_stakes(arb_bankroll, _dec_list)
            _over   = False
            _warns  = []
            for _i, (_name, _info) in enumerate(_outcomes.items()):
                _sv        = _stakes[_i] if _i < len(_stakes) else 0
                _bm_lim    = get_bm_limit(_info["bm"])
                _eff_lim   = min(liq_limit, _bm_lim)
                if liq_enabled and _sv > _eff_lim:
                    _over = True
                elif _sv > _eff_lim * liq_warn_pct / 100:
                    _warns.append(
                        f"⚠️ {_info['bm']} ({_name}): "
                        f"${_sv:.0f} = {_sv/_eff_lim*100:.0f}% от лимита ${_eff_lim:.0f}"
                    )
            if _over:
                liq_hidden.append(_arb)
            else:
                liq_ok.append({**_arb, "_liq_warnings": _warns})
        if liq_hidden:
            with st.expander(f"🚫 Скрыто {len(liq_hidden)} суребетов — ставка превышает лимит"):
                for _h in liq_hidden:
                    _ds = arb_stakes(arb_bankroll, [v["dec"] for v in _h["outcomes"].values()])
                    _ms = max(_ds) if _ds else 0
                    st.markdown(f"- **{_h['match']}** — макс ставка ${_ms:.0f} > лимита ${liq_limit:.0f}")
        arb_results = liq_ok

        if not arb_results:
            st.warning(
                "🔍 Суребеты не найдены среди загруженных матчей. "
                "**Совет:** добавь больше букмекеров (кнопка ✔️ Все в сайдбаре) "
                "— арбитраж возникает когда разные книги сильно расходятся в оценках."
            )
            # Показываем ближайшие к арбитражу матчи
            near_arb = []
            for match_name, grp in df.groupby("Матч"):
                best = {}
                for _, row in grp.iterrows():
                    try:
                        h_am = row.get("Odds Хозяева (Am)")
                        a_am = row.get("Odds Гости (Am)")
                        if h_am is None or a_am is None: continue
                        home = row["Хозяева"]; away = row["Гости"]
                        for name, am in [(home, float(h_am)), (away, float(a_am))]:
                            dec = american_to_decimal(am)
                            if name not in best or dec > best[name][0]:
                                best[name] = (dec, row["Букмекер"])
                        if has_draw:
                            d_am = row.get("Odds Ничья (Am)")
                            if d_am and str(d_am) != "nan":
                                dec = american_to_decimal(float(d_am))
                                if "Ничья" not in best or dec > best["Ничья"][0]:
                                    best["Ничья"] = (dec, row["Букмекер"])
                    except Exception: continue
                if len(best) >= 2:
                    dec_list = [v[0] for v in best.values()]
                    ap = arb_percentage(dec_list)
                    near_arb.append({"Матч": match_name, "Время": grp["Время"].iloc[0],
                                     "Arb%": round(ap * 100, 3),
                                     "До арбитража": f"{abs(round(ap * 100, 3))}% gap"})
            if near_arb:
                near_df = pd.DataFrame(near_arb).sort_values("Arb%", ascending=False).head(10)
                st.markdown("##### Ближайшие к суребету матчи")
                st.dataframe(near_df, use_container_width=True, hide_index=True)
        else:
            st.success(f"✅ Найдено **{len(arb_results)}** суребет(а) в текущих данных!")

            for arb in arb_results:
                profit_pct = arb["arb_pct"]
                profit_usd = round(arb_bankroll * profit_pct / 100, 2)
                outcomes   = arb["outcomes"]
                dec_list   = [v["dec"] for v in outcomes.values()]
                stakes     = arb_stakes(arb_bankroll, dec_list)
                outcome_names = list(outcomes.keys())
                liq_warn_list = arb.get("_liq_warnings", [])
                liq_warn_html = (
                    '<div style="background:#2d1f00;border:1px solid #f59e0b;border-radius:6px;'
                    'padding:6px 10px;margin-bottom:8px;font-size:11px;color:#fde68a">'
                    + "<br>".join(liq_warn_list) + "</div>"
                ) if liq_warn_list else ""

                st.markdown(f"""
<div style="background:#0f2a1a;border:2px solid #22c55e;border-radius:12px;padding:16px 20px;margin-bottom:16px">
  {liq_warn_html}
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;margin-bottom:12px">
    <div>
      <div style="font-size:11px;color:#94a3b8">{arb["time"]}</div>
      <div style="font-size:18px;font-weight:800;color:#4ade80">⚡ {arb["match"]}</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:26px;font-weight:900;color:#22c55e">+{profit_pct:.3f}%</div>
      <div style="font-size:14px;color:#4ade80">+${profit_usd:.2f} гарантировано</div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:8px">""", unsafe_allow_html=True)

                for i, (name, info) in enumerate(outcomes.items()):
                    stake_val = stakes[i] if i < len(stakes) else 0
                    payout    = round(stake_val * info["dec"], 2)
                    st.markdown(f"""
    <div style="background:#1e293b;border-radius:8px;padding:10px 14px">
      <div style="font-size:11px;color:#64748b;margin-bottom:2px">Исход: <b style="color:#e2e8f0">{name}</b></div>
      <div style="font-size:16px;font-weight:700;color:#fde68a">{info["am"]}</div>
      <div style="font-size:12px;color:#94a3b8">{info["dec"]:.3f} децимал</div>
      <div style="font-size:11px;color:#64748b;margin-top:6px">Букмекер</div>
      <div style="font-size:13px;font-weight:600;color:#93c5fd">{info["bm"]}</div>
      <div style="font-size:11px;color:#64748b;margin-top:6px">Ставка</div>
      <div style="font-size:15px;font-weight:700;color:#4ade80">${stake_val:.2f}</div>
      <div style="font-size:11px;color:#64748b">Выплата: ${payout:.2f}</div>
    </div>""", unsafe_allow_html=True)

                st.markdown("  </div>\n</div>", unsafe_allow_html=True)

            # ── Таблица всех суребетов ────────────────────────────────────
            arb_rows = []
            for arb in arb_results:
                outcomes  = arb["outcomes"]
                dec_list  = [v["dec"] for v in outcomes.values()]
                stakes    = arb_stakes(arb_bankroll, dec_list)
                for i, (name, info) in enumerate(outcomes.items()):
                    arb_rows.append({
                        "Матч":      arb["match"],
                        "Время":     arb["time"],
                        "Arb%":      f"+{arb['arb_pct']:.3f}%",
                        "Исход":     name,
                        "Букмекер":  info["bm"],
                        "Odds (Am)": info["am"],
                        "Odds (Dec)": round(info["dec"], 3),
                        "Ставка $":  stakes[i] if i < len(stakes) else 0,
                    })
            if arb_rows:
                arb_df = pd.DataFrame(arb_rows)
                st.dataframe(arb_df, use_container_width=True, hide_index=True,
                             height=min(500, 60 + len(arb_df) * 38))
                st.download_button(
                    "⬇️ CSV арбитражи",
                    arb_df.to_csv(index=False).encode(),
                    f"arbitrage_{sport_cfg['key']}_{__import__('datetime').datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv",
                )

            # ── Калькулятор для ручного ввода ─────────────────────────────
            st.divider()
            st.markdown("##### 🧮 Калькулятор арбитражных ставок")
            st.caption("Введи коэффициенты вручную для любого матча")
            calc_col1, calc_col2, calc_col3 = st.columns(3)
            with calc_col1:
                calc_d1 = st.number_input("Decimal Odds Исход 1", min_value=1.01, value=2.10, step=0.05, key="calc_d1")
            with calc_col2:
                calc_d2 = st.number_input("Decimal Odds Исход 2", min_value=1.01, value=2.05, step=0.05, key="calc_d2")
            with calc_col3:
                calc_d3_on = st.checkbox("Ничья / 3-й исход", value=False, key="calc_d3_on")
                calc_d3 = st.number_input("Decimal Odds Ничья", min_value=1.01, value=3.50, step=0.05,
                                           key="calc_d3", disabled=not calc_d3_on)

            calc_bank = st.number_input("Банкролл для калькулятора ($)", min_value=10.0,
                                         value=arb_bankroll, step=100.0, key="calc_bank")

            calc_odds = [calc_d1, calc_d2] + ([calc_d3] if calc_d3_on else [])
            calc_arb  = arb_percentage(calc_odds)
            calc_stakes = arb_stakes(calc_bank, calc_odds) if calc_arb > 0 else []

            if calc_arb > 0:
                calc_profit = round(calc_bank * calc_arb, 2)
                st.success(f"✅ СУРЕБЕТ! Arb% = +{calc_arb*100:.3f}% | Гарантированная прибыль: **${calc_profit:.2f}**")
                for i, (d, s) in enumerate(zip(calc_odds, calc_stakes)):
                    st.markdown(
                        f"**Исход {i+1}** (Dec: {d:.3f}) → ставка **${s:.2f}** "
                        f"→ выплата **${round(s*d,2):.2f}**"
                    )
            else:
                margin = abs(calc_arb * 100)
                st.info(f"ℹ️ Суребета нет. Margin букмекера: **{margin:.2f}%** (нужно перекрыть)")

# ── TAB 1: TABLE ──────────────────────────────
with tab_table:
    st.markdown(f"#### {cur_sport} · {market_label}{demo_tag}")
    match_opts = ["Все матчи"] + sorted(df["Матч"].unique().tolist())
    sel = st.selectbox("Фильтр по матчу", match_opts)
    show = df[df["Матч"]==sel] if sel!="Все матчи" else df
    show = show[[c for c in show.columns if not c.startswith("_")]]
    st.dataframe(show, use_container_width=True, hide_index=True,
                 height=min(500, 56+len(show)*35))
    st.download_button("⬇️ CSV", show.to_csv(index=False).encode(),
        f"odds_{sport_cfg['key']}_{market_key}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
        mime="text/csv")

# ── TAB 2: CHARTS ─────────────────────────────
with tab_chart:
    matches = sorted(df["Матч"].unique().tolist())
    sel2 = st.selectbox("Матч", matches, key="t2")
    mdf  = df[df["Матч"]==sel2].copy()
    home_t = mdf["Хозяева"].iloc[0]
    away_t = mdf["Гости"].iloc[0]
    color  = sport_cfg["color"]

    def safe_dec(col):
        return mdf[col].apply(lambda x: american_to_decimal(float(x)) if x is not None and str(x)!="nan" else None)

    if market_key == "h2h":
        fig = go.Figure()
        pairs = [(home_t,"Odds Хозяева (Am)",color),(away_t,"Odds Гости (Am)","#f97316")]
        if has_draw: pairs.append(("Ничья","Odds Ничья (Am)","#facc15"))
        for name,col,clr in pairs:
            dec_v = safe_dec(col)
            am_t  = mdf[col].apply(lambda x: fmt_am(x) if x is not None and str(x)!="nan" else "")
            fig.add_trace(go.Bar(name=name,x=mdf["Букмекер"],y=dec_v,marker_color=clr,
                                 text=am_t,textposition="outside"))
        fig.update_layout(title=f"Decimal Odds · {sel2}",barmode="group",
                          xaxis_title="Букмекер",yaxis_title="Decimal",height=400,**DARK)
        st.plotly_chart(fig,use_container_width=True)

        # No-vig probabilities
        prob_rows=[]
        for _,row in mdf.iterrows():
            try:
                h_am=float(row["Odds Хозяева (Am)"]); a_am=float(row["Odds Гости (Am)"])
                h_i=decimal_to_implied(american_to_decimal(h_am))
                a_i=decimal_to_implied(american_to_decimal(a_am))
                d_am=row.get("Odds Ничья (Am)")
                if has_draw and d_am and str(d_am)!="nan":
                    d_i=decimal_to_implied(american_to_decimal(float(d_am)))
                    nv=no_vig_prob([h_i,a_i,d_i])
                    prob_rows.append({"Букмекер":row["Букмекер"],home_t:nv[0],away_t:nv[1],"Ничья":nv[2]})
                else:
                    nv=no_vig_prob([h_i,a_i])
                    prob_rows.append({"Букмекер":row["Букмекер"],home_t:nv[0],away_t:nv[1]})
            except Exception: continue
        if prob_rows:
            pf=pd.DataFrame(prob_rows)
            fig2=go.Figure()
            for name,clr in [(home_t,color),(away_t,"#f97316")] + ([("Ничья","#facc15")] if has_draw else []):
                if name in pf.columns:
                    fig2.add_trace(go.Bar(name=name,x=pf["Букмекер"],y=pf[name],marker_color=clr,
                                         text=pf[name].apply(lambda x:f"{x:.1f}%"),textposition="outside"))
            fig2.update_layout(title="No-Vig вероятности",barmode="group",
                               yaxis_range=[0,105],height=380,**DARK)
            st.plotly_chart(fig2,use_container_width=True)

        # Best odds table
        best_rows=[]
        cols_chk=[(home_t,"Odds Хозяева (Am)"),(away_t,"Odds Гости (Am)")]
        if has_draw: cols_chk.append(("Ничья","Odds Ничья (Am)"))
        for name,col in cols_chk:
            sub=mdf[["Букмекер",col]].dropna()
            sub=sub[sub[col].apply(lambda x:str(x)!="nan")].copy()
            if sub.empty: continue
            sub["_d"]=sub[col].apply(lambda x:american_to_decimal(float(x)))
            best=sub.loc[sub["_d"].idxmax()]
            am_v=float(best[col]); dec_v=american_to_decimal(am_v)
            best_rows.append({"Исход":name,"Лучший букмекер":best["Букмекер"],
                "Odds (Am)":fmt_am(am_v),"Decimal":dec_v,
                "Implied %":f"{decimal_to_implied(dec_v):.1f}%"})
        if best_rows:
            st.markdown("##### 🏆 Лучшие коэффициенты")
            st.dataframe(pd.DataFrame(best_rows),use_container_width=True,hide_index=True)

    elif market_key=="spreads":
        fig=go.Figure()
        for name,col,clr in [(home_t,"Odds Хозяева (Am)",color),(away_t,"Odds Гости (Am)","#f97316")]:
            fig.add_trace(go.Bar(name=name,x=mdf["Букмекер"],y=safe_dec(col),marker_color=clr))
        fig.update_layout(title=f"Spread Odds · {sel2}",barmode="group",height=400,**DARK)
        st.plotly_chart(fig,use_container_width=True)
        sdf=mdf[["Букмекер","Спред Хозяева","Спред Гости"]].dropna()
        if not sdf.empty:
            fig3=go.Figure()
            for name,col,clr,pos in [(home_t,"Спред Хозяева",color,"top center"),(away_t,"Спред Гости","#f97316","bottom center")]:
                fig3.add_trace(go.Scatter(x=sdf["Букмекер"],y=sdf[col].astype(float),
                    mode="lines+markers+text",name=name,line=dict(color=clr,width=2),marker=dict(size=9),
                    text=sdf[col].astype(float).apply(lambda x:f"{x:+.1f}"),textposition=pos))
            fig3.update_layout(title="Линии спреда",height=300,**DARK)
            st.plotly_chart(fig3,use_container_width=True)

    elif market_key=="totals":
        fig=go.Figure()
        fig.add_trace(go.Bar(name="Over", x=mdf["Букмекер"],y=safe_dec("Odds Over (Am)"), marker_color="#22c55e"))
        fig.add_trace(go.Bar(name="Under",x=mdf["Букмекер"],y=safe_dec("Odds Under (Am)"),marker_color="#ef4444"))
        fig.update_layout(title=f"Totals · {sel2}",barmode="group",height=400,**DARK)
        st.plotly_chart(fig,use_container_width=True)
        tdf=mdf[["Букмекер","Тотал Линия"]].dropna()
        if not tdf.empty:
            fig4=go.Figure()
            fig4.add_trace(go.Scatter(x=tdf["Букмекер"],y=tdf["Тотал Линия"].astype(float),
                mode="lines+markers+text",name="Тотал",line=dict(color="#a855f7",width=2),marker=dict(size=9),
                text=tdf["Тотал Линия"].astype(float).apply(str),textposition="top center"))
            fig4.update_layout(title="Линии тотала",height=300,**DARK)
            st.plotly_chart(fig4,use_container_width=True)

# ── TAB 3: VALUE BETS ─────────────────────────
with tab_value:
    st.markdown("#### 💎 Value Bets — ставки с положительным EV")
    if market_key != "h2h":
        st.info("ℹ️ Value Bet расчёт работает для рынка **H2H / 1X2**.")
    else:
        col_method, col_gmail = st.columns([3,2])
        with col_method:
            st.info(
                "**No-Vig EV формула:**\n"
                "1. Implied % → 2. No-Vig нормализация → 3. EV Edge = fair×dec−1\n"
                + ("⚽ Трёхисходник (1/X/2) для Football." if has_draw else "🏈/🏀 Двухисходник.")
            )
        with col_gmail:
            if gmail_on:
                st.success(f"📧 Gmail-alert АКТИВЕН\nПорог: EV ≥ **{VALUE_THRESHOLD}%**\nПолучатель: {gmail_to}")
            else:
                st.warning("📧 Gmail-alert выключен\n*(включи в боковой панели)*")

        if vdf_all.empty:
            st.warning(f"Нет value bets с EV ≥ {min_edge}%. Снизь порог или добавь больше букмекеров.")
        else:
            st.success(f"✅ Найдено **{len(vdf_all)}** value bet(s) с EV Edge ≥ {min_edge}%")
            # Highlight high EV
            def highlight_ev(row):
                ev_str = row.get("EV Edge %","")
                try:
                    val = float(ev_str.replace("+","").replace("%",""))
                    if val >= VALUE_THRESHOLD:
                        return ["background-color:#065f46"]*len(row)
                except Exception:
                    pass
                return [""]*len(row)
            st.dataframe(vdf_all.style.apply(highlight_ev, axis=1),
                         use_container_width=True, height=min(600,60+len(vdf_all)*38))
            st.download_button("⬇️ CSV", vdf_all.to_csv(index=True).encode(),
                f"value_bets_{sport_cfg['key']}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv")

        # EV scatter
        st.divider()
        st.markdown("##### EV Edge (хозяева) — все матчи")
        ev_rows=[]
        for _,row in df.iterrows():
            h_am=row.get("Odds Хозяева (Am)"); a_am=row.get("Odds Гости (Am)")
            if h_am is None or a_am is None or str(h_am)=="nan" or str(a_am)=="nan": continue
            try:
                h_dec=american_to_decimal(float(h_am)); a_dec=american_to_decimal(float(a_am))
                h_i=decimal_to_implied(h_dec); a_i=decimal_to_implied(a_dec)
                d_am=row.get("Odds Ничья (Am)")
                nv=no_vig_prob([h_i,a_i,decimal_to_implied(american_to_decimal(float(d_am)))]
                               if (has_draw and d_am and str(d_am)!="nan")
                               else [h_i,a_i])
                ev_rows.append({"Матч":row["Матч"],"Букмекер":row["Букмекер"],
                                 "EV Хозяева %":round(ev_edge(nv[0],h_dec)*100,2)})
            except Exception: continue
        if ev_rows:
            evf=pd.DataFrame(ev_rows)
            fig_ev=px.scatter(evf,x="Букмекер",y="EV Хозяева %",color="Матч",
                size=evf["EV Хозяева %"].abs()+1,
                hover_data=["Матч","Букмекер","EV Хозяева %"],
                title="EV Edge Хозяева (%) по букмекерам",template="plotly_dark",height=400)
            fig_ev.add_hline(y=0,line_dash="dash",line_color="#ef4444",annotation_text="EV=0")
            fig_ev.add_hline(y=VALUE_THRESHOLD,line_dash="dot",line_color="#4ade80",
                             annotation_text=f"Gmail threshold {VALUE_THRESHOLD}%")
            fig_ev.update_layout(**DARK)
            st.plotly_chart(fig_ev,use_container_width=True)

# ── TAB 4: LIVE SCORES ────────────────────────
with tab_live:
    st.markdown("#### 📺 Live Scores — ESPN Public API")
    st.caption("Обновляется каждые 60 секунд · Данные: [ESPN](https://www.espn.com)")

    # League selector
    live_leagues = st.multiselect(
        "Лиги",
        list(ESPN_LEAGUES.keys()),
        default=list(ESPN_LEAGUES.keys()),
        key="live_leagues",
    )

    if not live_leagues:
        st.info("Выбери хотя бы одну лигу выше.")
        st.stop()

    refresh_scores = st.button("🔄 Обновить счета", key="refresh_scores")
    if refresh_scores:
        # Clear cache to force fresh fetch
        fetch_scores.clear()

    for league_name in live_leagues:
        cfg = ESPN_LEAGUES[league_name]
        st.markdown(f"### {league_name}")

        with st.spinner(f"Загружаю {league_name}…"):
            events = fetch_scores(cfg["path"])

        if not events:
            st.info(f"Нет текущих матчей для {league_name} (возможно, межсезонье).")
            continue

        # Split live / scheduled / final
        live_evs  = [e for e in events if e.get("competitions",[{}])[0].get("status",{}).get("type",{}).get("state")=="in"]
        sched_evs = [e for e in events if e.get("competitions",[{}])[0].get("status",{}).get("type",{}).get("state")=="pre"]
        final_evs = [e for e in events if e.get("competitions",[{}])[0].get("status",{}).get("type",{}).get("state")=="post"]

        # Summary badges
        cols_stat = st.columns(3)
        with cols_stat[0]:
            if live_evs:
                st.markdown(f'<span style="background:#065f46;color:#4ade80;padding:4px 10px;border-radius:12px;font-weight:700">🔴 LIVE: {len(live_evs)}</span>', unsafe_allow_html=True)
        with cols_stat[1]:
            st.markdown(f'<span style="background:#1e3a5f;color:#60a5fa;padding:4px 10px;border-radius:12px">📅 Предстоит: {len(sched_evs)}</span>', unsafe_allow_html=True)
        with cols_stat[2]:
            st.markdown(f'<span style="background:#1e293b;color:#94a3b8;padding:4px 10px;border-radius:12px">🏁 Завершено: {len(final_evs)}</span>', unsafe_allow_html=True)

        st.markdown("")

        # Render in columns
        if live_evs:
            st.markdown("**🔴 Сейчас играют**")
            cols = st.columns(min(len(live_evs), 3))
            for i, ev in enumerate(live_evs):
                with cols[i % 3]:
                    render_score_card(ev, cfg["period_name"])

        if sched_evs:
            with st.expander(f"📅 Предстоящие ({len(sched_evs)})", expanded=len(live_evs)==0):
                cols = st.columns(min(len(sched_evs), 3))
                for i, ev in enumerate(sched_evs):
                    with cols[i % 3]:
                        render_score_card(ev, cfg["period_name"])

        if final_evs:
            with st.expander(f"🏁 Завершённые ({len(final_evs)})", expanded=False):
                cols = st.columns(min(len(final_evs), 3))
                for i, ev in enumerate(final_evs):
                    with cols[i % 3]:
                        render_score_card(ev, cfg["period_name"])

        st.divider()

    # Auto-refresh scores every 60s
    if st.session_state.auto_refresh:
        st.markdown('<meta http-equiv="refresh" content="60">', unsafe_allow_html=True)

# ── TAB 6: HISTORICAL ODDS ─────────────────────────────
with tab_hist_odds:
    st.markdown("#### 📈 Исторические коэффициенты — снимок odds на выбранную дату")

    _ho_col1, _ho_col2, _ho_col3 = st.columns([1, 1, 1])
    with _ho_col1:
        _ho_date = st.date_input(
            "📅 Дата снимка",
            value=datetime(2024, 12, 1),
            min_value=datetime(2020, 6, 1),
            max_value=datetime.now(),
            key="hist_odds_date",
        )
    with _ho_col2:
        _ho_sport_label = st.selectbox(
            "🏟️ Лига",
            list(SPORTS_CATALOGUE.keys()),
            index=0,
            key="hist_odds_sport",
        )
    with _ho_col3:
        _ho_market_labels = SPORTS_CATALOGUE[_ho_sport_label]["markets"]
        _ho_market_label = st.selectbox(
            "📊 Рынок",
            _ho_market_labels,
            index=0,
            key="hist_odds_market",
        )

    _ho_sport_cfg = SPORTS_CATALOGUE[_ho_sport_label]
    _ho_market_key = MARKET_KEY_MAP.get(_ho_market_label, "h2h")
    _ho_has_draw = _ho_sport_cfg["has_draw"]
    _ho_date_iso = f"{_ho_date.isoformat()}T12:00:00Z"

    _ho_fetch = st.button("📥 Загрузить исторические коэффициенты",
                          use_container_width=True, key="hist_odds_fetch_btn")

    if _ho_fetch:
        if not api_key:
            st.warning("⚠️ Введи API ключ в боковой панели. Исторические данные недоступны в демо-режиме.")
        else:
            with st.spinner(f"Загружаю {_ho_sport_label} · {_ho_market_label} на {_ho_date}…"):
                _ho_events, _ho_ts = fetch_historical_odds(
                    api_key, _ho_sport_cfg["key"],
                    REGION_MAP[region_label], _ho_market_key, _ho_date_iso,
                )
            if _ho_events is None:
                st.error("❌ Ошибка загрузки. Проверь API ключ и доступность исторических данных для выбранной даты.")
            elif not _ho_events:
                st.info("ℹ️ Нет событий на выбранную дату. Попробуй другую дату или лигу.")
            else:
                st.session_state["hist_odds_events"] = _ho_events
                st.session_state["hist_odds_ts"] = _ho_ts
                st.session_state["hist_odds_mk"] = _ho_market_key
                st.session_state["hist_odds_draw"] = _ho_has_draw
                st.session_state["hist_odds_sport_label"] = _ho_sport_label

    # ── Display stored historical data ──────────────────
    _ho_stored = st.session_state.get("hist_odds_events")
    if _ho_stored:
        _ho_mk_stored = st.session_state.get("hist_odds_mk", "h2h")
        _ho_draw_stored = st.session_state.get("hist_odds_draw", False)
        _ho_ts_stored = st.session_state.get("hist_odds_ts", "")
        _ho_sport_stored = st.session_state.get("hist_odds_sport_label", "")

        _ho_df = parse_historical_to_df(_ho_stored, _ho_mk_stored, _ho_draw_stored)
        if not _ho_df.empty:
            st.success(f"✅ **{_ho_sport_stored}** — снимок **{_ho_ts_stored}** · "
                       f"**{len(_ho_stored)}** матчей · **{_ho_df['Букмекер'].nunique()}** букмекеров")

            # ── Summary metrics ────────────────────────────
            _hm1, _hm2, _hm3, _hm4 = st.columns(4)
            with _hm1:
                st.metric("Матчей", _ho_df["Матч"].nunique())
            with _hm2:
                st.metric("Букмекеров", _ho_df["Букмекер"].nunique())
            with _hm3:
                st.metric("Строк данных", len(_ho_df))
            with _hm4:
                st.metric("Рынок", _ho_mk_stored.upper())

            # ── Filter by match ────────────────────────────
            _ho_matches = sorted(_ho_df["Матч"].unique())
            _ho_sel_match = st.multiselect(
                "🔍 Фильтр по матчу",
                _ho_matches,
                default=[],
                key="hist_odds_match_filter",
            )
            _ho_display = _ho_df[_ho_df["Матч"].isin(_ho_sel_match)] if _ho_sel_match else _ho_df

            # ── Data table ─────────────────────────────────
            display_cols = [c for c in _ho_display.columns if not c.startswith("_")]
            st.dataframe(
                _ho_display[display_cols],
                use_container_width=True,
                height=min(600, 60 + len(_ho_display) * 36),
            )

            # ── Chart: odds comparison across bookmakers ───
            if _ho_mk_stored == "h2h" and "Odds Хозяева (Am)" in _ho_display.columns:
                st.markdown("##### 📊 Сравнение коэффициентов по букмекерам")
                _ho_chart_match = st.selectbox(
                    "Выбери матч для графика",
                    _ho_display["Матч"].unique(),
                    key="hist_odds_chart_match",
                )
                _ho_chart_data = _ho_display[_ho_display["Матч"] == _ho_chart_match].copy()
                if not _ho_chart_data.empty:
                    _ho_chart_data["Odds Хозяева (Am)"] = pd.to_numeric(
                        _ho_chart_data["Odds Хозяева (Am)"], errors="coerce"
                    )
                    _ho_chart_data["Odds Гости (Am)"] = pd.to_numeric(
                        _ho_chart_data["Odds Гости (Am)"], errors="coerce"
                    )
                    _ho_home = _ho_chart_data["Хозяева"].iloc[0]
                    _ho_away = _ho_chart_data["Гости"].iloc[0]

                    _ho_fig = go.Figure()
                    _ho_fig.add_trace(go.Bar(
                        x=_ho_chart_data["Букмекер"],
                        y=_ho_chart_data["Odds Хозяева (Am)"],
                        name=_ho_home,
                        marker_color="#38bdf8",
                    ))
                    _ho_fig.add_trace(go.Bar(
                        x=_ho_chart_data["Букмекер"],
                        y=_ho_chart_data["Odds Гости (Am)"],
                        name=_ho_away,
                        marker_color="#f97316",
                    ))
                    if _ho_draw_stored and "Odds Ничья (Am)" in _ho_chart_data.columns:
                        _ho_chart_data["Odds Ничья (Am)"] = pd.to_numeric(
                            _ho_chart_data["Odds Ничья (Am)"], errors="coerce"
                        )
                        _ho_fig.add_trace(go.Bar(
                            x=_ho_chart_data["Букмекер"],
                            y=_ho_chart_data["Odds Ничья (Am)"],
                            name="Ничья",
                            marker_color="#4ade80",
                        ))
                    _ho_fig.update_layout(
                        barmode="group",
                        title=f"Odds: {_ho_chart_match}",
                        xaxis_title="Букмекер",
                        yaxis_title="American Odds",
                        **DARK,
                    )
                    st.plotly_chart(_ho_fig, use_container_width=True)

            # ── Download CSV ───────────────────────────────
            st.download_button(
                "⬇️ Скачать CSV",
                _ho_display[display_cols].to_csv(index=False).encode(),
                f"historical_odds_{_ho_date}.csv",
                mime="text/csv",
                key="hist_odds_csv_btn",
            )
        else:
            st.info("ℹ️ Не удалось разобрать данные. Попробуй другой рынок или дату.")

    elif not _ho_stored:
        st.info(
            "📈 Здесь можно посмотреть **исторические коэффициенты** — "
            "снимок odds на любую дату начиная с июня 2020.\n\n"
            "1. Выбери дату, лигу и рынок\n"
            "2. Нажми **📥 Загрузить**\n"
            "3. Анализируй таблицу и графики\n\n"
            "**Требуется API ключ** [The Odds API](https://the-odds-api.com) "
            "(исторические запросы тарифицируются отдельно)."
        )

# ── TAB 7: HISTORY (Google Sheets) ────────────────────
with tab_history:
    st.markdown("#### 📊 История ставок — Google Sheets")

    _gs_url = st.session_state.get("gsheet_url", "")
    if not _gs_url:
        st.info("ℹ️ Укажи URL Google Таблицы в боковой панели (раздел ‘Google Sheets’).")
    else:
        col_h1, col_h2 = st.columns([2, 1])
        with col_h1:
            st.caption(f"🔗 Таблица: [{_gs_url[:60]}...]({_gs_url})")
        with col_h2:
            if st.button("📥 Обновить / Читать", use_container_width=True, key="hist_read_btn"):
                st.session_state["gs_read_triggered"] = True

        # Handle write trigger from sidebar
        _gs_write = st.session_state.get("gs_write_triggered", False)
        if "gs_write_triggered" in st.session_state:
            del st.session_state["gs_write_triggered"]
        if _gs_write:
            if not vdf_all.empty and market_key == "h2h":
                with st.spinner("Записываю value bets в Google Sheets…"):
                    ok, msg = log_value_bets_to_sheets(vdf_all, cur_sport, _gs_url)
                if ok:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
            else:
                st.warning("Нет value bets для записи. Сначала загрузи коэффициенты (рынок H2H).")

        # Handle read trigger
        _gs_read = st.session_state.get("gs_read_triggered", False)
        if "gs_read_triggered" in st.session_state:
            del st.session_state["gs_read_triggered"]
        if _gs_read:
            with st.spinner("Читаю историю из Google Sheets…"):
                hist_df, hist_err = read_history_from_sheets(_gs_url)
            if hist_err:
                st.error(f"❌ {hist_err}")
            elif hist_df is not None and not hist_df.empty:
                st.session_state["history_df"] = hist_df

        # Display stored history
        hist_display = st.session_state.get("history_df")
        if hist_display is not None and not hist_display.empty:
            st.success(f"✅ Загружено **{len(hist_display)}** записей из истории")

            # Summary metrics
            m1, m2, m3, m4 = st.columns(4)
            try:
                ev_col = [c for c in hist_display.columns if "EV" in c or "edge" in c.lower()]
                if ev_col:
                    evs = pd.to_numeric(hist_display[ev_col[0]].astype(str).str.replace("%","").str.replace("+",""), errors="coerce")
                    with m1: st.metric("Ср. EV Edge", f"{evs.mean():.1f}%" if not evs.isna().all() else "—")
                    with m2: st.metric("Макс EV Edge", f"{evs.max():.1f}%" if not evs.isna().all() else "—")
                with m3: st.metric("Всего записей", len(hist_display))
                bm_col = [c for c in hist_display.columns if "Букмекер" in c or "book" in c.lower()]
                if bm_col:
                    with m4: st.metric("Уник. букмекеров", hist_display[bm_col[0]].nunique())
            except Exception:
                pass

            st.dataframe(hist_display, use_container_width=True,
                         height=min(600, 60 + len(hist_display) * 36))
            st.download_button("⬇️ Скачать CSV",
                               hist_display.to_csv(index=False).encode(),
                               "value_bets_history.csv", mime="text/csv")
        else:
            st.info("📊 История пуста. \n\n"
                    "Чтобы заполнить: \n"
                    "1. Загрузи коэффициенты (рынок **H2H**) \n"
                    "2. Нажми **‘📝 Записать сейча’** в боковой панели \n"
                    "3. Нажми **‘📛 Обновить / Читать’** выше")

        # Instructions for setup
        with st.expander("ℹ️ Настройка Google Sheets", expanded=False):
            st.markdown("""
**Шаг 1.** Создай Google Cloud проект и включи **Google Sheets API + Google Drive API**.

**Шаг 2.** Создай Service Account, скачай JSON-ключ.

**Шаг 3.** Расшарий таблицу с email Service Account (роль Редактор).

**Шаг 4.** В Streamlit Cloud добавь секреты в формате:
```toml
GSHEET_URL = "https://docs.google.com/spreadsheets/d/.../edit"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n"
client_email = "...@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```
""")

# ── TAB 7: BANKROLL STATISTICS ───────────────────────────────────────────────
with tab_bankroll:
    st.markdown("#### 💰 Статистика банкролла")

    _gs_url_br = st.session_state.get("gsheet_url", "")
    if not _gs_url_br:
        st.info("ℹ️ Укажи URL Google Таблицы в боковой панели — история подгрузится автоматически.")
    else:
        # Загружаем историю (или берём из кеша)
        if "history_df" not in st.session_state or st.session_state.get("history_df") is None:
            with st.spinner("Загружаю историю из Google Sheets…"):
                _hist, _err = read_history_from_sheets(_gs_url_br)
            if not _err and _hist is not None and not _hist.empty:
                st.session_state["history_df"] = _hist

        hist_br = st.session_state.get("history_df")

        if hist_br is None or hist_br.empty:
            st.warning("История ставок пуста. Сначала залогируй value bets через вкладку 'История ставок'.")
            # Показываем демо-банкролл на основе текущих value bets
            if not vdf_all.empty:
                st.markdown("##### 📊 Демо: ожидаемый рост по текущим value bets")
                try:
                    demo_evs = pd.to_numeric(
                        vdf_all["EV Edge %"].astype(str).str.replace("%","").str.replace("+",""),
                        errors="coerce"
                    ).dropna()
                    demo_kelly = pd.to_numeric(
                        vdf_all.get("Kelly ¼ $", vdf_all.get("Kelly ¼ %", pd.Series([0]*len(vdf_all)))
                                   ).astype(str).str.replace("%","").str.replace("$",""),
                        errors="coerce"
                    ).fillna(0)
                    br_now = bankroll
                    demo_rows = []
                    for i, (ev, ks) in enumerate(zip(demo_evs, demo_kelly)):
                        ks_dollar = ks if ks > 1 else br_now * ks / 100
                        br_now   += br_now * (ev / 100) * 0.25  # quarter-kelly growth estimate
                        demo_rows.append({"Ставка #": i+1, "EV Edge %": f"+{ev:.2f}%", "Банкролл $": round(br_now,2)})
                    demo_df = pd.DataFrame(demo_rows)
                    fig_demo = px.line(
                        demo_df, x="Ставка #", y="Банкролл $",
                        title=f"Ожидаемый рост банкролла от {len(demo_evs)} value bets (Quarter Kelly)",
                        markers=True, template="plotly_dark", height=350
                    )
                    fig_demo.update_traces(line_color="#4ade80", marker_color="#a78bfa")
                    fig_demo.update_layout(**DARK)
                    st.plotly_chart(fig_demo, use_container_width=True)
                except Exception as _e:
                    st.caption(f"Нет данных для демо-графика: {_e}")
        else:
            # ── Подготовка данных ────────────────────────────────────────────
            hdf = hist_br.copy()
            # Нормализуем колонки
            ev_col   = next((c for c in hdf.columns if "EV" in c or "edge" in c.lower()), None)
            bm_col   = next((c for c in hdf.columns if "Букмекер" in c or "book" in c.lower()), None)
            date_col = next((c for c in hdf.columns if "Дата" in c or "date" in c.lower()), None)

            if ev_col:
                hdf["_ev"] = pd.to_numeric(
                    hdf[ev_col].astype(str).str.replace("%","").str.replace("+",""), errors="coerce"
                ).fillna(0)
            else:
                hdf["_ev"] = 0.0

            # ── Метрики верхнего уровня ───────────────────────────────────────
            total_bets   = len(hdf)
            avg_ev       = hdf["_ev"].mean()
            max_ev       = hdf["_ev"].max()
            pos_bets     = (hdf["_ev"] > 0).sum()

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("📊 Всего ставок",     total_bets)
            m2.metric("📈 Средний EV Edge",  f"{avg_ev:.1f}%")
            m3.metric("🏆 Макс EV Edge",     f"{max_ev:.1f}%")
            m4.metric("✅ Позитивных EV",    f"{pos_bets}/{total_bets}")
            st.divider()

            # ── P&L по дням ──────────────────────────────────────────────────
            if date_col:
                try:
                    hdf["_date"] = pd.to_datetime(hdf[date_col], dayfirst=True, errors="coerce")
                    daily = hdf.groupby("_date")["_ev"].agg(["sum","count"]).reset_index()
                    daily.columns = ["Дата","P&L EV%","Ставок"]
                    daily["Банкролл"] = bankroll * (1 + daily["P&L EV%"].cumsum() / 100 * 0.25)

                    col_pnl, col_br = st.columns(2)
                    with col_pnl:
                        fig_pnl = px.bar(
                            daily, x="Дата", y="P&L EV%",
                            title="P&L EV% по дням",
                            color="P&L EV%",
                            color_continuous_scale=["#ef4444","#94a3b8","#4ade80"],
                            template="plotly_dark", height=300
                        )
                        fig_pnl.update_layout(**DARK)
                        st.plotly_chart(fig_pnl, use_container_width=True)

                    with col_br:
                        fig_br = px.area(
                            daily, x="Дата", y="Банкролл",
                            title=f"Рост банкролла (Kelly ¼, старт ${bankroll:.0f})",
                            template="plotly_dark", height=300
                        )
                        fig_br.update_traces(line_color="#a78bfa", fillcolor="rgba(167,139,250,0.15)")
                        fig_br.update_layout(**DARK)
                        st.plotly_chart(fig_br, use_container_width=True)
                except Exception as _e:
                    st.warning(f"Не удалось построить P&L по дням: {_e}")

            # ── ROI по букмекеру ─────────────────────────────────────────────
            if bm_col:
                bm_stats = hdf.groupby(bm_col)["_ev"].agg(
                    Ставок="count", Ср_EV="mean", Сумм_EV="sum"
                ).reset_index().sort_values("Ср_EV", ascending=False)
                bm_stats.columns = ["Букмекер","Ставок","Ср. EV %","Суммарный EV %"]

                st.markdown("##### 🏦 ROI по букмекерам")
                fig_bm = px.bar(
                    bm_stats, x="Букмекер", y="Ср. EV %",
                    color="Ср. EV %",
                    color_continuous_scale=["#ef4444","#94a3b8","#4ade80"],
                    text="Ср. EV %",
                    title="Средний EV Edge по букмекерам",
                    template="plotly_dark", height=350
                )
                fig_bm.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
                fig_bm.update_layout(**DARK)
                st.plotly_chart(fig_bm, use_container_width=True)
                st.dataframe(bm_stats, use_container_width=True, hide_index=True)

            # ── Ожидаемый Kelly-рост ─────────────────────────────────────────
            st.markdown("##### 📈 Ожидаемый Kelly-рост (симуляция)")
            try:
                pos_ev_bets = hdf[hdf["_ev"] > 0]["_ev"].values
                if len(pos_ev_bets) > 0:
                    sim_bankroll = bankroll
                    sim_rows = [{"N": 0, "Банкролл $": sim_bankroll}]
                    for i, ev in enumerate(sorted(pos_ev_bets, reverse=True), 1):
                        sim_bankroll *= (1 + ev / 100 * 0.25)
                        sim_rows.append({"N": i, "Банкролл $": round(sim_bankroll, 2)})
                    sim_df = pd.DataFrame(sim_rows)
                    expected_roi = (sim_bankroll - bankroll) / bankroll * 100
                    st.success(f"📈 Ожидаемый ROI при всех {len(pos_ev_bets)} value bets: **+{expected_roi:.1f}%** → ${sim_bankroll:.2f}")
                    fig_sim = px.line(
                        sim_df, x="N", y="Банкролл $",
                        title="Симуляция роста банкролла (Quarter Kelly, лучшие EV)",
                        markers=False, template="plotly_dark", height=300
                    )
                    fig_sim.update_traces(line_color="#4ade80", line_width=2)
                    fig_sim.add_hline(y=bankroll, line_dash="dash", line_color="#ef4444",
                                      annotation_text="Стартовый банкролл")
                    fig_sim.update_layout(**DARK)
                    st.plotly_chart(fig_sim, use_container_width=True)
                else:
                    st.info("Нет позитивных EV ставок для симуляции.")
            except Exception as _e:
                st.warning(f"Ошибка симуляции: {_e}")

            st.download_button(
                "⬇️ Скачать историю CSV",
                hdf.drop(columns=[c for c in hdf.columns if c.startswith("_")], errors="ignore")
                   .to_csv(index=False).encode(),
                "bankroll_history.csv", mime="text/csv"
            )

# ── TAB 8: AI АНАЛИЗ (CrewAI-style multi-agent) ──────────────────────────────
with tab_ai:
    st.markdown("#### 🤖 AI Анализ — мульти-агент разбор value bets")
    st.caption("Три роли: OddsAnalyst · BettingStrategist · RiskManager — анализируют текущие сигналы")

    # ── Проверяем наличие crewai / openai ─────────────────────────────────────
    _crewai_ok = False
    _openai_ok = False
    try:
        import crewai  # noqa
        _crewai_ok = True
    except ImportError:
        pass
    try:
        import openai  # noqa
        _openai_ok = True
    except ImportError:
        pass

    # ── OpenAI API Key ─────────────────────────────────────────────────────────
    _oai_key = ""
    try:
        _oai_key = st.secrets.get("OPENAI_API_KEY", "")
    except Exception:
        pass
    if not _oai_key:
        import os as _os2
        _oai_key = _os2.environ.get("OPENAI_API_KEY", "")

    ai_col1, ai_col2 = st.columns([3, 1])
    with ai_col1:
        if not _oai_key:
            _oai_key_input = st.text_input(
                "🔑 OpenAI API Key (для AI агентов)",
                type="password",
                placeholder="sk-...",
                help="Нужен для запуска CrewAI агентов. Получи на platform.openai.com"
            )
            if _oai_key_input:
                _oai_key = _oai_key_input
        else:
            st.success("🔑 OpenAI API Key подключён через Secrets")
    with ai_col2:
        ai_model = st.selectbox(
            "Модель",
            ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
            index=0,
            help="gpt-4o-mini — самая дешёвая и быстрая"
        )

    # ── Собираем контекст из текущих данных ───────────────────────────────────
    _signals_ctx = []
    _arb_ctx     = []
    _vb_ctx      = []

    # Value bets контекст
    if not vdf_all.empty and market_key == "h2h":
        for _, _vr in vdf_all.head(10).iterrows():
            _vb_ctx.append(
                f"  • {_vr.get('Матч','?')} | {_vr.get('Исход','?')} @ {_vr.get('Букмекер','?')} "
                f"| Odds {_vr.get('Odds (Am)','?')} | EV {_vr.get('EV Edge %','?')}"
            )

    # H2H сигналы контекст
    if market_key == "h2h":
        try:
            _sdf_ctx = _build_betting_signals_v2(df, has_draw, sport_cfg["key"])
            for _, _sr in _sdf_ctx.head(5).iterrows():
                _signals_ctx.append(
                    f"  • {_sr.get('Матч','?')} → СТАВИТЬ: {_sr.get('На кого ставить','?')} "
                    f"| EV {_sr.get('EV Edge %','?')} | Уверенность {_sr.get('_conf',0)}/100"
                )
        except Exception:
            pass

    # Арбитраж контекст
    _arb_found = []
    for _mn, _mg in df.groupby("Матч"):
        _ar = find_arb_in_group(_mg, has_draw)
        if _ar:
            _arb_found.append(f"  • {_mn} | Arb% +{_ar['arb_pct']:.3f}%")
    _arb_ctx = _arb_found[:5]

    context_text = f"""Спорт: {sport_label} | Рынок: {market_label} | Регион: {region_label}
Банкролл: ${bankroll:.0f} | Матчей: {df['Матч'].nunique()} | Букмекеров: {df['Букмекер'].nunique()}

VALUE BETS (EV ≥ {min_edge}%):
{'\n'.join(_vb_ctx) if _vb_ctx else '  Не найдено'}

ШАРП СИГНАЛЫ (H2H):
{'\n'.join(_signals_ctx) if _signals_ctx else '  Нет данных (выбери рынок H2H)'}

АРБИТРАЖ:
{'\n'.join(_arb_ctx) if _arb_ctx else '  Суребеты не найдены'}"""

    with st.expander("📋 Контекст для AI агентов", expanded=False):
        st.code(context_text, language="")

    # ── Кнопка запуска ────────────────────────────────────────────────────────
    st.divider()
    run_ai = st.button(
        "🚀 Запустить AI анализ",
        type="primary",
        use_container_width=True,
        disabled=(not _oai_key),
        help="Требует OpenAI API Key" if not _oai_key else "Запустить мульти-агент анализ"
    )
    if not _oai_key:
        st.warning("⚠️ Введи OpenAI API Key выше для запуска AI агентов")

    if run_ai and _oai_key:
        # ── Если crewai установлен — используем настоящих агентов ─────────────
        if _crewai_ok:
            import os as _os3
            _os3.environ["OPENAI_API_KEY"] = _oai_key
            try:
                from crewai import Agent, Task, Crew, LLM

                _llm = LLM(model=f"openai/{ai_model}", api_key=_oai_key)

                _analyst = Agent(
                    role="Odds Analyst",
                    goal="Analyse EV Edge, Kelly signals and value bets from betting data. Identify the highest-confidence opportunities.",
                    backstory="You are an expert in sports betting mathematics. You specialise in Expected Value, no-vig probabilities and cross-book sharp signals.",
                    llm=_llm, verbose=False, allow_delegation=False
                )
                _strategist = Agent(
                    role="Betting Strategist",
                    goal="Recommend optimal stake sizing using Quarter Kelly criterion and rank bets by risk-adjusted return.",
                    backstory="You specialise in bankroll management, Kelly criterion, and constructing diversified betting portfolios.",
                    llm=_llm, verbose=False, allow_delegation=False
                )
                _risk_mgr = Agent(
                    role="Risk Manager",
                    goal="Assess exposure, flag correlated bets, warn about book limits and provide a final go/no-go recommendation.",
                    backstory="You monitor portfolio risk, book limits, and correlation between bets to prevent overexposure.",
                    llm=_llm, verbose=False, allow_delegation=False
                )

                _task1 = Task(
                    description=f"Analyse this betting data and rank top 3 value bets by EV Edge. Explain WHY each is a value bet.\n\nDATA:\n{context_text}",
                    expected_output="Ranked list of top 3 value bets with EV Edge explanation and confidence level in Russian.",
                    agent=_analyst
                )
                _task2 = Task(
                    description=f"Based on the analyst's findings and bankroll of ${bankroll:.0f}, calculate optimal Quarter Kelly stake for each top bet. Consider correlation between bets.",
                    expected_output="Stake recommendation in $ for each bet with Kelly calculation shown, in Russian.",
                    agent=_strategist
                )
                _task3 = Task(
                    description="Review the analyst and strategist recommendations. Flag any risks: correlated bets, book limits, market timing. Give final GO/NO-GO for each bet.",
                    expected_output="Risk assessment with final GO/NO-GO verdict for each bet and overall portfolio risk score 1-10, in Russian.",
                    agent=_risk_mgr
                )

                _crew = Crew(
                    agents=[_analyst, _strategist, _risk_mgr],
                    tasks=[_task1, _task2, _task3],
                    verbose=False
                )

                with st.spinner("🤖 AI агенты анализируют данные… (~15–30 сек)"):
                    _result = _crew.kickoff()

                st.markdown("### 🤖 Результат мульти-агент анализа")
                result_text = str(_result)
                # Разбиваем по агентам если возможно
                for _agent_name, _icon in [("Odds Analyst","🔍"), ("Betting Strategist","📊"), ("Risk Manager","🛡️")]:
                    if _agent_name.lower() in result_text.lower():
                        st.markdown(f"**{_icon} {_agent_name}**")
                st.markdown(result_text)

            except Exception as _crew_err:
                st.error(f"CrewAI ошибка: {_crew_err}")
                st.info("Переключаемся на прямой OpenAI анализ…")
                _crewai_ok = False  # fallback

        # ── Fallback: прямой OpenAI без crewai ───────────────────────────────
        if not _crewai_ok:
            try:
                import openai as _openai_mod
                _client = _openai_mod.OpenAI(api_key=_oai_key)

                _system_prompt = """Ты — мульти-агент система анализа спортивных ставок. 
Ты одновременно играешь три роли:
1. 🔍 OddsAnalyst — анализирует EV Edge и value bets
2. 📊 BettingStrategist — рекомендует размер ставки (Quarter Kelly)
3. 🛡️ RiskManager — оценивает риски и даёт финальный вердикт

Отвечай чётко по трём секциям. Используй конкретные цифры из данных."""

                _user_prompt = f"""Проанализируй следующие данные о ставках и дай рекомендации:

{context_text}

Структура ответа:
## 🔍 OddsAnalyst — Топ-3 value bets
(ранжируй по EV Edge, объясни почему это value)

## 📊 BettingStrategist — Размеры ставок  
(Quarter Kelly расчёт для каждой ставки при банкролле ${bankroll:.0f})

## 🛡️ RiskManager — Риски и вердикт
(GO/NO-GO для каждой ставки, общий риск 1-10)"""

                with st.spinner("🤖 AI анализирует данные… (~10–20 сек)"):
                    _resp = _client.chat.completions.create(
                        model=ai_model,
                        messages=[
                            {"role": "system", "content": _system_prompt},
                            {"role": "user",   "content": _user_prompt}
                        ],
                        temperature=0.3,
                        max_tokens=1500,
                    )
                _ai_text = _resp.choices[0].message.content

                # Рендерим красиво
                _sections = _ai_text.split("##")
                st.markdown("### 🤖 AI Анализ")
                for _sec in _sections:
                    _sec = _sec.strip()
                    if not _sec:
                        continue
                    _lines = _sec.split("\n", 1)
                    _title = _lines[0].strip()
                    _body  = _lines[1].strip() if len(_lines) > 1 else ""
                    # Цвет карточки по агенту
                    if "OddsAnalyst" in _title or "Analyst" in _title:
                        _brd = "#38bdf8"; _bg = "rgba(56,189,248,0.08)"
                    elif "Strategist" in _title:
                        _brd = "#a78bfa"; _bg = "rgba(167,139,250,0.08)"
                    elif "RiskManager" in _title or "Risk" in _title:
                        _brd = "#f97316"; _bg = "rgba(249,115,22,0.08)"
                    else:
                        _brd = T['border']; _bg = T['bg2']

                    st.markdown(f"""
<div style="background:{_bg};border-left:4px solid {_brd};border-radius:0 12px 12px 0;
padding:14px 18px;margin-bottom:12px">
  <div style="font-size:16px;font-weight:800;color:{_brd};margin-bottom:8px">{_title}</div>
  <div style="font-size:14px;color:{T['text']};white-space:pre-wrap">{_body}</div>
</div>""", unsafe_allow_html=True)

                # Сохраняем результат
                st.session_state["last_ai_analysis"] = _ai_text
                st.session_state["last_ai_context"]  = context_text

            except Exception as _oai_err:
                st.error(f"❌ Ошибка OpenAI: {_oai_err}")
                st.info("Проверь API ключ и доступность сети")

    # ── Показываем последний анализ если есть ────────────────────────────────
    elif not run_ai and st.session_state.get("last_ai_analysis"):
        st.markdown("##### 💾 Последний AI анализ (из кеша)")
        st.caption(f"Контекст: {st.session_state.get('last_ai_context','')[:100]}…")
        st.markdown(st.session_state["last_ai_analysis"])

    # ── Инструкция если нет ключа ─────────────────────────────────────────────
    if not run_ai and not st.session_state.get("last_ai_analysis"):
        st.markdown("""
**Как подключить AI агентов:**

1. Получи OpenAI API Key на [platform.openai.com](https://platform.openai.com/api-keys)
2. Введи ключ в поле выше **или** добавь в Streamlit Secrets:
```toml
OPENAI_API_KEY = "sk-..."
```
3. Для полноценных CrewAI агентов добавь в `requirements.txt`:
```
crewai>=0.28.0
openai>=1.0.0
```
4. Нажми **🚀 Запустить AI анализ** — три агента (Analyst, Strategist, RiskManager) 
   проанализируют текущие value bets и дадут рекомендации

> **Без crewai** работает прямой OpenAI режим — тот же анализ через gpt-4o-mini
""")

    st.markdown("""
<div style="background:#1e293b;border:1px solid #334155;border-radius:12px;padding:12px 16px;margin-top:16px">
  <div style="font-size:12px;color:#64748b">
    ⚠️ AI анализ носит <b>образовательный характер</b>. Это не финансовый совет.
    Ставки сопряжены с риском потери средств.
  </div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────
st.divider()
st.caption("Данные: [The Odds API](https://the-odds-api.com) · [ESPN](https://site.api.espn.com) · "
           "Только в образовательных целях. Ставки сопряжены с риском.")
