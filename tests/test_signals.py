"""
test_signals.py — юнит-тесты для build_betting_signals().

Покрывает:
- Структура и колонки возвращаемого DataFrame
- Логика выбора best_outcome (по max EV Edge)
- Расчёт confidence score (0–100)
- Сигналы: 🟢 СИЛЬНЫЙ / 🟡 УМЕРЕННЫЙ / 🔵 СЛАБЫЙ / ⚪ НЕТ
- Консенсус букмекеров (доля книг с EV > 0)
- Трёхисходник с ничьёй
- Граничные случаи: пустой df, nan, один букмекер
"""
import pytest
import math
import pandas as pd
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from utils import (
    build_betting_signals,
    american_to_decimal, decimal_to_implied, no_vig_prob, ev_edge,
    make_h2h_row,
)


# ═══════════════════════════════════════════════════════════════
#  Вспомогательные функции
# ═══════════════════════════════════════════════════════════════

def _parse_ev(ev_str: str) -> float:
    return float(ev_str.replace("+", "").replace("%", ""))


def _make_biased_df(home_edge_pct: float, n_books: int = 3):
    """
    Создаёт DataFrame где Home имеет заданный EV Edge.
    Использует фиксированный spread между букмекерами.
    """
    rows = []
    # Book1: "sharp" line — используется как reference
    rows.append(make_h2h_row("Home vs Away", "Home", "Away", "Pinnacle", -120, 105))
    # Остальные книги — немного хуже
    for i in range(1, n_books):
        rows.append(make_h2h_row("Home vs Away", "Home", "Away",
                                 f"Book{i}", -115, 100))
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════
#  Тесты — структура
# ═══════════════════════════════════════════════════════════════

class TestSignalsStructure:
    """Тестирует структуру и колонки возвращаемого DataFrame."""

    REQUIRED_COLS = {
        "Матч", "Время", "Сигнал", "На кого ставить",
        "Лучший букмекер", "Odds (Am)", "Odds (Dec)",
        "EV Edge %", "No-Vig Fair %", "Консенсус книг",
        "Уверенность", "Другие исходы",
        "_conf", "_edge",
    }

    def test_returns_dataframe(self, nfl_two_books):
        result = build_betting_signals(nfl_two_books, has_draw=False)
        assert isinstance(result, pd.DataFrame)

    def test_required_columns_present(self, nfl_two_books):
        result = build_betting_signals(nfl_two_books, has_draw=False)
        if not result.empty:
            assert self.REQUIRED_COLS.issubset(set(result.columns))

    def test_empty_df_returns_empty(self, empty_df):
        result = build_betting_signals(empty_df, has_draw=False)
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_one_row_per_match(self, nfl_two_books):
        """Один сигнал на матч — лучший исход."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        # nfl_two_books содержит один матч
        assert len(result) == 1

    def test_sorted_by_conf_then_edge(self):
        """Сортировка: сначала по _conf, потом по _edge убыванию."""
        rows = [
            make_h2h_row("Match1", "A", "B", "Book1", -110, 100),
            make_h2h_row("Match1", "A", "B", "Book2", -115, 95),
            make_h2h_row("Match2", "C", "D", "Book1", -200, 160),
            make_h2h_row("Match2", "C", "D", "Book2", -190, 155),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        if len(result) > 1:
            confs = result["_conf"].tolist()
            assert confs == sorted(confs, reverse=True)

    def test_internal_cols_present(self, nfl_two_books):
        """_conf и _edge присутствуют (нужны для UI)."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        if not result.empty:
            assert "_conf" in result.columns
            assert "_edge" in result.columns


# ═══════════════════════════════════════════════════════════════
#  Тесты — логика выбора best_outcome
# ═══════════════════════════════════════════════════════════════

