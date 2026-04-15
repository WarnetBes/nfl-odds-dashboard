"""
Sports Odds Dashboard
━━━━━━━━━━━━━━━━━━━━
- NFL · Football (9 leagues) · NBA
- Живые коэффициенты (The Odds API)
- Auto-refresh каждые 5 минут
- Value Bets с EV Edge + Gmail-уведомления
- Live Scores (ESPN Public API)
- История ставок в Google Sheets
"""

import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import pytz
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

try:
    import gspread
    from google.oauth2.service_account import Credentials as SACredentials
    GSPREAD_OK = True
except ImportError:
    GSPREAD_OK = False

# ── Импорт чистых функций из utils.py ────────
from utils import (
    build_betting_signals as _build_betting_signals_v2,
    compute_value_bets    as _compute_value_bets_v2,
    find_arb_in_group,
    arb_stakes,
    arb_percentage,
    kelly_stake,
    kelly_fraction,
    sport_ev_threshold,
    sharp_books_in_group,
    SPORT_EV_THRESHOLDS,
)
