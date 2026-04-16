"""Authentication & Paywall module for NFL Odds Dashboard.

Provides:
- Streamlit-authenticator integration with Google Sheets as user database
- Login/logout with cookie-based sessions
- Free/Pro/Sharp subscription tiers
- Tab/feature access control
- Row limit enforcement for Free tier
- User badge rendering in sidebar
- User registration with bcrypt password hashing
"""

from __future__ import annotations

import logging
from datetime import datetime, date
from typing import Dict, List, Literal, Optional, Tuple

import bcrypt
import streamlit as st

try:
    import gspread
    from google.oauth2.service_account import Credentials as SACredentials
    GSPREAD_OK = True
except ImportError:
    GSPREAD_OK = False

try:
    import streamlit_authenticator as stauth
    STAUTH_OK = True
except ImportError:
    STAUTH_OK = False

logger = logging.getLogger(__name__)

# ── GOOGLE SHEETS CONFIG ─────────────────────────────────────────────
GSHEETS_SCOPES: List[str] = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_COLUMNS: List[str] = [
    "username", "name", "email", "password_hash",
    "plan", "paid_until", "telegram_id", "created_at",
]

# ── SUBSCRIPTION PLANS ────────────────────────────────────────────────
PLAN_CONFIG: Dict[str, dict] = {
    "free": {
        "name": "Free",
        "icon": "🆓",
        "sports": ["🏈 NFL"],
        "row_limit": 5,
        "locked_tabs": [
            "💎 Value Bets",
            "⚡ Арбитраж",
            "🎯 Сигналы",
            "📊 История ставок",
            "💰 Статистика банкролла",
            "🤖 AI Анализ",
        ],
    },
    "pro": {
        "name": "Pro",
        "icon": "⭐",
        "sports": "all",
        "row_limit": None,
        "locked_tabs": [],
    },
    "sharp": {
        "name": "Sharp",
        "icon": "🔥",
        "sports": "all",
        "row_limit": None,
        "locked_tabs": [],
        "priority_support": True,
    },
}

# ── MOCK / FALLBACK USER DATABASE ────────────────────────────────────
_MOCK_USERS_DB: Dict[str, dict] = {
    "demo": {
        "email": "demo@example.com",
        "name": "Demo User",
        "password": bcrypt.hashpw("demo123".encode(), bcrypt.gensalt()).decode(),
        "plan": "free",
        "paid_until": "2099-12-31",
    },
    "pro_user": {
        "email": "pro@example.com",
        "name": "Pro User",
        "password": bcrypt.hashpw("pro456".encode(), bcrypt.gensalt()).decode(),
        "plan": "pro",
        "paid_until": "2026-12-31",
    },
}


# ── GOOGLE SHEETS CLIENT ─────────────────────────────────────────────
def get_sheets_client() -> gspread.Client:
    """Authenticate via ``st.secrets["gcp_service_account"]`` and return a
    ``gspread.Client``.

    Returns:
        An authorised gspread client.

    Raises:
        RuntimeError: If gspread is not installed or authentication fails.
    """
    if not GSPREAD_OK:
        raise RuntimeError("gspread не установлен")

    try:
        sa_info = dict(st.secrets["gcp_service_account"])
        creds = SACredentials.from_service_account_info(sa_info, scopes=GSHEETS_SCOPES)
        client = gspread.authorize(creds)
        return client
    except KeyError:
        raise RuntimeError("Секрет gcp_service_account не найден в st.secrets")
    except Exception as exc:
        raise RuntimeError(f"Ошибка авторизации GSheets: {exc}") from exc


# ── LOAD USERS FROM SHEETS ───────────────────────────────────────────
def load_users_from_sheets() -> Dict[str, dict]:
    """Load all users from Google Sheets and return a dict compatible with
    ``streamlit-authenticator``.

    The sheet is located at ``st.secrets["GSHEET_USERS_URL"]`` with columns::

        username | name | email | password_hash | plan | paid_until | telegram_id | created_at

    Returns:
        A dict keyed by username::

            {
                "username": {
                    "email": str,
                    "name": str,
                    "password": str,   # bcrypt hash
                    "plan": str,
                    "paid_until": str,
                },
                ...
            }

        Falls back to ``_MOCK_USERS_DB`` if Sheets is unavailable.
    """
    try:
        client = get_sheets_client()
        url = st.secrets["GSHEET_USERS_URL"]
        spreadsheet = client.open_by_url(url)
        worksheet = spreadsheet.sheet1
        records = worksheet.get_all_records()

        users: Dict[str, dict] = {}
        for row in records:
            uname = str(row.get("username", "")).strip()
            if not uname:
                continue
            users[uname] = {
                "email": str(row.get("email", "")),
                "name": str(row.get("name", uname)),
                "password": str(row.get("password_hash", "")),
                "plan": str(row.get("plan", "free")).lower(),
                "paid_until": str(row.get("paid_until", "")),
            }

        if users:
            return users

        logger.warning("Google Sheets пуст — используем mock-данные")
        return _MOCK_USERS_DB

    except Exception as exc:
        logger.error("Не удалось загрузить пользователей из Sheets: %s", exc)
        try:
            st.error(f"⚠️ Ошибка загрузки пользователей из Sheets: {exc}. Используем демо-данные.")
        except Exception:
            pass
        return _MOCK_USERS_DB