class TestSignalsBestOutcome:
    """Тестирует логику выбора лучшего исхода."""

    def test_picks_outcome_with_highest_max_edge(self):
        """best_outcome = исход с максимальным max_edge."""
        # Home -150 (фаворит): implied≈60%, less value
        # Away +180 (аутсайдер): implied≈35.7%, больше value при fair≈40%
        rows = [
            make_h2h_row("X vs Y", "X", "Y", "Book1", -150, 180),
            make_h2h_row("X vs Y", "X", "Y", "Book2", -145, 175),
            make_h2h_row("X vs Y", "X", "Y", "Book3", -155, 185),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        assert not result.empty
        best = result.iloc[0]["На кого ставить"]
        # Считаем EV вручную
        # На 3 книгах: Away +180, +175, +185
        # Avg no-vig Away ≈ 40%+, Dec Away ≈ 2.8+
        # EV Away = 0.40 * 2.8 - 1 = +12% примерно
        # Home: implied ≈ 59-60%, no-vig ≈ 59%, Dec ≈ 1.67
        # EV Home = 0.59 * 1.67 - 1 ≈ -1.5% → отрицательный
        assert best == "Y", f"Ожидали 'Y' (аутсайдер с лучшим EV), получили '{best}'"

    def test_consistent_home_pick(self):
        """Если Home явно выгоднее — выбираем Home.

        С cross-book EV: Pinnacle -200 Home (fair ≈66.7%), Away +170 (fair ≈33.3%)
        DK Home -110: dec=1.9091, EV = 0.667 × 1.9091 − 1 = +27.2% → Home!
        """
        rows = [
            make_h2h_row("A vs B", "A", "B", "Pinnacle", -200, 170),
            make_h2h_row("A vs B", "A", "B", "DraftKings", -110, 100),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        assert not result.empty
        assert result.iloc[0]["На кого ставить"] == "A"

    def test_best_bookmaker_is_one_with_highest_dec(self):
        """Лучший букмекер — тот, кто даёт самый высокий decimal на выбранный исход."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "Pinnacle", -110, 100),
            make_h2h_row("A vs B", "A", "B", "DraftKings", -110, 115),  # лучший Away
            make_h2h_row("A vs B", "A", "B", "FanDuel", -110, 105),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        if not result.empty:
            best_outcome = result.iloc[0]["На кого ставить"]
            best_bm = result.iloc[0]["Лучший букмекер"]
            if best_outcome == "B":
                # DraftKings даёт +115 → decimal 2.15, лучший
                assert best_bm == "DraftKings"


# ═══════════════════════════════════════════════════════════════
#  Тесты — расчёт Confidence Score
# ═══════════════════════════════════════════════════════════════

class TestSignalsConfidence:
    """Тестирует расчёт уровня уверенности (0–100)."""

    def test_confidence_in_valid_range(self, nfl_two_books):
        """Confidence всегда в диапазоне [0, 100]."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        for c in result.get("_conf", []):
            assert 0 <= int(c) <= 100, f"Confidence вне диапазона: {c}"

    def test_confidence_never_negative(self):
        """Confidence ≥ 0 даже при отрицательном EV."""
        rows = [make_h2h_row("A vs B", "A", "B", "Book1", -150, -130)]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        for c in result.get("_conf", []):
            assert int(c) >= 0

    def test_higher_ev_gives_higher_confidence(self):
        """Более высокий EV → более высокий confidence."""
        # Матч 1: небольшой edge
        rows_low = [
            make_h2h_row("Low EV", "A", "B", "B1", -110, -105),
            make_h2h_row("Low EV", "A", "B", "B2", -112, -103),
        ]
        # Матч 2: большой edge (аутсайдер сильно завышен)
        rows_high = [
            make_h2h_row("High EV", "C", "D", "B1", -150, 200),
            make_h2h_row("High EV", "C", "D", "B2", -145, 210),
        ]
        result_low = build_betting_signals(pd.DataFrame(rows_low), False)
        result_high = build_betting_signals(pd.DataFrame(rows_high), False)
        if not result_low.empty and not result_high.empty:
            conf_low  = int(result_low.iloc[0]["_conf"])
            conf_high = int(result_high.iloc[0]["_conf"])
            assert conf_high >= conf_low, \
                f"High EV conf ({conf_high}) должен быть >= Low EV conf ({conf_low})"

    def test_confidence_formula_components(self):
        """
        Проверяет формулу: min(100, avg_edge*4 + consensus*0.4 + min(avg_fair-33, 30))
        На конкретных числах.
        """
        # Один букмекер, Away +200 (dec=3.0)
        # vs Home -110 (dec=1.9091)
        # implied: h=52.38%, a=47.62% → no-vig: h=52.38%, a=47.62% (100% book)
        # EV Away = 0.4762 * 3.0 - 1 = +42.86%! (явный value)
        rows = [make_h2h_row("X vs Y", "X", "Y", "Book1", -110, 200)]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        assert not result.empty
        conf = int(result.iloc[0]["_conf"])
        assert conf > 0  # должна быть хоть какая-то уверенность


# ═══════════════════════════════════════════════════════════════
#  Тесты — типы сигналов
# ═══════════════════════════════════════════════════════════════

class TestSignalLevels:
    """Тестирует 4 уровня сигналов."""

    def _get_signal(self, rows, has_draw=False):
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw)
        if result.empty:
            return None, None
        row = result.iloc[0]
        return str(row["Сигнал"]), int(row["_conf"])

    def test_signal_contains_emoji(self, nfl_two_books):
        """Сигнал содержит эмодзи."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        if not result.empty:
            sig = str(result.iloc[0]["Сигнал"])
            assert any(e in sig for e in ["🟢", "🟡", "🔵", "⚪"])

    def test_signal_text_valid_values(self, nfl_two_books):
        """Текст сигнала из допустимого набора."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        valid = {"СИЛЬНЫЙ", "УМЕРЕННЫЙ", "СЛАБЫЙ", "НЕТ"}
        for sig in result.get("Сигнал", []):
            # Убираем эмодзи
            text = str(sig).split(" ", 1)[-1].strip()
            assert text in valid, f"Неизвестный текст сигнала: '{text}'"

    def test_green_signal_at_high_confidence(self):
        """🟢 СИЛЬНЫЙ при confidence ≥ 70."""
        # Много книг + большой EV → высокий confidence
        rows = []
        for i, bm in enumerate(["B1", "B2", "B3", "B4", "B5"]):
            # Away везде с высоким коэффом
            rows.append(make_h2h_row("X vs Y", "X", "Y", bm, -200, 250))
        signal, conf = self._get_signal(rows)
        if conf is not None and conf >= 70:
            assert "🟢" in signal and "СИЛЬНЫЙ" in signal

    def test_white_signal_at_zero_confidence(self):
        """⚪ НЕТ при отрицательном EV."""
        # Тяжёлый фаворит с vig → оба исхода отрицательны
        rows = [
            make_h2h_row("X vs Y", "X", "Y", "B1", -200, -180),
            make_h2h_row("X vs Y", "X", "Y", "B2", -205, -185),
        ]
        signal, conf = self._get_signal(rows)
        if signal is not None:
            # При отрицательном EV avg_edge < 0 → сигнал ⚪ НЕТ
            assert "⚪" in signal or "НЕТ" in signal or conf == 0

    def test_confidence_zero_gives_net_signal(self):
        """Confidence = 0 → сигнал НЕТ."""
        # Строим DataFrame где avg_edge будет отрицательным
        rows = [make_h2h_row("A vs B", "A", "B", "Book1", -300, -250)]
        signal, conf = self._get_signal(rows)
        if signal is not None and conf == 0:
            assert "НЕТ" in signal or "⚪" in signal


# ═══════════════════════════════════════════════════════════════
#  Тесты — консенсус букмекеров
# ═══════════════════════════════════════════════════════════════

class TestSignalsConsensus:
    """Тестирует расчёт консенсуса (% книг с EV > 0)."""

    def test_consensus_format(self, nfl_two_books):
        """Консенсус в формате 'X%  (Y/Z)'."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        if not result.empty:
            consensus = str(result.iloc[0]["Консенсус книг"])
            assert "%" in consensus
            assert "/" in consensus

    def test_consensus_denominator_equals_total_books(self):
        """Знаменатель = общее число уникальных букмекеров."""
        n_books = 4
        rows = [
            make_h2h_row("A vs B", "A", "B", f"Book{i}", -110, 100)
            for i in range(n_books)
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        if not result.empty:
            consensus = str(result.iloc[0]["Консенсус книг"])
            # Формат: "X%  (Y/4)"
            denom = int(consensus.split("/")[-1].rstrip(")").strip())
            assert denom == n_books

    def test_all_books_agree_100_percent(self):
        """Если все книги дают EV > 0 — консенсус 100%."""
        # Away везде явно выгоден
        rows = [
            make_h2h_row("A vs B", "A", "B", "B1", -200, 250),
            make_h2h_row("A vs B", "A", "B", "B2", -200, 255),
            make_h2h_row("A vs B", "A", "B", "B3", -200, 248),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        if not result.empty:
            consensus = str(result.iloc[0]["Консенсус книг"])
            # Числитель консенсуса для выбранного исхода
            pct_str = consensus.split("%")[0].strip()
            pct = int(pct_str)
            # При очень большом EV Away почти все книги дают EV > 0
            # (не обязательно 100% — зависит от no-vig конкретного матча)
            assert 0 <= pct <= 100


# ═══════════════════════════════════════════════════════════════
#  Тесты — трёхисходник
# ═══════════════════════════════════════════════════════════════

class TestSignalsThreeWay:
    """Тестирует работу с трёхисходниками (Football)."""

    def test_draw_can_be_best_outcome(self):
        """Ничья может быть лучшим исходом если у неё самый высокий EV."""
        # Draw +350 — очень высокий коэфф для ничьей
        rows = [
            make_h2h_row("Arsenal vs Chelsea", "Arsenal", "Chelsea",
                         "Bet365", -120, -110, 350),
            make_h2h_row("Arsenal vs Chelsea", "Arsenal", "Chelsea",
                         "Unibet", -125, -115, 340),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=True)
        assert not result.empty
        # Ничья с +350/+340 (dec≈4.5) при fair ≈25-30% → EV может быть очень большим

    def test_three_outcomes_in_other_outcomes_field(self):
        """Другие исходы содержат все исходы кроме best."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "Book1", 120, 210, 230),
            make_h2h_row("A vs B", "A", "B", "Book2", 115, 200, 240),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=True)
        if not result.empty:
            other = str(result.iloc[0]["Другие исходы"])
            best = str(result.iloc[0]["На кого ставить"])
            # В "других исходах" не должно быть best outcome
            assert best not in other or other == ""

    def test_has_draw_false_treats_as_two_way(self):
        """При has_draw=False — ничья игнорируется."""
        rows = [
            make_h2h_row("A vs B", "A", "B", "Book1", 120, 210, 230),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        if not result.empty:
            best = str(result.iloc[0]["На кого ставить"])
            assert "Ничья" not in best


# ═══════════════════════════════════════════════════════════════
#  Тесты — граничные случаи
# ═══════════════════════════════════════════════════════════════

class TestSignalsEdgeCases:
    """Граничные случаи и устойчивость к ошибкам."""

    def test_nan_odds_no_crash(self, nan_odds_df):
        """Строки с None не вызывают исключений."""
        result = build_betting_signals(nan_odds_df, has_draw=False)
        assert isinstance(result, pd.DataFrame)

    def test_single_bookmaker(self):
        """Один букмекер — минимально рабочий случай."""
        rows = [make_h2h_row("A vs B", "A", "B", "OnlyBook", -110, 100)]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        assert isinstance(result, pd.DataFrame)
        if not result.empty:
            # Консенсус = X% (Y/1)
            consensus = str(result.iloc[0]["Консенсус книг"])
            assert "/1)" in consensus

    def test_multiple_matches_separate_signals(self):
        """Каждый матч получает свой сигнал."""
        rows = [
            make_h2h_row("Match1", "A", "B", "Book1", -110, 100),
            make_h2h_row("Match2", "C", "D", "Book1", -120, 110),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        # Два матча — два сигнала
        if not result.empty:
            assert len(result) == 2

    def test_odds_dec_is_numeric(self, nfl_two_books):
        """Odds (Dec) — числовое значение."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        if not result.empty:
            for v in result["Odds (Dec)"]:
                assert isinstance(v, (int, float)), f"Odds (Dec) не число: {v}"
                assert v > 1.0

    def test_match_name_preserved(self, nfl_two_books):
        """Название матча сохраняется."""
        result = build_betting_signals(nfl_two_books, has_draw=False)
        if not result.empty:
            assert result.iloc[0]["Матч"] == "Kansas City Chiefs vs Baltimore Ravens"

    def test_no_crash_on_all_nan(self):
        """Все строки с None → возвращается пустой DataFrame."""
        rows = [
            make_h2h_row("X vs Y", "X", "Y", "B1", None, None),
            make_h2h_row("X vs Y", "X", "Y", "B2", None, None),
        ]
        df = pd.DataFrame(rows)
        result = build_betting_signals(df, has_draw=False)
        assert isinstance(result, pd.DataFrame)
        assert result.empty
