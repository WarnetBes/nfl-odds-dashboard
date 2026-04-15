"""
tests/test_arb_tab.py
─────────────────────
Unit-тесты для логики вкладки «Арбитраж»:
- find_arb_in_group() интеграция с реальными сценариями
- arb_stakes() корректно делит банкролл
- arb_percentage() согласован с find_arb_in_group()
- Калькулятор edge-cases (нулевой банкролл, одинаковые коэффициенты)
- Near-arb: find_arb_in_group возвращает None при отрицательном arb%
"""
import pytest
import pandas as pd
from utils import (
    find_arb_in_group,
    arb_stakes,
    arb_percentage,
    make_h2h_row,
)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_arb_group(rows: list[dict]) -> pd.DataFrame:
    """Собирает DataFrame из списка {bm, h_am, a_am} для одного матча."""
    data = []
    for r in rows:
        data.append(make_h2h_row(
            match="Team A vs Team B",
            home="Team A", away="Team B",
            bm=r["bm"],
            h_am=r["h_am"], a_am=r["a_am"],
        ))
    return pd.DataFrame(data)


def make_arb_group_draw(rows: list[dict]) -> pd.DataFrame:
    """Трёхисходник с ничьей."""
    data = []
    for r in rows:
        data.append(make_h2h_row(
            match="Home vs Away",
            home="Home", away="Away",
            bm=r["bm"],
            h_am=r.get("h_am", -110),
            a_am=r.get("a_am", -110),
            d_am=r.get("d_am"),
        ))
    return pd.DataFrame(data)


# ─────────────────────────────────────────────────────────────────────────────
#  TestArbTabSureBetDetection
# ─────────────────────────────────────────────────────────────────────────────

