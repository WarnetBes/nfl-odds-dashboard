"""
utils.py — чистые функции без Streamlit-зависимостей.
Импортируются как app.py, так и тестами.

Формулы (в порядке применения):
  1. american_to_decimal       — конвертация American → Decimal odds
  2. decimal_to_implied        — Decimal → Implied probability (%)
  3. no_vig_prob               — удаление vig (нормализация к 100%)
  4. ev_edge                   — EV = P_fair × D − 1
  5. kelly_fraction            — Критерий Келли: f* = (b×p − q) / b
  6. arb_percentage            — Surebet: Arb% = 1 − Σ(1/D_i)
  7. sharp_books_in_group      — Определение "шарп" книг в группе
  8. cross_book_sharp_ev       — Cross-book EV: Pinnacle/sharp как reference
  9. consensus_sharp_prob      — Средневзвешенный шарп-консенсус
  10. confidence_score_v2      — Расширенная формула уверенности
  11. sport_ev_threshold       — Минимальный EV-порог по виду спорта
  12. build_betting_signals    — Сигналы (агрегация по матчу, cross-book)
  13. compute_value_bets       — Value bets (cross-book EV)
  14. parse_espn_event         — Парсинг ESPN scoreboard event
  15. fetch_scores_from_url    — HTTP-запрос ESPN (injectable session)
  16. make_h2h_row             — Фабрика тестовых строк DataFrame
"""
from __future__ import annotations
import math
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
#  КОНСТАНТЫ
# ─────────────────────────────────────────────────────────────────────────────

# Букмекеры с минимальной маржой (vig ~1.5–2%) — используются как reference
SHARP_BOOKS = {
    "pinnacle", "pinnaclesports", "betfair", "betfair_ex_eu",
    "circa", "bookmaker", "bookmaker.eu", "betcris",
    "matchbook", "sport888", "888sport",
}

# Минимальный EV-порог по умолчанию если вид спорта не определён
DEFAULT_EV_THRESHOLD = 2.0


# ─────────────────────────────────────────────────────────────────────────────
#  1. КОНВЕРТАЦИЯ КОЭФФИЦИЕНТОВ
# ─────────────────────────────────────────────────────────────────────────────

def american_to_decimal(v: float) -> float:
    """American odds → Decimal odds.

    +150  → 2.5000
    -110  → 1.9091
    +100  → 2.0000
    -100  → 2.0000
    """
    if v >= 0:
        return round(v / 100 + 1, 4)
    return round(100 / abs(v) + 1, 4)


def decimal_to_implied(d: float) -> float:
    """Decimal odds → Implied probability (%).

    2.0   → 50.0%
    1.909 → 52.38%
    """
    return round(1 / d * 100, 2) if d > 0 else 0.0


def implied_to_decimal(p_pct: float) -> float:
    """Implied probability (%) → Decimal odds.

    50.0 → 2.0
    60.0 → 1.6667
    """
    return round(100 / p_pct, 4) if p_pct > 0 else 0.0


def no_vig_prob(probs: list) -> list:
    """Убирает vig нормализацией к 100%.

    [52.38, 52.38] (total=104.76%) → [50.0, 50.0]
    [54.55, 48.78] (total=103.33%) → [52.80, 47.20]
    """
    t = sum(probs)
    return [round(p / t * 100, 4) for p in probs] if t else probs


def ev_edge(fair_pct: float, dec: float) -> float:
    """EV Edge = P_fair × D − 1 (в долях, не процентах).

    fair_pct=55.0, dec=2.0  → EV = 0.55×2.0−1 = +0.10  (+10%)
    fair_pct=45.0, dec=1.90 → EV = 0.45×1.90−1 = −0.145 (−14.5%)
    """
    return round(fair_pct / 100 * dec - 1, 6)


def fmt_am(v) -> str:
    """Форматирует American odds: -110 → '-110', +150 → '+150'."""
    try:
        f = float(v)
        return f"+{int(f)}" if f >= 0 else str(int(f))
    except Exception:
        return str(v)


# ─────────────────────────────────────────────────────────────────────────────
#  2. KELLY CRITERION
# ─────────────────────────────────────────────────────────────────────────────

