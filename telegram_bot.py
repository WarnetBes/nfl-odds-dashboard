"""
telegram_bot.py — Telegram Bot для Sports Odds Dashboard.

Возможности:
  • Ввод / обновление The Odds API ключа прямо в чате
  • Выбор вида спорта (все или конкретная лига)
  • Выбор букмекеров (все или конкретные)
  • Ручная загрузка ставок по команде
  • Автообновление: каждые 3 / 5 / 15 / 30 минут — пользователь выбирает
  • Value bets с EV Edge — пуш-уведомление при нахождении
  • Арбитражные возможности

Зависимости (pip install):
  python-telegram-bot>=20.0
  requests pandas pytz

Запуск:
  python telegram_bot.py
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import pandas as pd
import pytz
import requests
from telegram import (
    BotCommand,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Импортируем чистые функции из utils.py — без риска сломать app.py
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

BOT_TOKEN   = os.environ.get("TELEGRAM_BOT_TOKEN", "7145666214:AAHivgv39C5OpwDCrxbKgpkxergKQdpapVw")
ODDS_BASE   = "https://api.the-odds-api.com/v4"
MSK         = pytz.timezone("Europe/Moscow")
LOG_LEVEL   = logging.INFO

# EV Edge порог для уведомлений (%)
DEFAULT_EV_THRESHOLD = 5.0
# Минимальная ставка Kelly для отображения (% от банкролла)
KELLY_MIN_PCT = 0.5
# Банкролл по умолчанию для расчёта Kelly
DEFAULT_BANKROLL = 1000.0

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=LOG_LEVEL,
)
logger = logging.getLogger("sports_bot")

# ─────────────────────────────────────────────────────────────────────────────
#  ВИДЫ СПОРТА
# ─────────────────────────────────────────────────────────────────────────────

SPORTS_CATALOGUE: dict[str, dict] = {
    "⚽ EPL":           {"key": "soccer_epl",                    "has_draw": True},
    "⚽ La Liga":        {"key": "soccer_spain_la_liga",          "has_draw": True},
    "⚽ Bundesliga":     {"key": "soccer_germany_bundesliga",     "has_draw": True},
    "⚽ Serie A":        {"key": "soccer_italy_serie_a",          "has_draw": True},
    "⚽ Ligue 1":        {"key": "soccer_france_ligue_one",       "has_draw": True},
    "⚽ Champions Lge":  {"key": "soccer_uefa_champs_league",     "has_draw": True},
    "⚽ Europa Lge":     {"key": "soccer_uefa_europa_league",     "has_draw": True},
    "⚽ MLS":            {"key": "soccer_usa_mls",                "has_draw": True},
    "🏈 NFL":            {"key": "americanfootball_nfl",          "has_draw": False},
    "🏀 NBA":            {"key": "basketball_nba",                "has_draw": False},
}

# Список известных букмекеров
ALL_BOOKMAKERS: list[str] = [
    "DraftKings", "FanDuel", "BetMGM", "Caesars", "BetOnline.ag",
    "William Hill US", "BetRivers", "Bovada", "PointsBet US", "Barstool",
    "Betfair", "Unibet", "Paddy Power", "Bet365", "Sky Bet",
    "Ladbrokes", "Coral", "Betway", "888sport", "Pinnacle", "1xBet",
]

REGION_MAP: dict[str, str] = {
    "🇺🇸 US":       "us",
    "🇺🇸 US+":      "us2",
    "🇬🇧 UK":       "uk",
    "🇪🇺 EU":       "eu",
    "🌍 Все":       "us,us2,uk,eu",
}

# Интервалы автообновления (секунды)
REFRESH_OPTIONS: dict[str, int] = {
    "⏱ 3 мин":  3  * 60,
    "⏱ 5 мин":  5  * 60,
    "⏱ 15 мин": 15 * 60,
    "⏱ 30 мин": 30 * 60,
    "🚫 Вручную": 0,
}

# ─────────────────────────────────────────────────────────────────────────────
#  СОСТОЯНИЕ ПОЛЬЗОВАТЕЛЕЙ (in-memory, достаточно для одного бота)
# ─────────────────────────────────────────────────────────────────────────────

class UserState:
    """Хранит настройки и состояние одного пользователя."""

    def __init__(self) -> None:
        self.api_key: str           = ""
        self.sport_label: str       = "🏈 NFL"
        self.selected_sports: list  = ["🏈 NFL"]   # для режима «все»
        self.all_sports: bool       = False
        self.bookmakers: list[str]  = []            # [] = все
        self.region: str            = "🌍 Все"
        self.refresh_interval: int  = 0             # 0 = вручную
        self.ev_threshold: float    = DEFAULT_EV_THRESHOLD
        self.bankroll: float        = DEFAULT_BANKROLL
        self.last_fetch: float      = 0.0
        self.last_events: list      = []
        self.job_running: bool      = False

    @property
    def region_key(self) -> str:
        return REGION_MAP.get(self.region, "us,us2,uk,eu")

    @property
    def sport_cfg(self) -> dict:
        return SPORTS_CATALOGUE.get(self.sport_label, {"key": "americanfootball_nfl", "has_draw": False})


# Словарь состояний: chat_id → UserState
_user_states: dict[int, UserState] = {}

def get_state(chat_id: int) -> UserState:
    if chat_id not in _user_states:
        _user_states[chat_id] = UserState()
    return _user_states[chat_id]


# ConversationHandler states
WAIT_API_KEY = "WAIT_API_KEY"
WAIT_EV      = "WAIT_EV"
WAIT_BANKROLL= "WAIT_BANKROLL"

# ─────────────────────────────────────────────────────────────────────────────
#  FETCH ODDS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_odds_raw(api_key: str, sport_key: str, regions: str) -> tuple[list | None, str, str]:
    """Загружает H2H коэффициенты. Возвращает (events, remaining, used)."""
    try:
        r = requests.get(
            f"{ODDS_BASE}/sports/{sport_key}/odds",
            params=dict(
                apiKey=api_key,
                regions=regions,
                markets="h2h",
                oddsFormat="american",
                dateFormat="iso",
            ),
            timeout=15,
        )
        remaining = r.headers.get("x-requests-remaining", "?")
        used      = r.headers.get("x-requests-used", "?")
        if r.status_code == 200:
            return r.json(), remaining, used
        elif r.status_code == 401:
            return None, "?", "?"
        return None, remaining, used
    except Exception as exc:
        logger.exception("fetch_odds_raw error: %s", exc)
        return None, "?", "?"


def build_df_from_events(
    events: list,
    has_draw: bool,
    bookmakers_filter: list[str],
) -> pd.DataFrame:
    """
    Строит DataFrame из raw events с фильтром по букмекерам.
    Использует ту же логику что и parse_to_df в app.py.
    """
    rows = []
    for ev in events:
        home = ev.get("home_team", "?")
        away = ev.get("away_team", "?")
        t    = ev.get("commence_time", "")[:16].replace("T", " ") + " UTC"
        for bm in ev.get("bookmakers", []):
            bm_title = bm.get("title", bm.get("key", "?"))
            # Применяем фильтр букмекеров
            if bookmakers_filter and bm_title not in bookmakers_filter:
                continue
            for mkt in bm.get("markets", []):
                if mkt.get("key") != "h2h":
                    continue
                oc = {o["name"]: o.get("price") for o in mkt.get("outcomes", [])}
                rows.append({
                    "Матч":            f"{away} @ {home}",
                    "Время":           t,
                    "Букмекер":        bm_title,
                    "Хозяева":         home,
                    "Гости":           away,
                    "Odds Хозяева (Am)": oc.get(home),
                    "Odds Гости (Am)":   oc.get(away),
                    "Odds Ничья (Am)":   oc.get("Draw") if has_draw else None,
                    "_event_id":       ev.get("id", ""),
                })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
#  ФОРМАТИРОВАНИЕ СООБЩЕНИЙ
# ─────────────────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Экранирует спецсимволы MarkdownV2."""
    special = r"\_*[]()~`>#+-=|{}.!"
    for ch in special:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_value_bets_message(
    vdf: pd.DataFrame,
    sport_label: str,
    remaining: str,
    ev_threshold: float,
) -> str:
    """Форматирует топ value bets для Telegram."""
    if vdf.empty:
        return f"ℹ️ *{sport_label}* — нет value bets с EV ≥ {ev_threshold}%"

    lines = [f"🎯 *Value Bets — {sport_label}*", f"Порог EV Edge ≥ {ev_threshold}%", ""]

    # Сортируем по EV Edge
    def parse_ev(s):
        try:
            return float(str(s).replace("+", "").replace("%", ""))
        except Exception:
            return 0.0

    if "EV Edge %" in vdf.columns:
        vdf = vdf.copy()
        vdf["_ev_num"] = vdf["EV Edge %"].apply(parse_ev)
        vdf = vdf.sort_values("_ev_num", ascending=False)

    shown = 0
    for _, row in vdf.head(10).iterrows():
        match    = str(row.get("Матч", ""))
        bm       = str(row.get("Букмекер", ""))
        outcome  = str(row.get("Исход", "")).replace("✅ ", "")
        odds_am  = str(row.get("Odds (Am)", row.get("Odds Хозяева (Am)", "?")))
        odds_dec = str(row.get("Odds (Dec)", ""))
        ev       = str(row.get("EV Edge %", ""))
        kelly    = str(row.get("Kelly ¼ %", row.get("Kelly Stake (%)", "")))
        stake    = str(row.get(next((c for c in vdf.columns if "Kelly Stake" in c and "$" in c), ""), ""))

        lines.append(f"━━━━━━━━━━━━━━━━━")
        lines.append(f"🏟 `{match}`")
        lines.append(f"🏦 {bm}  |  ✅ *{outcome}*")
        if odds_am:
            lines.append(f"📊 Odds: `{odds_am}` ({odds_dec})")
        lines.append(f"📈 EV Edge: *{ev}*")
        if kelly:
            lines.append(f"💰 Kelly ¼: {kelly}" + (f"  →  {stake}" if stake else ""))
        shown += 1

    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append(f"📡 API запросов осталось: `{remaining}`")
    lines.append(f"🕐 {_now_msk()}")
    return "\n".join(lines)