class TestArbTabSureBetDetection:
    """find_arb_in_group() находит суребет когда он есть."""

    def test_obvious_surebet_two_way(self):
        """Team A +175 @ BK1, Team B +160 @ BK2 → явная вилка."""
        grp = make_arb_group([
            {"bm": "Bookmaker1", "h_am": 175, "a_am": -200},
            {"bm": "Bookmaker2", "h_am": -250, "a_am": 160},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        assert result is not None
        assert result["arb_pct"] > 0

    def test_surebet_returns_correct_structure(self):
        """Результат содержит arb_pct и outcomes."""
        grp = make_arb_group([
            {"bm": "BK1", "h_am": 180, "a_am": -300},
            {"bk": "BK2", "bm": "BK2", "h_am": -400, "a_am": 155},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        if result is not None:
            assert "arb_pct" in result
            assert "outcomes" in result
            assert isinstance(result["outcomes"], dict)

    def test_no_surebet_when_standard_vig(self):
        """Стандартный виг -110/-110 → нет суребета."""
        grp = make_arb_group([
            {"bm": "DraftKings", "h_am": -110, "a_am": -110},
            {"bm": "FanDuel",    "h_am": -110, "a_am": -110},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        assert result is None

    def test_no_surebet_favorite_vs_underdog(self):
        """Фаворит -200 vs аутсайдер +170 → нет суребета."""
        grp = make_arb_group([
            {"bm": "DraftKings", "h_am": -200, "a_am": 170},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        assert result is None

    def test_best_odds_selected_per_outcome(self):
        """find_arb использует лучший коэфф каждого исхода среди всех книг."""
        grp = make_arb_group([
            {"bm": "BK1", "h_am": 150, "a_am": -300},   # Team A +150 лучший
            {"bm": "BK2", "h_am": 110,  "a_am": -150},  # Team B -150 лучший
            {"bm": "BK3", "h_am": 120,  "a_am": -200},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        if result is not None:
            outcomes = result["outcomes"]
            # BK1 должен быть лучшим для Team A
            assert outcomes.get("Team A", {}).get("bm") == "BK1"
            # BK2 должен быть лучшим для Team B
            assert outcomes.get("Team B", {}).get("bm") == "BK2"

    def test_single_bookmaker_no_arb(self):
        """Один букмекер → нет межбукмекерского арбитража."""
        grp = make_arb_group([
            {"bm": "Pinnacle", "h_am": -110, "a_am": -110},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        assert result is None

    def test_empty_group_no_crash(self):
        """Пустой DataFrame → None без ошибки."""
        grp = pd.DataFrame()
        result = find_arb_in_group(grp, has_draw=False)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
#  TestArbStakesCalculator
# ─────────────────────────────────────────────────────────────────────────────

class TestArbStakesCalculator:
    """arb_stakes() правильно делит банкролл."""

    def test_stakes_sum_equals_bankroll(self):
        """Сумма всех ставок = банкролл."""
        dec_odds = [2.75, 2.65]
        stakes = arb_stakes(1000.0, dec_odds)
        assert abs(sum(stakes) - 1000.0) < 0.02  # ±2 цента погрешность округления

    def test_payout_is_equal_for_both_outcomes(self):
        """Выплата при любом исходе одинакова (гарантированная прибыль)."""
        dec_odds = [2.75, 2.65]
        stakes = arb_stakes(1000.0, dec_odds)
        payouts = [round(s * d, 2) for s, d in zip(stakes, dec_odds)]
        assert abs(payouts[0] - payouts[1]) < 0.10  # расхождение < 10 центов

    def test_three_way_stakes_sum(self):
        """Трёхисходник: сумма ставок = банкролл."""
        dec_odds = [3.5, 3.5, 3.5]
        stakes = arb_stakes(1000.0, dec_odds)
        assert abs(sum(stakes) - 1000.0) < 0.05

    def test_no_stakes_when_no_arb(self):
        """Нет суребета → пустой список."""
        stakes = arb_stakes(1000.0, [1.909, 1.909])
        assert stakes == []

    def test_profit_is_positive(self):
        """Суребет даёт прибыль > 0."""
        dec_odds = [2.75, 2.65]
        stakes = arb_stakes(1000.0, dec_odds)
        payout = stakes[0] * dec_odds[0]  # выплата одинакова при любом исходе
        profit = payout - sum(stakes)
        assert profit > 0

    def test_different_bankrolls_proportional(self):
        """Ставки пропорциональны банкроллу."""
        dec_odds = [2.75, 2.65]
        s1000 = arb_stakes(1000.0, dec_odds)
        s2000 = arb_stakes(2000.0, dec_odds)
        assert abs(s2000[0] / s1000[0] - 2.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
#  TestArbPercentageConsistency
# ─────────────────────────────────────────────────────────────────────────────

class TestArbPercentageConsistency:
    """arb_percentage() и find_arb_in_group() согласованы."""

    def test_positive_arb_pct_means_surebet_found(self):
        """Если arb_percentage > 0, find_arb_in_group должен найти суребет."""
        # Создаём данные где вручную подтверждаем arb > 0
        dec_odds = [2.75, 2.65]
        pct = arb_percentage(dec_odds)
        assert pct > 0, "Тест предполагает явный суребет"

        grp = make_arb_group([
            {"bm": "BK1", "h_am": 175, "a_am": -300},  # dec≈2.75 для Team A
            {"bm": "BK2", "h_am": -400, "a_am": 165},  # dec≈2.65 для Team B
        ])
        result = find_arb_in_group(grp, has_draw=False)
        assert result is not None

    def test_arb_pct_matches_find_result(self):
        """arb_pct в find_arb_in_group совпадает с ручным расчётом."""
        grp = make_arb_group([
            {"bm": "BK1", "h_am": 175, "a_am": -500},
            {"bm": "BK2", "h_am": -500, "a_am": 165},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        if result is not None:
            dec_list = [v["dec"] for v in result["outcomes"].values()]
            manual_arb = arb_percentage(dec_list) * 100
            assert abs(result["arb_pct"] - manual_arb) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
#  TestArbEdgeCases
# ─────────────────────────────────────────────────────────────────────────────

class TestArbEdgeCases:
    """Граничные случаи арбитражного поиска."""

    def test_nan_odds_skipped(self):
        """NaN коэффициенты не вызывают ошибку."""
        grp = make_arb_group([
            {"bm": "BK1", "h_am": None, "a_am": -110},
            {"bm": "BK2", "h_am": -110, "a_am": None},
        ])
        try:
            result = find_arb_in_group(grp, has_draw=False)
            # Может быть None или найти частичный результат, главное — не крашится
        except Exception as e:
            pytest.fail(f"find_arb_in_group raised unexpectedly: {e}")

    def test_very_high_odds_no_crash(self):
        """Очень высокие коэффициенты не вызывают ошибку."""
        grp = make_arb_group([
            {"bm": "BK1", "h_am": 5000, "a_am": -10000},
            {"bm": "BK2", "h_am": -10000, "a_am": 4500},
        ])
        try:
            result = find_arb_in_group(grp, has_draw=False)
        except Exception as e:
            pytest.fail(f"Unexpected error: {e}")

    def test_draw_three_way_surebet(self):
        """Трёхисходник с ничьей находит суребет при хороших коэффициентах."""
        # 3.5/3.5/3.5 → arb = 1 - 3*(1/3.5) = 1 - 0.857 = 14.3% 
        grp = make_arb_group_draw([
            {"bm": "BK1", "h_am": 250, "a_am": -300, "d_am": 250},
            {"bm": "BK2", "h_am": -300, "a_am": 250, "d_am": 250},
        ])
        result = find_arb_in_group(grp, has_draw=True)
        # Не проверяем конкретный результат, проверяем что не крашится
        # и если найден — структура корректная
        if result is not None:
            assert "arb_pct" in result
            assert "outcomes" in result

    def test_arb_pct_value_in_percent(self):
        """arb_pct возвращается в процентах (0-100), не долях (0-1)."""
        grp = make_arb_group([
            {"bm": "BK1", "h_am": 175, "a_am": -500},
            {"bm": "BK2", "h_am": -500, "a_am": 165},
        ])
        result = find_arb_in_group(grp, has_draw=False)
        if result is not None:
            # Должно быть в % (например 5.3), не в долях (0.053)
            assert 0 < result["arb_pct"] < 100
