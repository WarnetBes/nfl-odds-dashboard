"""
test_live_scores.py — юнит-тесты для Live Scores (ESPN API).

Покрывает:
- parse_espn_event(): парсинг LIVE / Finished / Scheduled событий
- parse_espn_event(): граничные случаи (пустой dict, отсутствие команд, None)
- fetch_scores_from_url(): mock HTTP — 200 OK, пустой events[], ошибка сети,
  404, невалидный JSON, timeout
- Поля: home/away names, scores, venue, note, status_str
- Правильный period_name (Q для NFL/NBA, min для soccer)
"""
import pytest
import sys, pathlib
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from utils import parse_espn_event, fetch_scores_from_url


# ═══════════════════════════════════════════════════════════════
#  Фабрики тестовых данных ESPN
# ═══════════════════════════════════════════════════════════════

def _make_competitor(home_away: str, name: str, abbr: str, score: str = "—") -> dict:
    return {
        "homeAway": home_away,
        "score": score,
        "team": {"displayName": name, "abbreviation": abbr},
    }


def _make_status(state: str, detail: str = "", clock: str = "", period: int = 0) -> dict:
    return {
        "type": {"state": state, "detail": detail},
        "displayClock": clock,
        "period": period,
    }


def _make_event(
    state: str = "pre",
    detail: str = "",
    clock: str = "",
    period: int = 0,
    home_name: str = "Kansas City Chiefs",
    home_abbr: str = "KC",
    home_score: str = "—",
    away_name: str = "Baltimore Ravens",
    away_abbr: str = "BAL",
    away_score: str = "—",
    venue: str = "Arrowhead Stadium",
    city: str = "Kansas City",
    notes: list = None,
    date: str = "2026-01-15T20:20:00Z",
) -> dict:
    """Создаёт минимальный ESPN event dict."""
    return {
        "date": date,
        "competitions": [{
            "status": _make_status(state, detail, clock, period),
            "competitors": [
                _make_competitor("home", home_name, home_abbr, home_score),
                _make_competitor("away", away_name, away_abbr, away_score),
            ],
            "venue": {
                "fullName": venue,
                "address": {"city": city},
            },
            "notes": notes or [],
            "broadcasts": [],
        }],
    }


# ═══════════════════════════════════════════════════════════════
#  Тесты — parse_espn_event: LIVE матч
# ═══════════════════════════════════════════════════════════════

class TestParseEventLive:
    """Матч в состоянии LIVE (state='in')."""

    def test_state_is_in(self):
        ev = _make_event(state="in", clock="7:42", period=2)
        result = parse_espn_event(ev, "Q")
        assert result["state"] == "in"

    def test_status_str_nfl_format(self):
        """NFL: Q{period} · {clock}"""
        ev = _make_event(state="in", clock="7:42", period=2)
        result = parse_espn_event(ev, "Q")
        assert result["status_str"] == "Q2 · 7:42"

    def test_status_str_nba_format(self):
        """NBA: Q{period} · {clock}"""
        ev = _make_event(state="in", clock="3:10", period=4)
        result = parse_espn_event(ev, "Q")
        assert result["status_str"] == "Q4 · 3:10"

    def test_status_str_soccer_format(self):
        """Soccer: {clock}'"""
        ev = _make_event(state="in", clock="67", period=2)
        result = parse_espn_event(ev, "min")
        assert result["status_str"] == "67'"

    def test_home_score_present(self):
        ev = _make_event(state="in", home_score="21", away_score="14",
                         clock="2:00", period=3)
        result = parse_espn_event(ev, "Q")
        assert result["home_score"] == "21"
        assert result["away_score"] == "14"

    def test_clock_preserved(self):
        ev = _make_event(state="in", clock="14:23", period=1)
        result = parse_espn_event(ev, "Q")
        assert result["clock"] == "14:23"

    def test_period_preserved(self):
        ev = _make_event(state="in", period=3)
        result = parse_espn_event(ev, "Q")
        assert result["period"] == 3

    def test_period_name_in_result(self):
        ev = _make_event(state="in", period=2, clock="5:00")
        result = parse_espn_event(ev, "min")
        assert result["period_name"] == "min"