# ── AUTHENTICATOR ────────────────────────────────────────────────────
def init_authenticator() -> "stauth.Authenticate":
    """Create and return a ``streamlit_authenticator.Authenticate`` instance.

    - Loads users from Google Sheets (falls back to mock data).
    - Cookie name: ``"sports_arb_dashboard"``.
    - Cookie key from ``st.secrets["COOKIE_SECRET"]``.
    - Cookie expiry: 30 days.

    Returns:
        A configured ``stauth.Authenticate`` object.

    Raises:
        RuntimeError: If ``streamlit-authenticator`` is not installed.
    """
    if not STAUTH_OK:
        raise RuntimeError("streamlit-authenticator не установлен")

    users = load_users_from_sheets()

    credentials = {
        "usernames": {
            uname: {
                "email": data["email"],
                "name": data["name"],
                "password": data["password"],
            }
            for uname, data in users.items()
        }
    }

    try:
        cookie_key = st.secrets["COOKIE_SECRET"]
    except KeyError:
        cookie_key = "sports_arb_dashboard_default_key_change_me"
        logger.warning("COOKIE_SECRET не найден в st.secrets — используем дефолтный ключ")

    authenticator = stauth.Authenticate(
        credentials=credentials,
        cookie_name="sports_arb_dashboard",
        cookie_key=cookie_key,
        cookie_expiry_days=30,
    )

    # Store the full user data (including plan/paid_until) in session state
    if "_auth_users_data" not in st.session_state:
        st.session_state["_auth_users_data"] = users

    return authenticator


# ── USER PLAN ────────────────────────────────────────────────────────
def get_user_plan(username: str) -> str:
    """Return the subscription plan for *username*.

    Checks ``paid_until`` — if the date has passed, returns ``"free"``
    regardless of the stored plan value.

    Args:
        username: The username to look up.

    Returns:
        ``"pro"``, ``"sharp"``, or ``"free"``.
    """
    try:
        users = st.session_state.get("_auth_users_data")
        if not users:
            users = load_users_from_sheets()

        user = users.get(username)
        if not user:
            return "free"

        plan = user.get("plan", "free").lower()
        paid_until = user.get("paid_until", "")

        if not paid_until:
            return plan

        try:
            expiry = datetime.strptime(paid_until, "%Y-%m-%d").date()
            if expiry < date.today():
                return "free"
        except ValueError:
            logger.warning("Некорректная дата paid_until='%s' для %s", paid_until, username)
            return plan

        return plan

    except Exception as exc:
        logger.error("Ошибка get_user_plan(%s): %s", username, exc)
        return "free"


# ── REGISTER USER ────────────────────────────────────────────────────
def register_user(
    username: str,
    name: str,
    email: str,
    password: str,
) -> bool:
    """Register a new user by appending a row to Google Sheets.

    The password is hashed with ``bcrypt`` before storage.

    Args:
        username: Unique login name.
        name: Display name.
        email: User email address.
        password: Plain-text password (will be hashed).

    Returns:
        ``True`` on success, ``False`` if the username already exists or an
        error occurs.
    """
    try:
        client = get_sheets_client()
        url = st.secrets["GSHEET_USERS_URL"]
        spreadsheet = client.open_by_url(url)
        worksheet = spreadsheet.sheet1

        # Check for duplicate username
        existing = worksheet.get_all_records()
        for row in existing:
            if str(row.get("username", "")).strip().lower() == username.strip().lower():
                logger.warning("Регистрация: username '%s' уже существует", username)
                return False

        # Hash password with bcrypt
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        new_row = [
            username.strip(),
            name.strip(),
            email.strip(),
            password_hash,
            "free",                                     # plan
            "",                                         # paid_until
            "",                                         # telegram_id
            datetime.now().strftime("%Y-%m-%d %H:%M"),  # created_at
        ]

        worksheet.append_row(new_row, value_input_option="USER_ENTERED")

        # Invalidate cached users so next load picks up the new user
        if "_auth_users_data" in st.session_state:
            del st.session_state["_auth_users_data"]

        return True

    except Exception as exc:
        logger.error("Ошибка регистрации пользователя '%s': %s", username, exc)
        try:
            st.error(f"⚠️ Ошибка регистрации: {exc}")
        except Exception:
            pass
        return False


