"""
conftest.py — общие фикстуры и импорты для всех тестов.

Импортирует функции из utils.py (чистый Python, без Streamlit).
"""
import sys
import pathlib
import pytest
import pandas as pd

# Добавляем корень проекта в sys.path
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Импортируем функции из utils.py (без Streamlit)
from utils import (
    american_to_decimal,
    decimal_to_implied,
    no_vig_prob,
    ev_edge,
    fmt_am,
    compute_value_bets,
    build_betting_signals,
    make_h2h_row,
)



# ─────────────────────────────────────────────────────────────────
#  Fixtures
# ─────────────────────────────────────────────────────────────────

@pytest.fixture
def nfl_two_books():
    """
    Два букмекера на один матч NFL (без ничьей).
    DraftKings: Chiefs -110 / Ravens +100
    FanDuel:    Chiefs -115 / Ravens +105
    """
    rows = [
        make_h2h_row("Kansas City Chiefs vs Baltimore Ravens",
                     "Kansas City Chiefs", "Baltimore Ravens",
                     "DraftKings", -110, 100),
        make_h2h_row("Kansas City Chiefs vs Baltimore Ravens",
                     "Kansas City Chiefs", "Baltimore Ravens",
                     "FanDuel", -115, 105),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def nfl_value_bet():
    """
    Два букмекера — Pinnacle (sharp) vs DraftKings с завышенным Away.
    Eagles +200 у DraftKings vs Pinnacle Eagles +105 → явный value bet.
    """
    rows = [
        make_h2h_row("Dallas Cowboys vs Philadelphia Eagles",
                     "Dallas Cowboys", "Philadelphia Eagles",
                     "Pinnacle", -120, 105),
        make_h2h_row("Dallas Cowboys vs Philadelphia Eagles",
                     "Dallas Cowboys", "Philadelphia Eagles",
                     "DraftKings", -120, 200),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def football_three_way():
    """Матч EPL с ничьей (3-исходник), два букмекера."""
    rows = [
        make_h2h_row("Arsenal vs Chelsea", "Arsenal", "Chelsea",
                     "Bet365", 120, 210, 230),
        make_h2h_row("Arsenal vs Chelsea", "Arsenal", "Chelsea",
                     "Unibet", 115, 200, 240),
    ]
    return pd.DataFrame(rows)


@pytest.fixture
def empty_df():
    return pd.DataFrame()


@pytest.fixture
def nan_odds_df():
    """DataFrame с None в коэффициентах — должен обрабатываться без краша."""
    rows = [
        make_h2h_row("Team A vs Team B", "Team A", "Team B",
                     "BadBook", None, None),
        make_h2h_row("Team A vs Team B", "Team A", "Team B",
                     "GoodBook", -110, +110),
    ]
    return pd.DataFrame(rows)
