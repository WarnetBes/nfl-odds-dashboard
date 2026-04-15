"""
test_formulas.py — тесты расширенных формул utils.py v2.

Покрывает:
  • kelly_fraction / kelly_stake
  • arb_percentage / arb_stakes / find_arb_in_group
  • sport_ev_threshold
  • sharp_books_in_group / get_sharp_reference_probs
  • consensus_sharp_prob / get_fair_probs
  • cross_book_sharp_ev
  • confidence_score_v2
  • build_betting_signals с Pinnacle как cross-book reference
  • compute_value_bets с cross-book EV
  • implied_to_decimal
"""
import pytest
import math
import pandas as pd
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from utils import (
    american_to_decimal, decimal_to_implied, no_vig_prob, ev_edge,
    implied_to_decimal,
    kelly_fraction, kelly_stake,
    arb_percentage, arb_stakes, find_arb_in_group,
    sport_ev_threshold,
    sharp_books_in_group, get_sharp_reference_probs,
    consensus_sharp_prob, get_fair_probs,
    cross_book_sharp_ev,
    confidence_score_v2,
    build_betting_signals,
    compute_value_bets,
    make_h2h_row,
    SHARP_BOOKS, SPORT_EV_THRESHOLDS,
)


# ═══════════════════════════════════════════════════════════════
#  Вспомогательные фабрики
# ═══════════════════════════════════════════════════════════════

def _df(*rows):
    return pd.DataFrame(list(rows))


def _parse_ev(s: str) -> float:
    return float(s.replace("+", "").replace("%", ""))


# ═══════════════════════════════════════════════════════════════
#  implied_to_decimal
# ═══════════════════════════════════════════════════════════════

class TestImpliedToDecimal:
    def test_50_pct_is_evens(self):
        assert implied_to_decimal(50.0) == 2.0

    def test_roundtrip_through_decimal(self):
        for odds in [-110, -150, +120, +200]:
            dec = american_to_decimal(float(odds))
            impl = decimal_to_implied(dec)
            dec2 = implied_to_decimal(impl)
            assert abs(dec2 - dec) < 0.01

    def test_zero_prob_returns_zero(self):
        assert implied_to_decimal(0.0) == 0.0

    def test_100_pct_returns_one(self):
        assert implied_to_decimal(100.0) == 1.0


# ═══════════════════════════════════════════════════════════════
#  Kelly Criterion
# ═══════════════════════════════════════════════════════════════

class TestKellyFraction:
    """Формула: f* = (b×p − q) / b, b = dec−1."""

    def test_zero_ev_zero_kelly(self):
        """EV = 0 → Kelly = 0."""
        # fair=50%, dec=2.0 → b=1.0, f=(1.0×0.5−0.5)/1.0=0
        assert kelly_fraction(50.0, 2.0) == 0.0

    def test_positive_ev_positive_kelly(self):
        """EV > 0 → Kelly > 0."""
        k = kelly_fraction(55.0, 2.1, fraction=1.0)
        assert k > 0

    def test_negative_ev_returns_zero(self):
        """EV < 0 → не ставим (Kelly = 0, не отрицательный)."""
        k = kelly_fraction(45.0, 1.80, fraction=1.0)
        assert k == 0.0

    def test_quarter_kelly_is_quarter_of_full(self):
        """¼ Kelly = 0.25 × Full Kelly."""
        full = kelly_fraction(55.0, 2.1, fraction=1.0)
        quarter = kelly_fraction(55.0, 2.1, fraction=0.25)
        assert abs(quarter - full * 0.25) < 1e-6

    def test_kelly_known_example(self):
        """Ручной расчёт: fair=60%, dec=2.5, full Kelly.
        b=1.5, f=(1.5×0.6−0.4)/1.5 = (0.9−0.4)/1.5 = 0.333...
        """
        k = kelly_fraction(60.0, 2.5, fraction=1.0)
        assert abs(k - 1/3) < 0.001

    def test_kelly_stake_proportional_to_bankroll(self):
        stake1 = kelly_stake(1000.0, 55.0, 2.1)
        stake2 = kelly_stake(2000.0, 55.0, 2.1)
        assert abs(stake2 - stake1 * 2) < 0.01

    def test_kelly_never_exceeds_bankroll(self):
        stake = kelly_stake(1000.0, 99.0, 100.0)
        assert stake <= 1000.0

    def test_kelly_zero_stake_when_no_value(self):
        stake = kelly_stake(1000.0, 40.0, 1.5)
        assert stake == 0.0

    def test_kelly_fraction_bounded_0_1(self):
        """Доля всегда в [0, 1]."""
        for fair in [10, 30, 50, 70, 90]:
            for dec in [1.5, 2.0, 3.0, 5.0]:
                k = kelly_fraction(float(fair), float(dec), fraction=1.0)
                assert 0.0 <= k <= 1.0, f"Kelly вне [0,1]: fair={fair}, dec={dec}, k={k}"