def kelly_fraction(fair_prob_pct: float, dec_odds: float,
                   fraction: float = 0.25) -> float:
    """Критерий Келли для расчёта доли банкролла.

    f* = (b × p − q) / b,  где b = dec_odds − 1, p = P_fair, q = 1 − p

    fraction=0.25 → Четверть Келли (рекомендуется для управления риском).
    Возвращает долю [0.0 … 1.0]. Никогда не отрицательный.

    Примеры:
      fair=55%, dec=2.10 → b=1.10, f*=(1.10×0.55−0.45)/1.10 = 0.14 → 3.5% банка (¼K)
      fair=50%, dec=2.00 → b=1.00, f*=(1.0×0.50−0.50)/1.0  = 0.0  → не ставим
    """
    p = fair_prob_pct / 100
    q = 1 - p
    b = dec_odds - 1
    if b <= 0:
        return 0.0
    full_kelly = (b * p - q) / b
    return round(max(full_kelly * fraction, 0.0), 6)


def kelly_stake(bankroll: float, fair_prob_pct: float, dec_odds: float,
                fraction: float = 0.25) -> float:
    """Размер ставки в денежных единицах по Келли."""
    return round(bankroll * kelly_fraction(fair_prob_pct, dec_odds, fraction), 2)


# ─────────────────────────────────────────────────────────────────────────────
#  3. SUREBET / ARB DETECTION
# ─────────────────────────────────────────────────────────────────────────────

def arb_percentage(dec_odds_list: list) -> float:
    """Вычисляет Arb% = 1 − Σ(1/D_i).

    Положительный → surebet (гарантированная прибыль).
    dec_odds_list — лучшие коэффициенты на каждый исход у разных книг.

    Пример 2-way:
      Chiefs +175 (dec=2.75) у DraftKings, Ravens +165 (dec=2.65) у FanDuel
      Arb% = 1 − (1/2.75 + 1/2.65) = 1 − (0.364 + 0.377) = +25.9% → surebet!

    Пример нет вилки:
      Chiefs -145 (dec=1.69) + Ravens +125 (dec=2.25)
      Arb% = 1 − (0.592 + 0.444) = −3.6% → нет вилки
    """
    if not dec_odds_list or any(d <= 0 for d in dec_odds_list):
        return -999.0
    total_implied = sum(1 / d for d in dec_odds_list)
    return round(1 - total_implied, 6)


def arb_stakes(bankroll: float, dec_odds_list: list) -> list:
    """Распределяет банкролл для гарантированной прибыли при surebet.

    Возвращает список ставок [stake_1, stake_2, ...] в тех же единицах.
    Каждая ставка: stake_i = bankroll × (1/D_i) / Σ(1/D_j)
    """
    if arb_percentage(dec_odds_list) <= 0:
        return []
    implied = [1 / d for d in dec_odds_list]
    total = sum(implied)
    return [round(bankroll * imp / total, 2) for imp in implied]