# ═══════════════════════════════════════════════════════════════
#  Тесты — parse_espn_event: Finished матч
# ═══════════════════════════════════════════════════════════════

class TestParseEventFinished:
    """Завершённый матч (state='post')."""

    def test_state_is_post(self):
        ev = _make_event(state="post", detail="Final", home_score="28", away_score="24")
        result = parse_espn_event(ev, "Q")
        assert result["state"] == "post"

    def test_status_str_contains_flag(self):
        """Статус начинается с 🏁"""
        ev = _make_event(state="post", detail="Final")
        result = parse_espn_event(ev, "Q")
        assert result["status_str"].startswith("🏁")

    def test_status_str_contains_detail(self):
        ev = _make_event(state="post", detail="Final/OT")
        result = parse_espn_event(ev, "Q")
        assert "Final/OT" in result["status_str"]

    def test_final_scores_extracted(self):
        ev = _make_event(state="post", detail="Final",
                         home_score="35", away_score="17")
        result = parse_espn_event(ev, "Q")
        assert result["home_score"] == "35"
        assert result["away_score"] == "17"

    def test_detail_preserved(self):
        ev = _make_event(state="post", detail="Final/2OT")
        result = parse_espn_event(ev, "Q")
        assert result["detail"] == "Final/2OT"

    def test_period_zero_for_finished(self):
        """Для завершённых матчей period может быть 0."""
        ev = _make_event(state="post", period=0)
        result = parse_espn_event(ev, "Q")
        assert result["state"] == "post"


# ═══════════════════════════════════════════════════════════════
#  Тесты — parse_espn_event: Scheduled матч
# ═══════════════════════════════════════════════════════════════

class TestParseEventScheduled:
    """Запланированный матч (state='pre')."""

    def test_state_is_pre(self):
        ev = _make_event(state="pre", detail="7:00 PM ET")
        result = parse_espn_event(ev, "Q")
        assert result["state"] == "pre"

    def test_status_str_starts_with_calendar(self):
        """Статус начинается с 📅"""
        ev = _make_event(state="pre", detail="7:00 PM ET")
        result = parse_espn_event(ev, "Q")
        assert result["status_str"].startswith("📅")

    def test_score_is_dash_before_kickoff(self):
        """До начала матча счёт — '—'."""
        ev = _make_event(state="pre")
        result = parse_espn_event(ev, "Q")
        assert result["home_score"] == "—"
        assert result["away_score"] == "—"


# ═══════════════════════════════════════════════════════════════
#  Тесты — parse_espn_event: Команды и venue
# ═══════════════════════════════════════════════════════════════

class TestParseEventTeams:
    """Проверяет корректность извлечения команд."""

    def test_home_name_extracted(self):
        ev = _make_event(home_name="Los Angeles Lakers", home_abbr="LAL")
        result = parse_espn_event(ev, "Q")
        assert result["home_name"] == "Los Angeles Lakers"

    def test_away_name_extracted(self):
        ev = _make_event(away_name="Boston Celtics", away_abbr="BOS")
        result = parse_espn_event(ev, "Q")
        assert result["away_name"] == "Boston Celtics"

    def test_home_abbr_extracted(self):
        ev = _make_event(home_abbr="KC")
        result = parse_espn_event(ev, "Q")
        assert result["home_abbr"] == "KC"

    def test_away_abbr_extracted(self):
        ev = _make_event(away_abbr="PHI")
        result = parse_espn_event(ev, "Q")
        assert result["away_abbr"] == "PHI"

    def test_venue_extracted(self):
        ev = _make_event(venue="SoFi Stadium", city="Inglewood")
        result = parse_espn_event(ev, "Q")
        assert result["venue"] == "SoFi Stadium"
        assert result["city"] == "Inglewood"

    def test_home_away_assignment_correct(self):
        """home/away определяется по полю homeAway, не порядку."""
        ev = {
            "date": "2026-01-15T20:20:00Z",
            "competitions": [{
                "status": _make_status("pre"),
                # Away первым в списке
                "competitors": [
                    _make_competitor("away", "Philadelphia Eagles", "PHI", "—"),
                    _make_competitor("home", "Dallas Cowboys", "DAL", "—"),
                ],
                "venue": {},
                "notes": [],
                "broadcasts": [],
            }],
        }
        result = parse_espn_event(ev, "Q")
        assert result["home_name"] == "Dallas Cowboys"
        assert result["away_name"] == "Philadelphia Eagles"


