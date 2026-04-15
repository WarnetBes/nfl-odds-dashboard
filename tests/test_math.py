"""
test_math.py — юнит-тесты для базовых математических функций:
  american_to_decimal, decimal_to_implied, no_vig_prob, ev_edge, fmt_am
"""
import pytest
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from utils import (
    american_to_decimal, decimal_to_implied,
    no_vig_prob, ev_edge, fmt_am,
)


# ═══════════════════════════════════════════════════════════════
#  american_to_decimal
# ═══════════════════════════════════════════════════════════════

class TestAmericanToDecimal:
    """Конвертация American → Decimal odds."""

    def test_positive_plus100(self):
        # +100 → 2.00
        assert american_to_decimal(100) == 2.0

    def test_positive_plus200(self):
        # +200 → 3.00
        assert american_to_decimal(200) == 3.0

    def test_negative_minus100(self):
        # -100 → 2.00
        assert american_to_decimal(-100) == 2.0

    def test_negative_minus110(self):
        # -110 → 100/110 + 1 ≈ 1.9091
        result = american_to_decimal(-110)
        assert abs(result - 1.9091) < 0.001

    def test_negative_minus200(self):
        # -200 → 100/200 + 1 = 1.5
        assert american_to_decimal(-200) == 1.5

    def test_positive_plus110(self):
        # +110 → 110/100 + 1 = 2.1
        assert american_to_decimal(110) == 2.1

    def test_even_money_symmetry(self):
        # +100 и -100 должны давать одинаковый decimal
        assert american_to_decimal(100) == american_to_decimal(-100)

    def test_always_above_one(self):
        # Decimal odds всегда > 1
        for v in [-500, -200, -110, -105, 100, 110, 200, 500]:
            assert american_to_decimal(v) > 1.0, f"Failed for {v}"

    def test_heavy_favorite(self):
        # -500 → 100/500 + 1 = 1.2
        assert american_to_decimal(-500) == 1.2

    def test_big_underdog(self):
        # +500 → 500/100 + 1 = 6.0
        assert american_to_decimal(500) == 6.0


# ═══════════════════════════════════════════════════════════════
#  decimal_to_implied
# ═══════════════════════════════════════════════════════════════

class TestDecimalToImplied:
    """Конвертация Decimal → Implied Probability (%)."""

    def test_even_money(self):
        # 2.0 → 50%
        assert decimal_to_implied(2.0) == 50.0

    def test_favorite(self):
        # 1.5 → 66.67%
        result = decimal_to_implied(1.5)
        assert abs(result - 66.67) < 0.01

    def test_underdog(self):
        # 3.0 → 33.33%
        result = decimal_to_implied(3.0)
        assert abs(result - 33.33) < 0.01

    def test_zero_odds_returns_zero(self):
        # Нулевой decimal → 0 (защита от деления на ноль)
        assert decimal_to_implied(0) == 0.0

    def test_probability_range(self):
        # Результат всегда в диапазоне (0, 100]
        for d in [1.01, 1.5, 2.0, 3.0, 5.0, 10.0]:
            p = decimal_to_implied(d)
            assert 0 < p <= 100, f"Out of range for decimal={d}: got {p}"

    def test_roundtrip_consistency(self):
        # american → decimal → implied должен быть согласован
        am = -110
        dec = american_to_decimal(am)
        impl = decimal_to_implied(dec)
        # -110 ≈ 52.38% implied
        assert abs(impl - 52.38) < 0.01


# ═══════════════════════════════════════════════════════════════
#  no_vig_prob
# ═══════════════════════════════════════════════════════════════