# ── AUTHENTICATION GATE (backward-compatible) ────────────────────────
def run_auth_gate() -> None:
    """Main auth gate — call ONCE at the top of ``app.py`` after
    ``st.set_page_config()``.

    If ``streamlit-authenticator`` is available, uses cookie-based auth.
    Otherwise, falls back to the built-in simple login form.
    """
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None
        st.session_state.auth_plan = "free"

    if STAUTH_OK:
        _run_stauth_gate()
    else:
        _run_simple_gate()


def _run_stauth_gate() -> None:
    """Auth gate using ``streamlit-authenticator``."""
    if st.session_state.auth_user is not None:
        return

    try:
        authenticator = init_authenticator()
        authenticator.login(
            location="main",
            fields={
                "Form name": "🏆 Sports Odds Dashboard",
                "Username": "👤 Username",
                "Password": "🔑 Password",
                "Login": "🚀 Войти",
            },
        )
        # stauth 0.4.x stores results in session_state, not return value
        name = st.session_state.get("name")
        authentication_status = st.session_state.get("authentication_status")
        username = st.session_state.get("username")

        if authentication_status is True:
            plan = get_user_plan(username)
            st.session_state.auth_user = username
            st.session_state.auth_plan = plan
            st.session_state.auth_name = name
            st.session_state["_authenticator"] = authenticator
            st.rerun()
        elif authentication_status is False:
            st.error("❌ Неверный логин или пароль")
            _show_demo_credentials()
            st.stop()
        else:
            _show_demo_credentials()
            st.stop()
    except Exception as exc:
        logger.error("Ошибка streamlit-authenticator: %s", exc)
        st.warning("⚠️ Ошибка аутентификации — используем простую форму входа.")
        _run_simple_gate()


def _run_simple_gate() -> None:
    """Fallback auth gate using a simple ``st.form``."""
    if st.session_state.auth_user is not None:
        return

    _show_login_form()
    st.stop()


def _show_login_form() -> None:
    """Render the built-in simple login form (fallback mode)."""
    st.markdown(
        """<div style='text-align:center; padding:2rem 0;'>
        <h1 style='font-size:2.5rem;'>🏆 Sports Odds Dashboard</h1>
        <p style='color:#64748b; font-size:1.1rem;'>Войди чтобы продолжить</p>
        </div>""",
        unsafe_allow_html=True,
    )

    users = load_users_from_sheets()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("👤 Username", placeholder="demo")
            password = st.text_input("🔑 Password", type="password", placeholder="demo123")
            submit = st.form_submit_button("🚀 Войти", use_container_width=True, type="primary")

            if submit:
                if username in users:
                    user_data = users[username]
                    stored_hash = user_data.get("password", "")
                    # Support both bcrypt and legacy SHA-256 hashes
                    if stored_hash.startswith("$2"):
                        pw_ok = bcrypt.checkpw(password.encode(), stored_hash.encode())
                    else:
                        import hashlib
                        pw_ok = hashlib.sha256(password.encode()).hexdigest() == stored_hash

                    if pw_ok:
                        paid_until = user_data.get("paid_until", "2099-12-31")
                        try:
                            exp = datetime.strptime(paid_until, "%Y-%m-%d")
                            if exp < datetime.now():
                                st.error("❌ Подписка истекла")
                                return
                        except ValueError:
                            pass

                        plan = get_user_plan(username)
                        st.session_state.auth_user = username
                        st.session_state.auth_plan = plan
                        st.session_state.auth_name = user_data.get("name", username)
                        st.rerun()
                    else:
                        st.error("❌ Неверный пароль")
                else:
                    st.error("❌ Пользователь не найден")

        st.divider()
        _show_demo_credentials()


def _show_demo_credentials() -> None:
    """Display demo login credentials below the form."""
    st.markdown(
        """<div style='text-align:center;'>
        <p style='color:#64748b; font-size:0.85rem;'>Демо доступ:</p>
        <p><strong>demo</strong> / <strong>demo123</strong> (Free)<br>
        <strong>pro_user</strong> / <strong>pro456</strong> (Pro)</p>
        </div>""",
        unsafe_allow_html=True,
    )


# ── LOGOUT ───────────────────────────────────────────────────────────
def logout() -> None:
    """Log out the current user and reset session state."""
    authenticator = st.session_state.get("_authenticator")
    if authenticator is not None:
        try:
            authenticator.logout(location="unrendered")
        except Exception:
            pass

    st.session_state.auth_user = None
    st.session_state.auth_plan = "free"
    st.session_state.pop("auth_name", None)
    st.session_state.pop("_authenticator", None)
    st.session_state.pop("_auth_users_data", None)
    st.rerun()