def find_arb_in_group(grp: pd.DataFrame, has_draw: bool) -> dict | None:
    """Ищет surebet в группе строк одного матча.

    Берёт лучший коэффициент на каждый исход у любого букмекера.
    Возвращает dict с результатом или None если вилки нет.
    """
    best = {}  # outcome_name → (best_dec, best_bm, best_am)

    for _, row in grp.iterrows():
        h_am = row.get("Odds Хозяева (Am)")
        a_am = row.get("Odds Гости (Am)")
        if h_am is None or a_am is None:
            continue
        try:
            outcomes = [
                (row["Хозяева"], float(h_am)),
                (row["Гости"],   float(a_am)),
            ]
            d_am = row.get("Odds Ничья (Am)")
            if has_draw and d_am and str(d_am) != "nan":
                outcomes.append(("Ничья", float(d_am)))

            for name, am in outcomes:
                dec = american_to_decimal(am)
                bm  = row["Букмекер"]
                if name not in best or dec > best[name][0]:
                    best[name] = (dec, bm, fmt_am(am))
        except Exception:
            continue

    if len(best) < 2:
        return None

    dec_list = [v[0] for v in best.values()]
    arb_pct  = arb_percentage(dec_list)

    if arb_pct <= 0:
        return None

    return {
        "arb_pct":  round(arb_pct * 100, 3),
        "outcomes": {
            name: {"dec": v[0], "bm": v[1], "am": v[2]}
            for name, v in best.items()
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
#  4. SHARP BOOKS — CROSS-BOOK EV
# ─────────────────────────────────────────────────────────────────────────────

def sharp_books_in_group(grp: pd.DataFrame) -> set:
    """Возвращает множество шарп-букмекеров присутствующих в группе."""
    present = {str(bm).lower() for bm in grp["Букмекер"].unique()}
    return present & SHARP_BOOKS


def get_sharp_reference_probs(grp: pd.DataFrame, has_draw: bool) -> list | None:
    """Возвращает no-vig fair probabilities из шарп-книги или None.

    Приоритет: Pinnacle > другие шарп > None.
    Возвращает [p_home, p_away] или [p_home, p_away, p_draw].
    """
    sharp_in_grp = sharp_books_in_group(grp)
    if not sharp_in_grp:
        return None

    # Выбираем наиболее приоритетную шарп-книгу
    priority = ["pinnacle", "pinnaclesports", "bookmaker", "bookmaker.eu",
                "betfair", "circa", "matchbook"]
    chosen_bm = None
    for p in priority:
        if p in sharp_in_grp:
            chosen_bm = p
            break
    if chosen_bm is None:
        chosen_bm = next(iter(sharp_in_grp))

    # Находим строку этого букмекера
    sharp_rows = grp[grp["Букмекер"].str.lower() == chosen_bm]
    if sharp_rows.empty:
        return None

    row = sharp_rows.iloc[0]
    h_am = row.get("Odds Хозяева (Am)")
    a_am = row.get("Odds Гости (Am)")
    if h_am is None or a_am is None or str(h_am) == "nan" or str(a_am) == "nan":
        return None

    try:
        h_impl = decimal_to_implied(american_to_decimal(float(h_am)))
        a_impl = decimal_to_implied(american_to_decimal(float(a_am)))
        d_am = row.get("Odds Ничья (Am)")
        if has_draw and d_am and str(d_am) != "nan":
            d_impl = decimal_to_implied(american_to_decimal(float(d_am)))
            return no_vig_prob([h_impl, a_impl, d_impl])
        return no_vig_prob([h_impl, a_impl])
    except Exception:
        return None


def cross_book_sharp_ev(fair_prob_pct: float, dec_odds: float) -> float:
    """EV рассчитанный относительно шарп-reference fair probability.

    Возвращает EV в процентах (умножен на 100).
    Идентичен ev_edge() × 100, но подчёркивает что fair_prob — из шарп-книги.
    """
    return round(ev_edge(fair_prob_pct, dec_odds) * 100, 4)


def consensus_sharp_prob(grp: pd.DataFrame, has_draw: bool) -> list | None:
    """Средневзвешенный консенсус fair probability по всем книгам.

    Каждая книга = равный вес. Используется когда нет шарп-букмекера.
    Возвращает [p_home, p_away] или [p_home, p_away, p_draw] в %.
    """
    h_impls, a_impls, d_impls = [], [], []
    for _, row in grp.iterrows():
        h_am = row.get("Odds Хозяева (Am)")
        a_am = row.get("Odds Гости (Am)")
        if h_am is None or a_am is None or str(h_am) == "nan" or str(a_am) == "nan":
            continue
        try:
            h_impls.append(decimal_to_implied(american_to_decimal(float(h_am))))
            a_impls.append(decimal_to_implied(american_to_decimal(float(a_am))))
            d_am = row.get("Odds Ничья (Am)")
            if has_draw and d_am and str(d_am) != "nan":
                d_impls.append(decimal_to_implied(american_to_decimal(float(d_am))))
        except Exception:
            continue

    if not h_impls:
        return None
    avg_h = sum(h_impls) / len(h_impls)
    avg_a = sum(a_impls) / len(a_impls)
    if has_draw and d_impls:
        avg_d = sum(d_impls) / len(d_impls)
        return no_vig_prob([avg_h, avg_a, avg_d])
    return no_vig_prob([avg_h, avg_a])


def get_fair_probs(grp: pd.DataFrame, has_draw: bool) -> list | None:
    """Возвращает fair probabilities: шарп-reference если есть, иначе консенсус."""
    sharp = get_sharp_reference_probs(grp, has_draw)
    if sharp is not None:
        return sharp
    return consensus_sharp_prob(grp, has_draw)


# ─────────────────────────────────────────────────────────────────────────────
#  5. СПОРТИВНЫЕ ПОРОГИ EV
# ─────────────────────────────────────────────────────────────────────────────

# Минимальный EV для включения в сигналы по виду спорта
SPORT_EV_THRESHOLDS = {
    # NFL: vig ~4-5%, нужен EV ≥ 3% чтобы перекрыть
    "nfl":        3.0,
    "americanfootball_nfl": 3.0,
    # NBA: vig ~4%, тоталы самые дырявые → ≥ 2%
    "nba":        2.0,
    "basketball_nba": 2.0,
    # Soccer: vig ~5-6% у soft books, ≥ 4%
    "soccer":     4.0,
    "epl":        4.0,
    "soccer_epl": 4.0,
    "laliga":     4.0,
    "bundesliga": 4.0,
    "seriea":     4.0,
    "ligue1":     4.0,
    "ucl":        3.5,   # Лига чемпионов — более ликвидный рынок
    "mls":        5.0,   # MLS — менее ликвидный
    # Дефолт
    "default":    DEFAULT_EV_THRESHOLD,
}


def sport_ev_threshold(sport_key: str) -> float:
    """Возвращает минимальный EV-порог (%) для данного вида спорта."""
    key = sport_key.lower().strip().replace(" ", "").replace("-", "")
    for k, v in SPORT_EV_THRESHOLDS.items():
        if k.replace("-", "").replace("_", "") in key or key in k.replace("-", "").replace("_", ""):
            return v
    return SPORT_EV_THRESHOLDS["default"]


# ─────────────────────────────────────────────────────────────────────────────
#  6. РАСШИРЕННАЯ ФОРМУЛА УВЕРЕННОСТИ
# ─────────────────────────────────────────────────────────────────────────────

def confidence_score_v2(
    avg_ev_pct: float,
    max_ev_pct: float,
    consensus_pct: float,     # % книг с EV > 0 на этот исход
    n_books: int,             # число уникальных книг в матче
    has_sharp: bool,          # есть ли шарп-букмекер в группе
    fair_prob_pct: float,     # no-vig fair probability выбранного исхода
    sport_threshold: float = 2.0,
) -> int:
    """Расширенная формула уверенности (0–100).

    Компоненты:
      • EV-компонент    : avg_ev × 3 + max_ev × 2 (max 40 pts)
      • Консенсус       : consensus_pct × 0.30    (max 30 pts)
      • Книжный бонус   : log2(n_books+1) × 4     (max ~16 pts за 16 книг)
      • Шарп-бонус      : +15 если есть шарп-reference
      • Fair prob bonus : min(max(fair_prob-33, 0), 15) (max 15 pts)
      • Sport threshold : −5 если EV не превышает порог вида спорта

    Итог клиппируется в [0, 100].
    """
    # EV-компонент (avg и max взвешены)
    ev_component = max(avg_ev_pct, 0) * 3 + max(max_ev_pct, 0) * 2
    ev_component = min(ev_component, 40)

    # Консенсус
    consensus_component = min(consensus_pct * 0.30, 30)

    # Логарифмический бонус за число книг
    book_bonus = min(math.log2(n_books + 1) * 4, 16)

    # Шарп-бонус
    sharp_bonus = 15 if has_sharp else 0

    # Fair probability bonus (выше вероятность → чуть меньше ценности, но выше надёжность)
    # Для фаворитов (>60%) и явных аутсайдеров (<30%) бонус ниже
    fp = fair_prob_pct
    if fp >= 30 and fp <= 70:
        fp_bonus = min(fp - 33, 15)
    else:
        fp_bonus = 0

    # Штраф если EV < спортивного порога
    threshold_penalty = -5 if avg_ev_pct < sport_threshold else 0

    raw = ev_component + consensus_component + book_bonus + sharp_bonus + fp_bonus + threshold_penalty
    return max(0, min(100, int(raw)))


# ─────────────────────────────────────────────────────────────────────────────
#  7. BUILD BETTING SIGNALS (cross-book)
# ─────────────────────────────────────────────────────────────────────────────

def build_betting_signals(
    df: pd.DataFrame,
    has_draw: bool,
    sport_key: str = "default",
) -> pd.DataFrame:
    """Для каждого матча выдаёт лучший сигнал — на кого ставить.

    УЛУЧШЕНИЯ vs v1:
    - Если в группе есть Pinnacle/шарп → fair prob из них (cross-book EV)
    - Если нет → средневзвешенный консенсус всех книг
    - confidence_score_v2: учитывает sharp_bonus, book_count, sport_threshold
    - Kelly Fraction для рекомендуемого размера ставки

    Колонки результата:
      Матч, Время, Сигнал, На кого ставить, Лучший букмекер, Odds (Am),
      Odds (Dec), EV Edge %, No-Vig Fair %, Консенсус книг, Уверенность,
      Kelly ¼ %, Другие исходы, _conf, _edge
    """
    signals = []
    sport_threshold = sport_ev_threshold(sport_key)

    if df.empty or "Матч" not in df.columns:
        return pd.DataFrame()

    for match, grp in df.groupby("Матч"):
        home      = grp["Хозяева"].iloc[0]
        away      = grp["Гости"].iloc[0]
        time_str  = grp["Время"].iloc[0]
        has_sharp = bool(sharp_books_in_group(grp))

        # Fair probs: шарп-reference или консенсус
        fair_probs = get_fair_probs(grp, has_draw)
        if fair_probs is None:
            continue

        # Раскладываем fair_probs по именам исходов
        if has_draw and len(fair_probs) == 3:
            outcome_names  = [home, away, "Ничья"]
            outcome_fairs  = {n: p for n, p in zip(outcome_names, fair_probs)}
        else:
            outcome_names  = [home, away]
            outcome_fairs  = {n: p for n, p in zip([home, away], fair_probs[:2])}

        total_bm_count = len(grp["Букмекер"].unique())
        outcome_data   = {n: [] for n in outcome_names}

        for _, row in grp.iterrows():
            h_am = row.get("Odds Хозяева (Am)")
            a_am = row.get("Odds Гости (Am)")
            if h_am is None or a_am is None or str(h_am) == "nan" or str(a_am) == "nan":
                continue
            try:
                h_dec = american_to_decimal(float(h_am))
                a_dec = american_to_decimal(float(a_am))
                bm    = row["Букмекер"]

                pairs = [
                    (home, h_dec, fmt_am(h_am)),
                    (away, a_dec, fmt_am(a_am)),
                ]
                d_am = row.get("Odds Ничья (Am)")
                if has_draw and d_am and str(d_am) != "nan":
                    d_dec = american_to_decimal(float(d_am))
                    pairs.append(("Ничья", d_dec, fmt_am(d_am)))

                for name, dec, am_str in pairs:
                    if name not in outcome_fairs:
                        continue
                    fair = outcome_fairs[name]
                    edge = cross_book_sharp_ev(fair, dec)  # % already ×100
                    outcome_data[name].append({
                        "dec": dec, "fair": fair,
                        "edge": edge, "bm": bm, "am": am_str,
                    })
            except Exception:
                continue

        if not any(outcome_data.values()):
            continue

        best_outcome = None
        best_edge    = -999.0
        outcome_stats = {}

        for name, entries in outcome_data.items():
            if not entries:
                continue
            edges    = [e["edge"] for e in entries]
            decs     = [e["dec"]  for e in entries]
            positive = [e for e in entries if e["edge"] > 0]
            avg_edge = round(sum(edges) / len(edges), 4)
            max_edge = round(max(edges), 4)
            fair     = outcome_fairs.get(name, 50.0)
            best_dec = max(decs)
            best_bm  = next(e["bm"] for e in entries if e["dec"] == best_dec)
            best_am  = next(e["am"] for e in entries if e["dec"] == best_dec)
            consensus_pct = round(len(positive) / total_bm_count * 100)

            conf = confidence_score_v2(
                avg_ev_pct=avg_edge,
                max_ev_pct=max_edge,
                consensus_pct=consensus_pct,
                n_books=total_bm_count,
                has_sharp=has_sharp,
                fair_prob_pct=fair,
                sport_threshold=sport_threshold,
            )
            kf = kelly_fraction(fair, best_dec, fraction=0.25)

            outcome_stats[name] = {
                "avg_edge": avg_edge, "max_edge": max_edge,
                "fair": fair, "best_dec": best_dec,
                "best_bm": best_bm, "best_am": best_am,
                "consensus_pct": consensus_pct,
                "confidence": conf,
                "kelly_pct": round(kf * 100, 2),
                "books_count": len(entries),
            }
            if max_edge > best_edge:
                best_edge    = max_edge
                best_outcome = name

        if best_outcome is None:
            continue

        bs = outcome_stats[best_outcome]

        if bs["confidence"] >= 70:
            signal_emoji, signal_text = "🟢", "СИЛЬНЫЙ"
        elif bs["confidence"] >= 40:
            signal_emoji, signal_text = "🟡", "УМЕРЕННЫЙ"
        elif bs["avg_edge"] > 0:
            signal_emoji, signal_text = "🔵", "СЛАБЫЙ"
        else:
            signal_emoji, signal_text = "⚪", "НЕТ"

        # Sharp marker
        sharp_marker = "⚡ " if has_sharp else ""

        other_outcomes = [
            f"{n}: EV {s['avg_edge']:+.1f}% / fair {s['fair']:.0f}%"
            for n, s in outcome_stats.items() if n != best_outcome
        ]

        signals.append({
            "Матч":             match,
            "Время":            time_str,
            "Сигнал":           f"{signal_emoji} {signal_text}",
            "На кого ставить":  best_outcome,
            "Лучший букмекер":  bs["best_bm"],
            "Odds (Am)":        bs["best_am"],
            "Odds (Dec)":       bs["best_dec"],
            "EV Edge %":        f"{bs['max_edge']:+.2f}%",
            "No-Vig Fair %":    f"{bs['fair']:.1f}%",
            "Консенсус книг":   f"{bs['consensus_pct']}%  ({bs['books_count']}/{total_bm_count})",
            "Уверенность":      bs["confidence"],
            "Kelly ¼ %":        f"{bs['kelly_pct']:.2f}%",
            "Sharp Reference":  sharp_marker + ("✓" if has_sharp else "Консенсус"),
            "Другие исходы":    " | ".join(other_outcomes),
            "_conf":            bs["confidence"],
            "_edge":            bs["max_edge"],
        })

    if not signals:
        return pd.DataFrame()
    return pd.DataFrame(signals).sort_values(
        ["_conf", "_edge"], ascending=False
    ).reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
#  8. COMPUTE VALUE BETS (cross-book)
# ─────────────────────────────────────────────────────────────────────────────

def compute_value_bets(
    df: pd.DataFrame,
    has_draw: bool,
    min_edge_pct: float,
    sport_key: str = "default",
    bankroll: float = 1000.0,
) -> pd.DataFrame:
    """Находит value bets с cross-book EV (Pinnacle/sharp как reference).

    УЛУЧШЕНИЯ vs v1:
    - fair_prob из шарп-книги или консенсуса (не per-row)
    - Добавлены колонки Kelly Stake и Kelly %
    - Добавлена колонка Sharp Reference

    Фильтрация: edge >= min_edge_pct (в процентах).
    """
    if df.empty or "Матч" not in df.columns:
        return pd.DataFrame()

    rows = []
    for match, grp in df.groupby("Матч"):
        has_sharp  = bool(sharp_books_in_group(grp))
        fair_probs = get_fair_probs(grp, has_draw)
        if fair_probs is None:
            continue

        home = grp["Хозяева"].iloc[0]
        away = grp["Гости"].iloc[0]

        if has_draw and len(fair_probs) == 3:
            outcome_fairs = {home: fair_probs[0], away: fair_probs[1], "Ничья": fair_probs[2]}
        else:
            outcome_fairs = {home: fair_probs[0], away: fair_probs[1]}

        time_str = grp["Время"].iloc[0]
        sharp_label = "⚡ Pinnacle" if has_sharp else "Консенсус"

        for _, r in grp.iterrows():
            h_am = r.get("Odds Хозяева (Am)")
            a_am = r.get("Odds Гости (Am)")
            if h_am is None or a_am is None or str(h_am) == "nan" or str(a_am) == "nan":
                continue
            try:
                pairs = [
                    (home, float(h_am)),
                    (away, float(a_am)),
                ]
                d_am = r.get("Odds Ничья (Am)")
                if has_draw and d_am and str(d_am) != "nan":
                    pairs.append(("Ничья", float(d_am)))

                for name, am in pairs:
                    if name not in outcome_fairs:
                        continue
                    dec  = american_to_decimal(am)
                    fair = outcome_fairs[name]
                    impl = decimal_to_implied(dec)
                    edge = cross_book_sharp_ev(fair, dec)  # уже в %

                    if edge >= min_edge_pct:
                        kf    = kelly_fraction(fair, dec, fraction=0.25)
                        stake = kelly_stake(bankroll, fair, dec, fraction=0.25)
                        rows.append({
                            "Матч":           match,
                            "Время":          time_str,
                            "Букмекер":       r["Букмекер"],
                            "Исход":          f"✅ {name}",
                            "Odds (Am)":      fmt_am(am),
                            "Odds (Dec)":     dec,
                            "Implied %":      f"{impl:.2f}%",
                            "No-Vig Fair %":  f"{fair:.2f}%",
                            "EV Edge %":      f"+{edge:.2f}%",
                            "Kelly ¼ %":      f"{kf*100:.2f}%",
                            f"Kelly Stake ({int(bankroll)}$)": f"{stake:.2f}$",
                            "Reference":      sharp_label,
                            "_edge":          edge,
                        })
            except Exception:
                continue

    if rows:
        vdf = pd.DataFrame(rows).sort_values("_edge", ascending=False).reset_index(drop=True)
        vdf.index += 1
        return vdf.drop(columns=["_edge"])
    return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
#  9. ESPN LIVE SCORES — чистые функции
# ─────────────────────────────────────────────────────────────────────────────

def parse_espn_event(event: dict, period_name: str = "Q") -> dict:
    """Парсит одно ESPN-событие в плоский словарь.

    Ключи результата:
      state, detail, clock, period, home_name, away_name,
      home_score, away_score, home_abbr, away_abbr,
      venue, city, note, status_str, period_name
    """
    comp    = event.get("competitions", [{}])[0]
    status  = comp.get("status", event.get("status", {}))
    st_type = status.get("type", {})
    state   = st_type.get("state", "pre")
    detail  = st_type.get("detail", "")
    clock   = status.get("displayClock", "")
    period  = status.get("period", 0)

    competitors = comp.get("competitors", [])
    home = next((c for c in competitors if c.get("homeAway") == "home"), {})
    away = next((c for c in competitors if c.get("homeAway") == "away"), {})

    home_name  = home.get("team", {}).get("displayName", "—")
    away_name  = away.get("team", {}).get("displayName", "—")
    home_score = home.get("score", "—")
    away_score = away.get("score", "—")
    home_abbr  = home.get("team", {}).get("abbreviation", "")
    away_abbr  = away.get("team", {}).get("abbreviation", "")

    venue = comp.get("venue", {}).get("fullName", "")
    city  = comp.get("venue", {}).get("address", {}).get("city", "")

    notes    = comp.get("notes", [])
    note_str = notes[0].get("headline", "") if notes else ""

    if state == "in":
        status_str = f"{clock}'" if period_name == "min" else f"{period_name}{period} · {clock}"
    elif state == "post":
        status_str = f"🏁 {detail}"
    else:
        status_str = f"📅 {detail}"

    return {
        "state": state, "detail": detail, "clock": clock, "period": period,
        "home_name": home_name, "away_name": away_name,
        "home_score": home_score, "away_score": away_score,
        "home_abbr": home_abbr, "away_abbr": away_abbr,
        "venue": venue, "city": city,
        "note": note_str, "status_str": status_str, "period_name": period_name,
    }


def fetch_scores_from_url(url: str, session=None) -> list:
    """Загружает события из ESPN scoreboard API.

    session — объект с .get() (requests.Session или mock).
    """
    import requests as _requests
    _session = session if session is not None else _requests
    try:
        r = _session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code == 200:
            return r.json().get("events", [])
    except Exception:
        pass
    return []


# ─────────────────────────────────────────────────────────────────────────────
#  10. HISTORICAL ODDS
# ─────────────────────────────────────────────────────────────────────────────

ODDS_BASE = "https://api.the-odds-api.com/v4"


def fetch_historical_odds(
    api_key: str,
    sport_key: str,
    regions: str,
    market_key: str,
    date_iso: str,
    session=None,
) -> tuple:
    """Fetch historical odds snapshot from The Odds API.

    Parameters
    ----------
    api_key : str
        The Odds API key.
    sport_key : str
        Sport key, e.g. ``"americanfootball_nfl"``.
    regions : str
        Comma-separated region codes, e.g. ``"us,eu"``.
    market_key : str
        Market type: ``"h2h"``, ``"spreads"``, or ``"totals"``.
    date_iso : str
        ISO-8601 timestamp for the snapshot, e.g. ``"2024-01-15T12:00:00Z"``.
    session : requests-like, optional
        Injectable HTTP session (for testing).

    Returns
    -------
    tuple
        ``(data_list | None, timestamp | None)`` where *data_list* is the
        list of event dicts and *timestamp* is the snapshot timestamp string
        returned by the API (or ``None`` on error).
    """
    import requests as _requests
    _session = session if session is not None else _requests

    try:
        r = _session.get(
            f"{ODDS_BASE}/historical/sports/{sport_key}/odds",
            params=dict(
                apiKey=api_key,
                regions=regions,
                markets=market_key,
                oddsFormat="american",
                dateFormat="iso",
                date=date_iso,
            ),
            timeout=15,
        )
        if r.status_code == 200:
            body = r.json()
            return body.get("data", []), body.get("timestamp", date_iso)
        return None, None
    except Exception:
        return None, None


def parse_historical_to_df(events: list, market_key: str, has_draw: bool) -> pd.DataFrame:
    """Convert historical odds events into a flat DataFrame.

    The schema intentionally mirrors ``parse_to_df`` in *app.py* so that
    existing display helpers and value-bet logic can be reused.

    Parameters
    ----------
    events : list
        List of event dicts from :func:`fetch_historical_odds`.
    market_key : str
        ``"h2h"``, ``"spreads"``, or ``"totals"``.
    has_draw : bool
        Whether a draw outcome is expected (e.g. soccer leagues).

    Returns
    -------
    pd.DataFrame
    """
    rows: list[dict] = []
    for ev in events:
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")
        commence = ev.get("commence_time", "")
        for bm in ev.get("bookmakers", []):
            for mkt in bm.get("markets", []):
                if mkt["key"] != market_key:
                    continue
                oc = {o["name"]: o for o in mkt["outcomes"]}
                base = {
                    "Матч": f"{away} @ {home}",
                    "Время": commence,
                    "Букмекер": bm.get("title", bm["key"]),
                    "Хозяева": home,
                    "Гости": away,
                    "_event_id": ev.get("id", ""),
                }
                if market_key == "h2h":
                    row = {
                        **base,
                        "Odds Хозяева (Am)": oc.get(home, {}).get("price"),
                        "Odds Гости (Am)": oc.get(away, {}).get("price"),
                        "Odds Ничья (Am)": oc.get("Draw", {}).get("price") if has_draw else None,
                    }
                elif market_key == "spreads":
                    ho, ao = oc.get(home, {}), oc.get(away, {})
                    row = {
                        **base,
                        "Спред Хозяева": ho.get("point"),
                        "Odds Хозяева (Am)": ho.get("price"),
                        "Спред Гости": ao.get("point"),
                        "Odds Гости (Am)": ao.get("price"),
                    }
                elif market_key == "totals":
                    ov = next((o for o in mkt["outcomes"] if o["name"] == "Over"), {})
                    un = next((o for o in mkt["outcomes"] if o["name"] == "Under"), {})
                    row = {
                        **base,
                        "Тотал Линия": ov.get("point"),
                        "Odds Over (Am)": ov.get("price"),
                        "Odds Under (Am)": un.get("price"),
                    }
                else:
                    continue
                rows.append(row)
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────────────────────
#  11. TEST HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def make_h2h_row(match, home, away, bm, h_am, a_am,
                 d_am=None, time="15.04 12:00 МСК"):
    """Создаёт одну строку DataFrame в формате parse_to_df (h2h market)."""
    return {
        "Матч":               match,
        "Хозяева":            home,
        "Гости":              away,
        "Букмекер":           bm,
        "Время":              time,
        "Odds Хозяева (Am)":  h_am,
        "Odds Гости (Am)":    a_am,
        "Odds Ничья (Am)":    d_am,
    }
