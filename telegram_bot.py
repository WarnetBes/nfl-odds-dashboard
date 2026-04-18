"""
telegram_bot.py — Sports Odds Dashboard Bot v2.0
Удобное управление через inline-кнопки, persistent reply-keyboard,
быстрый статус в главном меню, все меню с кнопкой «Назад».
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import pytz
import requests
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest as TgBadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from utils import (
    american_to_decimal,
    decimal_to_implied,
    no_vig_prob,
    ev_edge,
    kelly_fraction,
    kelly_stake,
    arb_percentage,
    arb_stakes,
    find_arb_in_group,
    build_betting_signals,
    compute_value_bets,
    SHARP_BOOKS,
    SPORT_EV_THRESHOLDS,
)

# ─────────────────────────────────────────────────────────────────────────────
#  КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────────────────────────────────────

BOT_TOKEN           = os.environ.get("TELEGRAM_BOT_TOKEN", "7145666214:AAHivgv39C5OpwDCrxbKgpkxergKQdpapVw")
ODDS_BASE           = "https://api.the-odds-api.com/v4"
MSK                 = pytz.timezone("Europe/Moscow")
DEFAULT_EV_THRESHOLD = 5.0
KELLY_MIN_PCT       = 0.5
DEFAULT_BANKROLL    = 1000.0

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("sports_bot")

# ─────────────────────────────────────────────────────────────────────────────
#  КАТАЛОГИ
# ─────────────────────────────────────────────────────────────────────────────

SPORTS_CATALOGUE: dict[str, dict] = {
    "⚽ EPL":           {"key": "soccer_epl",                    "has_draw": True,  "flag": "🏴󠁧󠁢󠁥󠁮󠁧󠁿"},
    "⚽ La Liga":        {"key": "soccer_spain_la_liga",          "has_draw": True,  "flag": "🇪🇸"},
    "⚽ Bundesliga":     {"key": "soccer_germany_bundesliga",     "has_draw": True,  "flag": "🇩🇪"},
    "⚽ Serie A":        {"key": "soccer_italy_serie_a",          "has_draw": True,  "flag": "🇮🇹"},
    "⚽ Ligue 1":        {"key": "soccer_france_ligue_one",       "has_draw": True,  "flag": "🇫🇷"},
    "⚽ UCL":            {"key": "soccer_uefa_champs_league",     "has_draw": True,  "flag": "🏆"},
    "⚽ UEL":            {"key": "soccer_uefa_europa_league",     "has_draw": True,  "flag": "🟠"},
    "⚽ MLS":            {"key": "soccer_usa_mls",                "has_draw": True,  "flag": "🇺🇸"},
    "🏈 NFL":            {"key": "americanfootball_nfl",          "has_draw": False, "flag": "🏈"},
    "🏀 NBA":            {"key": "basketball_nba",                "has_draw": False, "flag": "🏀"},
}

US_BM_LIST = [
    "DraftKings", "FanDuel", "BetMGM", "Caesars", "BetOnline.ag",
    "William Hill US", "BetRivers", "Bovada", "PointsBet US", "Barstool",
]
EU_BM_LIST = [
    "Betfair", "Unibet", "Paddy Power", "Bet365", "Sky Bet",
    "Ladbrokes", "Coral", "Betway", "888sport", "Pinnacle", "1xBet",
]
ALL_BOOKMAKERS = US_BM_LIST + EU_BM_LIST

REGION_MAP: dict[str, str] = {
    "🇺🇸 US":   "us",
    "🇺🇸 US+":  "us2",
    "🇬🇧 UK":   "uk",
    "🇪🇺 EU":   "eu",
    "🌍 Все":   "us,us2,uk,eu",
}

REFRESH_OPTIONS: dict[str, int] = {
    "⏱ 3 мин":   3  * 60,
    "⏱ 5 мин":   5  * 60,
    "⏱ 15 мин":  15 * 60,
    "⏱ 30 мин":  30 * 60,
    "🚫 Вручную": 0,
}

# ─────────────────────────────────────────────────────────────────────────────
#  СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЕЙ
# ─────────────────────────────────────────────────────────────────────────────

class UserState:
    def __init__(self) -> None:
        self.api_key: str           = ""
        self.sport_label: str       = "🏈 NFL"
        self.all_sports: bool       = False
        self.bookmakers: list[str]  = []      # [] = все
        self.region: str            = "🌍 Все"
        self.refresh_interval: int  = 0       # 0 = вручную
        self.ev_threshold: float    = DEFAULT_EV_THRESHOLD
        self.bankroll: float        = DEFAULT_BANKROLL
        self.last_fetch: float      = 0.0
        self.last_events: list      = []
        self.last_remaining: str    = "?"
        self.last_vbets_count: int  = 0
        self.last_arb_count: int    = 0
        self.job_running: bool      = False
        # Пагинация value bets
        self.vbets_page: int        = 0
        self.last_vbets: list       = []      # кэш для пагинации

    @property
    def region_key(self) -> str:
        return REGION_MAP.get(self.region, "us,us2,uk,eu")

    @property
    def sport_cfg(self) -> dict:
        return SPORTS_CATALOGUE.get(self.sport_label, {"key": "americanfootball_nfl", "has_draw": False})

    @property
    def refresh_label(self) -> str:
        return next((k for k, v in REFRESH_OPTIONS.items() if v == self.refresh_interval), "вручную")

    @property
    def sport_display(self) -> str:
        return "🌐 Все лиги" if self.all_sports else self.sport_label

    @property
    def bm_display(self) -> str:
        if not self.bookmakers:
            return "все"
        if len(self.bookmakers) <= 3:
            return ", ".join(self.bookmakers)
        return f"{self.bookmakers[0]}, {self.bookmakers[1]} +{len(self.bookmakers)-2}"

    @property
    def key_ok(self) -> bool:
        return bool(self.api_key)

    @property
    def key_masked(self) -> str:
        if not self.api_key:
            return "❌ не задан"
        if len(self.api_key) > 8:
            return self.api_key[:4] + "****" + self.api_key[-4:]
        return "****"


_user_states: dict[int, UserState] = {}

def get_state(chat_id: int) -> UserState:
    if chat_id not in _user_states:
        _user_states[chat_id] = UserState()
    return _user_states[chat_id]


# ConversationHandler states
WAIT_API_KEY  = "WAIT_API_KEY"
WAIT_EV       = "WAIT_EV"
WAIT_BANKROLL = "WAIT_BANKROLL"

# ─────────────────────────────────────────────────────────────────────────────
#  FETCH
# ─────────────────────────────────────────────────────────────────────────────

def fetch_odds_raw(api_key: str, sport_key: str, regions: str) -> tuple[list | None, str, str]:
    try:
        r = requests.get(
            f"{ODDS_BASE}/sports/{sport_key}/odds",
            params=dict(
                apiKey=api_key, regions=regions,
                markets="h2h", oddsFormat="american", dateFormat="iso",
            ),
            timeout=15,
        )
        remaining = r.headers.get("x-requests-remaining", "?")
        used      = r.headers.get("x-requests-used", "?")
        if r.status_code == 200:
            return r.json(), remaining, used
        return None, remaining, used
    except Exception as exc:
        logger.exception("fetch_odds_raw: %s", exc)
        return None, "?", "?"


def build_df_from_events(events: list, has_draw: bool, bookmakers_filter: list[str]) -> pd.DataFrame:
    rows = []
    for ev in events:
        home = ev.get("home_team", "?")
        away = ev.get("away_team", "?")
        t    = ev.get("commence_time", "")[:16].replace("T", " ") + " UTC"
        for bm in ev.get("bookmakers", []):
            bm_title = bm.get("title", bm.get("key", "?"))
            if bookmakers_filter and bm_title not in bookmakers_filter:
                continue
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "h2h":
                    continue
                oc = {o["name"]: o.get("price") for o in mkt.get("outcomes", [])}
                rows.append({
                    "Матч":             f"{away} @ {home}",
                    "Время":            t,
                    "Букмекер":         bm_title,
                    "Хозяева":          home,
                    "Гости":            away,
                    "Odds Хозяева (Am)": oc.get(home),
                    "Odds Гости (Am)":   oc.get(away),
                    "Odds Ничья (Am)":   oc.get("Draw") if has_draw else None,
                    "_event_id":        ev.get("id", ""),
                })
    return pd.DataFrame(rows)

# ─────────────────────────────────────────────────────────────────────────────
#  УТИЛИТЫ
# ─────────────────────────────────────────────────────────────────────────────

def _now_msk() -> str:
    return datetime.now(MSK).strftime("%d.%m %H:%M МСК")

def _parse_ev(s) -> float:
    try:
        return float(str(s).replace("+", "").replace("%", ""))
    except Exception:
        return 0.0

def fmt_am(v) -> str:
    """Форматирует american odds."""
    try:
        n = float(v)
        return f"+{int(n)}" if n > 0 else str(int(n))
    except Exception:
        return str(v)

# ─────────────────────────────────────────────────────────────────────────────
#  ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
# ─────────────────────────────────────────────────────────────────────────────

PAGE_SIZE = 5  # value bets на страницу

def format_main_status(state: UserState) -> str:
    """Текст главного меню с текущим статусом."""
    key_icon = "✅" if state.key_ok else "❌"
    auto_icon = "🔄" if state.refresh_interval > 0 else "⏸"
    last = f"обновлено {_now_msk()}" if state.last_fetch > 0 else "ещё не загружено"
    vb = f"💎 {state.last_vbets_count} value bets" if state.last_vbets_count else ""
    arb = f"  |  ⚡ {state.last_arb_count} arb" if state.last_arb_count else ""

    lines = [
        "🏆 *Sports Odds Dashboard*",
        "",
        f"{key_icon} API ключ: `{state.key_masked}`",
        f"⚽ Спорт: {state.sport_display}",
        f"🏦 Букмекеры: {state.bm_display}",
        f"🌍 Регион: {state.region}",
        f"{auto_icon} Обновление: {state.refresh_label}",
        f"📈 EV порог: {state.ev_threshold}%  |  💰 ${state.bankroll:,.0f}",
        "",
        f"📡 API осталось: `{state.last_remaining}`",
    ]
    if vb or arb:
        lines.append(f"📊 Последний фетч: {vb}{arb}")
    lines.append(f"🕐 {last}")
    return "\n".join(lines)


def format_vbets_page(vbets: list[dict], page: int, sport_label: str, ev_threshold: float) -> tuple[str, int]:
    """Возвращает (text, total_pages)."""
    total = len(vbets)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = vbets[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]

    lines = [
        f"💎 *Value Bets — {sport_label}*",
        f"EV ≥ {ev_threshold}%  |  Стр. {page+1}/{total_pages}  ({total} всего)",
        "",
    ]
    for i, vb in enumerate(chunk, page * PAGE_SIZE + 1):
        match   = vb.get("Матч", "")
        bm      = vb.get("Букмекер", "")
        outcome = str(vb.get("Исход", "")).replace("✅ ", "")
        odds_am = vb.get("Odds (Am)", "?")
        odds_dec = vb.get("Odds (Dec)", "")
        ev_val  = vb.get("EV Edge %", "")
        kelly   = vb.get("Kelly ¼ %", "")
        stake   = vb.get("Kelly Stake ($)", "")

        lines.append(f"*{i}.* `{match}`")
        lines.append(f"   🏦 {bm} · ✅ *{outcome}*")
        lines.append(f"   📊 {odds_am}" + (f" ({odds_dec})" if odds_dec else ""))
        lines.append(f"   📈 EV: *{ev_val}*" + (f"  💰 {kelly}" if kelly else "") + (f" → {stake}" if stake else ""))
        lines.append("")

    lines.append(f"🕐 {_now_msk()}")
    return "\n".join(lines), total_pages


def format_arb_message(arb_list: list, sport_label: str) -> str:
    if not arb_list:
        return f"⚡ *Арбитраж — {sport_label}*\n\nАрбитражных возможностей не найдено"
    lines = [f"⚡ *Арбитраж — {sport_label}*", f"Найдено: {len(arb_list)}", ""]
    for arb in arb_list[:8]:
        match   = arb.get("match", "?")
        profit  = arb.get("profit_pct", 0)
        arb_pct = arb.get("arb_pct", 0)
        bms     = arb.get("bookmakers", [])
        outcomes = arb.get("outcomes", [])
        stakes  = arb.get("stakes", [])
        lines.append(f"━━━━━━━━━━━━━━━━━")
        lines.append(f"🏟 `{match}`")
        lines.append(f"💹 Прибыль: *+{profit:.2f}%*  (Margin: {arb_pct:.2f}%)")
        for bm, out, stk in zip(bms, outcomes, stakes):
            lines.append(f"   🏦 {bm}: *{out}* → ${stk:.2f}")
    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append(f"🕐 {_now_msk()}")
    return "\n".join(lines)


def format_signals_message(sig_df: pd.DataFrame, sport_label: str) -> str:
    if sig_df is None or sig_df.empty:
        return f"🎯 *Сигналы — {sport_label}*\n\nСигналов не найдено"
    lines = [f"🎯 *Сигналы — {sport_label}*", f"Найдено: {len(sig_df)}", ""]
    for _, row in sig_df.head(8).iterrows():
        match    = str(row.get("Матч", ""))
        outcome  = str(row.get("Лучший исход", row.get("Best Outcome", "")))
        best_bm  = str(row.get("Лучший букмекер", row.get("Best BM", "")))
        best_odds = str(row.get("Лучшие Odds (Am)", row.get("Best Odds Am", "")))
        ev_val   = str(row.get("Лучший EV", row.get("Best EV %", "")))
        conf     = str(row.get("Уверенность", row.get("Confidence", "")))
        lines.append(f"🏟 `{match}`")
        lines.append(f"   ✅ *{outcome}* @ {best_bm} `{best_odds}`")
        if ev_val:
            lines.append(f"   📈 EV: {ev_val}" + (f"  |  💡 {conf}" if conf else ""))
        lines.append("")
    lines.append(f"🕐 {_now_msk()}")
    return "\n".join(lines)


def format_status_message(state: UserState, context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> str:
    jobs = context.job_queue.get_jobs_by_name(str(chat_id))
    return (
        f"⚙️ *Настройки*\n\n"
        f"🔑 API ключ: `{state.key_masked}`\n"
        f"⚽ Спорт: {state.sport_display}\n"
        f"🏦 Букмекеры: {state.bm_display}\n"
        f"🌍 Регион: {state.region}\n"
        f"⏱ Обновление: {state.refresh_label}\n"
        f"📈 EV порог: {state.ev_threshold}%\n"
        f"💰 Банкролл: ${state.bankroll:,.0f}\n"
        f"📡 API осталось: {state.last_remaining}\n"
        f"🤖 Автообновление: {'✅ активно' if jobs else '❌ остановлено'}\n"
        f"🕐 {_now_msk()}"
    )

# ─────────────────────────────────────────────────────────────────────────────
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────────────────────

def kb_main(state: UserState) -> InlineKeyboardMarkup:
    """Главное меню с индикаторами состояния."""
    auto_lbl = f"🔄 {state.refresh_label}" if state.refresh_interval > 0 else "▶️ Автообновление"
    vb_lbl   = f"💎 VB ({state.last_vbets_count})" if state.last_vbets_count else "💎 Value Bets"
    arb_lbl  = f"⚡ Arb ({state.last_arb_count})" if state.last_arb_count else "⚡ Арбитраж"
    key_lbl  = "🔑 ✅ Ключ" if state.key_ok else "🔑 ❌ Ввести ключ"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Загрузить сейчас",    callback_data="fetch")],
        [InlineKeyboardButton(vb_lbl,                   callback_data="show_vbets"),
         InlineKeyboardButton(arb_lbl,                  callback_data="show_arb")],
        [InlineKeyboardButton("🎯 Сигналы",             callback_data="show_signals")],
        [InlineKeyboardButton("⚽ Спорт",               callback_data="menu_sport"),
         InlineKeyboardButton("🏦 Букмекеры",           callback_data="menu_bm")],
        [InlineKeyboardButton(auto_lbl,                 callback_data="menu_refresh"),
         InlineKeyboardButton("🌍 " + state.region,    callback_data="menu_region")],
        [InlineKeyboardButton(key_lbl,                  callback_data="set_key"),
         InlineKeyboardButton("⚙️ Настройки",           callback_data="settings")],
        [InlineKeyboardButton("🛑 Стоп",                callback_data="stop_refresh"),
         InlineKeyboardButton("📋 Статус",              callback_data="status")],
    ])


def kb_sport(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    all_mark = "✅ " if state.all_sports else "   "
    rows.append([InlineKeyboardButton(f"{all_mark}🌐 Все лиги", callback_data="sport_ALL")])
    keys = list(SPORTS_CATALOGUE.keys())
    for i in range(0, len(keys), 2):
        row = []
        for label in keys[i:i+2]:
            mark = "✅ " if (not state.all_sports and state.sport_label == label) else "   "
            row.append(InlineKeyboardButton(f"{mark}{label}", callback_data=f"sport_{label}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("« Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_bm(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    all_mark = "✅ " if not state.bookmakers else "   "
    rows.append([InlineKeyboardButton(f"{all_mark}🏦 Все букмекеры", callback_data="bm_ALL")])
    rows.append([
        InlineKeyboardButton(
            ("✅ " if state.bookmakers == US_BM_LIST else "   ") + "🇺🇸 US группа",
            callback_data="bm_group_US",
        ),
        InlineKeyboardButton(
            ("✅ " if state.bookmakers == EU_BM_LIST else "   ") + "🇪🇺 EU группа",
            callback_data="bm_group_EU",
        ),
    ])
    top_bms = ["DraftKings", "FanDuel", "BetMGM", "Pinnacle", "Betfair", "Bet365", "Caesars", "888sport"]
    for i in range(0, len(top_bms), 2):
        row = []
        for bm in top_bms[i:i+2]:
            mark = "✅ " if bm in state.bookmakers else "   "
            row.append(InlineKeyboardButton(f"{mark}{bm}", callback_data=f"bm_{bm}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("🗑 Очистить выбор", callback_data="bm_ALL")])
    rows.append([InlineKeyboardButton("« Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_refresh(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    for label, secs in REFRESH_OPTIONS.items():
        mark = "✅ " if state.refresh_interval == secs else "   "
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"refresh_{secs}")])
    rows.append([InlineKeyboardButton("🛑 Остановить сейчас", callback_data="stop_refresh")])
    rows.append([InlineKeyboardButton("« Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_region(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    for label in REGION_MAP:
        mark = "✅ " if state.region == label else "   "
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"region_{label}")])
    rows.append([InlineKeyboardButton("« Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_settings(state: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔑 API ключ: {state.key_masked}",    callback_data="set_key")],
        [InlineKeyboardButton(f"📈 EV порог: {state.ev_threshold}%", callback_data="set_ev")],
        [InlineKeyboardButton(f"💰 Банкролл: ${state.bankroll:,.0f}",callback_data="set_bankroll")],
        [InlineKeyboardButton("📋 Статус",                            callback_data="status")],
        [InlineKeyboardButton("« Главное меню",                       callback_data="back_main")],
    ])


def kb_vbets_pager(page: int, total_pages: int) -> InlineKeyboardMarkup:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Пред.", callback_data=f"vbets_page_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Следующ. ▶️", callback_data=f"vbets_page_{page+1}"))
    rows = [nav] if nav else []
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data="fetch")])
    rows.append([InlineKeyboardButton("« Главное меню", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_arb_back() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="fetch")],
        [InlineKeyboardButton("« Главное меню", callback_data="back_main")],
    ])

# ─────────────────────────────────────────────────────────────────────────────
#  ЯДРО: ЗАГРУЗКА И АНАЛИЗ
# ─────────────────────────────────────────────────────────────────────────────

async def _do_fetch(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state: UserState,
    *,
    send_always: bool = True,
    quiet: bool = False,
) -> tuple[list, list, list]:
    """
    Загружает данные и возвращает (vbets_rows, arb_list, sig_dfs).
    Не отправляет сообщений сам — только возвращает результаты.
    """
    if not state.api_key:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ *API ключ не задан*\n\nНажми 🔑 в главном меню или введи /setkey",
            parse_mode=ParseMode.MARKDOWN,
        )
        return [], [], []

    sports_to_load = (
        list(SPORTS_CATALOGUE.items()) if state.all_sports
        else [(state.sport_label, state.sport_cfg)]
    )

    if not quiet:
        n = len(sports_to_load)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏳ Загружаю {n} лиг{'у' if n == 1 else 'и' if n < 5 else ''}…",
        )

    all_vbets: list[dict]         = []
    all_arbs:  list[dict]         = []
    all_sigs:  list[pd.DataFrame] = []
    min_remaining = "?"

    for label, cfg in sports_to_load:
        events, remaining, used = fetch_odds_raw(
            state.api_key, cfg["key"], state.region_key,
        )
        if remaining != "?":
            min_remaining = remaining

        if not events:
            continue

        state.last_events = events
        state.last_fetch  = time.time()

        df = build_df_from_events(events, cfg["has_draw"], state.bookmakers)
        if df.empty:
            continue

        # Value Bets
        vdf = compute_value_bets(df, cfg["has_draw"], state.ev_threshold)
        if not vdf.empty:
            # Kelly Stake
            def _add_kelly(r):
                try:
                    nv_pct = float(str(r.get("No-Vig Fair %", 0)).replace("%", "") or 0)
                    dec    = float(r.get("Odds (Dec)", 0) or 0)
                    stk    = kelly_stake(state.bankroll, nv_pct, dec)
                    return f"${stk:.2f}"
                except Exception:
                    return ""
            vdf["Kelly Stake ($)"] = vdf.apply(_add_kelly, axis=1)
            vdf["_sport"] = label
            for _, row in vdf.iterrows():
                all_vbets.append(dict(row))

        # Арбитраж
        for _, grp in df.groupby("Матч"):
            arb = find_arb_in_group(grp, cfg["has_draw"])
            if arb:
                dec_list = arb.get("dec_odds", [])
                if dec_list:
                    arb_pct_val = arb_percentage(dec_list)
                    if arb_pct_val > 0:
                        profit = (1 / arb_pct_val - 1) * 100
                        stakes_list = arb_stakes(state.bankroll, dec_list)
                        arb["arb_pct"]    = arb_pct_val * 100
                        arb["profit_pct"] = profit
                        arb["stakes"]     = stakes_list
                        arb["sport"] = label
                        all_arbs.append(arb)

        # Сигналы
        try:
            sig_df = build_betting_signals(df, cfg["has_draw"])
            if sig_df is not None and not sig_df.empty:
                sig_df["_sport"] = label
                all_sigs.append(sig_df)
        except Exception:
            pass

    # Сортируем value bets по EV
    all_vbets.sort(key=lambda r: _parse_ev(r.get("EV Edge %", 0)), reverse=True)

    # Обновляем кэш
    state.last_remaining  = min_remaining
    state.last_vbets_count = len(all_vbets)
    state.last_arb_count  = len(all_arbs)
    state.last_vbets       = all_vbets
    state.vbets_page       = 0

    return all_vbets, all_arbs, all_sigs


async def _do_fetch_and_send(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state: UserState,
    *,
    send_always: bool = True,
    quiet: bool = False,
) -> None:
    """Загружает и отправляет результаты в чат, затем обновляет главное меню."""
    vbets, arbs, sigs = await _do_fetch(context, chat_id, state, send_always=send_always, quiet=quiet)
    sport_name = "🌐 Все лиги" if state.all_sports else state.sport_label

    # Value bets
    if vbets:
        text, total_pages = format_vbets_page(vbets, 0, sport_name, state.ev_threshold)
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_vbets_pager(0, total_pages),
        )
    elif send_always:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Обновлено · {sport_name}\nValue bets с EV ≥ {state.ev_threshold}% не найдено\n📡 API: {state.last_remaining}",
        )

    # Арбитраж
    if arbs:
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_arb_message(arbs, sport_name),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_arb_back(),
        )

    # Главное меню обновляется отдельно через show_main


async def show_main(update_or_query, state: UserState, *, edit: bool = False) -> None:
    """Показывает/обновляет главное меню."""
    text = format_main_status(state)
    kb   = kb_main(state)
    if edit and hasattr(update_or_query, "edit_message_text"):
        try:
            await update_or_query.edit_message_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
    elif hasattr(update_or_query, "message"):
        await update_or_query.message.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    elif hasattr(update_or_query, "reply_text"):
        await update_or_query.reply_text(text, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)

# ─────────────────────────────────────────────────────────────────────────────
#  JOB: АВТООБНОВЛЕНИЕ
# ─────────────────────────────────────────────────────────────────────────────

async def _auto_refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = context.job.chat_id
    state   = get_state(chat_id)
    logger.info("auto_refresh_job: chat_id=%s", chat_id)
    vbets, arbs, _ = await _do_fetch(context, chat_id, state, send_always=False, quiet=True)
    sport_name = "🌐 Все лиги" if state.all_sports else state.sport_label

    if vbets:
        text, total_pages = format_vbets_page(vbets, 0, sport_name, state.ev_threshold)
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"🔔 *Авто-обновление* · {_now_msk()}\n\n" + text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_vbets_pager(0, total_pages),
        )
    if arbs:
        await context.bot.send_message(
            chat_id=chat_id,
            text=format_arb_message(arbs, sport_name),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=kb_arb_back(),
        )


def _cancel_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    for job in context.job_queue.get_jobs_by_name(str(chat_id)):
        job.schedule_removal()


def _schedule_refresh(context: ContextTypes.DEFAULT_TYPE, chat_id: int, interval: int) -> None:
    _cancel_jobs(context, chat_id)
    if interval > 0:
        context.job_queue.run_repeating(
            _auto_refresh_job,
            interval=interval,
            first=interval,
            chat_id=chat_id,
            name=str(chat_id),
        )
        logger.info("Scheduled refresh every %ds for chat %s", interval, chat_id)

# ─────────────────────────────────────────────────────────────────────────────
#  КОМАНДЫ
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    state = get_state(update.effective_chat.id)
    await show_main(update, state)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Справка Sports Odds Dashboard Bot*\n\n"
        "*Команды:*\n"
        "/start — главное меню\n"
        "/fetch — загрузить ставки вручную\n"
        "/status — текущие настройки\n"
        "/setkey — ввести API ключ\n"
        "/stop — остановить автообновление\n"
        "/help — эта справка\n\n"
        "*Кнопки главного меню:*\n"
        "📊 — загрузить прямо сейчас\n"
        "💎 VB — просмотр value bets с пагинацией\n"
        "⚡ Arb — арбитражные возможности\n"
        "🎯 Сигналы — Sharp EV сигналы\n"
        "⚽ — выбор лиги или всех лиг\n"
        "🏦 — фильтр букмекеров (US/EU/все)\n"
        "🔄 — включить авто-обновление\n"
        "🌍 — регион букмекеров\n"
        "🔑 — ввести/сменить API ключ\n"
        "⚙️ — настройки (EV порог, банкролл)\n"
        "🛑 — остановить автообновление\n"
        "📋 — полный статус настроек\n\n"
        "*API ключ:* [the-odds-api.com](https://the-odds-api.com/account/) — 500 бесплатных запросов/мес"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN,
                                    disable_web_page_preview=True,
                                    reply_markup=kb_main(get_state(update.effective_chat.id)))


async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    await _do_fetch_and_send(context, chat_id, state, send_always=True)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    await update.message.reply_text(
        format_status_message(state, context, chat_id),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb_settings(state),
    )


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _cancel_jobs(context, chat_id)
    state = get_state(chat_id)
    state.refresh_interval = 0
    await update.message.reply_text(
        "🛑 Автообновление остановлено",
        reply_markup=kb_main(state),
    )

# ─────────────────────────────────────────────────────────────────────────────
#  CONVERSATION: ВВОД API КЛЮЧА
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_setkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    await update.message.reply_text(
        "🔑 *Введи API ключ The Odds API*\n\n"
        "Получить бесплатно: [the-odds-api.com](https://the-odds-api.com/account/)\n"
        "500 запросов/месяц бесплатно\n\n"
        "Введи ключ следующим сообщением или /cancel для отмены:",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    return WAIT_API_KEY


async def receive_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    key     = update.message.text.strip()
    state   = get_state(chat_id)
    msg     = await update.message.reply_text("⏳ Проверяю ключ…")
    events, remaining, used = fetch_odds_raw(key, "americanfootball_nfl", "us")
    if events is not None:
        state.api_key       = key
        state.last_remaining = remaining
        await msg.edit_text(
            f"✅ *Ключ принят!*\nОсталось запросов: `{remaining}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        await show_main(update, state)
    else:
        await msg.edit_text(
            "❌ Ключ недействителен или исчерпаны запросы.\n"
            "Попробуй снова /setkey или /cancel для отмены"
        )
    return ConversationHandler.END


async def conv_set_ev_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    state = get_state(update.effective_chat.id)
    await update.message.reply_text(
        f"📈 *EV порог сейчас: {state.ev_threshold}%*\n\n"
        "Введи новое значение (от 0 до 50), например `5.0`:\n/cancel — отмена",
        parse_mode=ParseMode.MARKDOWN,
    )
    return WAIT_EV


async def receive_ev_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    try:
        val = float(update.message.text.strip().replace("%", "").replace(",", "."))
        if 0 <= val <= 50:
            state.ev_threshold = val
            await update.message.reply_text(
                f"✅ EV порог: *{val}%*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(state),
            )
        else:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи число от 0 до 50, например: `5.0`",
                                        parse_mode=ParseMode.MARKDOWN)
    return ConversationHandler.END


async def conv_set_bankroll_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    state = get_state(update.effective_chat.id)
    await update.message.reply_text(
        f"💰 *Банкролл сейчас: ${state.bankroll:,.0f}*\n\n"
        "Введи сумму (от 10 до 10,000,000), например `1000`:\n/cancel — отмена",
        parse_mode=ParseMode.MARKDOWN,
    )
    return WAIT_BANKROLL


async def receive_bankroll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    try:
        val = float(update.message.text.strip().replace("$", "").replace(",", ".").replace(" ", ""))
        if 10 <= val <= 10_000_000:
            state.bankroll = val
            await update.message.reply_text(
                f"✅ Банкролл: *${val:,.0f}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main(state),
            )
        else:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Введи сумму от 10 до 10,000,000, например: `1000`",
            parse_mode=ParseMode.MARKDOWN,
        )
    return ConversationHandler.END


async def cancel_conv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    state = get_state(update.effective_chat.id)
    await update.message.reply_text("❌ Отменено", reply_markup=kb_main(state))
    return ConversationHandler.END

# ─────────────────────────────────────────────────────────────────────────────
#  CALLBACK QUERY HANDLER
# ─────────────────────────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    chat_id = query.message.chat_id
    state   = get_state(chat_id)
    data    = query.data
    await query.answer()

    # ── Главное меню ──────────────────────────────────────────────────────────
    if data in ("back_main", "main"):
        await query.edit_message_text(
            format_main_status(state),
            reply_markup=kb_main(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Загрузить сейчас ─────────────────────────────────────────────────────
    elif data == "fetch":
        await query.edit_message_text("⏳ Загружаю данные…")
        await _do_fetch_and_send(context, chat_id, state, send_always=True)
        # Обновим исходное сообщение с новым главным меню
        try:
            await query.edit_message_text(
                format_main_status(state),
                reply_markup=kb_main(state),
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    # ── Value Bets (просмотр из кэша) ────────────────────────────────────────
    elif data == "show_vbets":
        if not state.last_vbets:
            await query.edit_message_text(
                "💎 Кэш пуст — нажми 📊 Загрузить сейчас",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📊 Загрузить", callback_data="fetch"),
                    InlineKeyboardButton("« Назад", callback_data="back_main"),
                ]]),
            )
            return
        sport_name = "🌐 Все лиги" if state.all_sports else state.sport_label
        text, total_pages = format_vbets_page(
            state.last_vbets, state.vbets_page, sport_name, state.ev_threshold,
        )
        await query.edit_message_text(
            text,
            reply_markup=kb_vbets_pager(state.vbets_page, total_pages),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Value Bets пагинация ─────────────────────────────────────────────────
    elif data.startswith("vbets_page_"):
        page = int(data[len("vbets_page_"):])
        state.vbets_page = page
        if not state.last_vbets:
            await query.answer("Кэш пуст — загрузи данные снова", show_alert=True)
            return
        sport_name = "🌐 Все лиги" if state.all_sports else state.sport_label
        text, total_pages = format_vbets_page(
            state.last_vbets, page, sport_name, state.ev_threshold,
        )
        await query.edit_message_text(
            text,
            reply_markup=kb_vbets_pager(page, total_pages),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Арбитраж (из кэша) ───────────────────────────────────────────────────
    elif data == "show_arb":
        sport_name = "🌐 Все лиги" if state.all_sports else state.sport_label
        # Пересчитываем из last_events если есть
        all_arbs = []
        if state.last_events:
            cfg = state.sport_cfg
            df  = build_df_from_events(state.last_events, cfg["has_draw"], state.bookmakers)
            for _, grp in df.groupby("Матч"):
                arb = find_arb_in_group(grp, cfg["has_draw"])
                if arb:
                    dec_list = arb.get("dec_odds", [])
                    if dec_list:
                        arb_pct_val = arb_percentage(dec_list)
                        if arb_pct_val > 0:
                            arb["profit_pct"] = (1 / arb_pct_val - 1) * 100
                            arb["arb_pct"]    = arb_pct_val * 100
                            arb["stakes"]     = arb_stakes(state.bankroll, dec_list)
                            all_arbs.append(arb)
        if not all_arbs and not state.last_events:
            await query.edit_message_text(
                "⚡ Данных нет — нажми 📊 Загрузить сейчас",
                reply_markup=kb_arb_back(),
            )
            return
        await query.edit_message_text(
            format_arb_message(all_arbs, sport_name),
            reply_markup=kb_arb_back(),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Сигналы ───────────────────────────────────────────────────────────────
    elif data == "show_signals":
        sport_name = "🌐 Все лиги" if state.all_sports else state.sport_label
        sig_df = None
        if state.last_events:
            cfg = state.sport_cfg
            df  = build_df_from_events(state.last_events, cfg["has_draw"], state.bookmakers)
            try:
                sig_df = build_betting_signals(df, cfg["has_draw"])
            except Exception:
                sig_df = None
        await query.edit_message_text(
            format_signals_message(sig_df, sport_name),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Обновить", callback_data="fetch")],
                [InlineKeyboardButton("« Главное меню", callback_data="back_main")],
            ]),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Меню спорта ───────────────────────────────────────────────────────────
    elif data == "menu_sport":
        sport_name = "🌐 Все лиги" if state.all_sports else state.sport_label
        await query.edit_message_text(
            f"⚽🏈🏀 *Выбор лиги*\n\nСейчас: {sport_name}",
            reply_markup=kb_sport(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "sport_ALL":
        state.all_sports = True
        await query.edit_message_text(
            "✅ *Выбрано: Все лиги*",
            reply_markup=kb_sport(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("sport_"):
        label = data[6:]
        if label in SPORTS_CATALOGUE:
            state.all_sports  = False
            state.sport_label = label
            await query.edit_message_text(
                f"✅ *Выбрано: {label}*",
                reply_markup=kb_sport(state),
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Меню букмекеров ───────────────────────────────────────────────────────
    elif data == "menu_bm":
        bm_str = state.bm_display
        await query.edit_message_text(
            f"🏦 *Выбор букмекеров*\n\nСейчас: {bm_str}\n\nМожно выбрать несколько — нажимай на каждого:",
            reply_markup=kb_bm(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "bm_ALL":
        state.bookmakers = []
        await query.edit_message_text(
            "✅ Все букмекеры включены",
            reply_markup=kb_bm(state),
        )

    elif data == "bm_group_US":
        state.bookmakers = list(US_BM_LIST)
        await query.edit_message_text(
            f"✅ US букмекеры ({len(US_BM_LIST)}): {', '.join(US_BM_LIST[:4])}…",
            reply_markup=kb_bm(state),
        )

    elif data == "bm_group_EU":
        state.bookmakers = list(EU_BM_LIST)
        await query.edit_message_text(
            f"✅ EU букмекеры ({len(EU_BM_LIST)}): {', '.join(EU_BM_LIST[:4])}…",
            reply_markup=kb_bm(state),
        )

    elif data.startswith("bm_"):
        bm = data[3:]
        if bm in ALL_BOOKMAKERS:
            if bm in state.bookmakers:
                state.bookmakers.remove(bm)
                action = "❌ убран"
            else:
                state.bookmakers.append(bm)
                action = "✅ добавлен"
            selected_str = ", ".join(state.bookmakers) if state.bookmakers else "все"
            await query.edit_message_text(
                f"{action}: *{bm}*\n\nВыбрано: {selected_str}",
                reply_markup=kb_bm(state),
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Меню автообновления ───────────────────────────────────────────────────
    elif data == "menu_refresh":
        await query.edit_message_text(
            f"⏱ *Автообновление*\n\nСейчас: {state.refresh_label}",
            reply_markup=kb_refresh(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("refresh_"):
        secs = int(data[8:])
        state.refresh_interval = secs
        _schedule_refresh(context, chat_id, secs)
        label = next((k for k, v in REFRESH_OPTIONS.items() if v == secs), "вручную")
        msg   = f"✅ *Автообновление: {label}*" if secs > 0 else "🚫 Автообновление отключено"
        await query.edit_message_text(
            msg, reply_markup=kb_refresh(state), parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "stop_refresh":
        _cancel_jobs(context, chat_id)
        state.refresh_interval = 0
        await query.edit_message_text(
            "🛑 *Автообновление остановлено*",
            reply_markup=kb_main(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Меню региона ─────────────────────────────────────────────────────────
    elif data == "menu_region":
        await query.edit_message_text(
            f"🌍 *Регион букмекеров*\n\nСейчас: {state.region}",
            reply_markup=kb_region(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("region_"):
        region = data[7:]
        if region in REGION_MAP:
            state.region = region
            await query.edit_message_text(
                f"✅ *Регион: {region}*",
                reply_markup=kb_region(state),
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Настройки ────────────────────────────────────────────────────────────
    elif data == "settings":
        await query.edit_message_text(
            "⚙️ *Настройки*\nВыбери параметр:",
            reply_markup=kb_settings(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "set_key":
        context.user_data["awaiting"] = "key"
        await query.edit_message_text(
            "🔑 *Введи API ключ следующим сообщением*\n\n"
            "Получить: [the-odds-api.com](https://the-odds-api.com/account/)\n"
            "/cancel для отмены",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )

    elif data == "set_ev":
        context.user_data["awaiting"] = "ev"
        await query.edit_message_text(
            f"📈 *EV порог сейчас: {state.ev_threshold}%*\n\n"
            "Введи новое значение (0–50), например `5.0`:\n/cancel для отмены",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "set_bankroll":
        context.user_data["awaiting"] = "bankroll"
        await query.edit_message_text(
            f"💰 *Банкролл сейчас: ${state.bankroll:,.0f}*\n\n"
            "Введи сумму, например `1000`:\n/cancel для отмены",
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Статус ───────────────────────────────────────────────────────────────
    elif data == "status":
        await query.edit_message_text(
            format_status_message(state, context, chat_id),
            reply_markup=kb_settings(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "noop":
        pass  # индикатор страницы — ничего не делаем

# ─────────────────────────────────────────────────────────────────────────────
#  ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ
# ─────────────────────────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id  = update.effective_chat.id
    state    = get_state(chat_id)
    awaiting = context.user_data.get("awaiting")
    text     = update.message.text.strip()

    if awaiting == "key":
        context.user_data["awaiting"] = None
        msg = await update.message.reply_text("⏳ Проверяю ключ…")
        events, remaining, used = fetch_odds_raw(text, "americanfootball_nfl", "us")
        if events is not None:
            state.api_key        = text
            state.last_remaining = remaining
            await msg.edit_text(f"✅ *Ключ принят!* Осталось: `{remaining}`",
                                 parse_mode=ParseMode.MARKDOWN)
        else:
            await msg.edit_text("❌ Ключ недействителен. Попробуй ещё раз или /cancel")
            return
        await show_main(update, state)

    elif awaiting == "ev":
        context.user_data["awaiting"] = None
        try:
            val = float(text.replace("%", "").replace(",", "."))
            if 0 <= val <= 50:
                state.ev_threshold = val
                await update.message.reply_text(
                    f"✅ EV порог: *{val}%*", parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_main(state),
                )
            else:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Введи число 0–50, например `5.0`",
                                            parse_mode=ParseMode.MARKDOWN)

    elif awaiting == "bankroll":
        context.user_data["awaiting"] = None
        try:
            val = float(text.replace("$", "").replace(",", ".").replace(" ", ""))
            if 10 <= val <= 10_000_000:
                state.bankroll = val
                await update.message.reply_text(
                    f"✅ Банкролл: *${val:,.0f}*", parse_mode=ParseMode.MARKDOWN,
                    reply_markup=kb_main(state),
                )
            else:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Введи сумму 10–10,000,000, например `1000`",
                                            parse_mode=ParseMode.MARKDOWN)

    else:
        # Любой текст → показываем главное меню
        await show_main(update, state)

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv_setkey = ConversationHandler(
        entry_points=[CommandHandler("setkey", cmd_setkey)],
        states={WAIT_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key)]},
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("fetch",  cmd_fetch))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(conv_setkey)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Глобальный обработчик ошибок — спрятываем BadRequest (сообщение не изменилось) и логируем остальное
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        err = context.error
        if isinstance(err, TgBadRequest) and "not modified" in str(err).lower():
            return  # игнорируем — безвредная ошибка
        logger.warning("Update %s вызвал ошибку: %s", update, err)

    app.add_error_handler(error_handler)

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start",  "Главное меню"),
            BotCommand("fetch",  "Загрузить ставки"),
            BotCommand("status", "Статус настроек"),
            BotCommand("setkey", "Ввести API ключ"),
            BotCommand("stop",   "Стоп автообновления"),
            BotCommand("help",   "Справка"),
        ])

    app.post_init = post_init
    logger.info("Starting Sports Odds Dashboard Bot v2.0…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