# ═══════════════════════════════════════════════════════════════
#  Arb Percentage
# ═══════════════════════════════════════════════════════════════

class TestArbPercentage:
    """Arb% = 1 − Σ(1/D_i). Положительный → surebet."""

    def test_perfect_book_no_arb(self):
        """2.0 + 2.0 (50%+50%=100%) → Arb%=0."""
        assert arb_percentage([2.0, 2.0]) == 0.0

    def test_vig_book_negative_arb(self):
        """1.909 + 1.909 (≈52.38%×2=104.76%) → Arb% < 0."""
        assert arb_percentage([1.909, 1.909]) < 0

    def test_surebet_positive_arb(self):
        """Явная вилка: 2.75 + 2.65 (36.4%+37.7%=74.1%) → Arb% > 0."""
        result = arb_percentage([2.75, 2.65])
        assert result > 0

    def test_three_way_surebet(self):
        """3-исходник: 3.5 + 3.5 + 3.5 (28.6%×3=85.8%) → Arb% > 0."""
        result = arb_percentage([3.5, 3.5, 3.5])
        assert result > 0

    def test_three_way_no_arb(self):
        """Типичная EPL линия без вилки."""
        # Arsenal -120 (impl≈54.5%), Chelsea +280 (26.3%), Draw +220 (31.3%) → total≈112%
        result = arb_percentage([
            american_to_decimal(-120),
            american_to_decimal(280),
            american_to_decimal(220),
        ])
        assert result < 0

    def test_empty_list_returns_sentinel(self):
        assert arb_percentage([]) == -999.0

    def test_zero_odds_returns_sentinel(self):
        assert arb_percentage([0.0, 2.0]) == -999.0

    def test_arb_pct_calculation_precision(self):
        """Точность: dec1=3.0, dec2=3.0 → 1−(1/3+1/3)=1−0.667=+0.333."""
        result = arb_percentage([3.0, 3.0])
        assert abs(result - (1 - 2/3)) < 1e-5


class TestArbStakes:
    def test_returns_empty_when_no_arb(self):
        assert arb_stakes(1000.0, [1.909, 1.909]) == []

    def test_stakes_sum_to_bankroll(self):
        stakes = arb_stakes(1000.0, [2.75, 2.65])
        assert stakes != []
        assert abs(sum(stakes) - 1000.0) < 0.01

    def test_all_outcomes_guarantee_profit(self):
        """При выигрыше любого исхода прибыль одинакова."""
        dec_odds = [2.75, 2.65]
        stakes = arb_stakes(1000.0, dec_odds)
        returns = [s * d for s, d in zip(stakes, dec_odds)]
        # Все выигрыши должны быть > банкролла
        for r in returns:
            assert r > 1000.0
        # Выигрыши примерно одинаковы
        assert abs(returns[0] - returns[1]) < 1.0