# ═══════════════════════════════════════════════════════════════
#  Тесты — parse_espn_event: Playoff notes
# ═══════════════════════════════════════════════════════════════

class TestParseEventNotes:
    """Playoff / special notes."""

    def test_note_extracted_when_present(self):
        notes = [{"headline": "AFC Championship Game"}]
        ev = _make_event(notes=notes)
        result = parse_espn_event(ev, "Q")
        assert result["note"] == "AFC Championship Game"

    def test_note_empty_when_absent(self):
        ev = _make_event(notes=[])
        result = parse_espn_event(ev, "Q")
        assert result["note"] == ""

    def test_note_uses_first_element(self):
        notes = [{"headline": "Super Bowl LVIII"}, {"headline": "Ignored"}]
        ev = _make_event(notes=notes)
        result = parse_espn_event(ev, "Q")
        assert result["note"] == "Super Bowl LVIII"


# ═══════════════════════════════════════════════════════════════
#  Тесты — parse_espn_event: Граничные случаи
# ═══════════════════════════════════════════════════════════════

class TestParseEventEdgeCases:
    """Устойчивость к неполным / пустым данным ESPN."""

    def test_empty_event_no_crash(self):
        """Полностью пустой словарь не вызывает исключение."""
        result = parse_espn_event({}, "Q")
        assert isinstance(result, dict)

    def test_empty_event_defaults(self):
        """Пустой dict → разумные дефолты."""
        result = parse_espn_event({}, "Q")
        assert result["state"] == "pre"
        assert result["home_name"] == "—"
        assert result["away_name"] == "—"
        assert result["home_score"] == "—"
        assert result["away_score"] == "—"

    def test_missing_competitions_no_crash(self):
        """Отсутствие competitions → не падает."""
        result = parse_espn_event({"date": "2026-01-15T20:20:00Z"}, "Q")
        assert isinstance(result, dict)

    def test_missing_competitors_no_crash(self):
        """Отсутствие competitors → имена '—'."""
        ev = {
            "competitions": [{
                "status": _make_status("in", clock="5:00", period=2),
                "competitors": [],
                "venue": {},
                "notes": [],
            }]
        }
        result = parse_espn_event(ev, "Q")
        assert result["home_name"] == "—"
        assert result["away_name"] == "—"

    def test_only_home_competitor_no_crash(self):
        """Только один конкурент (home) — away '—'."""
        ev = {
            "competitions": [{
                "status": _make_status("pre"),
                "competitors": [
                    _make_competitor("home", "Team A", "TA"),
                ],
                "venue": {},
                "notes": [],
            }]
        }
        result = parse_espn_event(ev, "Q")
        assert result["home_name"] == "Team A"
        assert result["away_name"] == "—"

    def test_unknown_state_treated_as_pre(self):
        """Неизвестный state → дефолт 'pre'."""
        ev = _make_event(state="halftime")  # нестандартное значение
        # state не будет "in" или "post" → fallthrough к else
        result = parse_espn_event(ev, "Q")
        # status_str должен начинаться с 📅 (pre-логика)
        assert result["status_str"].startswith("📅")

    def test_missing_venue_empty_strings(self):
        """Нет venue → пустые строки."""
        ev = {
            "competitions": [{
                "status": _make_status("post", "Final"),
                "competitors": [],
                "venue": {},
                "notes": [],
            }]
        }
        result = parse_espn_event(ev, "Q")
        assert result["venue"] == ""
        assert result["city"] == ""

    def test_all_required_keys_present(self):
        """Возвращаемый dict содержит все обязательные ключи."""
        required = {
            "state", "detail", "clock", "period",
            "home_name", "away_name", "home_score", "away_score",
            "home_abbr", "away_abbr", "venue", "city",
            "note", "status_str", "period_name",
        }
        result = parse_espn_event({}, "Q")
        assert required.issubset(set(result.keys()))

    def test_no_crash_with_none_score(self):
        """Если score отсутствует в competitor — возвращается '—'."""
        ev = {
            "competitions": [{
                "status": _make_status("in", clock="10:00", period=1),
                "competitors": [
                    {"homeAway": "home", "team": {"displayName": "A", "abbreviation": "A"}},
                    {"homeAway": "away", "team": {"displayName": "B", "abbreviation": "B"}},
                ],
                "venue": {},
                "notes": [],
            }]
        }
        result = parse_espn_event(ev, "Q")
        assert result["home_score"] == "—"
        assert result["away_score"] == "—"


