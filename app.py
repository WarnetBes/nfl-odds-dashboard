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
)

# ─────────────────────────────────────────────
#  PAGE CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Sports Odds Dashboard",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
#  CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
.main-title {
    font-size:2.1rem; font-weight:800;
    background:linear-gradient(135deg,#a78bfa,#38bdf8);
    -webkit-background-clip:text; -webkit-text-fill-color:transparent;
}
.live-dot {
    display:inline-block; width:10px; height:10px;
    border-radius:50%; background:#22c55e;
    box-shadow:0 0 6px #22c55e;
    animation: pulse 1.2s infinite;
    margin-right:6px; vertical-align:middle;
}
@keyframes pulse {
    0%,100%{opacity:1;transform:scale(1)}
    50%{opacity:.5;transform:scale(1.3)}
}
.score-card {
    background:linear-gradient(135deg,#1e3a5f,#0d1b2a);
    border:1px solid #334155; border-radius:12px;
    padding:14px 18px; margin-bottom:10px;
}
.score-live  { border-color:#22c55e !important; }
.score-final { border-color:#64748b !important; opacity:.85; }
.score-pre   { border-color:#3b82f6 !important; }
.team-name   { font-size:1rem; font-weight:600; color:#e2e8f0; }
.team-score  { font-size:1.6rem; font-weight:800; color:#00b4d8; }
.status-live { color:#22c55e; font-size:.82rem; font-weight:700; }
.status-fin  { color:#94a3b8; font-size:.82rem; }
.status-pre  { color:#60a5fa; font-size:.82rem; }
.timer-bar   { background:#1e293b; border-radius:8px; padding:8px 14px; font-size:.85rem; color:#94a3b8; }
.value-high  { color:#4ade80; font-weight:800; }
div[data-testid="stDataFrame"] { border-radius:10px; overflow:hidden; }
</style>
""", unsafe_allow_html=True)

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
defaults = {
    "events": None, "remaining": None, "used": None,
    "demo_mode": False, "last_sport": None, "last_market": None,
    "last_fetch_ts": 0, "auto_refresh": True,
    "gmail_sent_ids": set(),   # track already-alerted value bets
    "saved_api_key": "",       # persisted API key
    "selected_bm_state": [],   # persisted bookmaker selection
    "sport_filter": "Все",    # sport category filter
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─────────────────────────────────────────────
#  SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Настройки")
    st.divider()

    # ── Odds API ──────────────────────────────
    _typed_key = st.text_input("🔑 The Odds API Key", type="password",
        value=st.session_state.saved_api_key,
        placeholder="Пусто = демо-режим",
        help="https://the-odds-api.com — 500 запросов/мес бесплатно")
    # Persist key across reruns
    if _typed_key:
        st.session_state.saved_api_key = _typed_key
    api_key = st.session_state.saved_api_key
    if api_key:
        st.caption("✅ API ключ сохранён")

    # ── Sport / League filter ─────────────────
    SPORT_FILTER_OPTIONS = ["Все", "⚽ Только Football", "🏈 Только NFL", "🏀 Только NBA"]
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

    sport_label  = st.selectbox("🏆 Вид спорта / Лига", _visible_sports)
    sport_cfg    = SPORTS_CATALOGUE[sport_label]
    has_draw     = sport_cfg["has_draw"]
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
            st.success(msg) if ok else st.error(msg)
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
    st.divider()
    st.caption("📡 [The Odds API](https://the-odds-api.com) · [ESPN API](https://site.api.espn.com)")

# ─────────────────────────────────────────────
#  HEADER
# ─────────────────────────────────────────────
st.markdown('<div class="main-title">🏆 Sports Odds Dashboard</div>', unsafe_allow_html=True)
st.caption("NFL · Football · NBA — Коэффициенты · Live Scores · Value Bets · Gmail Alerts")

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

st.divider()

# ─────────────────────────────────────────────
#  AUTO-REFRESH TRIGGER
# ─────────────────────────────────────────────
should_fetch = fetch_btn
if (st.session_state.auto_refresh
        and st.session_state.events is not None
        and elapsed >= AUTO_REFRESH):
    should_fetch = True

# ─────────────────────────────────────────────
#  FETCH ODDS
# ─────────────────────────────────────────────
if should_fetch:
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
tab_signals, tab_arb, tab_table, tab_chart, tab_value, tab_live, tab_history, tab_bankroll = st.tabs([
    "🎯 Сигналы",
    "⚡ Арбитраж",
    "📋 Коэффициенты",
    "📊 Сравнение букмекеров",
    "💎 Value Bets",
    "📺 Live Scores",
    "📊 История ставок",
    "💰 Статистика банкролла",
])

DARK = dict(plot_bgcolor="#0d1b2a", paper_bgcolor="#0d1b2a", font_color="#e2e8f0")

# ── TAB 0: BETTING SIGNALS v2 (Sharp EV + Kelly ¼ Stake) ─────────────────
with tab_signals:
    st.markdown("#### 🎯 На кого ставить — Sharp EV сигналы (Pinnacle reference + Kelly ¼)")
    if market_key != "h2h":
        st.info("ℹ️ Сигналы работают только для рынка **H2H / 1X2**.")
    else:
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
  <span style="background:#1e293b;color:#94a3b8;padding:4px 12px;border-radius:20px">⚪ НЕТ</span>
</div>""",
                unsafe_allow_html=True,
            )

            for _, sig in sdf.iterrows():
                conf       = int(sig["_conf"]) if "_conf" in sig.index else 0
                edge_val   = float(sig["_edge"]) if "_edge" in sig.index else 0.0
                signal_str = str(sig["Сигнал"])
                is_sharp   = str(sig.get("Sharp Reference", "")).startswith("⚡")

                if is_sharp:
                    card_bg, border, text_clr = "#1a1a2e", "#a78bfa", "#a78bfa"
                elif conf >= 70:
                    card_bg, border, text_clr = "#0d2a1a", "#4ade80", "#4ade80"
                elif conf >= 40:
                    card_bg, border, text_clr = "#2a1a00", "#fde68a", "#fde68a"
                elif edge_val > 0:
                    card_bg, border, text_clr = "#0d1b2a", "#93c5fd", "#93c5fd"
                else:
                    card_bg, border, text_clr = "#111827", "#475569", "#94a3b8"

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

                kelly_cell_bg  = "#2d1f5e" if kelly_dollar > 0 else "#1e293b"
                kelly_cell_brd = "border:1px solid #7c3aed;" if kelly_dollar > 0 else ""
                kelly_color    = "#c4b5fd" if kelly_dollar > 0 else "#475569"
                ev_color       = "#4ade80" if edge_val > 0 else "#f87171"
                ref_color      = "#a78bfa" if is_sharp else "#94a3b8"

                st.markdown(f"""
<div style="background:{card_bg};border:2px solid {border};border-radius:12px;padding:16px 20px;margin-bottom:14px">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div>
      <div style="font-size:11px;color:#94a3b8;margin-bottom:2px">{sig["Матч"]} &middot; {sig["Время"]}{sharp_badge}</div>
      <div style="font-size:20px;font-weight:800;color:{text_clr}">{signal_str} — СТАВИТЬ: {sig["На кого ставить"]}</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:22px;font-weight:900;color:{text_clr}">{sig["Odds (Am)"]}</div>
      <div style="font-size:12px;color:#94a3b8">{sig["Odds (Dec)"]:.2f} децимал</div>
    </div>
  </div>
  <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;margin-top:12px">
    <div style="background:#1e293b;border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:#64748b">🏦 Лучший букмекер</div>
      <div style="font-size:14px;font-weight:700;color:#e2e8f0">{sig["Лучший букмекер"]}</div>
    </div>
    <div style="background:#1e293b;border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:#64748b">💰 EV Edge</div>
      <div style="font-size:14px;font-weight:700;color:{ev_color}">{sig["EV Edge %"]}</div>
    </div>
    <div style="background:#1e293b;border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:#64748b">📉 No-Vig Fair</div>
      <div style="font-size:14px;font-weight:700;color:#e2e8f0">{sig["No-Vig Fair %"]}</div>
    </div>
    <div style="background:#1e293b;border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:#64748b">🤝 Консенсус</div>
      <div style="font-size:14px;font-weight:700;color:#e2e8f0">{sig["Консенсус книг"]}</div>
    </div>
    <div style="background:{kelly_cell_bg};{kelly_cell_brd}border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:#64748b">📈 Kelly ¼ Ставка</div>
      <div style="font-size:14px;font-weight:700;color:{kelly_color}">${kelly_dollar:.2f} <span style="font-size:11px;color:#64748b">({kelly_pct_str})</span></div>
    </div>
    <div style="background:#1e293b;border-radius:8px;padding:8px 12px">
      <div style="font-size:10px;color:#64748b">📊 Референс</div>
      <div style="font-size:14px;font-weight:700;color:{ref_color}">{sig.get("Sharp Reference", "Консенсус")}</div>
    </div>
  </div>
  <div style="margin-top:10px">
    <div style="font-size:10px;color:#64748b;margin-bottom:4px">Уверенность сигнала: {conf}/100</div>
    <div style="background:#0f172a;border-radius:4px;height:8px;overflow:hidden">
      <div style="background:{border};height:8px;width:{conf}%;border-radius:4px;transition:width .4s"></div>
    </div>
  </div>
  {'<div style="font-size:11px;color:#64748b;margin-top:8px">🔄 ' + str(sig["Другие исходы"]) + '</div>' if sig["Другие исходы"] else ''}
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

# ── TAB 6: HISTORY (Google Sheets) ────────────────────
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

# ─────────────────────────────────────────────
#  FOOTER
# ─────────────────────────────────────────────
st.divider()
st.caption("Данные: [The Odds API](https://the-odds-api.com) · [ESPN](https://site.api.espn.com) · "
           "Только в образовательных целях. Ставки сопряжены с риском.")
