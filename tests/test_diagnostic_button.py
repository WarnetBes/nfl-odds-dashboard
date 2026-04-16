"""
test_diagnostic_button.py — regression tests for the Diagnostic Button (🩺 Проверить подключения).

Simulates clicking the diagnostic button and verifies that the correct status
messages are displayed for each of the three connections:

  1. The Odds API  — key check + HTTP status handling
  2. Gmail SMTP    — credentials check + SMTP_SSL login handling
  3. Google Sheets — URL check + gspread client + open_by_url handling

Each scenario mirrors the exact logic in app.py (lines 1558-1628) and asserts
the precise status message strings the user would see.
"""

import smtplib
import pytest
from unittest.mock import MagicMock, patch

ODDS_BASE = "https://api.the-odds-api.com/v4"


# ═══════════════════════════════════════════════════════════════════════════════
#  Helpers — replicate diagnostic logic from app.py
# ═══════════════════════════════════════════════════════════════════════════════

def run_odds_api_diagnostic(api_key: str) -> tuple[str, str]:
    """
    Replicate the Odds API diagnostic check from app.py.

    Returns (level, message) where level is 'error', 'success', or 'warning'.
    """
    import requests

    if not api_key:
        return ("error", "❌ The Odds API: ключ не задан")

    try:
        r = requests.get(
            f"{ODDS_BASE}/sports",
            params={"apiKey": api_key},
            timeout=8,
        )
        if r.status_code == 200:
            remaining = r.headers.get("x-requests-remaining", "?")
            return ("success", f"✅ The Odds API: OK — осталось {remaining} запросов")
        elif r.status_code == 401:
            return ("error", "❌ The Odds API: неверный ключ (401)")
        else:
            return ("warning", f"⚠️ The Odds API: статус {r.status_code}")
    except Exception as e:
        return ("error", f"❌ The Odds API: {e}")


def run_gmail_diagnostic(gmail_from: str, gmail_pass: str) -> tuple[str, str]:
    """
    Replicate the Gmail SMTP diagnostic check from app.py.

    Returns (level, message).
    """
    if not gmail_from or not gmail_pass:
        return ("warning", "⚠️ Gmail: email или App Password не заполнены")

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=8) as srv:
            srv.login(gmail_from, gmail_pass)
        return ("success", f"✅ Gmail: авторизация OK ({gmail_from})")
    except smtplib.SMTPAuthenticationError:
        return ("error", "❌ Gmail: ошибка авторизации — проверь App Password")
    except Exception as e:
        return ("error", f"❌ Gmail: {e}")


def run_gsheets_diagnostic(
    gsheet_url: str,
    get_gspread_client_fn,
) -> tuple[str, str]:
    """
    Replicate the Google Sheets diagnostic check from app.py.

    Returns (level, message).
    """
    if not gsheet_url:
        return ("warning", "⚠️ Google Sheets: URL не задан")

    client, err = get_gspread_client_fn()
    if client is None:
        return ("error", f"❌ Google Sheets: {err}")

    try:
        sh = client.open_by_url(gsheet_url)
        return ("success", f"✅ Google Sheets: OK — '{sh.title}'")
    except Exception as e:
        return ("error", f"❌ Google Sheets: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
#  1. The Odds API — diagnostic scenarios
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticOddsApi:
    """Verifies every Odds API status message the diagnostic button can show."""

    def test_no_api_key_shows_error(self):
        """Empty API key → error: 'ключ не задан'."""
        level, msg = run_odds_api_diagnostic("")
        assert level == "error"
        assert "ключ не задан" in msg

    def test_none_api_key_shows_error(self):
        """None-ish API key (empty string from env) → error."""
        level, msg = run_odds_api_diagnostic("")
        assert level == "error"
        assert "❌" in msg

    def test_200_ok_shows_success_with_remaining(self):
        """HTTP 200 → success message with remaining requests count."""
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"x-requests-remaining": "487"}
            mock_get.return_value = resp

            level, msg = run_odds_api_diagnostic("valid_key_123")

        assert level == "success"
        assert "✅" in msg
        assert "487" in msg
        assert "осталось" in msg

    def test_200_ok_missing_header_shows_question_mark(self):
        """HTTP 200 but no x-requests-remaining header → '?' in message."""
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {}
            mock_get.return_value = resp

            level, msg = run_odds_api_diagnostic("valid_key")

        assert level == "success"
        assert "?" in msg

    def test_401_invalid_key_shows_error(self):
        """HTTP 401 → error: 'неверный ключ (401)'."""
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 401
            resp.headers = {}
            mock_get.return_value = resp

            level, msg = run_odds_api_diagnostic("bad_key")

        assert level == "error"
        assert "неверный ключ (401)" in msg

    def test_500_server_error_shows_warning(self):
        """HTTP 500 → warning with status code."""
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 500
            resp.headers = {}
            mock_get.return_value = resp

            level, msg = run_odds_api_diagnostic("some_key")

        assert level == "warning"
        assert "⚠️" in msg
        assert "500" in msg

    def test_429_rate_limit_shows_warning(self):
        """HTTP 429 (rate limit) → warning with status code."""
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 429
            resp.headers = {}
            mock_get.return_value = resp

            level, msg = run_odds_api_diagnostic("some_key")

        assert level == "warning"
        assert "429" in msg

    def test_timeout_shows_error(self):
        """requests.Timeout → error with exception text."""
        import requests as req

        with patch("requests.get", side_effect=req.exceptions.Timeout("timed out")):
            level, msg = run_odds_api_diagnostic("some_key")

        assert level == "error"
        assert "❌" in msg
        assert "timed out" in msg

    def test_connection_error_shows_error(self):
        """requests.ConnectionError → error with exception text."""
        import requests as req

        with patch("requests.get", side_effect=req.exceptions.ConnectionError("DNS failure")):
            level, msg = run_odds_api_diagnostic("some_key")

        assert level == "error"
        assert "DNS failure" in msg