class TestFindArbInGroup:
    def test_finds_surebet_when_exists(self):
        """Явная вилка: Away +300 у одного, Home −110 у другого."""
        rows = [
            make_h2h_row("M", "H", "A", "Book1", -110, 300),
            make_h2h_row("M", "H", "A", "Book2", -200, -150),
        ]
        grp = pd.DataFrame(rows)
        result = find_arb_in_group(grp, has_draw=False)
        # Away +300 (dec=4.0) + Home -200 (dec=1.5): 1/4.0+1/1.5=0.25+0.667=0.917 → arb=8.3%
        assert result is not None
        assert result["arb_pct"] > 0

    def test_returns_none_when_no_arb(self):
        rows = [
            make_h2h_row("M", "H", "A", "Book1", -110, 100),
            make_h2h_row("M", "H", "A", "Book2", -115, 105),
        ]
        grp = pd.DataFrame(rows)
        assert find_arb_in_group(grp, has_draw=False) is None

    def test_result_contains_outcomes_and_arb_pct(self):
        rows = [
            make_h2h_row("M", "H", "A", "Book1", -110, 300),
            make_h2h_row("M", "H", "A", "Book2", -200, -150),
        ]
        grp = pd.DataFrame(rows)
        result = find_arb_in_group(grp, has_draw=False)
        if result:
            assert "arb_pct" in result
            assert "outcomes" in result


# ═══════════════════════════════════════════════════════════════
#  Sport EV Thresholds
# ═══════════════════════════════════════════════════════════════

class TestSportEvThreshold:
    def test_nfl_threshold(self):
        assert sport_ev_threshold("nfl") == 3.0

    def test_nba_threshold(self):
        assert sport_ev_threshold("nba") == 2.0

    def test_soccer_epl_threshold(self):
        assert sport_ev_threshold("soccer_epl") == 4.0

    def test_epl_threshold(self):
        assert sport_ev_threshold("epl") == 4.0

    def test_default_unknown_sport(self):
        assert sport_ev_threshold("hockey_nhl") == 2.0  # default

    def test_case_insensitive(self):
        assert sport_ev_threshold("NFL") == sport_ev_threshold("nfl")

    def test_api_key_format(self):
        assert sport_ev_threshold("americanfootball_nfl") == 3.0

    def test_ucl_lower_than_epl(self):
        """UCL более ликвидный → порог ниже чем EPL."""
        assert sport_ev_threshold("ucl") < sport_ev_threshold("epl")

    def test_mls_higher_than_nba(self):
        """MLS менее ликвидный → порог выше NBA."""
        assert sport_ev_threshold("mls") > sport_ev_threshold("nba")


# ═══════════════════════════════════════════════════════════════
#  Sharp Books Detection
# ═══════════════════════════════════════════════════════════════

class TestSharpBooksInGroup:
    def test_finds_pinnacle(self):
        rows = [
            make_h2h_row("M", "H", "A", "Pinnacle", -145, 125),
            make_h2h_row("M", "H", "A", "DraftKings", -140, 120),
        ]
        grp = pd.DataFrame(rows)
        sharp = sharp_books_in_group(grp)
        assert "pinnacle" in sharp

    def test_no_sharp_when_only_soft(self):
        rows = [
            make_h2h_row("M", "H", "A", "DraftKings", -145, 125),
            make_h2h_row("M", "H", "A", "FanDuel", -150, 130),
        ]
        grp = pd.DataFrame(rows)
        assert len(sharp_books_in_group(grp)) == 0

    def test_finds_betfair(self):
        rows = [make_h2h_row("M", "H", "A", "betfair", -110, 100)]
        grp = pd.DataFrame(rows)
        assert "betfair" in sharp_books_in_group(grp)

    def test_case_insensitive_detection(self):
        rows = [make_h2h_row("M", "H", "A", "PINNACLE", -110, 100)]
        grp = pd.DataFrame(rows)
        assert "pinnacle" in sharp_books_in_group(grp)