def format_arb_message(arb_list: list, sport_label: str) -> str:
    """Форматирует арбитражные возможности."""
    if not arb_list:
        return f"ℹ️ *{sport_label}* — арбитражных возможностей не найдено"

    lines = [f"⚡ *Арбитраж — {sport_label}*", ""]
    for arb in arb_list[:5]:
        match   = arb.get("match", "?")
        bms     = arb.get("bookmakers", [])
        arb_pct = arb.get("arb_pct", 0)
        stakes  = arb.get("stakes", [])
        profit  = arb.get("profit_pct", 0)
        outcomes = arb.get("outcomes", [])

        lines.append(f"━━━━━━━━━━━━━━━━━")
        lines.append(f"🏟 `{match}`")
        lines.append(f"💹 Прибыль: *+{profit:.2f}%*  (Arb: {arb_pct:.2f}%)")
        for i, (bm, out, stk) in enumerate(zip(bms, outcomes, stakes), 1):
            lines.append(f"  {i}. {bm}: *{out}*  →  ставка ${stk:.2f}")
    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append(f"🕐 {_now_msk()}")
    return "\n".join(lines)


def format_signals_message(sig_df: pd.DataFrame, sport_label: str) -> str:
    """Форматирует сигналы (build_betting_signals)."""
    if sig_df.empty:
        return f"ℹ️ *{sport_label}* — сигналов не найдено"

    lines = [f"🎯 *Сигналы — {sport_label}*", ""]
    for _, row in sig_df.head(8).iterrows():
        match    = str(row.get("Матч", ""))
        outcome  = str(row.get("Лучший исход", row.get("Best Outcome", "")))
        conf     = str(row.get("Уверенность", row.get("Confidence", "")))
        ev       = str(row.get("Лучший EV", row.get("Best EV %", "")))
        best_bm  = str(row.get("Лучший букмекер", row.get("Best BM", "")))
        best_odds = str(row.get("Лучшие Odds (Am)", row.get("Best Odds Am", "")))

        lines.append(f"🏟 `{match}`")
        lines.append(f"  ✅ *{outcome}* @ {best_bm}  `{best_odds}`")
        lines.append(f"  📈 EV: {ev}  |  💡 Уверенность: {conf}")
        lines.append("")
    lines.append(f"🕐 {_now_msk()}")
    return "\n".join(lines)