# ═══════════════════════════════════════════════════════════════
#  Тесты — fetch_scores_from_url: mock HTTP
# ═══════════════════════════════════════════════════════════════

class TestFetchScoresFromUrl:
    """
    Тестирует fetch_scores_from_url с mock-сессией.
    Не делает реальных HTTP-запросов.
    """

    ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"

    def _mock_session(self, status_code: int, json_body: dict = None,
                      raise_exc: Exception = None):
        """Создаёт mock-объект с методом .get()."""
        mock = MagicMock()
        if raise_exc:
            mock.get.side_effect = raise_exc
        else:
            response = MagicMock()
            response.status_code = status_code
            if json_body is not None:
                response.json.return_value = json_body
            mock.get.return_value = response
        return mock

    def test_200_with_events_returns_list(self):
        """200 OK с events → возвращает список событий."""
        events = [_make_event(), _make_event(state="in")]
        session = self._mock_session(200, {"events": events})
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert isinstance(result, list)
        assert len(result) == 2

    def test_200_empty_events_returns_empty_list(self):
        """200 OK с пустым events[] → пустой список."""
        session = self._mock_session(200, {"events": []})
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert result == []

    def test_200_missing_events_key_returns_empty(self):
        """200 OK без ключа 'events' → пустой список."""
        session = self._mock_session(200, {"scoreboard": "data"})
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert result == []

    def test_404_returns_empty_list(self):
        """404 → пустой список (не crash)."""
        session = self._mock_session(404)
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert result == []

    def test_500_returns_empty_list(self):
        """500 → пустой список."""
        session = self._mock_session(500)
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert result == []

    def test_network_error_returns_empty_list(self):
        """ConnectionError → пустой список (не crash)."""
        session = self._mock_session(0, raise_exc=ConnectionError("timeout"))
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert result == []

    def test_timeout_returns_empty_list(self):
        """TimeoutError → пустой список."""
        import requests as req
        session = self._mock_session(0, raise_exc=req.exceptions.Timeout())
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert result == []

    def test_json_decode_error_returns_empty(self):
        """Невалидный JSON (json() выбрасывает) → пустой список."""
        import json
        mock = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.side_effect = json.JSONDecodeError("err", "", 0)
        mock.get.return_value = response
        result = fetch_scores_from_url(self.ESPN_URL, mock)
        assert result == []

    def test_correct_url_called(self):
        """Проверяет, что функция вызывает именно переданный URL."""
        session = self._mock_session(200, {"events": []})
        fetch_scores_from_url(self.ESPN_URL, session)
        session.get.assert_called_once()
        call_url = session.get.call_args[0][0]
        assert call_url == self.ESPN_URL

    def test_user_agent_header_sent(self):
        """Запрос отправляется с заголовком User-Agent."""
        session = self._mock_session(200, {"events": []})
        fetch_scores_from_url(self.ESPN_URL, session)
        call_kwargs = session.get.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert "User-Agent" in headers

    def test_returns_event_dicts(self):
        """Каждый элемент возвращаемого списка — словарь."""
        events = [_make_event(state="post"), _make_event(state="in")]
        session = self._mock_session(200, {"events": events})
        result = fetch_scores_from_url(self.ESPN_URL, session)
        for item in result:
            assert isinstance(item, dict)

    def test_single_event_returned(self):
        """Один event в ответе."""
        session = self._mock_session(200, {"events": [_make_event()]})
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert len(result) == 1

    def test_large_response_no_crash(self):
        """Большой список событий — нет ошибок."""
        events = [_make_event(state="pre") for _ in range(50)]
        session = self._mock_session(200, {"events": events})
        result = fetch_scores_from_url(self.ESPN_URL, session)
        assert len(result) == 50