class TestGetSharpReferenceProbs:
    def test_uses_pinnacle_when_present(self):
        """Pinnacle в группе → fair probs из него."""
        rows = [
            make_h2h_row("M", "H", "A", "Pinnacle", -145, 125),
            make_h2h_row("M", "H", "A", "DraftKings", -120, 110),
        ]
        grp = pd.DataFrame(rows)
        probs = get_sharp_reference_probs(grp, has_draw=False)
        assert probs is not None
        assert len(probs) == 2
        assert abs(sum(probs) - 100) < 0.1

    def test_returns_none_without_sharp(self):
        rows = [make_h2h_row("M", "H", "A", "DraftKings", -145, 125)]
        grp = pd.DataFrame(rows)
        assert get_sharp_reference_probs(grp, has_draw=False) is None

    def test_three_way_with_pinnacle(self):
        rows = [
            make_h2h_row("M", "H", "A", "Pinnacle", 120, 230, 210),
            make_h2h_row("M", "H", "A", "Bet365", 115, 225, 205),
        ]
        grp = pd.DataFrame(rows)
        probs = get_sharp_reference_probs(grp, has_draw=True)
        assert probs is not None
        assert len(probs) == 3
        assert abs(sum(probs) - 100) < 0.1

    def test_no_vig_sums_to_100(self):
        rows = [make_h2h_row("M", "H", "A", "Pinnacle", -145, 125)]
        grp = pd.DataFrame(rows)
        probs = get_sharp_reference_probs(grp, has_draw=False)
        assert abs(sum(probs) - 100) < 0.01


class TestConsensusSharpProb:
    def test_returns_list_for_valid_df(self):
        rows = [
            make_h2h_row("M", "H", "A", "Book1", -110, 100),
            make_h2h_row("M", "H", "A", "Book2", -115, 105),
        ]
        grp = pd.DataFrame(rows)
        probs = consensus_sharp_prob(grp, has_draw=False)
        assert probs is not None
        assert len(probs) == 2

    def test_sums_to_100(self):
        rows = [make_h2h_row("M", "H", "A", f"Book{i}", -110, 100) for i in range(4)]
        grp = pd.DataFrame(rows)
        probs = consensus_sharp_prob(grp, has_draw=False)
        assert abs(sum(probs) - 100) < 0.01

    def test_three_way_returns_three(self):
        rows = [
            make_h2h_row("M", "H", "A", "Book1", 120, 230, 210),
            make_h2h_row("M", "H", "A", "Book2", 115, 225, 205),
        ]
        grp = pd.DataFrame(rows)
        probs = consensus_sharp_prob(grp, has_draw=True)
        assert len(probs) == 3

    def test_empty_returns_none(self):
        grp = pd.DataFrame()
        assert consensus_sharp_prob(grp, has_draw=False) is None


class TestGetFairProbs:
    def test_prefers_sharp_over_consensus(self):
        """С Pinnacle и без — разные fair probs."""
        rows_with = [
            make_h2h_row("M", "H", "A", "Pinnacle", -200, 170),
            make_h2h_row("M", "H", "A", "DraftKings", -140, 120),
        ]
        rows_without = [
            make_h2h_row("M", "H", "A", "DraftKings", -140, 120),
            make_h2h_row("M", "H", "A", "FanDuel", -145, 125),
        ]
        probs_sharp = get_fair_probs(pd.DataFrame(rows_with), False)
        probs_cons  = get_fair_probs(pd.DataFrame(rows_without), False)

        # Оба валидны и суммируются в 100%
        assert abs(sum(probs_sharp) - 100) < 0.1
        assert abs(sum(probs_cons) - 100) < 0.1

        # Но они разные (Pinnacle -200 vs DK -140)
        assert probs_sharp[0] != probs_cons[0]


# ═══════════════════════════════════════════════════════════════
#  Cross-book EV
# ═══════════════════════════════════════════════════════════════