class TestNoVigProb:
    """No-vig нормализация вероятностей."""

    def test_two_way_sums_to_100(self):
        # Два исхода: implied 52.38 + 52.38 = 104.76 (vig ~4.76%)
        probs = [52.38, 52.38]
        result = no_vig_prob(probs)
        assert abs(sum(result) - 100) < 0.01

    def test_two_way_equal_splits_evenly(self):
        # Симметричные коэффициенты → 50/50
        result = no_vig_prob([50.0, 50.0])
        assert result == [50.0, 50.0]

    def test_three_way_sums_to_100(self):
        # Три исхода (Football 1X2)
        probs = [45.0, 30.0, 35.0]  # сумма 110%
        result = no_vig_prob(probs)
        assert abs(sum(result) - 100) < 0.01

    def test_three_way_preserves_ratios(self):
        # Соотношения между исходами сохраняются
        probs = [40.0, 40.0, 40.0]  # 120% total
        result = no_vig_prob(probs)
        assert abs(result[0] - result[1]) < 0.01
        assert abs(result[1] - result[2]) < 0.01

    def test_no_vig_removes_overround(self):
        # После нормализации vig исчезает
        # -110/-110 → implied 52.38/52.38 = 104.76% overround
        h_impl = decimal_to_implied(american_to_decimal(-110))
        a_impl = decimal_to_implied(american_to_decimal(-110))
        assert h_impl + a_impl > 100  # overround существует
        result = no_vig_prob([h_impl, a_impl])
        assert abs(sum(result) - 100) < 0.01  # после нормализации = 100%

    def test_empty_list_handled(self):
        # Пустой список не должен вызывать краш
        result = no_vig_prob([])
        assert result == []

    def test_single_outcome(self):
        result = no_vig_prob([75.0])
        assert result == [100.0]

    def test_asymmetric_market(self):
        # Фаворит -200, аутсайдер +150
        h_impl = decimal_to_implied(american_to_decimal(-200))  # ≈66.67%
        a_impl = decimal_to_implied(american_to_decimal(150))   # ≈40%
        result = no_vig_prob([h_impl, a_impl])
        # Фаворит должен иметь > 50% no-vig
        assert result[0] > 50
        assert result[1] < 50
        assert abs(sum(result) - 100) < 0.01


# ═══════════════════════════════════════════════════════════════
#  ev_edge
# ═══════════════════════════════════════════════════════════════

class TestEvEdge:
    """EV Edge = fair_prob/100 * decimal - 1."""

    def test_zero_edge_at_fair_price(self):
        # Если коэфф точно соответствует fair prob → EV = 0
        # fair = 50%, decimal = 2.0: 0.5 * 2.0 - 1 = 0
        assert ev_edge(50.0, 2.0) == 0.0

    def test_positive_edge(self):
        # fair = 55%, decimal = 2.0: 0.55 * 2.0 - 1 = +0.10
        result = ev_edge(55.0, 2.0)
        assert abs(result - 0.10) < 0.001

    def test_negative_edge(self):
        # fair = 45%, decimal = 2.0: 0.45 * 2.0 - 1 = -0.10
        result = ev_edge(45.0, 2.0)
        assert abs(result - (-0.10)) < 0.001

    def test_value_bet_scenario(self):
        # Bookmaker даёт +200 (decimal 3.0), fair prob = 40%
        # EV = 0.40 * 3.0 - 1 = 0.20 = +20%
        result = ev_edge(40.0, 3.0)
        assert abs(result - 0.20) < 0.001

    def test_negative_edge_heavy_favorite(self):
        # Ставишь на фаворита с vig: fair=70%, decimal=1.3
        # EV = 0.70 * 1.3 - 1 = -0.09 = -9%
        result = ev_edge(70.0, 1.3)
        assert result < 0

    def test_ev_scales_with_odds(self):
        # При одинаковом fair prob, выше odds → выше EV
        ev_low  = ev_edge(40.0, 2.0)
        ev_high = ev_edge(40.0, 3.0)
        assert ev_high > ev_low


# ═══════════════════════════════════════════════════════════════
#  fmt_am
# ═══════════════════════════════════════════════════════════════

class TestFmtAm:
    """Форматирование American odds в строку."""

    def test_positive_adds_plus(self):
        assert fmt_am(100) == "+100"
        assert fmt_am(200) == "+200"

    def test_negative_no_plus(self):
        assert fmt_am(-110) == "-110"
        assert fmt_am(-200) == "-200"

    def test_zero_is_positive(self):
        assert fmt_am(0) == "+0"

    def test_string_input(self):
        # Принимает строки тоже
        assert fmt_am("110") == "+110"
        assert fmt_am("-110") == "-110"

    def test_float_rounds_to_int(self):
        assert fmt_am(110.0) == "+110"

    def test_invalid_returns_string(self):
        # Некорректный ввод не крашится
        result = fmt_am("N/A")
        assert isinstance(result, str)
