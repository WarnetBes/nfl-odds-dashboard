"""
test_historical_odds.py — тесты для исторических коэффициентов.

Покрывает:
  1. fetch_historical_odds() — корректный URL, параметры, парсинг ответа
  2. fetch_historical_odds() — ошибки (non-200, network exception, пустой data)
  3. parse_historical_to_df() — h2h, spreads, totals, пустой вход
  4. parse_historical_to_df() — draw outcome (soccer)
"""
import sys
import pathlib
import pytest
import pandas as pd
from unittest.mock import MagicMock

ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from utils import fetch_historical_odds, parse_historical_to_df


# ─────────────────────────────────────────────────────────────────
#  Sample API responses
# ─────────────────────────────────────────────────────────────────

SAMPLE_HIST_RESPONSE = {
    "timestamp": "2024-01-15T12:00:00Z",
    "data": [
        {
            "id": "hist1",
            "sport_key": "americanfootball_nfl",
            "commence_time": "2024-01-15T20:00:00Z",
            "home_team": "Kansas City Chiefs",
            "away_team": "Baltimore Ravens",
            "bookmakers": [
                {
                    "key": "draftkings",
                    "title": "DraftKings",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Kansas City Chiefs", "price": -145},
                                {"name": "Baltimore Ravens", "price": 125},
                            ],
                        }
                    ],
                },
                {
                    "key": "fanduel",
                    "title": "FanDuel",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Kansas City Chiefs", "price": -150},
                                {"name": "Baltimore Ravens", "price": 130},
                            ],
                        }
                    ],
                },
            ],
        }
    ],
}

