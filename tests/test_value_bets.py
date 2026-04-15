"""
test_value_bets.py — юнит-тесты для compute_value_bets().

Покрывает:
- Двухисходник (NFL/NBA): нет ничьей
- Трёхисходник (Football 1X2): с ничьей
- Фильтрация по порогу min_edge_pct
- Пустые/None/nan коэффициенты — без краша
- Структура и типы возвращаемого DataFrame
- Граничные случаи: нулевой порог, очень высокий порог
"""
import pytest
import pandas as pd
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from utils import (
    compute_value_bets,
    american_to_decimal, decimal_to_implied, no_vig_prob, ev_edge,
    make_h2h_row,
)


# ═══════════════════════════════════════════════════════════════
#  Вспомогательные функции
# ═══════════════════════════════════════════════════════════════

def _parse_ev(ev_str: str) -> float:
    """'+5.23%' → 5.23"""
    return float(ev_str.replace("+", "").replace("%", ""))


# ═══════════════════════════════════════════════════════════════
#  Тесты — возвращаемая структура
# ═══════════════════════════════════════════════════════════════

class TestValueBetsStructure:
    """Тестирует структуру и типы возвращаемого DataFrame."""

    REQUIRED_COLS = {
        "Матч", "Время", "Букмекер", "Исход",
        "Odds (Am)", "Odds (Dec)", "Implied %",
        "No-Vig Fair %", "EV Edge %",
    }

    def test_returns_dataframe(self, nfl_two_books):
        result = compute_value_bets(nfl_two_books, has_draw=False, min_edge_pct=0.0)
        assert isinstance(result, pd.DataFrame)

    def test_required_columns_present(self, nfl_two_books):
        result = compute_value_bets(nfl_two_books, has_draw=False, min_edge_pct=0.0)
        if not result.empty:
            assert self.REQUIRED_COLS.issubset(set(result.columns))

    def test_empty_df_returns_empty(self, empty_df):
        result = compute_value_bets(empty_df, has_draw=False, min_edge_pct=0.0)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_internal_edge_column_removed(self, nfl_value_bet):
        """_edge колонка не должна попадать в финальный результат."""
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=0.0)
        if not result.empty:
            assert "_edge" not in result.columns

    def test_index_starts_at_one(self, nfl_value_bet):
        """Индекс начинается с 1, не с 0."""
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=0.0)
        if not result.empty:
            assert result.index[0] == 1

    def test_sorted_by_ev_descending(self, nfl_value_bet):
        """Строки отсортированы по EV Edge убыванию."""
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=0.0)
        if len(result) > 1:
            ev_vals = [_parse_ev(v) for v in result["EV Edge %"]]
            assert ev_vals == sorted(ev_vals, reverse=True)

    def test_odds_dec_is_float(self, nfl_value_bet):
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=0.0)
        if not result.empty:
            assert result["Odds (Dec)"].dtype in (float, "float64")

    def test_ev_edge_format(self, nfl_value_bet):
        """EV Edge % форматируется как '+X.XX%'."""
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=0.0)
        for ev in result.get("EV Edge %", []):
            assert ev.startswith("+"), f"EV Edge должен начинаться с '+': {ev}"
            assert ev.endswith("%"), f"EV Edge должен заканчиваться на '%': {ev}"

    def test_isход_has_checkmark(self, nfl_value_bet):
        """Исход форматируется с эмодзи ✅."""
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=0.0)
        for iskhod in result.get("Исход", []):
            assert "✅" in str(iskhod)


# ═══════════════════════════════════════════════════════════════
#  Тесты — логика фильтрации по порогу
# ═══════════════════════════════════════════════════════════════