# ═══════════════════════════════════════════════════════════════
#  Интеграционные тесты — связка fetch + parse
# ═══════════════════════════════════════════════════════════════

class TestFetchAndParse:
    """Проверяет связку: fetch_scores_from_url → parse_espn_event."""

    ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

    def _mock_session(self, events):
        mock = MagicMock()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"events": events}
        mock.get.return_value = response
        return mock

    def test_live_event_parsed_correctly(self):
        """LIVE матч: fetch → parse → state=='in'."""
        ev = _make_event(state="in", home_name="Lakers", away_name="Celtics",
                         home_score="102", away_score="98", clock="2:34", period=4)
        session = self._mock_session([ev])
        events = fetch_scores_from_url(self.ESPN_URL, session)
        assert len(events) == 1
        parsed = parse_espn_event(events[0], "Q")
        assert parsed["state"] == "in"
        assert parsed["home_name"] == "Lakers"
        assert parsed["away_name"] == "Celtics"
        assert parsed["home_score"] == "102"
        assert parsed["status_str"] == "Q4 · 2:34"

    def test_finished_event_parsed_correctly(self):
        """Завершённый матч: fetch → parse → state=='post'."""
        ev = _make_event(state="post", detail="Final",
                         home_score="110", away_score="105")
        session = self._mock_session([ev])
        events = fetch_scores_from_url(self.ESPN_URL, session)
        parsed = parse_espn_event(events[0], "Q")
        assert parsed["state"] == "post"
        assert "🏁" in parsed["status_str"]
        assert parsed["home_score"] == "110"

    def test_mixed_states_all_parsed(self):
        """Несколько событий с разными статусами."""
        evs = [
            _make_event(state="pre"),
            _make_event(state="in", clock="5:00", period=2),
            _make_event(state="post", detail="Final"),
        ]
        session = self._mock_session(evs)
        events = fetch_scores_from_url(self.ESPN_URL, session)
        assert len(events) == 3
        states = [parse_espn_event(e, "Q")["state"] for e in events]
        assert set(states) == {"pre", "in", "post"}

    def test_empty_response_yields_no_parsed_events(self):
        """Пустой ответ → ни одного события для парсинга."""
        session = self._mock_session([])
        events = fetch_scores_from_url(self.ESPN_URL, session)
        assert events == []
        parsed = [parse_espn_event(e, "Q") for e in events]
        assert parsed == []

    def test_soccer_period_name_in_status(self):
        """Soccer: status_str содержит минуты с апострофом."""
        ev = _make_event(state="in", clock="74", period=2)
        session = self._mock_session([ev])
        events = fetch_scores_from_url(self.ESPN_URL, session)
        parsed = parse_espn_event(events[0], "min")
        assert parsed["status_str"] == "74'"