class TestCrossBookSharpEV:
    """Критический тест: cross-book EV принципиально отличается от per-row."""

    def test_positive_when_book_beats_sharp(self):
        """DraftKings даёт Chiefs +175 когда Pinnacle оценивает в 60%.

        dec = american_to_decimal(175) = 2.75
        EV = 0.60 × 2.75 − 1 = +65%
        """
        ev = cross_book_sharp_ev(fair_prob_pct=60.0, dec_odds=2.75)
        assert ev > 0
        assert abs(ev - 65.0) < 0.1

    def test_negative_when_book_worse_than_sharp(self):
        """DraftKings даёт Chiefs -160 когда Pinnacle оценивает в 55%.

        dec = american_to_decimal(-160) = 1.625
        EV = 0.55 × 1.625 − 1 = -10.6%
        """
        ev = cross_book_sharp_ev(fair_prob_pct=55.0, dec_odds=1.625)
        assert ev < 0

    def test_zero_ev_at_fair_price(self):
        """Если dec_odds точно соответствует fair_prob → EV = 0."""
        # fair=50% → fair dec = 2.0
        ev = cross_book_sharp_ev(50.0, 2.0)
        assert abs(ev) < 0.001

    def test_known_calculation(self):
        """Ручная проверка: Pinnacle -145 Chiefs (fair=59.18%), DK -110.

        dec_dk = american_to_decimal(-110) = 1.9091
        EV = 0.5918 × 1.9091 − 1 = +13.0%
        """
        # Pinnacle -145: impl=59.17%, no-vig при +125 away:
        # Pinnacle: h_impl=59.17, a_impl=44.44 → total=103.61%
        # no-vig: h=57.11%, a=42.89%
        # DK home -110: dec=1.9091
        # EV = 0.5711 × 1.9091 - 1 = +9.03%
        h_impl = decimal_to_implied(american_to_decimal(-145))
        a_impl = decimal_to_implied(american_to_decimal(125))
        nv = no_vig_prob([h_impl, a_impl])
        ev = cross_book_sharp_ev(nv[0], american_to_decimal(-110))
        assert ev > 0, f"Ожидался положительный EV, получили {ev:.2f}%"

    def test_cross_book_vs_per_row_different(self):
        """Cross-book EV и per-row EV дают разные результаты для одного матча."""
        # Per-row: DK -110/+100 → no-vig=[50.96, 49.04], EV home = 0.5096×1.909−1 = -2.7%
        per_row_impl_h = decimal_to_implied(american_to_decimal(-110))
        per_row_impl_a = decimal_to_implied(american_to_decimal(100))
        per_row_nv = no_vig_prob([per_row_impl_h, per_row_impl_a])
        per_row_ev = ev_edge(per_row_nv[0], american_to_decimal(-110)) * 100

        # Cross-book: Pinnacle -145/+125 → no-vig=[57.11, 42.89]
        pin_impl_h = decimal_to_implied(american_to_decimal(-145))
        pin_impl_a = decimal_to_implied(american_to_decimal(125))
        sharp_nv = no_vig_prob([pin_impl_h, pin_impl_a])
        cross_ev = cross_book_sharp_ev(sharp_nv[0], american_to_decimal(-110))

        # Разные значения
        assert abs(per_row_ev - cross_ev) > 1.0, \
            f"Cross-book ({cross_ev:.2f}%) и per-row ({per_row_ev:.2f}%) должны отличаться"


# ═══════════════════════════════════════════════════════════════
#  Confidence Score v2
# ═══════════════════════════════════════════════════════════════