SAMPLE_HIST_SPREADS = {
    "timestamp": "2024-01-15T12:00:00Z",
    "data": [
        {
            "id": "hist_sp1",
            "sport_key": "americanfootball_nfl",
            "commence_time": "2024-01-15T20:00:00Z",
            "home_team": "Dallas Cowboys",
            "away_team": "Philadelphia Eagles",
            "bookmakers": [
                {
                    "key": "pinnacle",
                    "title": "Pinnacle",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Dallas Cowboys", "price": -110, "point": -3.0},
                                {"name": "Philadelphia Eagles", "price": -110, "point": 3.0},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}

SAMPLE_HIST_TOTALS = {
    "timestamp": "2024-01-15T12:00:00Z",
    "data": [
        {
            "id": "hist_t1",
            "sport_key": "americanfootball_nfl",
            "commence_time": "2024-01-15T20:00:00Z",
            "home_team": "Dallas Cowboys",
            "away_team": "Philadelphia Eagles",
            "bookmakers": [
                {
                    "key": "betmgm",
                    "title": "BetMGM",
                    "markets": [
                        {
                            "key": "totals",
                            "outcomes": [
                                {"name": "Over", "price": -110, "point": 47.5},
                                {"name": "Under", "price": -110, "point": 47.5},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}

SAMPLE_HIST_DRAW = {
    "timestamp": "2024-03-01T12:00:00Z",
    "data": [
        {
            "id": "hist_epl1",
            "sport_key": "soccer_epl",
            "commence_time": "2024-03-01T15:00:00Z",
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "bookmakers": [
                {
                    "key": "bet365",
                    "title": "Bet365",
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [
                                {"name": "Arsenal", "price": 120},
                                {"name": "Chelsea", "price": 210},
                                {"name": "Draw", "price": 230},
                            ],
                        }
                    ],
                }
            ],
        }
    ],
}


def _mock_session(status_code, json_body):
    """Create a mock HTTP session returning the given response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    session = MagicMock()
    session.get.return_value = resp
    return session


# ─────────────────────────────────────────────────────────────────
#  ГРУППА 1: fetch_historical_odds
# ─────────────────────────────────────────────────────────────────

class TestFetchHistoricalOdds:

    def test_success_returns_data_and_timestamp(self):
        session = _mock_session(200, SAMPLE_HIST_RESPONSE)
        data, ts = fetch_historical_odds(
            "test-key", "americanfootball_nfl", "us", "h2h",
            "2024-01-15T12:00:00Z", session=session,
        )
        assert data is not None
        assert len(data) == 1
        assert ts == "2024-01-15T12:00:00Z"

    def test_correct_url_and_params(self):
        session = _mock_session(200, SAMPLE_HIST_RESPONSE)
        fetch_historical_odds(
            "my-key", "americanfootball_nfl", "us,eu", "h2h",
            "2024-01-15T12:00:00Z", session=session,
        )
        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        assert "/historical/sports/americanfootball_nfl/odds" in args[0]
        params = kwargs["params"]
        assert params["apiKey"] == "my-key"
        assert params["regions"] == "us,eu"
        assert params["markets"] == "h2h"
        assert params["date"] == "2024-01-15T12:00:00Z"
        assert params["oddsFormat"] == "american"

    def test_non_200_returns_none(self):
        session = _mock_session(401, {"message": "Unauthorized"})
        data, ts = fetch_historical_odds(
            "bad-key", "americanfootball_nfl", "us", "h2h",
            "2024-01-15T12:00:00Z", session=session,
        )
        assert data is None
        assert ts is None

    def test_network_error_returns_none(self):
        session = MagicMock()
        session.get.side_effect = ConnectionError("timeout")
        data, ts = fetch_historical_odds(
            "key", "americanfootball_nfl", "us", "h2h",
            "2024-01-15T12:00:00Z", session=session,
        )
        assert data is None
        assert ts is None

    def test_empty_data_returns_empty_list(self):
        session = _mock_session(200, {"timestamp": "2024-01-15T12:00:00Z", "data": []})
        data, ts = fetch_historical_odds(
            "key", "americanfootball_nfl", "us", "h2h",
            "2024-01-15T12:00:00Z", session=session,
        )
        assert data == []
        assert ts == "2024-01-15T12:00:00Z"

    def test_missing_timestamp_falls_back_to_date_iso(self):
        session = _mock_session(200, {"data": [{"id": "x"}]})
        data, ts = fetch_historical_odds(
            "key", "americanfootball_nfl", "us", "h2h",
            "2024-06-01T00:00:00Z", session=session,
        )
        assert ts == "2024-06-01T00:00:00Z"

    def test_422_returns_none(self):
        session = _mock_session(422, {"message": "Invalid date"})
        data, ts = fetch_historical_odds(
            "key", "americanfootball_nfl", "us", "h2h",
            "1999-01-01T00:00:00Z", session=session,
        )
        assert data is None
        assert ts is None


# ─────────────────────────────────────────────────────────────────
#  ГРУППА 2: parse_historical_to_df — H2H
# ─────────────────────────────────────────────────────────────────

class TestParseHistoricalH2H:

    def test_basic_h2h_parse(self):
        df = parse_historical_to_df(SAMPLE_HIST_RESPONSE["data"], "h2h", False)
        assert not df.empty
        assert len(df) == 2  # 2 bookmakers
        assert "Матч" in df.columns
        assert "Букмекер" in df.columns
        assert "Odds Хозяева (Am)" in df.columns
        assert "Odds Гости (Am)" in df.columns

    def test_h2h_no_draw_column_is_none(self):
        df = parse_historical_to_df(SAMPLE_HIST_RESPONSE["data"], "h2h", False)
        assert all(v is None for v in df["Odds Ничья (Am)"])

    def test_h2h_match_format(self):
        df = parse_historical_to_df(SAMPLE_HIST_RESPONSE["data"], "h2h", False)
        assert df["Матч"].iloc[0] == "Baltimore Ravens @ Kansas City Chiefs"

    def test_h2h_bookmaker_names(self):
        df = parse_historical_to_df(SAMPLE_HIST_RESPONSE["data"], "h2h", False)
        bms = set(df["Букмекер"])
        assert "DraftKings" in bms
        assert "FanDuel" in bms

    def test_h2h_odds_values(self):
        df = parse_historical_to_df(SAMPLE_HIST_RESPONSE["data"], "h2h", False)
        dk = df[df["Букмекер"] == "DraftKings"].iloc[0]
        assert dk["Odds Хозяева (Am)"] == -145
        assert dk["Odds Гости (Am)"] == 125


# ─────────────────────────────────────────────────────────────────
#  ГРУППА 3: parse_historical_to_df — Spreads
# ─────────────────────────────────────────────────────────────────

class TestParseHistoricalSpreads:

    def test_spreads_parse(self):
        df = parse_historical_to_df(SAMPLE_HIST_SPREADS["data"], "spreads", False)
        assert not df.empty
        assert len(df) == 1
        assert "Спред Хозяева" in df.columns
        assert "Спред Гости" in df.columns

    def test_spreads_values(self):
        df = parse_historical_to_df(SAMPLE_HIST_SPREADS["data"], "spreads", False)
        row = df.iloc[0]
        assert row["Спред Хозяева"] == -3.0
        assert row["Спред Гости"] == 3.0
        assert row["Odds Хозяева (Am)"] == -110


# ─────────────────────────────────────────────────────────────────
#  ГРУППА 4: parse_historical_to_df — Totals
# ─────────────────────────────────────────────────────────────────

class TestParseHistoricalTotals:

    def test_totals_parse(self):
        df = parse_historical_to_df(SAMPLE_HIST_TOTALS["data"], "totals", False)
        assert not df.empty
        assert "Тотал Линия" in df.columns
        assert "Odds Over (Am)" in df.columns
        assert "Odds Under (Am)" in df.columns

    def test_totals_values(self):
        df = parse_historical_to_df(SAMPLE_HIST_TOTALS["data"], "totals", False)
        row = df.iloc[0]
        assert row["Тотал Линия"] == 47.5
        assert row["Odds Over (Am)"] == -110
        assert row["Odds Under (Am)"] == -110


# ─────────────────────────────────────────────────────────────────
#  ГРУППА 5: parse_historical_to_df — Draw (soccer)
# ─────────────────────────────────────────────────────────────────

class TestParseHistoricalDraw:

    def test_draw_included_when_has_draw(self):
        df = parse_historical_to_df(SAMPLE_HIST_DRAW["data"], "h2h", True)
        assert not df.empty
        assert df["Odds Ничья (Am)"].iloc[0] == 230

    def test_draw_excluded_when_no_draw(self):
        df = parse_historical_to_df(SAMPLE_HIST_DRAW["data"], "h2h", False)
        assert all(v is None for v in df["Odds Ничья (Am)"])


# ─────────────────────────────────────────────────────────────────
#  ГРУППА 6: Edge cases
# ─────────────────────────────────────────────────────────────────

class TestParseHistoricalEdgeCases:

    def test_empty_events_returns_empty_df(self):
        df = parse_historical_to_df([], "h2h", False)
        assert df.empty

    def test_event_without_bookmakers(self):
        events = [{"id": "x", "home_team": "A", "away_team": "B",
                    "commence_time": "", "bookmakers": []}]
        df = parse_historical_to_df(events, "h2h", False)
        assert df.empty

    def test_mismatched_market_key_skipped(self):
        events = [
            {
                "id": "x",
                "home_team": "A",
                "away_team": "B",
                "commence_time": "",
                "bookmakers": [
                    {
                        "key": "bk",
                        "title": "BK",
                        "markets": [
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -110, "point": 45},
                                    {"name": "Under", "price": -110, "point": 45},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        df = parse_historical_to_df(events, "h2h", False)
        assert df.empty

    def test_multiple_events_parsed(self):
        events = SAMPLE_HIST_RESPONSE["data"] + SAMPLE_HIST_DRAW["data"]
        df = parse_historical_to_df(events, "h2h", True)
        assert len(df) == 3  # 2 from NFL + 1 from EPL
        assert df["Матч"].nunique() == 2
