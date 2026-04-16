"""Authentication & Paywall module for NFL Odds Dashboard.

Provides:
- Login/logout with simple user database
- Free/Pro/Sharp subscription tiers
- Tab/feature access control
- Row limit enforcement for Free tier
- User badge rendering in sidebar
"""
import streamlit as st
import hashlib
import hmac
import os
import secrets as _secrets_mod
from datetime import datetime
from typing import Literal, Dict, List

# ── SUBSCRIPTION PLANS ────────────────────────────────────────────────
PLAN_CONFIG = {
    "free": {
        "name": "Free",
        "icon": "🆓",
        "sports": ["🏈 NFL"],  # Only NFL for free
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
        "sports": "all",  # All 10 leagues
        "row_limit": None,  # Unlimited
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

# ── USER DATABASE (in production: use database or st.secrets) ─────────

# --- Salted password hashing (PBKDF2-HMAC-SHA256) ---
_HASH_ALGO      = "sha256"
_HASH_ITERATIONS = 260_000  # OWASP 2023 recommendation for PBKDF2-SHA256

def _hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash *password* with a random salt using PBKDF2-HMAC-SHA256.

    Returns ``salt_hex:hash_hex`` so the salt is stored alongside the hash.
    If *salt* is ``None`` a new 16-byte random salt is generated.
    """
    if salt is None:
        salt = _secrets_mod.token_bytes(16)
    dk = hashlib.pbkdf2_hmac(_HASH_ALGO, password.encode(), salt, _HASH_ITERATIONS)
    return salt.hex() + ":" + dk.hex()

def _verify_password(password: str, stored: str) -> bool:
    """Constant-time verification of *password* against a ``salt:hash`` string."""
    try:
        salt_hex, hash_hex = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac(_HASH_ALGO, password.encode(), salt, _HASH_ITERATIONS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False

# Pre-computed salted hashes for demo accounts.
# In production these should come from a database or st.secrets.
USERS_DB = {
    "demo": {
        "password_hash": _hash_password("demo123", salt=b"demo_fixed_salt!"),
        "plan": "free",
        "name": "Demo User",
        "expires": "2099-12-31",
    },
    "pro_user": {
        "password_hash": _hash_password("pro456", salt=b"pro__fixed_salt!"),
        "plan": "pro",
        "name": "Pro User",
        "expires": "2026-12-31",
    },
}

# ── AUTHENTICATION ────────────────────────────────────────────────────
def run_auth_gate():
    """Main auth gate - call this ONCE at the top of app.py after st.set_page_config()."""
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None
        st.session_state.auth_plan = "free"
    
    if st.session_state.auth_user is None:
        _show_login_form()
        st.stop()

def _show_login_form():
    """Renders login form and handles authentication."""
    st.markdown("""<div style='text-align:center; padding:2rem 0;'>
        <h1 style='font-size:2.5rem;'>🏆 Sports Odds Dashboard</h1>
        <p style='color:#64748b; font-size:1.1rem;'>Войди чтобы продолжить</p>
    </div>""", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("👤 Username", placeholder="demo")
            password = st.text_input("🔑 Password", type="password", placeholder="demo123")
            submit = st.form_submit_button("🚀 Войти", use_container_width=True, type="primary")
            
            if submit:
                if username in USERS_DB:
                    user_data = USERS_DB[username]
                    if _verify_password(password, user_data["password_hash"]):
                        # Check expiration
                        exp = datetime.strptime(user_data["expires"], "%Y-%m-%d")
                        if exp < datetime.now():
                            st.error("❌ Подписка истекла")
                        else:
                            st.session_state.auth_user = username
                            st.session_state.auth_plan = user_data["plan"]
                            st.session_state.auth_name = user_data["name"]
                            st.rerun()
                    else:
                        st.error("❌ Неверный пароль")
                else:
                    st.error("❌ Пользователь не найден")
        
        st.divider()
        st.markdown("""<div style='text-align:center;'>
            <p style='color:#64748b; font-size:0.85rem;'>Демо доступ:</p>
            <p><strong>demo</strong> / <strong>demo123</strong> (Free)<br>
            <strong>pro_user</strong> / <strong>pro456</strong> (Pro)</p>
        </div>""", unsafe_allow_html=True)

def logout():
    """Logout current user."""
    st.session_state.auth_user = None
    st.session_state.auth_plan = "free"
    st.rerun()

def render_user_badge():
    """Renders user info badge in sidebar with logout button."""
    if st.session_state.auth_user:
        plan = st.session_state.auth_plan
        cfg = PLAN_CONFIG[plan]
        name = st.session_state.get("auth_name", st.session_state.auth_user)
        
        st.markdown(f"""<div style='background:#1e293b; padding:12px; border-radius:10px; 
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
        </div>""", unsafe_allow_html=True)
        
        if st.button("🚪 Выйти", key="logout_btn", use_container_width=True, type="secondary"):
            logout()

# ── ACCESS CONTROL ───────────────────────────────────────────────────
def is_tab_locked(tab_name: str) -> bool:
    """Returns True if tab is locked for current user's plan."""
    plan = st.session_state.get("auth_plan", "free")
    locked = PLAN_CONFIG[plan]["locked_tabs"]
    return tab_name in locked

def get_available_sports() -> List[str]:
    """Returns list of sports available for current plan."""
    plan = st.session_state.get("auth_plan", "free")
    sports = PLAN_CONFIG[plan]["sports"]
    if sports == "all":
        return "all"
    return sports

def apply_rows_limit(df, limit_override=None):
    """Applies row limit to dataframe for Free plan."""
    plan = st.session_state.get("auth_plan", "free")
    limit = limit_override if limit_override is not None else PLAN_CONFIG[plan]["row_limit"]
    
    if limit is None:
        return df
    return df.head(limit)

def render_upgrade_banner(tab_name: str):
    """Renders upgrade banner for locked tabs."""
    st.markdown(f"""<div style='background: linear-gradient(135deg, #7c3aed, #2563eb); 
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
    </div>""", unsafe_allow_html=True)

def render_rows_limit_banner(total_rows: int):
    """Renders banner when row limit is applied."""
    plan = st.session_state.get("auth_plan", "free")
    limit = PLAN_CONFIG[plan]["row_limit"]
    
    if limit and total_rows > limit:
        st.warning(f"🔒 **Free план** показывает только {limit} из {total_rows} строк. "
                   f"Обновись до **Pro** для полного доступа.", icon="⚠️")