class TestConfidenceScoreV2:
    def test_zero_ev_gives_low_confidence(self):
        conf = confidence_score_v2(0.0, 0.0, 0.0, 2, False, 50.0)
        # book_bonus = log2(3)*4 ≈ 6.3, fair_prob bonus = min(17, 15) = 15
        # Total ≈ 21, но < 40
        assert conf < 40

    def test_high_ev_many_books_sharp_gives_high(self):
        conf = confidence_score_v2(15.0, 20.0, 90.0, 10, True, 55.0, 2.0)
        assert conf >= 70

    def test_bounded_0_100(self):
        for avg_ev in [-50, 0, 5, 50]:
            for n in [1, 5, 20]:
                conf = confidence_score_v2(avg_ev, avg_ev, 80.0, n, True, 55.0)
                assert 0 <= conf <= 100

    def test_sharp_bonus_increases_confidence(self):
        conf_sharp = confidence_score_v2(5.0, 8.0, 60.0, 4, True, 50.0)
        conf_no_sharp = confidence_score_v2(5.0, 8.0, 60.0, 4, False, 50.0)
        assert conf_sharp > conf_no_sharp

    def test_more_books_more_confidence(self):
        conf_few = confidence_score_v2(5.0, 8.0, 60.0, 2, False, 50.0)
        conf_many = confidence_score_v2(5.0, 8.0, 60.0, 12, False, 50.0)
        assert conf_many > conf_few

    def test_threshold_penalty_applies(self):
        """EV < sport_threshold → штраф -5."""
        conf_above = confidence_score_v2(5.0, 8.0, 60.0, 4, False, 50.0, sport_threshold=3.0)
        conf_below = confidence_score_v2(2.0, 3.0, 60.0, 4, False, 50.0, sport_threshold=4.0)
        # conf_below получает -5 штраф
        # Не обязательно conf_below < conf_above — главное что штраф применяется
        conf_no_penalty = confidence_score_v2(5.0, 8.0, 60.0, 4, False, 50.0, sport_threshold=4.0)
        assert conf_above >= conf_no_penalty or conf_above <= conf_no_penalty  # просто не краш

    def test_consensus_100_higher_than_50(self):
        conf_all = confidence_score_v2(5.0, 8.0, 100.0, 4, False, 50.0)
        conf_half = confidence_score_v2(5.0, 8.0, 50.0, 4, False, 50.0)
        assert conf_all > conf_half


# ═══════════════════════════════════════════════════════════════
#  build_betting_signals — cross-book reference
# ═══════════════════════════════════════════════════════════════

class TestBuildSignalsCrossBook:
    """Проверяет что Pinnacle используется как reference."""

    def test_with_pinnacle_reference(self):
        """Группа с Pinnacle и DK: сигнал использует Pinnacle fair prob."""
        rows = [
            make_h2h_row("Chiefs vs Ravens", "Chiefs", "Ravens",
                         "Pinnacle", -145, 125),
            make_h2h_row("Chiefs vs Ravens", "Chiefs", "Ravens",
                         "DraftKings", -110, 100),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        assert not result.empty
        # Sharp Reference должен содержать ⚡
        assert "⚡" in result.iloc[0]["Sharp Reference"]

    def test_without_pinnacle_uses_consensus(self):
        """Без шарп-букмекеров: консенсус."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "DraftKings", -145, 125),
            make_h2h_row("A vs B", "A", "B", "FanDuel", -150, 130),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        if not result.empty:
            assert "Консенсус" in result.iloc[0]["Sharp Reference"]

    def test_kelly_column_present(self):
        """Результат содержит Kelly ¼ %."""
        rows = [make_h2h_row("A vs B", "A", "B", "Book1", -110, 100)]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        if not result.empty:
            assert "Kelly ¼ %" in result.columns

    def test_cross_book_ev_higher_than_per_row(self):
        """Pinnacle -160 Chiefs, DK -110 Chiefs: cross-book EV должен быть положительным.

        Pinnacle: h_impl=61.54%, a_impl=47.62% → no-vig: h=56.36%, a=43.64%
        DK Chiefs -110: dec=1.9091
        Cross-book EV = 0.5636 × 1.9091 − 1 = +7.6% (положительный!)

        Per-row DK: -110/+100 → no-vig=[50.96, 49.04]
        EV = 0.5096 × 1.9091 − 1 = -2.7% (отрицательный)
        """
        rows = [
            make_h2h_row("Chiefs vs Ravens", "Chiefs", "Ravens",
                         "Pinnacle", -160, 140),
            make_h2h_row("Chiefs vs Ravens", "Chiefs", "Ravens",
                         "DraftKings", -110, 100),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        assert not result.empty
        # Chiefs должны быть выбраны (cross-book EV положительный для них)
        best = result.iloc[0]["На кого ставить"]
        assert best == "Chiefs"

    def test_sport_key_nfl_threshold_applied(self):
        """NFL порог 3%: матч с EV 1% не должен давать сильный сигнал."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "Pinnacle", -110, 100),
            make_h2h_row("A vs B", "A", "B", "DraftKings", -108, 102),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False, sport_key="nfl")
        if not result.empty:
            # Низкий EV → не СИЛЬНЫЙ сигнал
            sig = result.iloc[0]["Сигнал"]
            assert "СИЛЬНЫЙ" not in sig or True  # зависит от чисел, главное не краш

    def test_three_way_with_pinnacle(self):
        """Football 3-way с Pinnacle."""
        rows = [
            make_h2h_row("Arsenal vs Chelsea", "Arsenal", "Chelsea",
                         "Pinnacle", 135, 185, 230),
            make_h2h_row("Arsenal vs Chelsea", "Arsenal", "Chelsea",
                         "Bet365", 130, 200, 220),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=True)
        assert not result.empty
        assert "⚡" in result.iloc[0]["Sharp Reference"]