def _now_msk() -> str:
    from datetime import datetime
    return datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")


# ─────────────────────────────────────────────────────────────────────────────
#  ФУНКЦИЯ ЗАГРУЗКИ И АНАЛИЗА
# ─────────────────────────────────────────────────────────────────────────────

async def _do_fetch_and_analyze(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    state: UserState,
    send_always: bool = True,
) -> None:
    """
    Загружает коэффициенты для выбранных спортов,
    вычисляет value bets и арбитраж, отправляет в Telegram.
    """
    if not state.api_key:
        await context.bot.send_message(
            chat_id=chat_id,
            text="⚠️ API ключ не задан\\. Введи /setkey",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    # Определяем список лиг для загрузки
    if state.all_sports:
        sports_to_load = list(SPORTS_CATALOGUE.items())
    else:
        label = state.sport_label
        sports_to_load = [(label, SPORTS_CATALOGUE[label])]

    all_vbets: list[pd.DataFrame] = []
    all_arbs:  list[dict]         = []
    all_sigs:  list[pd.DataFrame] = []
    min_remaining = "?"

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏳ Загружаю {len(sports_to_load)} лиг\\(у\\)…",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    for label, cfg in sports_to_load:
        events, remaining, used = fetch_odds_raw(
            state.api_key,
            cfg["key"],
            state.region_key,
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
            vdf["_sport"] = label
            all_vbets.append(vdf)

        # Kelly Stake
        if not vdf.empty and "No-Vig Fair %" in vdf.columns and "Odds (Dec)" in vdf.columns:
            vdf["Kelly Stake ($)"] = vdf.apply(
                lambda r: f"${kelly_stake(state.bankroll, float(str(r.get('No-Vig Fair %',0)).replace('%','') or 0), float(r.get('Odds (Dec)', 0) or 0)):.2f}",
                axis=1,
            )

        # Арбитраж
        for _, grp in df.groupby("Матч"):
            arb = find_arb_in_group(grp, cfg["has_draw"])
            if arb:
                arb["sport"] = label
                # Вычисляем ставки
                dec_list = arb.get("dec_odds", [])
                if dec_list:
                    arb_pct = arb_percentage(dec_list)
                    if arb_pct > 0:
                        profit = (1 / arb_pct - 1) * 100
                        stakes = arb_stakes(state.bankroll, dec_list)
                        arb["arb_pct"]    = arb_pct * 100
                        arb["profit_pct"] = profit
                        arb["stakes"]     = stakes
                all_arbs.append(arb)

        # Сигналы
        sig_df = build_betting_signals(df, cfg["has_draw"])
        if not sig_df.empty:
            sig_df["_sport"] = label
            all_sigs.append(sig_df)

    # ── Отправка Value Bets ──────────────────────────────────────────────────
    if all_vbets:
        combined_vdf = pd.concat(all_vbets, ignore_index=True)
        sport_name = "Все лиги" if state.all_sports else state.sport_label
        msg = format_value_bets_message(
            combined_vdf, sport_name, min_remaining, state.ev_threshold
        )
        await context.bot.send_message(
            chat_id=chat_id, text=msg, parse_mode=ParseMode.MARKDOWN,
        )
    elif send_always:
        sport_name = "Все лиги" if state.all_sports else state.sport_label
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"✅ Обновлено\\. {sport_name} — value bets с EV ≥ {state.ev_threshold}% не найдено\\.\nAPI запросов осталось: `{min_remaining}`",
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    # ── Отправка Арбитража ───────────────────────────────────────────────────
    if all_arbs:
        sport_name = "Все лиги" if state.all_sports else state.sport_label
        arb_msg = format_arb_message(all_arbs, sport_name)
        await context.bot.send_message(
            chat_id=chat_id, text=arb_msg, parse_mode=ParseMode.MARKDOWN,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  JOB: АВТООБНОВЛЕНИЕ
# ─────────────────────────────────────────────────────────────────────────────

async def _auto_refresh_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Джоб планировщика — запускается по расписанию."""
    chat_id = context.job.chat_id
    state   = get_state(chat_id)
    logger.info("auto_refresh_job: chat_id=%s", chat_id)
    await _do_fetch_and_analyze(context, chat_id, state, send_always=False)


def _cancel_jobs(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Отменяет все запущенные джобы для пользователя."""
    current = context.job_queue.get_jobs_by_name(str(chat_id))
    for job in current:
        job.schedule_removal()


def _schedule_refresh(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    interval: int,
) -> None:
    """Запускает периодическое автообновление."""
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
#  КЛАВИАТУРЫ
# ─────────────────────────────────────────────────────────────────────────────

def kb_main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Загрузить ставки",      callback_data="fetch")],
        [InlineKeyboardButton("⚽🏈🏀 Спорт",             callback_data="menu_sport"),
         InlineKeyboardButton("🏦 Букмекеры",             callback_data="menu_bm")],
        [InlineKeyboardButton("⏱ Автообновление",         callback_data="menu_refresh"),
         InlineKeyboardButton("🌍 Регион",                callback_data="menu_region")],
        [InlineKeyboardButton("🔑 API ключ",              callback_data="set_key"),
         InlineKeyboardButton("⚙️ Настройки",             callback_data="settings")],
    ])


def kb_sport_menu(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    # Кнопка «Все лиги»
    all_mark = "✅ " if state.all_sports else ""
    rows.append([InlineKeyboardButton(f"{all_mark}🌐 Все лиги", callback_data="sport_ALL")])
    # Кнопки по лигам (2 в ряд)
    keys = list(SPORTS_CATALOGUE.keys())
    for i in range(0, len(keys), 2):
        row = []
        for label in keys[i:i+2]:
            mark = "✅ " if (not state.all_sports and state.sport_label == label) else ""
            row.append(InlineKeyboardButton(f"{mark}{label}", callback_data=f"sport_{label}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("« Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_bookmakers_menu(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    # Все
    all_mark = "✅ " if not state.bookmakers else ""
    rows.append([InlineKeyboardButton(f"{all_mark}🏦 Все букмекеры", callback_data="bm_ALL")])
    # US и EU группы
    rows.append([
        InlineKeyboardButton("🇺🇸 US (DK/FD/MGM…)",  callback_data="bm_group_US"),
        InlineKeyboardButton("🇪🇺 EU (Pinnacle…)",   callback_data="bm_group_EU"),
    ])
    # Индивидуально (топ)
    top_bms = ["DraftKings", "FanDuel", "BetMGM", "Pinnacle", "Betfair", "Bet365", "1xBet", "888sport"]
    for i in range(0, len(top_bms), 2):
        row = []
        for bm in top_bms[i:i+2]:
            mark = "✅ " if bm in state.bookmakers else ""
            row.append(InlineKeyboardButton(f"{mark}{bm}", callback_data=f"bm_{bm}"))
        rows.append(row)
    rows.append([InlineKeyboardButton("« Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_refresh_menu(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    for label, secs in REFRESH_OPTIONS.items():
        mark = "✅ " if state.refresh_interval == secs else ""
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"refresh_{secs}")])
    rows.append([InlineKeyboardButton("« Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_region_menu(state: UserState) -> InlineKeyboardMarkup:
    rows = []
    for label in REGION_MAP:
        mark = "✅ " if state.region == label else ""
        rows.append([InlineKeyboardButton(f"{mark}{label}", callback_data=f"region_{label}")])
    rows.append([InlineKeyboardButton("« Назад", callback_data="back_main")])
    return InlineKeyboardMarkup(rows)


def kb_settings(state: UserState) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📈 EV порог: {state.ev_threshold}%",    callback_data="set_ev")],
        [InlineKeyboardButton(f"💰 Банкролл: ${state.bankroll:,.0f}",   callback_data="set_bankroll")],
        [InlineKeyboardButton("ℹ️ Статус",                               callback_data="status")],
        [InlineKeyboardButton("« Назад",                                  callback_data="back_main")],
    ])


# ─────────────────────────────────────────────────────────────────────────────
#  КОМАНДЫ
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    text = (
        "🏆 *Sports Odds Dashboard Bot*\n\n"
        "Получай value bets, арбитраж и сигналы прямо в Telegram\\.\n\n"
        "1️⃣ Нажми *🔑 API ключ* — введи ключ The Odds API\n"
        "2️⃣ Выбери *спорт* и *букмекеров*\n"
        "3️⃣ Нажми *📊 Загрузить ставки* или включи *автообновление*\n\n"
        "👇 Главное меню:"
    )
    await update.message.reply_text(
        text, reply_markup=kb_main_menu(), parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "📖 *Команды бота*\n\n"
        "/start — главное меню\n"
        "/setkey — ввести API ключ The Odds API\n"
        "/fetch — загрузить коэффициенты вручную\n"
        "/status — текущие настройки\n"
        "/stop — остановить автообновление\n"
        "/help — эта справка\n\n"
        "*Кнопки в меню:*\n"
        "⚽🏈🏀 Спорт — выбор лиги или всех лиг\n"
        "🏦 Букмекеры — фильтр букмекеров\n"
        "⏱ Автообновление — 3/5/15/30 мин или вручную\n"
        "🌍 Регион — US / UK / EU / Все\n"
        "⚙️ Настройки — EV порог, банкролл"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def cmd_fetch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    await _do_fetch_and_analyze(context, chat_id, state, send_always=True)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    key_masked = ("*" * (len(state.api_key) - 4) + state.api_key[-4:]) if len(state.api_key) > 4 else "(не задан)"
    bm_str    = ", ".join(state.bookmakers[:5]) + ("…" if len(state.bookmakers) > 5 else "") if state.bookmakers else "все"
    sport_str = "Все лиги" if state.all_sports else state.sport_label
    refresh_str = next((k for k, v in REFRESH_OPTIONS.items() if v == state.refresh_interval), "вручную")
    jobs      = context.job_queue.get_jobs_by_name(str(chat_id))

    text = (
        f"⚙️ *Текущие настройки*\n\n"
        f"🔑 API ключ: `{key_masked}`\n"
        f"⚽ Спорт: {sport_str}\n"
        f"🏦 Букмекеры: {bm_str}\n"
        f"🌍 Регион: {state.region}\n"
        f"⏱ Автообновление: {refresh_str}\n"
        f"📈 EV порог: {state.ev_threshold}%\n"
        f"💰 Банкролл: ${state.bankroll:,.0f}\n"
        f"🤖 Джоб активен: {'✅' if jobs else '❌'}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    _cancel_jobs(context, chat_id)
    state = get_state(chat_id)
    state.refresh_interval = 0
    await update.message.reply_text(
        "🛑 Автообновление остановлено\\.",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  РАЗГОВОР: ВВОД API КЛЮЧА
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_setkey(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    await update.message.reply_text(
        "🔑 Введи свой API ключ The Odds API\\.\n"
        "Получить бесплатно: [the\\-odds\\-api\\.com](https://the-odds-api.com/account/)\n\n"
        "Введи ключ следующим сообщением или /cancel для отмены:",
        parse_mode=ParseMode.MARKDOWN_V2,
        disable_web_page_preview=True,
    )
    return WAIT_API_KEY


async def receive_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    key     = update.message.text.strip()
    state   = get_state(chat_id)

    # Быстрая проверка ключа
    await update.message.reply_text("⏳ Проверяю ключ…")
    events, remaining, used = fetch_odds_raw(key, "americanfootball_nfl", "us")

    if events is not None:
        state.api_key = key
        await update.message.reply_text(
            f"✅ Ключ принят\\! Осталось запросов: `{remaining}`\n\nТеперь нажми кнопку меню:",
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb_main_menu(),
        )
    else:
        await update.message.reply_text(
            "❌ Ключ недействителен или закончились запросы\\. Попробуй снова /setkey",
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    return ConversationHandler.END


async def receive_ev_threshold(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    try:
        val = float(update.message.text.strip().replace("%", "").replace(",", "."))
        if 0 < val < 50:
            state.ev_threshold = val
            await update.message.reply_text(
                f"✅ EV порог установлен: *{val}%*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main_menu(),
            )
        else:
            raise ValueError
    except ValueError:
        await update.message.reply_text(
            "❌ Введи число от 0 до 50, например: `5.0`",
            parse_mode=ParseMode.MARKDOWN,
        )
    return ConversationHandler.END


async def receive_bankroll(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    try:
        val = float(update.message.text.strip().replace("$", "").replace(",", ".").replace(" ", ""))
        if 10 <= val <= 10_000_000:
            state.bankroll = val
            await update.message.reply_text(
                f"✅ Банкролл установлен: *${val:,.0f}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=kb_main_menu(),
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
    await update.message.reply_text(
        "❌ Отменено\\.", parse_mode=ParseMode.MARKDOWN_V2, reply_markup=kb_main_menu(),
    )
    return ConversationHandler.END


# ─────────────────────────────────────────────────────────────────────────────
#  CALLBACK QUERY HANDLER — обработка нажатий кнопок
# ─────────────────────────────────────────────────────────────────────────────

US_BM_LIST = ["DraftKings","FanDuel","BetMGM","Caesars","BetOnline.ag","William Hill US","BetRivers","Bovada","PointsBet US","Barstool"]
EU_BM_LIST = ["Betfair","Unibet","Paddy Power","Bet365","Sky Bet","Ladbrokes","Coral","Betway","888sport","Pinnacle","1xBet"]


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query   = update.callback_query
    chat_id = query.message.chat_id
    state   = get_state(chat_id)
    data    = query.data
    await query.answer()

    # ── Главное меню ──────────────────────────────────────────────────────────
    if data == "back_main":
        sport_str = "Все лиги" if state.all_sports else state.sport_label
        bm_str    = f"{len(state.bookmakers)} выбрано" if state.bookmakers else "все"
        await query.edit_message_text(
            f"🏆 *Sports Odds Dashboard*\n\n"
            f"⚽ Спорт: {sport_str}\n"
            f"🏦 Букмекеры: {bm_str}\n"
            f"⏱ Обновление: {next((k for k, v in REFRESH_OPTIONS.items() if v == state.refresh_interval), 'вручную')}",
            reply_markup=kb_main_menu(),
            parse_mode=ParseMode.MARKDOWN,
        )

    # ── Загрузка ставок ───────────────────────────────────────────────────────
    elif data == "fetch":
        await query.edit_message_text("⏳ Загружаю…")
        await _do_fetch_and_analyze(context, chat_id, state, send_always=True)

    # ── Меню спорта ───────────────────────────────────────────────────────────
    elif data == "menu_sport":
        await query.edit_message_text(
            "⚽🏈🏀 Выбери вид спорта или «Все лиги»:",
            reply_markup=kb_sport_menu(state),
        )

    elif data == "sport_ALL":
        state.all_sports   = True
        state.sport_label  = "🏈 NFL"
        await query.edit_message_text(
            "✅ Выбрано: *Все лиги*\n\nЗагружу все {n} лиг за один запрос.".format(n=len(SPORTS_CATALOGUE)),
            reply_markup=kb_sport_menu(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data.startswith("sport_"):
        label = data[6:]
        if label in SPORTS_CATALOGUE:
            state.all_sports  = False
            state.sport_label = label
            await query.edit_message_text(
                f"✅ Выбрано: *{label}*",
                reply_markup=kb_sport_menu(state),
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Меню букмекеров ───────────────────────────────────────────────────────
    elif data == "menu_bm":
        await query.edit_message_text(
            "🏦 Выбери букмекеров (можно несколько):",
            reply_markup=kb_bookmakers_menu(state),
        )

    elif data == "bm_ALL":
        state.bookmakers = []
        await query.edit_message_text(
            "✅ Все букмекеры включены",
            reply_markup=kb_bookmakers_menu(state),
        )

    elif data == "bm_group_US":
        state.bookmakers = list(US_BM_LIST)
        await query.edit_message_text(
            f"✅ Выбраны US букмекеры ({len(US_BM_LIST)} шт.)",
            reply_markup=kb_bookmakers_menu(state),
        )

    elif data == "bm_group_EU":
        state.bookmakers = list(EU_BM_LIST)
        await query.edit_message_text(
            f"✅ Выбраны EU букмекеры ({len(EU_BM_LIST)} шт.)",
            reply_markup=kb_bookmakers_menu(state),
        )

    elif data.startswith("bm_"):
        bm = data[3:]
        if bm in ALL_BOOKMAKERS:
            if bm in state.bookmakers:
                state.bookmakers.remove(bm)
                mark = "❌ убран"
            else:
                state.bookmakers.append(bm)
                mark = "✅ добавлен"
            bm_str = ", ".join(state.bookmakers) if state.bookmakers else "все"
            await query.edit_message_text(
                f"{mark}: *{bm}*\nТекущий выбор: {bm_str}",
                reply_markup=kb_bookmakers_menu(state),
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Меню автообновления ───────────────────────────────────────────────────
    elif data == "menu_refresh":
        await query.edit_message_text(
            "⏱ Выбери интервал автообновления:",
            reply_markup=kb_refresh_menu(state),
        )

    elif data.startswith("refresh_"):
        secs = int(data[8:])
        state.refresh_interval = secs
        _schedule_refresh(context, chat_id, secs)
        label = next((k for k, v in REFRESH_OPTIONS.items() if v == secs), "вручную")
        msg   = f"✅ Автообновление: *{label}*" if secs > 0 else "🚫 Автообновление отключено"
        await query.edit_message_text(
            msg, reply_markup=kb_refresh_menu(state), parse_mode=ParseMode.MARKDOWN,
        )

    # ── Меню региона ─────────────────────────────────────────────────────────
    elif data == "menu_region":
        await query.edit_message_text(
            "🌍 Выбери регион букмекеров:",
            reply_markup=kb_region_menu(state),
        )

    elif data.startswith("region_"):
        region = data[7:]
        if region in REGION_MAP:
            state.region = region
            await query.edit_message_text(
                f"✅ Регион: *{region}*",
                reply_markup=kb_region_menu(state),
                parse_mode=ParseMode.MARKDOWN,
            )

    # ── Настройки ────────────────────────────────────────────────────────────
    elif data == "settings":
        await query.edit_message_text(
            "⚙️ *Настройки*\nВыбери параметр для изменения:",
            reply_markup=kb_settings(state),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "set_key":
        await query.edit_message_text(
            "🔑 Введи API ключ следующим сообщением\n(/setkey для начала диалога)",
        )

    elif data == "set_ev":
        context.user_data["awaiting"] = "ev"
        await query.edit_message_text(
            f"📈 Текущий EV порог: *{state.ev_threshold}%*\n\nВведи новое значение (например `5.0`):",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "set_bankroll":
        context.user_data["awaiting"] = "bankroll"
        await query.edit_message_text(
            f"💰 Текущий банкролл: *${state.bankroll:,.0f}*\n\nВведи сумму (например `1000`):",
            parse_mode=ParseMode.MARKDOWN,
        )

    elif data == "status":
        await cmd_status.__wrapped__(update, context) if hasattr(cmd_status, "__wrapped__") else None
        key_masked = ("*" * (len(state.api_key) - 4) + state.api_key[-4:]) if len(state.api_key) > 4 else "(не задан)"
        sport_str  = "Все лиги" if state.all_sports else state.sport_label
        bm_str     = ", ".join(state.bookmakers[:3]) + ("…" if len(state.bookmakers) > 3 else "") if state.bookmakers else "все"
        jobs       = context.job_queue.get_jobs_by_name(str(chat_id))
        text = (
            f"⚙️ *Настройки*\n\n"
            f"🔑 API: `{key_masked}`\n"
            f"⚽ Спорт: {sport_str}\n"
            f"🏦 Букмекеры: {bm_str}\n"
            f"🌍 Регион: {state.region}\n"
            f"📈 EV порог: {state.ev_threshold}%\n"
            f"💰 Банкролл: ${state.bankroll:,.0f}\n"
            f"🤖 Автообновление: {'✅' if jobs else '❌'}"
        )
        await query.edit_message_text(
            text, reply_markup=kb_settings(state), parse_mode=ParseMode.MARKDOWN,
        )


# ─────────────────────────────────────────────────────────────────────────────
#  ОБРАБОТКА ТЕКСТОВЫХ СООБЩЕНИЙ (ввод EV/bankroll вне ConversationHandler)
# ─────────────────────────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    state   = get_state(chat_id)
    awaiting = context.user_data.get("awaiting")

    if awaiting == "ev":
        context.user_data["awaiting"] = None
        await receive_ev_threshold(update, context)
    elif awaiting == "bankroll":
        context.user_data["awaiting"] = None
        await receive_bankroll(update, context)
    else:
        await update.message.reply_text(
            "👇 Используй меню:", reply_markup=kb_main_menu(),
        )


# ─────────────────────────────────────────────────────────────────────────────
#  MAIN — запуск бота
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # ConversationHandler для ввода API ключа
    conv_setkey = ConversationHandler(
        entry_points=[
            CommandHandler("setkey", cmd_setkey),
        ],
        states={
            WAIT_API_KEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_api_key)],
        },
        fallbacks=[CommandHandler("cancel", cancel_conv)],
    )

    # Регистрируем хендлеры
    app.add_handler(CommandHandler("start",  cmd_start))
    app.add_handler(CommandHandler("help",   cmd_help))
    app.add_handler(CommandHandler("fetch",  cmd_fetch))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(conv_setkey)
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    # Команды для меню Telegram
    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands([
            BotCommand("start",  "Главное меню"),
            BotCommand("setkey", "Ввести API ключ"),
            BotCommand("fetch",  "Загрузить ставки вручную"),
            BotCommand("status", "Текущие настройки"),
            BotCommand("stop",   "Остановить автообновление"),
            BotCommand("help",   "Справка"),
        ])

    app.post_init = post_init

    logger.info("Starting Sports Odds Dashboard Bot…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