# ═══════════════════════════════════════════════════════════════════════════════
#  2. Gmail SMTP — diagnostic scenarios
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticGmail:
    """Verifies every Gmail status message the diagnostic button can show."""

    def test_no_email_shows_warning(self):
        """Empty sender email → warning: 'не заполнены'."""
        level, msg = run_gmail_diagnostic("", "some_pass")
        assert level == "warning"
        assert "не заполнены" in msg

    def test_no_password_shows_warning(self):
        """Empty password → warning: 'не заполнены'."""
        level, msg = run_gmail_diagnostic("user@gmail.com", "")
        assert level == "warning"
        assert "не заполнены" in msg

    def test_both_empty_shows_warning(self):
        """Both empty → warning: 'не заполнены'."""
        level, msg = run_gmail_diagnostic("", "")
        assert level == "warning"
        assert "⚠️" in msg

    def test_successful_login_shows_success(self):
        """SMTP login OK → success with sender address."""
        with patch("smtplib.SMTP_SSL") as mock_ssl:
            instance = MagicMock()
            mock_ssl.return_value.__enter__ = MagicMock(return_value=instance)
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)

            level, msg = run_gmail_diagnostic("user@gmail.com", "app_pass_123")

        assert level == "success"
        assert "✅" in msg
        assert "user@gmail.com" in msg
        assert "авторизация OK" in msg

    def test_auth_error_shows_error(self):
        """SMTPAuthenticationError → error: 'ошибка авторизации'."""
        with patch("smtplib.SMTP_SSL") as mock_ssl:
            instance = MagicMock()
            instance.login.side_effect = smtplib.SMTPAuthenticationError(
                535, b"Bad credentials"
            )
            mock_ssl.return_value.__enter__ = MagicMock(return_value=instance)
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)

            level, msg = run_gmail_diagnostic("user@gmail.com", "wrong_pass")

        assert level == "error"
        assert "❌" in msg
        assert "ошибка авторизации" in msg
        assert "App Password" in msg

    def test_connection_refused_shows_error(self):
        """ConnectionRefusedError → error with exception text."""
        with patch("smtplib.SMTP_SSL", side_effect=ConnectionRefusedError("refused")):
            level, msg = run_gmail_diagnostic("user@gmail.com", "pass123")

        assert level == "error"
        assert "❌" in msg
        assert "refused" in msg

    def test_generic_smtp_exception_shows_error(self):
        """Generic Exception during SMTP → error with exception text."""
        with patch("smtplib.SMTP_SSL", side_effect=OSError("Network unreachable")):
            level, msg = run_gmail_diagnostic("user@gmail.com", "pass123")

        assert level == "error"
        assert "Network unreachable" in msg


# ═══════════════════════════════════════════════════════════════════════════════
#  3. Google Sheets — diagnostic scenarios
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticGSheets:
    """Verifies every Google Sheets status message the diagnostic button can show."""

    def test_no_url_shows_warning(self):
        """Empty GSheet URL → warning: 'URL не задан'."""
        level, msg = run_gsheets_diagnostic("", lambda: (None, None))
        assert level == "warning"
        assert "URL не задан" in msg

    def test_client_none_shows_error(self):
        """get_gspread_client returns (None, error) → error with error message."""
        err_text = "gspread не установлен"

        def mock_client():
            return None, err_text

        level, msg = run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/abc123/edit",
            mock_client,
        )
        assert level == "error"
        assert "❌" in msg
        assert err_text in msg

    def test_client_none_missing_secrets_shows_error(self):
        """get_gspread_client missing secrets → error with auth message."""
        def mock_client():
            return None, "Секрет gcp_service_account не найден в st.secrets"

        level, msg = run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/abc/edit",
            mock_client,
        )
        assert level == "error"
        assert "gcp_service_account" in msg

    def test_successful_open_shows_success_with_title(self):
        """Successful open_by_url → success with sheet title."""
        mock_client = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "MyBets"
        mock_client.open_by_url.return_value = mock_sheet

        level, msg = run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/abc123/edit",
            lambda: (mock_client, None),
        )
        assert level == "success"
        assert "✅" in msg
        assert "MyBets" in msg
        assert "OK" in msg

    def test_spreadsheet_not_found_shows_error(self):
        """open_by_url raises Exception → error with exception text."""
        mock_client = MagicMock()
        mock_client.open_by_url.side_effect = Exception("Spreadsheet not found")

        level, msg = run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/bad_id/edit",
            lambda: (mock_client, None),
        )
        assert level == "error"
        assert "❌" in msg
        assert "Spreadsheet not found" in msg

    def test_permission_denied_shows_error(self):
        """open_by_url raises permission error → error with message."""
        mock_client = MagicMock()
        mock_client.open_by_url.side_effect = Exception(
            "403: The caller does not have permission"
        )

        level, msg = run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/locked/edit",
            lambda: (mock_client, None),
        )
        assert level == "error"
        assert "permission" in msg

    def test_client_auth_error_shows_error(self):
        """get_gspread_client returns auth error → error with auth message."""
        def mock_client():
            return None, "Ошибка авторизации: invalid_grant"

        level, msg = run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/abc/edit",
            mock_client,
        )
        assert level == "error"
        assert "Ошибка авторизации" in msg


