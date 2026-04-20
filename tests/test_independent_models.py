"""
tests/test_independent_models.py
Тесты для новых независимых моделей (блоки 11–17 utils.py).
Не затрагивают существующие тесты и функции ядра.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from utils import (
    elo_expected_prob,
    elo_update_pair,
    elo_edge_vs_market,
    clv_pct,
    avg_clv_pct,
    bayesian_shrink_prob,
    market_efficiency_score,
    compute_srs,
    srs_projected_spread,
    poisson_pmf,
    poisson_over_prob,
    composite_independent_score,
)


# ─────────────────────────────────────────────────────────────────────────────
#  11. Elo Rating
# ─────────────────────────────────────────────────────────────────────────────

def test_elo_expected_prob_symmetric():
    """При равных рейтингах хозяева чуть фавориты (home advantage)."""
    p = elo_expected_prob(1500, 1500, "default")
    assert 0.55 < p < 0.65, f"Ожидали 0.55–0.65, получили {p}"


def test_elo_expected_prob_returns_0_to_1():
    """Вероятность всегда в [0, 1]."""
    assert 0 < elo_expected_prob(1200, 1800, "americanfootball_nfl") < 1
    assert 0 < elo_expected_prob(1800, 1200, "basketball_nba") < 1


def test_elo_update_pair_home_win_increases_rating():
    """После победы хозяев их рейтинг растёт, гостей — падает."""
    new_home, new_away = elo_update_pair(1500, 1500, True, "default")
    assert new_home > 1500
    assert new_away < 1500


def test_elo_update_pair_away_win():
    """После победы гостей их рейтинг растёт."""
    new_home, new_away = elo_update_pair(1500, 1500, False, "soccer_epl")
    assert new_home < 1500
    assert new_away > 1500


def test_elo_edge_vs_market_positive():
    """Elo выше рынка → положительный edge."""
    assert elo_edge_vs_market(0.57, 52.0) > 0


def test_elo_edge_vs_market_negative():
    """Elo ниже рынка → отрицательный edge."""
    assert elo_edge_vs_market(0.45, 52.0) < 0


# ─────────────────────────────────────────────────────────────────────────────
#  12. CLV
# ─────────────────────────────────────────────────────────────────────────────

def test_clv_positive_when_close_worse_than_open():
    """
    CLV = 1/open - 1/close.
    close=2.00 < open=2.10 → implied close > implied open → CLV < 0 (rynok sdvinulsya ne v nashu polzu).
    CLV > 0 esli implied open > implied close, t.e. open_dec < close_dec.
    """
    # open=2.00, close=2.10: 1/2.00=0.50 > 1/2.10=0.476 → CLV > 0 (ставили хуже чем closing)
    assert clv_pct(2.00, 2.10) > 0


def test_clv_negative_when_close_better_than_open():
    """Ставили по худшей цене (open 2.10 vs close 2.00) → отрицательный CLV."""
    # 1/2.10 < 1/2.00 → CLV < 0
    assert clv_pct(2.10, 2.00) < 0


def test_clv_zero_on_invalid():
    """Нулевые или отрицательные odds → 0.0."""
    assert clv_pct(0, 2.0) == 0.0
    assert clv_pct(2.0, 0) == 0.0


def test_avg_clv_pct_empty():
    assert avg_clv_pct([]) == 0.0


def test_avg_clv_pct_values():
    vals = [2.0, 4.0, 6.0]
    assert abs(avg_clv_pct(vals) - 4.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
#  13. Bayesian Shrinkage
# ─────────────────────────────────────────────────────────────────────────────

def test_bayesian_shrink_prob_pulls_to_50_at_1_book():
    """При 1 букмекере вероятность сильно сдвигается к 50%."""
    raw = 62.0
    shrunk = bayesian_shrink_prob(raw, n_books=1)
    assert 50.0 < shrunk < raw


def test_bayesian_shrink_prob_less_shrink_at_10_books():
    """При 10 букмекерах сдвиг минимальный."""
    raw = 62.0
    shrunk_1  = bayesian_shrink_prob(raw, n_books=1)
    shrunk_10 = bayesian_shrink_prob(raw, n_books=10)
    assert shrunk_10 > shrunk_1  # Меньше сдвига при большем числе книг


def test_bayesian_shrink_prob_at_50_stays_50():
    """50% не должна сдвигаться."""
    assert bayesian_shrink_prob(50.0, n_books=1) == 50.0


# ─────────────────────────────────────────────────────────────────────────────
#  14. Market Efficiency Score
# ─────────────────────────────────────────────────────────────────────────────

def test_market_efficiency_score_range():
    """MES всегда в [0, 100]."""
    mes = market_efficiency_score([1.91, 1.95, 1.93, 1.92])
    assert 0 <= mes <= 100


def test_market_efficiency_score_perfect_agreement():
    """Абсолютное совпадение odds → MES = 100."""
    mes = market_efficiency_score([2.0, 2.0, 2.0, 2.0])
    assert mes == 100.0


def test_market_efficiency_score_single_value():
    """Один источник → MES = 50 (нейтральный дефолт)."""
    assert market_efficiency_score([2.0]) == 50.0


def test_market_efficiency_score_empty():
    """Пустой список → MES = 50."""
    assert market_efficiency_score([]) == 50.0


def test_market_efficiency_score_high_variance():
    """Большой разброс → низкий MES."""
    mes = market_efficiency_score([1.5, 2.5, 3.5, 4.5])
    assert mes < 50.0


# ─────────────────────────────────────────────────────────────────────────────
#  15. SRS
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_srs_returns_dict():
    games = [
        {"home": "A", "away": "B", "home_score": 24, "away_score": 17},
        {"home": "B", "away": "C", "home_score": 20, "away_score": 10},
        {"home": "C", "away": "A", "home_score": 14, "away_score": 21},
    ]
    ratings = compute_srs(games)
    assert isinstance(ratings, dict)
    assert set(ratings.keys()) == {"A", "B", "C"}


def test_compute_srs_stronger_team_has_higher_rating():
    """
    SRS сходится правильно только при 3+ командах (нужен разный пул соперников).
    Strong должен иметь рейтинг выше Weak.
    """
    games = [
        {"home": "Strong", "away": "Weak",   "home_score": 40, "away_score": 0},
        {"home": "Strong", "away": "Mid",    "home_score": 30, "away_score": 20},
        {"home": "Mid",    "away": "Weak",   "home_score": 25, "away_score": 15},
        {"home": "Weak",   "away": "Mid",    "home_score": 10, "away_score": 28},
    ]
    ratings = compute_srs(games)
    assert ratings["Strong"] > ratings["Weak"]


def test_srs_projected_spread_returns_float():
    spread = srs_projected_spread("A", "B", {"A": 3.2, "B": 1.1}, 2.5)
    assert isinstance(spread, float)


def test_srs_projected_spread_home_adv():
    """Даже при равных рейтингах хозяева фавориты из-за home_adv."""
    spread = srs_projected_spread("A", "B", {"A": 0.0, "B": 0.0}, 2.5)
    assert spread == 2.5


def test_srs_unknown_team_defaults_to_zero():
    """Неизвестная команда → 0.0 в рейтинге."""
    spread = srs_projected_spread("Unknown", "Also Unknown", {}, 3.0)
    assert spread == 3.0


# ─────────────────────────────────────────────────────────────────────────────
#  16. Poisson
# ─────────────────────────────────────────────────────────────────────────────

def test_poisson_pmf_valid():
    p = poisson_pmf(2.5, 2)
    assert 0 < p < 1


def test_poisson_pmf_zero_lambda():
    assert poisson_pmf(0, 2) == 0.0


def test_poisson_pmf_negative_k():
    assert poisson_pmf(2.5, -1) == 0.0


def test_poisson_pmf_k_zero():
    """P(X=0) = e^(-lmbda)"""
    import math
    p = poisson_pmf(2.5, 0)
    assert abs(p - math.exp(-2.5)) < 1e-8


def test_poisson_over_prob_range():
    p = poisson_over_prob(1.4, 1.2, 2.5)
    assert 0 <= p <= 100


def test_poisson_over_prob_high_lambda():
    """При очень высоком лямбда вероятность Over близка к 100%."""
    p = poisson_over_prob(10.0, 10.0, 2.5)
    assert p > 95.0


def test_poisson_over_prob_low_lambda():
    """При очень низком лямбда вероятность Over низкая."""
    p = poisson_over_prob(0.1, 0.1, 2.5)
    assert p < 10.0


# ─────────────────────────────────────────────────────────────────────────────
#  17. Composite Independent Score
# ─────────────────────────────────────────────────────────────────────────────

def test_composite_independent_score_range():
    score = composite_independent_score(4.0, 5.0, 80.0)
    assert 0 <= score <= 100


def test_composite_independent_score_all_zero():
    """Все нули → 0 (только efficiency_signal может дать немного)."""
    score = composite_independent_score(0.0, 0.0, 100.0)
    assert score == 0.0


def test_composite_independent_score_max():
    """Максимальные позитивные входы → близко к 100."""
    score = composite_independent_score(12.0, 10.0, 0.0)
    assert score == 100.0


def test_composite_negative_inputs_clamped():
    """Отрицательные edge → ноль (clamp), не отрицательный скор."""
    score = composite_independent_score(-5.0, -5.0, 50.0)
    assert score >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
#  Регрессионный тест: confidence_score_v2 с bayesian shrinkage
# ─────────────────────────────────────────────────────────────────────────────

def test_confidence_score_v2_unchanged_signature():
    """confidence_score_v2 принимает те же аргументы и возвращает int в [0,100]."""
    from utils import confidence_score_v2
    result = confidence_score_v2(
        avg_ev_pct=5.0,
        max_ev_pct=8.0,
        consensus_pct=70.0,
        n_books=5,
        has_sharp=True,
        fair_prob_pct=55.0,
        sport_threshold=2.0,
    )
    assert isinstance(result, int)
    assert 0 <= result <= 100


def test_confidence_score_v2_more_books_less_shrinkage():
    """
    При большом числе книг shrinkage меньше → fair_prob influence выше
    → confidence при прочих равных выше или равен.
    """
    from utils import confidence_score_v2
    c_few  = confidence_score_v2(5.0, 8.0, 70.0, 1,  True, 65.0)
    c_many = confidence_score_v2(5.0, 8.0, 70.0, 12, True, 65.0)
    # fair_prob=65 → выходит за [30,70], поэтому fp_bonus=0 в обоих случаях
    # но c_many должен иметь больший book_bonus
    assert c_many >= c_few