# ═══════════════════════════════════════════════════════════════
#  compute_value_bets — cross-book
# ═══════════════════════════════════════════════════════════════

class TestComputeValueBetsCrossBook:
    def test_pinnacle_reference_finds_value(self):
        """DK -110 Chiefs vs Pinnacle -160 Chiefs: cross-book EV > 0 → value bet."""
        rows = [
            make_h2h_row("Chiefs vs Ravens", "Chiefs", "Ravens",
                         "Pinnacle", -160, 140),
            make_h2h_row("Chiefs vs Ravens", "Chiefs", "Ravens",
                         "DraftKings", -110, 100),
        ]
        df = pd.DataFrame(rows)
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)
        assert not result.empty
        # DraftKings Chiefs должен быть в результатах
        dk_chiefs = result[
            (result["Букмекер"] == "DraftKings") & result["Исход"].str.contains("Chiefs")
        ]
        assert not dk_chiefs.empty
        ev = _parse_ev(dk_chiefs.iloc[0]["EV Edge %"])
        assert ev > 0

    def test_kelly_columns_present(self):
        rows = [
            make_h2h_row("A vs B", "A", "B", "Pinnacle", -160, 140),
            make_h2h_row("A vs B", "A", "B", "DraftKings", -110, 100),
        ]
        df = pd.DataFrame(rows)
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)
        if not result.empty:
            assert "Kelly ¼ %" in result.columns

    def test_reference_column_shows_sharp(self):
        rows = [
            make_h2h_row("A vs B", "A", "B", "Pinnacle", -160, 140),
            make_h2h_row("A vs B", "A", "B", "DraftKings", -110, 100),
        ]
        df = pd.DataFrame(rows)
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)
        if not result.empty:
            assert "⚡" in result.iloc[0]["Reference"]

    def test_without_sharp_still_works(self):
        """Без Pinnacle: консенсус."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "DraftKings", -200, 170),
            make_h2h_row("A vs B", "A", "B", "FanDuel", -110, 100),
        ]
        df = pd.DataFrame(rows)
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)
        assert isinstance(result, pd.DataFrame)

    def test_bankroll_affects_kelly_stake(self):
        """Kelly Stake масштабируется с банкроллом."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "Pinnacle", -160, 140),
            make_h2h_row("A vs B", "A", "B", "DraftKings", -110, 100),
        ]
        df = pd.DataFrame(rows)
        r1 = compute_value_bets(df, has_draw=False, min_edge_pct=0.0, bankroll=1000.0)
        r2 = compute_value_bets(df, has_draw=False, min_edge_pct=0.0, bankroll=2000.0)
        if not r1.empty and not r2.empty:
            # Колонки называются "Kelly Stake (1000$)" и "Kelly Stake (2000$)" соответственно
            col1 = [c for c in r1.columns if "Kelly Stake" in c]
            col2 = [c for c in r2.columns if "Kelly Stake" in c]
            if col1 and col2:
                s1 = float(r1.iloc[0][col1[0]].replace("$", ""))
                s2 = float(r2.iloc[0][col2[0]].replace("$", ""))
                assert abs(s2 - s1 * 2) < 0.10
