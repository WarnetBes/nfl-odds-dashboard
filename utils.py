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
    # Bayesian shrinkage: регрессия к 50% при малом числе книг — устраняет переуверенность
    fp = bayesian_shrink_prob(fair_prob_pct, n_books)
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
#  10. TEST HELPERS
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


# ─────────────────────────────────────────────────────────────────────────────
#  11. ELO RATING — независимая оценка силы команд
# ─────────────────────────────────────────────────────────────────────────────

ELO_INITIAL = 1500.0
ELO_K = {
    "americanfootball_nfl": 20.0,
    "soccer_epl":           20.0,
    "basketball_nba":       15.0,
    "default":              20.0,
}
ELO_HOME_ADV = {
    "americanfootball_nfl": 65.0,
    "soccer_epl":           60.0,
    "basketball_nba":       100.0,
    "default":              65.0,
}


def elo_expected_prob(r_home: float, r_away: float, sport_key: str = "default") -> float:
    """Вероятность победы хозяев по Elo (с учётом home advantage)."""
    h = ELO_HOME_ADV.get(sport_key, ELO_HOME_ADV["default"])
    return round(1 / (1 + 10 ** ((r_away - (r_home + h)) / 400)), 6)


def elo_update_pair(
    r_home: float, r_away: float, home_win: bool, sport_key: str = "default"
) -> tuple:
    """Обновляет Elo после матча. Возвращает (new_home_rating, new_away_rating)."""
    k = ELO_K.get(sport_key, ELO_K["default"])
    exp_home = elo_expected_prob(r_home, r_away, sport_key)
    s_home = 1.0 if home_win else 0.0
    s_away = 1.0 - s_home
    new_home = r_home + k * (s_home - exp_home)
    new_away = r_away + k * (s_away - (1.0 - exp_home))
    return round(new_home, 3), round(new_away, 3)


def elo_edge_vs_market(elo_home_prob: float, market_home_prob_pct: float) -> float:
    """
    Разница между Elo-вероятностью и рыночной implied probability (в пп).
    Положительное значение = Elo выше рынка → потенциальная ценность.
    """
    return round((elo_home_prob - market_home_prob_pct / 100.0) * 100.0, 4)


# ─────────────────────────────────────────────────────────────────────────────
#  12. CLOSING LINE VALUE (CLV)
# ─────────────────────────────────────────────────────────────────────────────


def clv_pct(open_dec: float, close_dec: float) -> float:
    """
    CLV в процентных пунктах implied probability.
    Положительное значение = ставка по лучшей цене, чем closing line.
    """
    if open_dec <= 0 or close_dec <= 0:
        return 0.0
    return round((1 / open_dec - 1 / close_dec) * 100, 4)


def avg_clv_pct(values: list) -> float:
    """Средний CLV по списку значений."""
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


# ─────────────────────────────────────────────────────────────────────────────
#  13. BAYESIAN SHRINKAGE
# ─────────────────────────────────────────────────────────────────────────────


def bayesian_shrink_prob(fair_prob_pct: float, n_books: int, alpha: float = 3.0) -> float:
    """
    Регрессия вероятности к 50% при малом числе источников.
    alpha — сила априора (рекомендуется 3.0).
    """
    n = max(int(n_books), 0)
    w_prior = alpha / (alpha + n) if (alpha + n) > 0 else 1.0
    shrunk = fair_prob_pct * (1 - w_prior) + 50.0 * w_prior
    return round(shrunk, 4)


# ─────────────────────────────────────────────────────────────────────────────
#  14. MARKET EFFICIENCY SCORE
# ─────────────────────────────────────────────────────────────────────────────