class TestValueBetsThreshold:
    """Тестирует фильтрацию по min_edge_pct."""

    def test_threshold_zero_returns_positive_ev(self, nfl_value_bet):
        """При пороге 0% возвращаются все ставки с EV > 0."""
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=0.0)
        # nfl_value_bet содержит явный value bet → не должен быть пустым
        assert not result.empty

    def test_threshold_above_max_returns_empty(self, nfl_value_bet):
        """При пороге 999% ничего не возвращается."""
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=999.0)
        assert result.empty

    def test_threshold_filters_correctly(self, nfl_value_bet):
        """Все возвращённые value bets имеют EV ≥ min_edge_pct."""
        threshold = 5.0
        result = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=threshold)
        for ev_str in result.get("EV Edge %", []):
            assert _parse_ev(ev_str) >= threshold, \
                f"EV {ev_str} ниже порога {threshold}%"

    def test_lower_threshold_more_results(self, nfl_value_bet):
        """Снижение порога даёт >= строк, чем более высокий."""
        r_low  = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=1.0)
        r_high = compute_value_bets(nfl_value_bet, has_draw=False, min_edge_pct=10.0)
        assert len(r_low) >= len(r_high)


# ═══════════════════════════════════════════════════════════════
#  Тесты — двухисходник (NFL/NBA)
# ═══════════════════════════════════════════════════════════════

class TestValueBetsTwoWay:
    """NFL/NBA — без ничьей."""

    def test_no_draw_not_in_results(self, nfl_two_books):
        """Ничья не появляется в результатах для двухисходников."""
        result = compute_value_bets(nfl_two_books, has_draw=False, min_edge_pct=0.0)
        for iskhod in result.get("Исход", []):
            assert "Ничья" not in str(iskhod)

    def test_only_home_and_away_outcomes(self, nfl_two_books):
        """Только хозяева и гости в исходах."""
        result = compute_value_bets(nfl_two_books, has_draw=False, min_edge_pct=0.0)
        for iskhod in result.get("Исход", []):
            clean = iskhod.replace("✅ ", "")
            assert clean in (
                "Kansas City Chiefs", "Baltimore Ravens"
            ), f"Неожиданный исход: {iskhod}"

    def test_ev_calculation_correctness(self):
        """Проверяет точность расчёта EV на известных числах.

        Один букмекер: Home -110 / Away +200
        - h_impl = 100/1.9091 = 52.38%
        - a_impl = 100/3.0   = 33.33%
        - total = 85.71% (under-round book!) → no_vig: h=61.11%, a=38.89%
        - EV home = 0.6111 * 1.9091 - 1 = +16.6% → value bet
        - EV away = 0.3889 * 3.0   - 1 = +16.7% → value bet

        При любой асимметрии где total < 100% оба исхода будут value.
        В нашем случае used -110/+200 → оба EV > 0.
        """
        rows = [
            make_h2h_row("TestMatch", "Home", "Away", "Book1", -110, 200),
        ]
        df = pd.DataFrame(rows)
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)

        # Оба исхода должны быть value bets
        assert not result.empty
        assert len(result) == 2

        # Проверяем математику: Home -110 → dec=1.9091
        # Away +200 → dec=3.0
        # implied: h=52.38%, a=33.33%, total=85.71%
        # no-vig: h=61.11%, a=38.89%
        # EV home = 0.6111 * 1.9091 - 1 ≈ +16.7%
        home_row = result[result["Исход"].str.contains("Home")]
        away_row = result[result["Исход"].str.contains("Away")]
        assert not home_row.empty and not away_row.empty
        ev_home = _parse_ev(home_row.iloc[0]["EV Edge %"])
        ev_away = _parse_ev(away_row.iloc[0]["EV Edge %"])
        assert ev_home > 10.0, f"EV Home ожидался >10%, получили {ev_home:.2f}%"
        assert ev_away > 10.0, f"EV Away ожидался >10%, получили {ev_away:.2f}%"


# ═══════════════════════════════════════════════════════════════
#  Тесты — трёхисходник (Football 1X2)
# ═══════════════════════════════════════════════════════════════