# ── SIDEBAR BADGE ────────────────────────────────────────────────────
def render_user_badge() -> None:
    """Render user info badge in the sidebar with a logout button."""
    if st.session_state.auth_user:
        plan = st.session_state.auth_plan
        cfg = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])
        name = st.session_state.get("auth_name", st.session_state.auth_user)

        st.markdown(
            f"""<div style='background:#1e293b; padding:12px; border-radius:10px;
            border:1px solid #334155; margin-bottom:1rem;'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <div>
                    <div style='font-size:0.75rem; color:#64748b;'>Пользователь</div>
                    <div style='font-weight:700; color:#e2e8f0;'>{name}</div>
                </div>
                <div style='text-align:right;'>
                    <div style='font-size:1.5rem;'>{cfg["icon"]}</div>
                    <div style='font-size:0.75rem; color:#a78bfa; font-weight:600;'>{cfg["name"]}</div>
                </div>
            </div>
        </div>""",
            unsafe_allow_html=True,
        )

        if st.button("🚪 Выйти", key="logout_btn", use_container_width=True, type="secondary"):
            logout()


# ── ACCESS CONTROL ───────────────────────────────────────────────────
def is_tab_locked(tab_name: str) -> bool:
    """Return ``True`` if *tab_name* is locked for the current user's plan.

    Args:
        tab_name: Display name of the tab (e.g. ``"💎 Value Bets"``).

    Returns:
        Whether the tab is locked.
    """
    plan = st.session_state.get("auth_plan", "free")
    locked: List[str] = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])["locked_tabs"]
    return tab_name in locked


def get_available_sports() -> List[str] | str:
    """Return the list of sports available for the current plan.

    Returns:
        ``"all"`` for Pro/Sharp plans, or a list of sport labels for Free.
    """
    plan = st.session_state.get("auth_plan", "free")
    sports = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])["sports"]
    if sports == "all":
        return "all"
    return sports


def apply_rows_limit(df, limit_override: Optional[int] = None):
    """Apply a row limit to *df* for Free-plan users.

    Args:
        df: A pandas DataFrame to truncate.
        limit_override: Optional explicit row limit (overrides plan default).

    Returns:
        The (possibly truncated) DataFrame.
    """
    plan = st.session_state.get("auth_plan", "free")
    limit = limit_override if limit_override is not None else PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])["row_limit"]

    if limit is None:
        return df
    return df.head(limit)


def render_upgrade_banner(tab_name: str) -> None:
    """Render an upgrade banner for locked tabs.

    Args:
        tab_name: Display name of the locked tab.
    """
    st.markdown(
        f"""<div style='background: linear-gradient(135deg, #7c3aed, #2563eb);
        padding:2rem; border-radius:16px; text-align:center; margin:2rem 0;'>
        <h2 style='color:white; margin:0;'>🔒 {tab_name} — Pro функция</h2>
        <p style='color:#e2e8f0; font-size:1.1rem; margin:1rem 0;'>
            Эта вкладка доступна только подписчикам <strong>Pro</strong> и <strong>Sharp</strong>
        </p>
        <div style='background:rgba(255,255,255,0.1); border-radius:12px; padding:1.5rem; margin:1.5rem 0;'>
            <p style='color:white; font-size:1rem; margin:0.5rem 0;'>⭐ <strong>Pro</strong> — $15/мес</p>
            <p style='color:#cbd5e1; font-size:0.9rem; margin:0;'>
                Все 10 лиг · Value Bets · Арбитраж · Kelly Stake · Gmail-алерты
            </p>
        </div>
        <div style='background:rgba(255,255,255,0.1); border-radius:12px; padding:1.5rem; margin:1.5rem 0;'>
            <p style='color:white; font-size:1rem; margin:0.5rem 0;'>🔥 <strong>Sharp</strong> — $40/мес</p>
            <p style='color:#cbd5e1; font-size:0.9rem; margin:0;'>
                Pro + AI-агент анализа · Приоритетная поддержка
            </p>
        </div>
        <p style='color:#e2e8f0; font-size:0.85rem; margin-top:1.5rem;'>
            ℹ️ Свяжись с нами для подключения: <strong>support@yourdomain.com</strong>
        </p>
    </div>""",
        unsafe_allow_html=True,
    )


def render_rows_limit_banner(total_rows: int) -> None:
    """Render a banner when the row limit is applied.

    Args:
        total_rows: Total number of rows in the untruncated data.
    """
    plan = st.session_state.get("auth_plan", "free")
    limit = PLAN_CONFIG.get(plan, PLAN_CONFIG["free"])["row_limit"]

    if limit and total_rows > limit:
        st.warning(
            f"🔒 **Free план** показывает только {limit} из {total_rows} строк. "
            f"Обновись до **Pro** для полного доступа.",
            icon="⚠️",
        )