def market_efficiency_score(dec_odds_list: list) -> float:
    """
    Насколько рынок согласован по одному исходу у разных букмекеров.
    100 = очень согласован, 0 = шумный / неустоявшийся.
    Основан на коэффициенте вариации decimal odds.
    """
    vals = [float(x) for x in dec_odds_list if x and float(x) > 0]
    if len(vals) < 2:
        return 50.0
    mean_val = sum(vals) / len(vals)
    if mean_val <= 0:
        return 0.0
    variance = sum((x - mean_val) ** 2 for x in vals) / len(vals)
    std = variance ** 0.5
    cv = std / mean_val
    score = max(0.0, 100.0 * (1.0 - 10.0 * cv))
    return round(score, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  15. SIMPLE RATING SYSTEM (SRS)
# ─────────────────────────────────────────────────────────────────────────────


def compute_srs(games: list, iterations: int = 12) -> dict:
    """
    Итерационный алгоритм SRS: оценивает силу команды в очках с поправкой
    на силу соперников.

    games = [
        {"home": "Chiefs", "away": "Bills", "home_score": 27, "away_score": 21},
        ...
    ]
    Возвращает dict {team_name: srs_rating}.
    """
    teams: set = set()
    for g in games:
        teams.add(g["home"])
        teams.add(g["away"])

    ratings = {team: 0.0 for team in teams}

    for _ in range(iterations):
        totals = {team: 0.0 for team in teams}
        counts = {team: 0 for team in teams}

        for g in games:
            home = g["home"]
            away = g["away"]
            margin = float(g["home_score"]) - float(g["away_score"])

            totals[home] += margin + ratings[away]
            totals[away] += -margin + ratings[home]
            counts[home] += 1
            counts[away] += 1

        for team in teams:
            ratings[team] = round(totals[team] / counts[team], 4) if counts[team] else 0.0

    return ratings


def srs_projected_spread(
    home_team: str,
    away_team: str,
    ratings: dict,
    home_adv_points: float = 2.5,
) -> float:
    """
    Прогноз спреда на основе SRS.
    Положительное значение = хозяева фавориты.
    """
    return round(
        ratings.get(home_team, 0.0) - ratings.get(away_team, 0.0) + home_adv_points,
        3,
    )


# ─────────────────────────────────────────────────────────────────────────────
#  16. POISSON TOTALS MODEL
# ─────────────────────────────────────────────────────────────────────────────


def poisson_pmf(lmbda: float, k: int) -> float:
    """P(X=k) для распределения Пуассона с параметром lmbda."""
    if lmbda <= 0 or k < 0:
        return 0.0
    return round((lmbda ** k) * math.exp(-lmbda) / math.factorial(k), 10)


def poisson_over_prob(lambda_home: float, lambda_away: float, total_line: float) -> float:
    """
    Вероятность Over total_line (в %) по модели Пуассона.
    Experimental model — для NFL использовать только как ориентир,
    т.к. распределение очков не идеально пуассоновское.
    """
    total_lambda = max(lambda_home, 0.0) + max(lambda_away, 0.0)
    cutoff = int(total_line)
    prob_under_or_equal = sum(poisson_pmf(total_lambda, k) for k in range(cutoff + 1))
    return round((1.0 - prob_under_or_equal) * 100.0, 4)


# ─────────────────────────────────────────────────────────────────────────────
#  17. COMPOSITE INDEPENDENT SCORE
# ─────────────────────────────────────────────────────────────────────────────


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def composite_independent_score(
    elo_edge_pct: float,
    ev_edge_pct: float,
    mes: float,
) -> float:
    """
    Итоговый независимый скор (0–100), объединяющий Elo, EV и MES.
    Использовать только как дополнительную колонку, не как замену Kelly/EV.

    Веса: Elo 45%, Market EV 35%, Market Inefficiency 20%.
    """
    elo_signal        = _clamp01(max(elo_edge_pct, 0.0) / 12.0)
    market_signal     = _clamp01(max(ev_edge_pct,  0.0) / 10.0)
    efficiency_signal = _clamp01((100.0 - mes)     / 100.0)
    score = 100.0 * (0.45 * elo_signal + 0.35 * market_signal + 0.20 * efficiency_signal)
    return round(score, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  18. MARGIN-OF-VICTORY ELO (Elo с поправкой на счёт)
# ─────────────────────────────────────────────────────────────────────────────

def mov_multiplier(score_diff: float) -> float:
    """
    Множитель Margin-of-Victory для Elo.
    Крупная победа обновляет рейтинг сильнее.
    M = ln(|MOV| + 1)
    """
    return round(math.log(abs(float(score_diff)) + 1.0), 6)


def elo_update_with_margin(
    rating: float,
    expected: float,
    score: float,
    score_diff: float,
    sport_key: str = "americanfootball_nfl",
) -> float:
    """
    Elo-обновление с поправкой на маржу победы.
    R' = R + K × M × (S − E)
    score: 1.0 — победа, 0.0 — поражение, 0.5 — ничья
    score_diff: разница очков (положительная для победителя)
    """
    k = ELO_K.get(sport_key, ELO_K["americanfootball_nfl"])
    m = mov_multiplier(score_diff)
    return round(rating + k * m * (score - expected), 3)


# ─────────────────────────────────────────────────────────────────────────────
#  19. РАСШИРЕННЫЙ CLV + POISSON HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def clv_from_american(open_am: float, close_am: float) -> float:
    """
    CLV из американских коэффициентов.
    CLV = (1/D_close − 1/D_open) × 100
    Положительный CLV → ты открыл ставку до того, как рынок сдвинулся в ту же сторону
    (закрывающий коэффициент хуже открывающего — beat the close).
    Пример: open=-110, close=-120 → CLV > 0 (рынок сдвинулся против тебя)
    """
    # american_to_decimal(0) = 1.0 — невалидно (нет выплаты), отсекаем
    if open_am == 0 or close_am == 0:
        return 0.0
    d_open  = american_to_decimal(open_am)
    d_close = american_to_decimal(close_am)
    if d_open <= 1.0 or d_close <= 1.0:
        return 0.0
    return round((1.0 / d_close - 1.0 / d_open) * 100.0, 4)


def poisson_total_under_prob(
    lambda_home: float, lambda_away: float, total_line: float
) -> float:
    """
    Вероятность Under total_line (в %) по модели Пуассона.
    Комплемент к poisson_over_prob.
    """
    return round(100.0 - poisson_over_prob(lambda_home, lambda_away, total_line), 4)


def lambda_from_stats(
    avg_gf: float,
    avg_ga: float,
    opp_avg_ga: float,
    opp_avg_gf: float,
    league_avg: float,
    home: bool = True,
) -> float:
    """
    Ожидаемые голы/очки команды по Dixon-Coles параметризации.
    λ = league_avg × Att_i × Def_j × HFA
    Att_i = avg_gf / league_avg,  Def_j = opp_avg_ga / league_avg
    HFA: 1.1 (хозяева) / 0.9 (гости)
    """
    if league_avg <= 0:
        return max(avg_gf, 0.1)
    att  = avg_gf      / league_avg
    def_ = opp_avg_ga  / league_avg
    hfa  = 1.1 if home else 0.9
    return round(league_avg * att * def_ * hfa, 4)


# ─────────────────────────────────────────────────────────────────────────────
#  20. КАЛИБРОВКА И ИСТОРИЧЕСКАЯ АНАЛИТИКА
# ─────────────────────────────────────────────────────────────────────────────

def clamp_0_100(x: float) -> float:
    """Зажать значение в [0, 100]. Публичный alias для _clamp01-based логики."""
    return max(0.0, min(100.0, float(x)))


def brier_score(prob_list: list, outcome_list: list) -> float:
    """
    Brier Score — метрика калибровки вероятностных предсказаний.
    BS = (1/N) × Σ (p_i − y_i)²
    Чем ближе к 0 — тем лучше. Случайная модель: 0.25.
    prob_list: предсказанные вероятности [0.0–1.0]
    outcome_list: фактические исходы [1 или 0]
    """
    if not prob_list or not outcome_list:
        return 0.0
    if len(prob_list) != len(outcome_list):
        return 0.0
    errors = [(float(p) - float(y)) ** 2 for p, y in zip(prob_list, outcome_list)]
    return round(sum(errors) / len(errors), 6)


def log_loss_score(prob_list: list, outcome_list: list, eps: float = 1e-7) -> float:
    """
    Log-Loss (кросс-энтропия) — строже Brier, штрафует за уверенные ошибки.
    LL = −(1/N) × Σ [y×ln(p) + (1−y)×ln(1−p)]
    Чем меньше — тем лучше.
    """
    if not prob_list or not outcome_list:
        return 0.0
    if len(prob_list) != len(outcome_list):
        return 0.0
    total = 0.0
    for p, y in zip(prob_list, outcome_list):
        p = max(eps, min(1.0 - eps, float(p)))
        y = float(y)
        total += y * math.log(p) + (1.0 - y) * math.log(1.0 - p)
    return round(-total / len(prob_list), 6)


def roi_percent(profits: list, stakes: list) -> float:
    """
    ROI по истории ставок.
    ROI = (Σ profit / Σ stake) × 100
    profits: список прибылей (отрицательные — проигрыш)
    stakes:  список размеров ставок (всегда положительные)
    """
    total_stake  = sum(float(s) for s in stakes)
    total_profit = sum(float(p) for p in profits)
    if total_stake <= 0:
        return 0.0
    return round((total_profit / total_stake) * 100.0, 4)


def yield_percent(profits: list, stakes: list) -> float:
    """Alias для roi_percent (европейская терминология)."""
    return roi_percent(profits, stakes)


def win_rate(outcomes: list) -> float:
    """
    Процент выигрышных ставок.
    outcomes: список [1, 0, 1, ...] (1 = win)
    """
    if not outcomes:
        return 0.0
    return round(sum(1 for o in outcomes if float(o) == 1.0) / len(outcomes) * 100.0, 2)


def expected_value_from_history(
    avg_odds_dec: float, win_rate_pct: float
) -> float:
    """
    Ожидаемое EV% на основе исторической win rate.
    EV = (p × (D−1) − (1−p)) × 100
    """
    p = win_rate_pct / 100.0
    return round((p * (avg_odds_dec - 1.0) - (1.0 - p)) * 100.0, 2)


# ─────────────────────────────────────────────────────────────────────────────
#  21. LINE MOVEMENT & STEAM DETECTION + PARLAY EV
# ─────────────────────────────────────────────────────────────────────────────

def detect_line_movement(
    snapshots: list,
    threshold_pct: float = 3.0,
) -> list:
    """
    Обнаруживает значительное движение линии по implied probability.
    snapshots: список dict {"ts": float, "bm": str, "home_dec": float, "away_dec": float}
    threshold_pct: минимальное движение в % implied для алерта.
    Возвращает список словарей с описанием движений.
    """
    if len(snapshots) < 2:
        return []
    alerts = []
    first = snapshots[0]
    last  = snapshots[-1]
    for outcome, key in [("Хозяева", "home_dec"), ("Гости", "away_dec")]:
        v0 = float(first.get(key, 0) or 0)
        v1 = float(last.get(key, 0) or 0)
        if v0 <= 1.0 or v1 <= 1.0:
            continue
        move = (1.0 / v1 - 1.0 / v0) * 100.0
        if abs(move) >= threshold_pct:
            direction = "⬆️ Рост implied" if move > 0 else "⬇️ Падение implied"
            alerts.append({
                "outcome":      outcome,
                "move_pct":     round(move, 2),
                "direction":    direction,
                "from_dec":     round(v0, 4),
                "to_dec":       round(v1, 4),
                "n_snapshots":  len(snapshots),
            })
    return alerts


def detect_steam_move(
    snapshots_by_bm: dict,
    time_window_sec: float = 120.0,
    min_books_moved: int = 3,
    threshold_implied_pct: float = 1.5,
) -> bool:
    """
    Steam move — синхронное движение у N+ букмекеров в одну сторону.
    snapshots_by_bm: {"Pinnacle": [{"ts": unix, "home_dec": 2.1, ...}, ...], ...}
    Возвращает True если detected.
    """
    if not snapshots_by_bm:
        return False
    all_last_ts = [s[-1]["ts"] for s in snapshots_by_bm.values() if s]
    if not all_last_ts:
        return False
    now = max(all_last_ts)
    direction_counts = {"up": 0, "down": 0}
    for bm, snaps in snapshots_by_bm.items():
        recent = [s for s in snaps if now - float(s.get("ts", 0)) <= time_window_sec]
        if len(recent) < 2:
            continue
        v0 = float(recent[0].get("home_dec", 0) or 0)
        v1 = float(recent[-1].get("home_dec", 0) or 0)
        if v0 <= 1.0 or v1 <= 1.0:
            continue
        move = (1.0 / v1 - 1.0 / v0) * 100.0
        if move > threshold_implied_pct:
            direction_counts["up"] += 1
        elif move < -threshold_implied_pct:
            direction_counts["down"] += 1
    return max(direction_counts.values()) >= min_books_moved


def parlay_ev(legs: list) -> float:
    """
    EV многоногового парлея.
    legs = [{"fair_prob_pct": 55.0, "dec_odds": 2.10}, ...]
    EV_parlay = (Π fair_prob_i) × (Π dec_odds_i) − 1
    Положительное значение → положительный ожидаемый исход.
    """
    if not legs:
        return 0.0
    prob_product = 1.0
    odds_product = 1.0
    for leg in legs:
        p = float(leg.get("fair_prob_pct", 50.0)) / 100.0
        d = float(leg.get("dec_odds", 2.0))
        if p <= 0 or d <= 1.0:
            return 0.0
        prob_product *= p
        odds_product *= d
    return round(prob_product * odds_product - 1.0, 6)


def parlay_kelly_stake(
    legs: list,
    bankroll: float,
    fraction: float = 0.25,
) -> float:
    """
    Kelly stake для парлея.
    f* = fraction × ((p × D − 1) / (D − 1))
    где p = prob_product, D = odds_product.
    """
    if not legs or bankroll <= 0:
        return 0.0
    p = 1.0
    d = 1.0
    for leg in legs:
        p *= float(leg.get("fair_prob_pct", 50.0)) / 100.0
        d *= float(leg.get("dec_odds", 2.0))
    if d <= 1.0:
        return 0.0
    f_raw = (p * d - 1.0) / (d - 1.0)
    return round(max(0.0, fraction * f_raw * bankroll), 2)