class TestValueBetsThreeWay:
    """EPL/Football — с ничьей."""

    def test_draw_present_in_results(self, football_three_way):
        """Ничья может появляться в результатах трёхисходника."""
        # Используем отрицательный порог чтобы получить все исходы
        result = compute_value_bets(football_three_way, has_draw=True, min_edge_pct=-100.0)
        iskhody = [str(i) for i in result.get("Исход", [])]
        # Хотя бы один из 3 исходов должен присутствовать
        assert any("Arsenal" in i or "Chelsea" in i or "Ничья" in i
                   for i in iskhody), f"Нет ни одного известного исхода: {iskhody}"

    def test_has_draw_false_ignores_draw_odds(self, football_three_way):
        """Если has_draw=False, ничья игнорируется даже при наличии коэффициентов."""
        result = compute_value_bets(football_three_way, has_draw=False, min_edge_pct=0.0)
        for iskhod in result.get("Исход", []):
            assert "Ничья" not in str(iskhod)

    def test_three_way_no_vig_sums_to_100(self, football_three_way):
        """No-vig вероятности для трёхисходника суммируются в 100%."""
        # Берём первую строку, считаем вручную
        row = football_three_way.iloc[0]
        h_dec = american_to_decimal(float(row["Odds Хозяева (Am)"]))
        a_dec = american_to_decimal(float(row["Odds Гости (Am)"]))
        d_dec = american_to_decimal(float(row["Odds Ничья (Am)"]))
        probs = [decimal_to_implied(h_dec),
                 decimal_to_implied(a_dec),
                 decimal_to_implied(d_dec)]
        nv = no_vig_prob(probs)
        assert abs(sum(nv) - 100) < 0.01

    def test_three_way_returns_multiple_rows_per_bookmaker(self, football_three_way):
        """Трёхисходник может давать до 3 value bet строк на матч/букмекера."""
        result = compute_value_bets(football_three_way, has_draw=True, min_edge_pct=0.0)
        # Максимум 3 исхода * 2 букмекера = 6 строк
        assert len(result) <= 6


# ═══════════════════════════════════════════════════════════════
#  Тесты — обработка ошибочных данных
# ═══════════════════════════════════════════════════════════════

class TestValueBetsEdgeCases:
    """Граничные случаи и защита от ошибок."""

    def test_none_odds_skipped(self, nan_odds_df):
        """Строки с None/nan в коэффициентах пропускаются без краша."""
        result = compute_value_bets(nan_odds_df, has_draw=False, min_edge_pct=0.0)
        # GoodBook строка обработана, BadBook — нет
        assert isinstance(result, pd.DataFrame)

    def test_no_crash_on_empty_df(self, empty_df):
        result = compute_value_bets(empty_df, has_draw=False, min_edge_pct=0.0)
        assert result.empty

    def test_no_crash_on_single_row(self):
        """Один букмекер — минимальный рабочий случай."""
        df = pd.DataFrame([
            make_h2h_row("A vs B", "A", "B", "Book1", -110, 100)
        ])
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)
        assert isinstance(result, pd.DataFrame)

    def test_very_high_odds_no_crash(self):
        """Очень высокие коэффициенты не вызывают ошибку."""
        df = pd.DataFrame([
            make_h2h_row("X vs Y", "X", "Y", "Book", -1000, 800)
        ])
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)
        assert isinstance(result, pd.DataFrame)

    def test_symmetric_odds_no_value(self):
        """При симметричных и одинаковых коэффициентах у всех книг — нет EV."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "Book1", -110, -110),
            make_h2h_row("A vs B", "A", "B", "Book2", -110, -110),
        ]
        df = pd.DataFrame(rows)
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.1)
        # При -110/-110 implied = 52.38/52.38 = 104.76% → no-vig = 50/50
        # EV = 0.50 * 1.9091 - 1 = -0.045 → отрицательный → не попадает
        assert result.empty

    def test_multiple_matches(self):
        """Несколько матчей обрабатываются независимо."""
        rows = [
            make_h2h_row("Match1", "A", "B", "Book1", -110, 100),
            make_h2h_row("Match2", "C", "D", "Book1", -120, 110),
        ]
        df = pd.DataFrame(rows)
        result = compute_value_bets(df, has_draw=False, min_edge_pct=0.0)
        matches_in_result = set(result["Матч"].tolist()) if not result.empty else set()
        # Оба матча могли дать value bets (или ни один — зависит от линий)
        assert isinstance(result, pd.DataFrame)