# ═══════════════════════════════════════════════════════════════════════════════
#  4. Full diagnostic flow — all three checks in sequence
# ═══════════════════════════════════════════════════════════════════════════════

class TestDiagnosticFullFlow:
    """Simulates a full diagnostic button click checking all three connections."""

    def test_all_connections_ok(self):
        """All three services healthy → three success messages."""
        results = []

        # Odds API — 200 OK
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"x-requests-remaining": "450"}
            mock_get.return_value = resp
            results.append(run_odds_api_diagnostic("valid_key"))

        # Gmail — login OK
        with patch("smtplib.SMTP_SSL") as mock_ssl:
            instance = MagicMock()
            mock_ssl.return_value.__enter__ = MagicMock(return_value=instance)
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            results.append(run_gmail_diagnostic("user@gmail.com", "app_pass"))

        # GSheets — open OK
        mock_client = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.title = "ValueBets"
        mock_client.open_by_url.return_value = mock_sheet
        results.append(run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/abc/edit",
            lambda: (mock_client, None),
        ))

        assert len(results) == 3
        for level, msg in results:
            assert level == "success", f"Expected success but got {level}: {msg}"
            assert "✅" in msg

    def test_all_connections_fail(self):
        """All three services down → three error/warning messages."""
        results = []

        # Odds API — no key
        results.append(run_odds_api_diagnostic(""))

        # Gmail — no credentials
        results.append(run_gmail_diagnostic("", ""))

        # GSheets — no URL
        results.append(run_gsheets_diagnostic("", lambda: (None, None)))

        assert len(results) == 3
        for level, _msg in results:
            assert level in ("error", "warning")

    def test_mixed_results(self):
        """Odds OK, Gmail fail, GSheets warning → mixed statuses."""
        results = []

        # Odds API — 200 OK
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 200
            resp.headers = {"x-requests-remaining": "100"}
            mock_get.return_value = resp
            results.append(run_odds_api_diagnostic("valid_key"))

        # Gmail — auth error
        with patch("smtplib.SMTP_SSL") as mock_ssl:
            instance = MagicMock()
            instance.login.side_effect = smtplib.SMTPAuthenticationError(
                535, b"Bad credentials"
            )
            mock_ssl.return_value.__enter__ = MagicMock(return_value=instance)
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            results.append(run_gmail_diagnostic("user@gmail.com", "wrong_pass"))

        # GSheets — no URL
        results.append(run_gsheets_diagnostic("", lambda: (None, None)))

        assert results[0][0] == "success"
        assert results[1][0] == "error"
        assert results[2][0] == "warning"

    def test_odds_401_gmail_ok_gsheets_client_error(self):
        """Odds 401, Gmail OK, GSheets client error → error, success, error."""
        results = []

        # Odds API — 401
        with patch("requests.get") as mock_get:
            resp = MagicMock()
            resp.status_code = 401
            resp.headers = {}
            mock_get.return_value = resp
            results.append(run_odds_api_diagnostic("invalid_key"))

        # Gmail — login OK
        with patch("smtplib.SMTP_SSL") as mock_ssl:
            instance = MagicMock()
            mock_ssl.return_value.__enter__ = MagicMock(return_value=instance)
            mock_ssl.return_value.__exit__ = MagicMock(return_value=False)
            results.append(run_gmail_diagnostic("user@gmail.com", "app_pass"))

        # GSheets — client returns None
        results.append(run_gsheets_diagnostic(
            "https://docs.google.com/spreadsheets/d/abc/edit",
            lambda: (None, "gspread не установлен"),
        ))

        assert results[0][0] == "error"
        assert "401" in results[0][1]
        assert results[1][0] == "success"
        assert "авторизация OK" in results[1][1]
        assert results[2][0] == "error"
        assert "gspread" in results[2][1]
